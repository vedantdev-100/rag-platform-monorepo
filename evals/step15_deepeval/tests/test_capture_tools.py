import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_tools as tools


class CaptureToolTests(unittest.TestCase):
    def test_reviewed_recall_includes_missed_labels(self):
        scores = tools.ranked_metrics(['a', 'b'], {'a': 2, 'b': 0, 'missed': 1})
        self.assertEqual(scores['precision_at_5'], .2)
        self.assertEqual(scores['labeled_recall_at_5'], .5)

    def test_missing_label_is_not_implicitly_irrelevant(self):
        with self.assertRaises(ValueError):
            tools.ranked_metrics(['a'], {})

    def test_bounded_context_keeps_actual_truncation(self):
        record = {'messages': [{'content': 'Question: q\nEvidence (JSON records):\n' +
                    json.dumps({'label': 'S1', 'text': 'short'})}],
                  'retrieved': [{'content': 'short plus text never supplied'}]}
        self.assertEqual(tools.exact_context(record)[0]['text'], 'short')

    def test_25_case_selection_does_not_leak_documents_between_splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'source/data').mkdir(parents=True)
            (root / 'source/pdfs').mkdir()
            rows = []
            for doc in ('a', 'b', 'c', 'd'):
                (root / 'source/pdfs' / (doc + '.pdf')).write_bytes(b'synthetic fixture')
                for i in range(10):
                    rows.append({'financebench_id': doc + str(i), 'doc_name': doc,
                        'question': 'q', 'answer': 'a', 'question_reasoning': None,
                        'evidence': [{'doc_name': doc, 'evidence_page_num': 0, 'evidence_text': 'evidence'}]})
            (root / 'source/data/financebench_open_source.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            tools.prepare(root / 'source', 25, 15, root / 'out')
            cases = tools.load_rows(root / 'out/golden.jsonl')
            self.assertEqual(len(cases), 25)
            docs = lambda split: {e['document_key'] for c in cases if c['split'] == split for e in c['evidence']}
            self.assertFalse(docs('dev') & docs('test'))


if __name__ == '__main__':
    unittest.main()
