"""DeepEval owns semantic scoring; deterministic audit metrics remain separate."""
from dataclasses import dataclass
import math
import re

from deepeval.metrics import (AnswerRelevancyMetric, FaithfulnessMetric,
    ContextualPrecisionMetric, ContextualRecallMetric, ContextualRelevancyMetric, GEval)
from deepeval.test_case import LLMTestCase, SingleTurnParams

from capture_tools import exact_context, ranked_metrics

METRIC_DEFINITION_VERSION = 'deepeval-step15-v1'
CUSTOM_STEPS = {
    'correctness': [
        'Compare the actual answer to the reference answer in relation to the question.',
        'Check quantities, units, time periods, entity names and logical conclusions. Accept equivalent paraphrases.',
        'Penalize incorrect facts, contradictions and missing required reference information; do not reward word overlap.'],
    'completeness': [
        'Identify the facts required by the reference answer for the question.',
        'Check how many required facts the actual answer correctly covers, including units and periods.',
        'Score completeness of required facts, penalizing omissions and vague substitutes.'],
    'citation_support': [
        'Identify factual claims and their [Snumber] citations in the actual answer.',
        'Match each citation to the same labeled passage in retrieval_context, which is the exact context supplied.',
        'Assess whether the cited passage supports the associated claim; penalize incorrect labels, unsupported claims and contradictions.'],
    'citation_coverage': [
        'Identify the factual claims in the actual answer that require citations.',
        'Check whether each claim has an appropriate [Snumber] citation to a supplied passage that supports it.',
        'Score how completely factual claims have supporting citations; a decorative citation at the end does not automatically cover every claim.']}


@dataclass
class MetricSpec:
    key: str
    metric: object
    scope: str
    implementation: str
    test_case: LLMTestCase


def metric_specs(case, record, judge, profile='full'):
    answer = record.get('answer') or {}
    output = answer.get('answer') or '[No completed generated answer]'
    final_valid = not record.get('error') and answer.get('status') == 'answered'
    base = dict(input=case['query'], actual_output=output, expected_output=case['reference_answer'],
                name=case['case_id'])
    retrieved = [r['content'] for r in record.get('retrieved', [])]
    blocks = exact_context(record)
    bounded = [b['text'] for b in blocks]
    labeled = [f'[{b["label"]}] {b["text"]}' for b in blocks]
    retrieval_case = LLMTestCase(**base, retrieval_context=retrieved)
    generation_case = LLMTestCase(**base, retrieval_context=bounded)
    citation_case = LLMTestCase(**base, retrieval_context=labeled)
    common = dict(model=judge, threshold=None, async_mode=False, include_reason=True, eval_mode='llm')
    specs = []
    if record['mode'] != 'oracle' and retrieved:
        for key, cls in [('contextual_precision', ContextualPrecisionMetric),
                         ('contextual_recall', ContextualRecallMetric)]:
            specs.append(MetricSpec('deepeval_' + key, cls(**common), 'ranked_retrieval',
                                    cls.__name__, retrieval_case))
        specs.append(MetricSpec('deepeval_retrieved_context_relevancy', ContextualRelevancyMetric(**common),
                                'ranked_retrieval', 'ContextualRelevancyMetric', retrieval_case))
    if record['mode'] != 'retriever' and bounded:
        specs.append(MetricSpec('deepeval_context_relevancy', ContextualRelevancyMetric(**common),
                                'exact_bounded_context', 'ContextualRelevancyMetric', generation_case))
        if profile == 'full':
            specs.append(MetricSpec('deepeval_context_budget_recall', ContextualRecallMetric(**common),
                                    'exact_bounded_context', 'ContextualRecallMetric', generation_case))
    if record['mode'] != 'retriever' and final_valid:
        specs.append(MetricSpec('deepeval_answer_relevancy', AnswerRelevancyMetric(**common),
                                'completed_answer', 'AnswerRelevancyMetric', generation_case))
        if bounded:
            specs.append(MetricSpec('deepeval_faithfulness', FaithfulnessMetric(**common),
                                    'exact_bounded_context', 'FaithfulnessMetric', generation_case))
        keys = ['correctness'] if profile == 'core' else list(CUSTOM_STEPS)
        for key in keys:
            if key.startswith('citation') and not bounded:
                continue
            params = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT,
                      SingleTurnParams.RETRIEVAL_CONTEXT if key.startswith('citation') else SingleTurnParams.EXPECTED_OUTPUT]
            metric = GEval(name=key.replace('_', ' ').title(), evaluation_steps=CUSTOM_STEPS[key],
                           evaluation_params=params, model=judge, threshold=None, async_mode=False)
            specs.append(MetricSpec('deepeval_geval_' + key, metric,
                                    'labeled_exact_context' if key.startswith('citation') else 'reference_answer',
                                    'GEval: task-specific fixed evaluation_steps',
                                    citation_case if key.startswith('citation') else generation_case))
    return specs


def score_case(case, record, judge, profile='full', labels=None):
    metrics, details, errors = {}, {}, []
    skipped = {}
    final_valid = not record.get('error') and (record.get('answer') or {}).get('status') == 'answered'
    if record['mode'] != 'retriever':
        metrics['application_completed_answer'] = float(final_valid)
        if (record.get('answer') or {}).get('status') == 'insufficient_context':
            metrics['application_false_abstention'] = 1.0
        elif final_valid:
            metrics['application_false_abstention'] = 0.0
        else:
            metrics['application_false_abstention'] = None
        if not final_valid:
            skipped['generator_metrics'] = record.get('error') or (record.get('answer') or {}).get('status') or 'no_completed_answer'
    rows = record.get('retrieved') or []
    if record['mode'] != 'oracle':
        if not rows:
            skipped['retrieval_metrics'] = 'no_retrieved_context; no vacuous perfect scores'
        mapping = record['document_map']
        gold_ids = {mapping[e['document_key']]['id'] for e in case['evidence']}
        found = {r['document_id'] for r in rows[:5]}
        metrics['audit_gold_document_hit_at_5'] = float(bool(gold_ids & found))
        metrics['audit_labeled_document_recall_at_5'] = len(gold_ids & found) / len(gold_ids)
        if labels is not None:
            metrics.update({'human_' + key: value for key, value in
                            ranked_metrics([r['chunk_id'] for r in rows], labels).items()})
    if record['mode'] != 'retriever' and not exact_context(record):
        skipped['bounded_context_metrics'] = 'no_exact_context_supplied'
    for spec in metric_specs(case, record, judge, profile):
        try:
            spec.metric.measure(spec.test_case, _show_indicator=False)
            score = spec.metric.score
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError('metric_returned_invalid_score')
            metrics[spec.key] = score
            details[spec.key] = {'score': score, 'reason': spec.metric.reason,
                                'scope': spec.scope, 'implementation': spec.implementation}
        except Exception as exc:
            metrics[spec.key] = None
            # Provider bodies, prompts and exception text are deliberately excluded.
            errors.append({'metric': spec.key, 'scope': spec.scope, 'type': type(exc).__name__})
    if final_valid:
        text = record['answer']['answer']
        supplied = {b['label'] for b in exact_context(record)}
        citations = set(re.findall(r'\[(S\d+)\]', text))
        metrics['audit_citation_labels_valid'] = float(bool(citations) and citations <= supplied)
    return {'case_id': case['case_id'], 'split': case['split'], 'mode': record['mode'], 'tags': case['tags'],
            'metrics': metrics, 'metric_details': details, 'judge_errors': errors, 'skipped': skipped,
            'generation_error': record.get('error')}
