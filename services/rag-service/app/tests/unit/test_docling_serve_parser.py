import asyncio
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.exceptions import IngestionError
from app.rag.ingestion.chunking.docling_chunker import DoclingHybridChunker
from app.rag.ingestion.chunking.tokenizers import ApproxTokenizer
from app.rag.ingestion.parsers.docling_serve_parser import (
    DoclingServeParser, DoclingServeConfigurationError, DoclingServeConversionFailed,
    DoclingServePartialConversion, DoclingServeSchemaMismatch, DoclingServeUnavailable,
    DoclingServeVersionMismatch, decode_document, form_options, verify_schema,
)
from app.workflows.policy import processing_version

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'


def settings(**values):
    return Settings(_env_file=None, DATABASE_URL='postgresql+asyncpg://test:test@localhost/test',
                    RAG_PARSER_BACKEND='docling_serve', **values)


class DocumentDecodeTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((FIXTURES / 'docling_serve_2_78_success.json').read_text())
        self.settings = settings()

    def test_2_78_export_decodes_with_installed_client_and_preserves_structure(self):
        parsed = decode_document(self.payload, self.settings)
        self.assertEqual(parsed.metadata['tables'], 1)
        self.assertEqual(parsed.metadata['pictures_described'], 1)
        self.assertEqual(parsed.metadata['parser_core_version'], '2.78.0')
        table = next(e for e in parsed.elements if e.modality == 'table')
        self.assertIn('120', table.text)
        self.assertEqual(table.headings, ['Quarterly results'])
        self.assertEqual(table.metadata['page'], 1)
        picture = next(e for e in parsed.elements if e.modality == 'image')
        self.assertIn('Bar chart', picture.text)
        chunks = DoclingHybridChunker(ApproxTokenizer(max_tokens=500)).chunk(parsed)
        self.assertTrue(chunks)
        self.assertTrue(any('120' in c.content for c in chunks))
        self.assertTrue(any(c.modality == 'table' for c in chunks))
        self.assertTrue(any(c.metadata['pages'] == [1] for c in chunks))
        self.assertTrue(any('Quarterly results' in c.metadata['headings'] for c in chunks))

    def test_new_language_metadata_preserved_in_namespace(self):
        raw = self.payload['document']['json_content']
        raw['pictures'][0]['meta']['language'] = {'language': 'en', 'confidence': 0.9}
        parsed = decode_document(self.payload, self.settings)
        meta = parsed.native.pictures[0].meta.model_dump()
        # On newer clients this stays a native field; older clients retain it
        # under a named extension without changing structural information.
        value = meta.get('docling_serve__language', meta.get('language'))
        self.assertEqual(value['language'], 'en')
        self.assertEqual(raw['pictures'][0]['meta']['language']['language'], 'en')

    def test_partial_conversion_never_indexes(self):
        self.payload['status'] = 'partial_success'
        with self.assertRaises(DoclingServePartialConversion):
            decode_document(self.payload, self.settings)

    def test_failure_retryable_not_partial_output(self):
        self.payload['status'] = 'failure'
        with self.assertRaises(DoclingServeConversionFailed):
            decode_document(self.payload, self.settings)

    def test_success_with_errors_rejected(self):
        self.payload['errors'] = [{'error_message': 'sensitive server path'}]
        with self.assertRaises(DoclingServeSchemaMismatch):
            decode_document(self.payload, self.settings)

    def test_missing_json_not_downgraded_to_markdown(self):
        self.payload['document'] = {'md_content': '# Hello'}
        with self.assertRaises(DoclingServeSchemaMismatch):
            decode_document(self.payload, self.settings)

    def test_future_schema_rejected(self):
        self.payload['document']['json_content']['version'] = '99.0.0'
        with self.assertRaises(DoclingServeSchemaMismatch):
            decode_document(self.payload, self.settings)

    def test_local_fingerprint_unchanged_remote_versions_fenced(self):
        local = settings().model_copy(update={'RAG_PARSER_BACKEND': 'docling'})
        self.assertNotEqual(processing_version(local), processing_version(self.settings))
        changed = self.settings.model_copy(update={'DOCLING_SERVE_EXPECTED_VERSION': 'next'})
        self.assertNotEqual(processing_version(changed), processing_version(self.settings))
        key = self.settings.model_copy(update={'DOCLING_SERVE_API_KEY': SecretStr('new-secret')})
        self.assertEqual(processing_version(key), processing_version(self.settings))

    def test_config_rejects_urls_and_inverted_timeouts(self):
        for values in ({'DOCLING_SERVE_URL':'http://user:secret@server'},
                       {'DOCLING_SERVE_URL':'http://server/path'},
                       {'DOCLING_SERVE_HTTP_TIMEOUT_SECONDS': 950},
                       {'DOCLING_SERVE_DOCUMENT_TIMEOUT_SECONDS': 640}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                settings(**values)

    def test_picture_options_preserved_and_custom_threshold_rejected(self):
        local = settings(RAG_PICTURE_DESCRIPTION_ENABLED=True)
        payload = json.loads(form_options(local)['picture_description_local'])
        self.assertEqual(payload['repo_id'], local.RAG_PICTURE_DESCRIPTION_MODEL)
        self.assertEqual(payload['prompt'], local.RAG_PICTURE_DESCRIPTION_PROMPT)
        api = settings(RAG_PICTURE_DESCRIPTION_ENABLED=True, RAG_PICTURE_DESCRIPTION_BACKEND='api',
                       RAG_PICTURE_DESCRIPTION_API_URL='http://vision:8000/v1/chat/completions',
                       RAG_PICTURE_DESCRIPTION_API_MODEL='vision-model',
                       RAG_PICTURE_DESCRIPTION_API_KEY=SecretStr('test-key'))
        payload = json.loads(form_options(api)['picture_description_api'])
        self.assertEqual(payload['headers']['Authorization'], 'Bearer test-key')
        with self.assertRaises(ValidationError):
            settings(RAG_PICTURE_DESCRIPTION_ENABLED=True, RAG_PICTURE_MIN_AREA=0.1)


class HttpAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = settings(DOCLING_SERVE_API_KEY=SecretStr('internal-key'))
        self.payload = json.loads((FIXTURES / 'docling_serve_2_78_success.json').read_text())
        self.schema = json.loads((FIXTURES / 'docling_serve_1_21_contract.json').read_text())
        self.calls = []
        self.versions = {'docling-serve':'1.21.0','docling':'2.96.1','docling-core':'2.78.0'}

    def parser(self, *, conversion=None, version=None):
        async def handler(request):
            self.calls.append(request)
            self.assertEqual(request.headers['X-Api-Key'], 'internal-key')
            if request.url.path == '/version':
                return httpx.Response(200,json=version or self.versions)
            if request.url.path == '/openapi.json':
                return httpx.Response(200,json=self.schema)
            return conversion if conversion is not None else httpx.Response(200,json=self.payload)
        return DoclingServeParser(self.settings, transport=httpx.MockTransport(handler))

    async def test_multipart_txt_alias_flags_and_raw_bytes(self):
        parsed = await self.parser().parse(b'raw file bytes', 'private-name.txt')
        request = self.calls[-1]
        body = request.content
        self.assertEqual(request.url.path, '/v1/convert/file')
        self.assertIn(b'filename="document.md"', body)
        self.assertIn(b'raw file bytes', body)
        self.assertNotIn(b'private-name', body)
        self.assertIn(b'name="target_type"\r\n\r\ninbody', body)
        self.assertIn(b'name="to_formats"\r\n\r\njson', body)
        self.assertIn(b'name="do_ocr"\r\n\r\nfalse', body)
        self.assertIn(b'name="do_table_structure"\r\n\r\ntrue', body)
        self.assertIsNotNone(parsed.native)

    async def test_version_mismatch_stops_before_post(self):
        with self.assertRaises(DoclingServeVersionMismatch):
            await self.parser(version={**self.versions,'docling-core':'9.0.0'}).parse(b'x','test.pdf')
        self.assertEqual(len(self.calls),1)

    async def test_http_infrastructure_failures_retryable(self):
        for status in (408,429,500,503):
            with self.subTest(status=status), self.assertRaises(DoclingServeUnavailable):
                await self.parser(conversion=httpx.Response(status)).parse(b'x','test.pdf')

    async def test_http_config_errors_are_not_document_rejections(self):
        for status in (401,403,404,422):
            with self.subTest(status=status), self.assertRaises(DoclingServeConfigurationError):
                await self.parser(conversion=httpx.Response(status)).parse(b'x','test.pdf')

    async def test_413_is_terminal_document_error(self):
        with self.assertRaises(IngestionError):
            await self.parser(conversion=httpx.Response(413)).parse(b'x','test.pdf')

    async def test_transport_error_retryable(self):
        def handler(request):
            raise httpx.ConnectError('internal diagnostic',request=request)
        with self.assertRaises(DoclingServeUnavailable) as caught:
            await DoclingServeParser(self.settings,transport=httpx.MockTransport(handler)).parse(b'x','test.pdf')
        self.assertNotIn('internal diagnostic',str(caught.exception))

    async def test_invalid_json_and_oversized_response(self):
        with self.assertRaises(DoclingServeSchemaMismatch):
            await self.parser(conversion=httpx.Response(200,content=b'not-json')).parse(b'x','test.pdf')
        with self.assertRaises(DoclingServeSchemaMismatch):
            self.settings.DOCLING_SERVE_MAX_RESPONSE_MB = 1
            await self.parser(conversion=httpx.Response(200,content=b'x'*(1024*1024+1))).parse(b'x','test.pdf')

    async def test_schema_option_missing_fails_before_conversion(self):
        self.schema['components']['schemas']['Body_process_file_v1_convert_file_post']['properties'].pop('to_formats')
        with self.assertRaises(DoclingServeSchemaMismatch):
            await self.parser().parse(b'x','test.pdf')
        self.assertEqual(len(self.calls),2)

    async def test_cancellation_propagates(self):
        entered = asyncio.Event()
        exited = asyncio.Event()
        async def handler(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                exited.set()
        task = asyncio.create_task(DoclingServeParser(self.settings,
            transport=httpx.MockTransport(handler)).parse(b'x','test.pdf'))
        await asyncio.wait_for(entered.wait(),2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(exited.is_set())

    async def test_unsupported_and_empty_inputs_make_no_requests(self):
        for content, filename in ((b'','test.pdf'),(b'x','test.exe')):
            with self.assertRaises(IngestionError):
                await self.parser().parse(content,filename)
        self.assertEqual(self.calls,[])
