"""Executed in a temporary API-container subprocess, never in the API server."""
import asyncio
import dataclasses
import hashlib
import json
import pathlib
import sys


def digest(path):
    return hashlib.sha256(pathlib.Path(path).read_text().replace('\r\n', '\n').encode()).hexdigest()


async def capture(payload):
    import httpx
    from app.rag.generation.settings import get_generation_settings
    from app.rag.generation.providers.openai_compatible import build_provider
    from app.rag.generation.service import GenerationService
    from app.rag.retrieval.base import RetrievedChunk

    for path, expected in payload['expected_hashes'].items():
        # Resolve imports relative to the installed app, not the caller's cwd.
        import app
        actual = pathlib.Path(app.__file__).resolve().parent.parent / path
        if digest(actual) != expected:
            raise RuntimeError('step14_source_mismatch:' + path)
    settings = get_generation_settings()
    if payload['mode'] != 'retriever' and (not settings.active or settings.RAG_GENERATION_STRATEGY != 'standard'):
        raise RuntimeError('enable_standard_generation_first')
    trace = {'case_id': payload['case']['case_id'], 'mode': payload['mode'],
             'query': payload['case']['query'], 'retrieved': [], 'messages': [],
             'raw_result': None, 'answer': None, 'error': None,
             'source_hashes': payload['expected_hashes'],
             'settings': {'provider': settings.RAG_LLM_PROVIDER, 'model': settings.model,
                          'context_max_bytes': settings.RAG_CONTEXT_MAX_BYTES,
                          'context_max_chunks': settings.RAG_CONTEXT_MAX_CHUNKS,
                          'top_k': payload['top_k']}}
    from app.core.config import get_settings
    core = get_settings()
    trace['settings'].update({key: getattr(core, key, None) for key in (
        'EMBEDDING_SERVICE_REVISION', 'RAG_EMBEDDING_MODEL', 'RAG_EMBEDDING_BACKEND',
        'RAG_RETRIEVER_BACKEND', 'RAG_RETRIEVAL_CANDIDATES', 'RAG_RERANKER_BACKEND',
        'RAG_CHUNKER_BACKEND', 'RAG_CHUNKER_MAX_TOKENS')})
    if payload.get('expected_settings') and payload['expected_settings'] != trace['settings']:
        raise RuntimeError('evaluation_configuration_changed:use_a_new_capture_file')
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=120,
             headers={'Authorization': 'Bearer ' + payload['token']}) as client:
        async def guard():
            r = await client.get('/api/v1/documents', params={'limit': 1})
            if r.status_code != 200:
                from app.rag.generation.types import GenerationError
                raise GenerationError('evaluation_authorization_failed', r.status_code)

        class Retriever:
            async def retrieve(self, query, *, owner_id, top_k):
                if payload['mode'] == 'oracle':
                    rows = [dict(chunk_id='gold-' + str(i),
                                 document_id=payload['document_map'][e['document_key']]['id'],
                                 content=e['text'], score=1.0, modality='text',
                                 metadata={'page_number': e['page_index'] + 1})
                            for i, e in enumerate(payload['case']['evidence'])]
                else:
                    r = await client.post('/api/v1/documents/search',
                                          json={'query': query, 'top_k': top_k})
                    if r.status_code != 200:
                        from app.rag.generation.types import GenerationError
                        raise GenerationError('evaluation_search_http_' + str(r.status_code), r.status_code)
                    data = r.json()
                    rows = data['results']
                    trace['retrieval_backend'] = data.get('retriever_backend')
                    trace['reranked'] = data.get('reranked')
                trace['retrieved'] = rows
                return [RetrievedChunk(**row) for row in rows]

        class Provider:
            def __init__(self):
                self.inner = build_provider(settings)
            async def generate(self, messages, emit):
                # Exact input, including any context-builder truncation.
                trace['messages'] = messages
                result = await self.inner.generate(messages, emit)
                trace['raw_result'] = dataclasses.asdict(result)
                return result
            async def close(self):
                await self.inner.close()

        try:
            await guard()
            if payload['mode'] == 'retriever':
                await Retriever().retrieve(payload['case']['query'], owner_id='http-scoped',
                                           top_k=payload['top_k'])
            else:
                provider = Provider()
                service = GenerationService(settings, Retriever(), provider)
                try:
                    answer = await service.run(payload['case']['query'], 'http-scoped',
                                               payload['top_k'], guard=guard)
                    trace['answer'] = answer.model_dump()
                finally:
                    await service.close()
        except Exception as exc:
            trace['error'] = getattr(exc, 'code', type(exc).__name__)
    return trace


if __name__ == '__main__':
    try:
        result = asyncio.run(capture(json.load(sys.stdin)))
    except Exception as exc:
        # Do not print exception bodies: they can contain service details.
        result = {'fatal': str(exc) if str(exc).startswith(('step14_source_mismatch:',
                    'enable_standard_generation_first', 'evaluation_configuration_changed:')) else type(exc).__name__}
    print('STEP15_RESULT=' + json.dumps(result, ensure_ascii=False))
