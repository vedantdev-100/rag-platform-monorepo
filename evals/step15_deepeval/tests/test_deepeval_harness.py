import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run  # sets local-only configuration before DeepEval imports
from deepeval.metrics import FaithfulnessMetric, ContextualPrecisionMetric, GEval
from pydantic import BaseModel, ValidationError
from lmstudio_judge import LMStudioJudge
from metrics_backend import metric_specs, score_case


def fixtures(mode='pipeline'):
    case = {'case_id': 'one', 'query': 'Who owns Atlas?', 'reference_answer': 'Mira owns Atlas.',
            'split': 'dev', 'tags': ['fact'], 'evidence': [{'document_key': 'atlas'}]}
    record = {'case_id': 'one', 'mode': mode, 'document_map': {'atlas': {'id': 'd'}},
        'retrieved': [{'chunk_id': 'a', 'document_id': 'd',
                      'content': 'Mira owns Atlas. Extra text never supplied.'}],
        'answer': {'status': 'answered', 'answer': 'Mira owns Atlas [S1]'}, 'error': None,
        'messages': [{'content': 'Question: Who owns Atlas?\nEvidence (JSON records):\n' +
                       json.dumps({'label': 'S1', 'text': 'Mira owns Atlas.'})}]}
    return case, record


def fake_response(url, *, data, **kwargs):
    """Scripted schema-compatible responses; metrics themselves execute for real."""
    schema = data['response_format']['json_schema']['schema']
    props = schema['properties']
    if 'truths' in props:
        value = {'truths': ['Mira owns Atlas.']}
    elif 'claims' in props:
        value = {'claims': ['Mira owns Atlas.']}
    elif 'statements' in props:
        value = {'statements': ['Mira owns Atlas.']}
    elif 'verdicts' in props:
        value = {'verdicts': [{'verdict': 'yes', 'reason': 'supported', 'statement': 'Mira owns Atlas.'}]}
    elif 'score' in props:
        value = {'score': 10.0, 'reason': 'fully correct'}
    else:
        value = {'reason': 'fully supported'}
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value)}}]}


class AdapterTests(unittest.TestCase):
    def judge(self, folder, revision='q4-v1'):
        return LMStudioJudge({'EVAL_JUDGE_MODEL': 'local-model', 'EVAL_JUDGE_REVISION': revision,
                              'EVAL_DEEPEVAL_CACHE_DIR': folder})

    def test_schema_output_and_cache(self):
        class Answer(BaseModel):
            reason: str
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', side_effect=fake_response) as http:
            j = self.judge(tmp)
            self.assertIsInstance(j.generate('prompt', Answer), Answer)
            self.assertIsInstance(j.generate('prompt', Answer), Answer)
            self.assertEqual(http.call_count, 1)
            self.assertEqual(j.cache_hits, 1)
            self.assertTrue(http.call_args.args[0].startswith('http://127.0.0.1:1234/v1'))
            self.assertIn('json_schema', http.call_args.kwargs['data']['response_format'])

    def test_async_schema_adapter(self):
        class Answer(BaseModel):
            reason: str
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', side_effect=fake_response):
            self.assertIsInstance(asyncio.run(self.judge(tmp).a_generate('prompt', Answer)), Answer)

    def test_truncated_response_not_cached(self):
        class Answer(BaseModel):
            reason: str
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', return_value={
            'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                self.judge(tmp).generate('prompt', Answer)
            self.assertFalse(list(Path(tmp).glob('*.json')))

    def test_schema_failure_not_cached(self):
        class Answer(BaseModel):
            reason: str
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', return_value={
            'choices': [{'finish_reason': 'stop', 'message': {'content': '{"wrong": 1}'}}]}):
            with self.assertRaises(ValidationError):
                self.judge(tmp).generate('prompt', Answer)
            self.assertFalse(list(Path(tmp).glob('*.json')))

    def test_cache_separated_by_judge_revision(self):
        class Answer(BaseModel):
            reason: str
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', side_effect=fake_response) as http:
            self.judge(tmp, 'one').generate('prompt', Answer)
            self.judge(tmp, 'two').generate('prompt', Answer)
            self.assertEqual(http.call_count, 2)


class MetricTests(unittest.TestCase):
    def test_metric_specs_use_library_classes_and_explicit_local_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = LMStudioJudge({'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4', 'EVAL_DEEPEVAL_CACHE_DIR': tmp})
            case, record = fixtures()
            specs = metric_specs(case, record, j)
            self.assertTrue(any(isinstance(s.metric, FaithfulnessMetric) for s in specs))
            self.assertTrue(any(isinstance(s.metric, ContextualPrecisionMetric) for s in specs))
            self.assertTrue(any(isinstance(s.metric, GEval) for s in specs))
            for s in specs:
                self.assertIs(s.metric.model, j)
                self.assertIsNone(s.metric.threshold)
                self.assertFalse(s.metric.async_mode)
            faithful = next(s for s in specs if isinstance(s.metric, FaithfulnessMetric))
            self.assertEqual(faithful.test_case.retrieval_context, ['Mira owns Atlas.'])
            precision = next(s for s in specs if isinstance(s.metric, ContextualPrecisionMetric))
            self.assertIn('Extra text', precision.test_case.retrieval_context[0])

    def test_real_deepeval_metrics_execute_with_scripted_local_api(self):
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', side_effect=fake_response):
            j = LMStudioJudge({'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4', 'EVAL_DEEPEVAL_CACHE_DIR': tmp})
            case, record = fixtures()
            result = score_case(case, record, j)
            self.assertEqual(result['judge_errors'], [])
            for key, value in result['metrics'].items():
                if key.startswith('deepeval_'):
                    self.assertEqual(value, 1.0, key)
            self.assertEqual(len(result['metric_details']), 11)

    def test_failed_generation_skips_generator_scores_but_retains_failure(self):
        case, record = fixtures()
        record['error'] = 'invalid_citations'
        record['answer'] = None
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', side_effect=fake_response):
            j = LMStudioJudge({'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4', 'EVAL_DEEPEVAL_CACHE_DIR': tmp})
            result = score_case(case, record, j)
            self.assertEqual(result['metrics']['application_completed_answer'], 0)
            self.assertNotIn('deepeval_faithfulness', result['metrics'])
            self.assertEqual(result['skipped']['generator_metrics'], 'invalid_citations')

    def test_oracle_does_not_claim_retriever_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = LMStudioJudge({'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4', 'EVAL_DEEPEVAL_CACHE_DIR': tmp})
            case, record = fixtures('oracle')
            specs = metric_specs(case, record, j)
            self.assertFalse(any(s.scope == 'ranked_retrieval' for s in specs))

    def test_retriever_only_does_not_score_placeholder_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = LMStudioJudge({'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4', 'EVAL_DEEPEVAL_CACHE_DIR': tmp})
            case, record = fixtures('retriever')
            record['answer'] = None
            record['messages'] = []
            specs = metric_specs(case, record, j)
            self.assertTrue(all(s.scope == 'ranked_retrieval' for s in specs))

    def test_empty_context_does_not_receive_vacuous_perfect_scores(self):
        case, record = fixtures()
        record.update(retrieved=[], messages=[], answer={'status': 'insufficient_context'})
        with tempfile.TemporaryDirectory() as tmp:
            j = LMStudioJudge({'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4', 'EVAL_DEEPEVAL_CACHE_DIR': tmp})
            result = score_case(case, record, j)
            self.assertFalse(any(k.startswith('deepeval_') for k in result['metrics']))
            self.assertEqual(result['metrics']['application_false_abstention'], 1)

    def test_evaluator_error_is_missing_score_not_generator_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch('lmstudio_judge.request', side_effect=OSError('offline')):
            j = LMStudioJudge({'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4', 'EVAL_DEEPEVAL_CACHE_DIR': tmp})
            case, record = fixtures()
            result = score_case(case, record, j, profile='core')
            self.assertTrue(result['judge_errors'])
            self.assertEqual(result['metrics']['application_completed_answer'], 1)
            self.assertIsNone(result['metrics']['deepeval_faithfulness'])

    def test_replay_existing_capture_format_writes_deepeval_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'data'
            data.mkdir()
            case, record = fixtures()
            (data / 'golden.jsonl').write_text(json.dumps(case) + '\n')
            import capture_tools
            record['run_identity'] = {'dataset_sha256': capture_tools.sha((data / 'golden.jsonl').read_bytes())}
            record['settings'] = {'model': 'generator-test'}
            captures = root / 'old-captures.jsonl'
            captures.write_text(json.dumps(record) + '\n')
            cfg = {'EVAL_JUDGE_MODEL': 'local', 'EVAL_JUDGE_REVISION': 'q4',
                   'EVAL_DEEPEVAL_CACHE_DIR': str(root / 'cache')}
            args = SimpleNamespace(data=str(data), captures=str(captures), out=str(root / 'report'),
                                   labels=None, profile='full', limit=None)
            with patch('lmstudio_judge.request', side_effect=fake_response):
                run.judge_runs(args, cfg)
            summary = json.loads((root / 'report/summary.json').read_text())
            self.assertEqual(summary['backend'], 'deepeval')
            self.assertEqual(summary['case_count'], 1)
            self.assertEqual(summary['cases_with_judge_errors'], 0)
            self.assertEqual(summary['groups']['all']['deepeval_faithfulness']['mean'], 1)
            self.assertTrue((root / 'report/report.md').exists())


if __name__ == '__main__':
    unittest.main()
