import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('step15', ROOT / 'run.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MetricTests(unittest.TestCase):
    def test_ranked_metrics_include_unretrieved_gold(self):
        got = m.ranked_metrics(['a', 'b'], {'a': 2, 'b': 0, 'c': 1})
        self.assertEqual(got['precision_at_5'], .2)
        self.assertEqual(got['labeled_recall_at_5'], .5)
        self.assertEqual(got['mrr_at_5'], 1)
        self.assertLess(got['ndcg_at_5'], 1)

    def test_no_gold_is_not_perfect_recall(self):
        got = m.ranked_metrics(['a'], {'a': 0})
        self.assertIsNone(got['labeled_recall_at_5'])
        self.assertIsNone(got['ndcg_at_5'])

    def test_unjudged_and_duplicate_results_rejected(self):
        with self.assertRaises(ValueError):
            m.ranked_metrics(['a'], {})
        with self.assertRaises(ValueError):
            m.ranked_metrics(['a', 'a'], {'a': 1})

    def test_context_is_truncated_provider_input_not_full_retrieved(self):
        record = {'messages': [{'content': 'Question: q\nEvidence (JSON records):\n' +
                               json.dumps({'label': 'S1', 'text': 'short'})}],
                  'retrieved': [{'content': 'short and extra never supplied'}]}
        self.assertEqual(m.exact_context(record), [{'label': 'S1', 'text': 'short'}])

    def test_schema_rejects_boolean_grade_and_extra_fields(self):
        schema = m.object_schema({'grade': m.integer_schema(0, 4)})
        for value in [{'grade': True}, {'grade': 5}, {'grade': 1, 'extra': 1}]:
            with self.assertRaises(ValueError):
                m.validate_schema(value, schema)


class JudgeTests(unittest.TestCase):
    def test_truncated_output_not_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = m.Judge({'EVAL_JUDGE_MODEL': 'test', 'EVAL_JUDGE_REVISION': 'q4-v1', 'EVAL_CACHE_DIR': tmp})
            with patch.object(m, 'request', return_value={'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}):
                with self.assertRaises(ValueError):
                    j.call('test', {}, m.object_schema({}))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_changed_judge_revision_has_different_cache_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"grade": 4}'}}]}
            schema = m.object_schema({'grade': m.integer_schema(0, 4)})
            cfg = {'EVAL_JUDGE_MODEL': 'test', 'EVAL_JUDGE_REVISION': 'one', 'EVAL_CACHE_DIR': tmp}
            with patch.object(m, 'request', return_value=response) as call:
                m.Judge(cfg).call('test', {}, schema)
                m.Judge(cfg).call('test', {}, schema)
                cfg['EVAL_JUDGE_REVISION'] = 'two'
                m.Judge(cfg).call('test', {}, schema)
                self.assertEqual(call.call_count, 2)

    def test_quote_not_in_context_rejected(self):
        class Fake:
            def call(self, *args):
                return {'claims': [{'claim': 'wrong', 'verdict': 'supported', 'support_label': 'S1',
                        'support_quote': 'invented', 'citations': []}]}
        with self.assertRaises(ValueError):
            m.judge_answer(Fake(), {'query': 'q'}, {'answer': {'status': 'answered', 'answer': 'wrong'}},
                           [{'label': 'S1', 'text': 'actual evidence'}])

    def test_reference_support_quote_not_in_retrieval_rejected(self):
        class Fake:
            def call(self, *args):
                return {'facts': [{'fact': 'fact', 'in_retrieved': 1, 'retrieved_id': 'a',
                    'retrieved_quote': 'invented', 'in_context': 0, 'context_label': '',
                    'context_quote': '', 'in_answer': 0}]}
        with self.assertRaises(ValueError):
            m.judge_reference(Fake(), {'query': 'q', 'reference_answer': 'fact'},
                              {'retrieved': [{'chunk_id': 'a', 'content': 'actual'}]}, [])

    def test_duplicate_judge_passage_ids_rejected(self):
        class Fake:
            def call(self, *args):
                return {'items': [{'id': 'a', 'grade': 1}, {'id': 'a', 'grade': 1}]}
        with self.assertRaises(ValueError):
            m.judged_relevance(Fake(), 'q', [{'id': 'a'}, {'id': 'b'}])

    def test_failed_generation_retained_without_claiming_success(self):
        class Fake:
            def call(self, *args):
                raise ValueError('judge offline')
        case = {'case_id': 'one', 'query': 'q', 'split': 'dev', 'tags': [],
                'reference_answer': 'answer', 'evidence': [{'document_key': 'doc'}]}
        record = {'document_map': {'doc': {'id': 'd'}}, 'mode': 'pipeline',
                  'retrieved': [], 'error': 'invalid_citations', 'answer': None}
        got = m.score_case(case, record, Fake())
        self.assertEqual(got['metrics']['supported_answer_success'], 0)
        self.assertEqual(got['metrics']['pipeline_answered'], 0)
        self.assertNotIn('faithfulness', got['metrics'])
        self.assertTrue(got['judge_errors'])

    def test_all_evidence_labels_must_be_accounted_for(self):
        class Fake:
            def call(self, *args):
                return {'claims': []}
        with self.assertRaises(ValueError):
            m.judge_answer(Fake(), {'query': 'q'}, {'answer': {'status': 'answered', 'answer': 'Fact [S1]'}},
                           [{'label': 'S1', 'text': 'Fact'}])

    def test_full_scoring_preserves_separate_metric_denominators(self):
        class Fake:
            def call(self, task, value, schema):
                if 'passages' in value:
                    return {'items': [{'id': p['id'], 'grade': 2, 'reason': 'direct'} for p in value['passages']]}
                if 'reference' in value and 'retrieved' in value:
                    return {'facts': [{'fact': 'Mira owns Atlas', 'in_retrieved': 1, 'retrieved_id': 'a',
                        'retrieved_quote': 'Mira owns Atlas.', 'in_context': 1, 'context_label': 'S1',
                        'context_quote': 'Mira owns Atlas.', 'in_answer': 1}]}
                if 'context' in value:
                    return {'claims': [{'claim': 'Mira owns Atlas', 'verdict': 'supported', 'support_label': 'S1',
                        'support_quote': 'Mira owns Atlas.', 'citations': [{'label': 'S1', 'verdict': 'supported',
                                                                        'quote': 'Mira owns Atlas.'}]}]}
                return {'grade': 4, 'reason': 'correct'}
        case = {'case_id': 'one', 'query': 'q', 'split': 'dev', 'tags': [],
                'reference_answer': 'Mira owns Atlas', 'evidence': [{'document_key': 'doc'}]}
        record = {'document_map': {'doc': {'id': 'd'}}, 'mode': 'pipeline',
                  'retrieved': [{'chunk_id': 'a', 'document_id': 'd', 'content': 'Mira owns Atlas.'}],
                  'answer': {'status': 'answered', 'answer': 'Mira owns Atlas [S1]'},
                  'messages': [{'content': 'Question: q\nEvidence (JSON records):\n' +
                               json.dumps({'label': 'S1', 'text': 'Mira owns Atlas.'})}]}
        scored = m.score_case(case, record, Fake())
        self.assertEqual(scored['judge_errors'], [])
        self.assertEqual(scored['metrics']['judge_precision_at_5'], .2)
        self.assertEqual(scored['metrics']['faithfulness'], 1)
        self.assertEqual(scored['metrics']['context_relevance'], 1)
        self.assertEqual(scored['metrics']['judge_reference_claim_recall_at_5'], 1)
        self.assertEqual(scored['metrics']['supported_answer_success'], 1)


class DatasetTests(unittest.TestCase):
    def test_preparation_disjoint_docs_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'source/data').mkdir(parents=True)
            (root / 'source/pdfs').mkdir()
            rows = []
            for doc in ['a', 'b', 'c', 'd']:
                (root / 'source/pdfs' / (doc + '.pdf')).write_bytes(b'fake fixture')
                for i in range(10):
                    rows.append({'financebench_id': f'{doc}-{i}', 'doc_name': doc,
                                 'question': 'q', 'answer': 'a', 'question_reasoning': None, 'evidence': [
                        {'doc_name': doc, 'evidence_page_num': 0, 'evidence_text': 'fact'}]})
            (root / 'source/data/financebench_open_source.jsonl').write_text(
                '\n'.join(json.dumps(r) for r in rows))
            m.prepare(root / 'source', 25, 15, root / 'out')
            cases = m.load_rows(root / 'out/golden.jsonl')
            self.assertEqual(len(cases), 25)
            docs = lambda split: {e['document_key'] for c in cases if c['split'] == split for e in c['evidence']}
            self.assertFalse(docs('dev') & docs('test'))
            manifest = json.loads((root / 'out/manifest.json').read_text())
            self.assertEqual(manifest['dataset_sha256'], m.sha((root / 'out/golden.jsonl').read_bytes()))
            with self.assertRaises(ValueError):
                m.prepare(root / 'source', 25, 15, root / 'out')

    def test_count_outside_requested_range_rejected(self):
        with self.assertRaises(ValueError):
            m.prepare('unused', 100, 15, 'unused')


if __name__ == '__main__':
    unittest.main()
