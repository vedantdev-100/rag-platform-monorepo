"""Run with the existing Step 14 API dependency environment, not host stdlib."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import httpx
    from app.rag.generation.settings import GenerationSettings
    from app.rag.generation.types import ProviderResult
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('container_capture', ROOT / 'container_capture.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


@unittest.skipUnless(AVAILABLE, 'Run inside the Step 14 dependency environment for graph integration tests')
class GraphTests(unittest.TestCase):
    def run_case(self, text='Mira owns Atlas [S1]', empty=False, authorized=True, mode='pipeline'):
        cfg = GenerationSettings(_env_file=None, RAG_RUNTIME_ROLE='api', RAG_GENERATION_ENABLED=True,
                                 RAG_LLM_PROVIDER='groq', GROQ_API_KEY='test', GROQ_MODEL='mock',
                                 RAG_CONTEXT_MAX_BYTES=2000)
        retrieved = [{'chunk_id': 'a', 'document_id': 'doc', 'content': 'Mira owns Atlas. ' + 'x' * 5000,
                      'score': 1., 'modality': 'text', 'metadata': {}}]
        original_client = httpx.AsyncClient
        def http_handler(request):
            if not authorized:
                return httpx.Response(401)
            if request.method == 'GET':
                return httpx.Response(200, json={'documents': []})
            return httpx.Response(200, json={'results': [] if empty else retrieved,
                                            'retriever_backend': 'hybrid', 'reranked': False})
        def client(*args, **kwargs):
            return original_client(*args, transport=httpx.MockTransport(http_handler), **kwargs)
        class FakeProvider:
            async def generate(self, messages, emit):
                return ProviderResult(text=text, finish_reason='stop', provider='groq', model='mock')
            async def close(self):
                pass
        payload = {'expected_hashes': {}, 'case': {'case_id': 'one', 'query': 'Who owns Atlas?',
                   'evidence': [{'document_key': 'atlas', 'text': 'Mira owns Atlas.', 'page_index': 0}]},
                   'mode': mode, 'token': 'test', 'top_k': 5, 'document_map': {'atlas': {'id': 'doc'}}}
        with patch('app.rag.generation.settings.get_generation_settings', return_value=cfg), \
             patch('app.core.config.get_settings', return_value=SimpleNamespace()), \
             patch('app.rag.generation.providers.openai_compatible.build_provider', return_value=FakeProvider()), \
             patch('httpx.AsyncClient', side_effect=client):
            return asyncio.run(capture.capture(payload))

    def test_real_graph_captures_exact_bounded_provider_input(self):
        record = self.run_case()
        self.assertEqual(record['answer']['status'], 'answered')
        self.assertGreater(len(record['retrieved'][0]['content']), 5000)
        self.assertLess(len(record['messages'][1]['content']), 2000)
        self.assertEqual(record['raw_result']['text'], 'Mira owns Atlas [S1]')

    def test_invalid_citation_retains_raw_output_as_failure(self):
        record = self.run_case(text='Mira owns Atlas [S99]')
        self.assertEqual(record['error'], 'invalid_citations')
        self.assertIsNone(record['answer'])
        self.assertTrue(record['raw_result']['text'].endswith('[S99]'))

    def test_no_evidence_abstains_without_provider_call(self):
        record = self.run_case(empty=True)
        self.assertEqual(record['answer']['status'], 'insufficient_context')
        self.assertIsNone(record['raw_result'])
        self.assertEqual(record['messages'], [])

    def test_auth_failure_stops_before_generation(self):
        record = self.run_case(authorized=False)
        self.assertEqual(record['error'], 'evaluation_authorization_failed')
        self.assertIsNone(record['raw_result'])

    def test_oracle_uses_gold_evidence_only(self):
        record = self.run_case(mode='oracle')
        self.assertEqual(record['retrieved'][0]['chunk_id'], 'gold-0')
        self.assertEqual(record['retrieved'][0]['content'], 'Mira owns Atlas.')
        self.assertEqual(record['answer']['status'], 'answered')

    def test_retriever_mode_makes_no_generation_call(self):
        record = self.run_case(mode='retriever')
        self.assertEqual(len(record['retrieved']), 1)
        self.assertIsNone(record['raw_result'])


if __name__ == '__main__':
    unittest.main()
