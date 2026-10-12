import json
from pathlib import Path
import sys
import os
import subprocess
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_tools as tools


class CaptureToolTests(unittest.TestCase):
    def test_unicode_capture_is_decoded_as_utf8_not_windows_acp(self):
        value = {'answer': 'Financial text: € “growth” Ελληνικά 😐',
                 'messages': [{'content': 'Exact evidence 😐'}]}
        raw = ('STEP15_RESULT=' + json.dumps(value, ensure_ascii=False) + '\n').encode('utf-8')
        with self.assertRaises(UnicodeDecodeError):
            raw.decode('cp1252')
        self.assertEqual(tools.parse_capture_result(raw), value)

    def test_invalid_utf8_evidence_is_rejected_not_replaced(self):
        with self.assertRaises(UnicodeDecodeError):
            tools.parse_capture_result(b'STEP15_RESULT={"answer":"\xff"}\n')

    def test_binary_subprocess_capture_preserves_international_text(self):
        value = {'query': 'Résumé', 'answer': '€ 😐'}
        code = ('import json,sys;sys.stdout.buffer.write((' + repr('STEP15_RESULT=') +
                ' + json.dumps(' + repr(value) + ',ensure_ascii=False)).encode("utf-8"))')
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, check=True)
        self.assertEqual(tools.parse_capture_result(result.stdout), value)

    def test_tmp_script_can_import_uninstalled_app_from_container_workdir(self):
        # Reproduce the actual runtime topology: helper in /tmp, uninstalled app
        # in cwd, and no PYTHONPATH supplied by the test runner.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'api/app').mkdir(parents=True)
            (root / 'tmp').mkdir()
            (root / 'api/app/__init__.py').write_text('MARKER = "api-source-found"\n')
            helper = Path(__file__).resolve().parents[1] / 'container_capture.py'
            prefix = helper.read_text().split("if __name__ == '__main__':")[0]
            script = root / 'tmp/probe.py'
            script.write_text(prefix + '\nimport app\nprint(app.MARKER)\n')
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            result = subprocess.run([sys.executable, str(script)], cwd=root / 'api',
                                    env=env, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), 'api-source-found')

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
