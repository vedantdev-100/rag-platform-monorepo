"""Offline boundary tests; no paid APIs, live database or model weights."""
import json
import unittest
import uuid

import httpx
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.exceptions import RetrievalError
from app.rag.retrieval.base import RetrievedChunk, reciprocal_rank_fusion
from app.rag.retrieval.service import RetrievalService
from app.rag.retrieval.rerankers.cohere_reranker import CohereReranker
from app.rag.retrieval.rerankers.voyage_reranker import VoyageReranker
from app.schemas.search import SearchRequest
from rag_persistence.repositories.chunk_repository import ChunkRepository


def chunk(index):
    return RetrievedChunk(str(index), "doc", f"text {index}", 0.5,
                          metadata={"pages": [1], "headings": ["Example"]})


class Session:
    def __init__(self):
        self.active = False
        self.rollbacks = 0
    def in_transaction(self):
        return self.active
    async def rollback(self):
        self.rollbacks += 1
        self.active = False


class Retriever:
    def __init__(self, session, *, empty=False, fail=False):
        self.session, self.empty, self.fail = session, empty, fail
        self.calls = []
    async def retrieve(self, query, *, owner_id, top_k):
        self.calls.append((query, owner_id, top_k))
        self.session.active = True
        if self.fail:
            raise RuntimeError("DB read failed")
        return [] if self.empty else [chunk(i) for i in range(top_k)]


class RequestTests(unittest.TestCase):
    def test_query_trim_preserves_meaning(self):
        self.assertEqual(SearchRequest(query="  Explain RAG? \n").query, "Explain RAG?")
        self.assertIsNone(SearchRequest(query="hello").top_k)

    def test_invalid_queries_and_limits(self):
        for query in ("", " \t\n", "x" * 2001):
            with self.subTest(query_length=len(query)), self.assertRaises(ValidationError):
                SearchRequest(query=query)
        for limit in (0, -1, 51, True, "5", 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValidationError):
                SearchRequest(query="query", top_k=limit)

    def test_rrf_deduplicates_and_retains_citation_metadata(self):
        a, b, shared = chunk(1), chunk(2), chunk(3)
        results = reciprocal_rank_fusion([[a, shared], [b, shared]])
        self.assertEqual(results[0].chunk_id, shared.chunk_id)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].metadata, shared.metadata)


class ConfigurationTests(unittest.TestCase):
    def settings(self, **kwargs):
        from app.core.config import Settings
        return Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
                        RAG_RUNTIME_ROLE="development", RAG_PARSER_BACKEND="docling",
                        RAG_EMBEDDING_BACKEND="stub", **kwargs)

    def test_environment_style_integer_values_remain_supported(self):
        settings = self.settings(RAG_DEFAULT_TOP_K="5", RAG_RETRIEVAL_CANDIDATES="20")
        self.assertEqual(settings.RAG_DEFAULT_TOP_K, 5)
        self.assertEqual(settings.RAG_RETRIEVAL_CANDIDATES, 20)

    def test_unbounded_or_invalid_configuration_is_rejected(self):
        for field, value in (("RAG_DEFAULT_TOP_K", 51), ("RAG_RETRIEVAL_CANDIDATES", 101),
                             ("RAG_RRF_K", 0), ("RAG_RERANKER_TOP_N", 0)):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.settings(**{field: value})


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def service(self, session, *, backend="hybrid", reranker=None, **kwargs):
        retriever = Retriever(session, **kwargs)
        return RetrievalService(retriever, reranker, backend=backend,
                                default_top_k=5, candidates=20), retriever

    async def test_default_returns_five_from_twenty_candidates(self):
        session = Session(); service, retriever = self.service(session)
        result = await service.retrieve(session, " query ", owner_id="owner")
        self.assertEqual(retriever.calls, [("query", "owner", 20)])
        self.assertEqual(len(result.results), 5)
        self.assertFalse(result.reranked)
        self.assertFalse(session.active)

    async def test_explicit_small_k_keeps_broad_hybrid_pool(self):
        session = Session(); service, retriever = self.service(session)
        result = await service.retrieve(session, "query", owner_id="owner", top_k=2)
        self.assertEqual(retriever.calls[0][2], 20)
        self.assertEqual(len(result.results), 2)

    async def test_requested_k_larger_than_pool_is_supported(self):
        session = Session(); service, retriever = self.service(session)
        result = await service.retrieve(session, "query", owner_id="owner", top_k=50)
        self.assertEqual(retriever.calls[0][2], 50)
        self.assertEqual(len(result.results), 50)

    async def test_pure_search_without_reranker_uses_final_limit(self):
        for backend in ("vector", "keyword"):
            session = Session(); service, retriever = self.service(session, backend=backend)
            await service.retrieve(session, "query", owner_id="owner")
            self.assertEqual(retriever.calls[0][2], 5)

    async def test_remote_reranking_starts_after_transaction_release(self):
        session = Session()
        class Reranker:
            async def rerank(inner, query, chunks, *, top_n):
                self.assertFalse(session.in_transaction())
                self.assertEqual(session.rollbacks, 1)
                self.assertEqual(len(chunks), 20)
                self.assertEqual(top_n, 5)
                return list(reversed(chunks))[:top_n]
        service, _ = self.service(session, reranker=Reranker())
        result = await service.retrieve(session, "query", owner_id="owner")
        self.assertTrue(result.reranked)
        self.assertEqual(result.results[0].chunk_id, "19")

    async def test_empty_results_skip_reranking(self):
        class Reranker:
            async def rerank(self, *args, **kwargs):
                raise AssertionError("Empty candidates must not call the provider")
        session = Session(); service, _ = self.service(session, reranker=Reranker(), empty=True)
        result = await service.retrieve(session, "query", owner_id="owner")
        self.assertEqual(result.results, [])
        self.assertFalse(result.reranked)

    async def test_database_failure_also_releases_transaction(self):
        session = Session(); service, _ = self.service(session, fail=True)
        with self.assertRaises(RuntimeError):
            await service.retrieve(session, "query", owner_id="owner")
        self.assertFalse(session.active)
        self.assertEqual(session.rollbacks, 1)

    async def test_active_caller_transaction_is_not_rolled_back(self):
        session = Session(); session.active = True
        service, retriever = self.service(session)
        with self.assertRaises(RuntimeError):
            await service.retrieve(session, "query", owner_id="owner")
        self.assertEqual(retriever.calls, [])
        self.assertEqual(session.rollbacks, 0)

    async def test_invalid_internal_input_does_not_start_work(self):
        session = Session(); service, retriever = self.service(session)
        for query, limit in ((" ", 5), ("query", 51), ("query", True)):
            with self.assertRaises(ValueError):
                await service.retrieve(session, query, owner_id="owner", top_k=limit)
        self.assertEqual(retriever.calls, [])


class RepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_queries_bind_owner_and_ingested_status(self):
        statements = []
        class Session:
            async def execute(self, statement):
                statements.append(statement)
                class Result:
                    def all(self): return []
                return Result()
        owner = uuid.uuid4()
        repo = ChunkRepository(Session(), default_top_k=5)
        await repo.similarity_search([1.] + [0.] * 767, owner_id=owner, top_k=20)
        await repo.keyword_search("retrieval", owner_id=owner, top_k=20)
        for statement in statements:
            compiled = statement.compile(dialect=postgresql.dialect())
            where = str(compiled).split("WHERE", 1)[1]
            self.assertIn("documents.owner_id =", where)
            self.assertIn("documents.status =", where)
            self.assertIn(owner, compiled.params.values())
            self.assertIn("ingested", compiled.params.values())
            self.assertIn(20, compiled.params.values())


class RerankerTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_results_keep_only_real_chunks_and_metadata(self):
        for cls, key, limit_key in ((CohereReranker, "results", "top_n"),
                                    (VoyageReranker, "data", "top_k")):
            def handler(request):
                payload = json.loads(request.content)
                self.assertEqual(payload[limit_key], 2)
                return httpx.Response(200, json={key: [{"index": 1, "relevance_score": .8},
                                                       {"index": 0, "relevance_score": .2}]})
            reranker = cls("test", "model", transport=httpx.MockTransport(handler))
            results = await reranker.rerank("query", [chunk(0), chunk(1)], top_n=5)
            self.assertEqual([r.chunk_id for r in results], ["1", "0"])
            self.assertEqual(results[0].metadata["pages"], [1])

    async def test_invalid_remote_results_raise_controlled_error(self):
        bad = [None, {}, [{"index": -1, "relevance_score": .5}],
               [{"index": 5, "relevance_score": .5}], [{"index": True, "relevance_score": .5}],
               [{"index": 0, "relevance_score": True}], [{"index": 0, "relevance_score": "0.5"}],
               [{"index": 0, "relevance_score": float("nan")}],
               [{"index": 0, "relevance_score": 10 ** 400}],
               [{"index": 0, "relevance_score": .8}, {"index": 0, "relevance_score": .3}]]
        for cls, key in ((CohereReranker, "results"), (VoyageReranker, "data")):
            for rows in bad:
                with self.subTest(provider=key, kind=type(rows).__name__):
                    transport = httpx.MockTransport(lambda request: httpx.Response(200,
                        content=json.dumps({key: rows}).encode(), headers={"content-type": "application/json"}))
                    reranker = cls("test", "model", transport=transport)
                    with self.assertRaises(RetrievalError):
                        await reranker.rerank("query", [chunk(0), chunk(1)], top_n=2)

    async def test_http_and_invalid_json_failures_are_sanitized(self):
        for status, body in ((503, b"private provider detail"), (200, b"not JSON")):
            transport = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
            reranker = CohereReranker("secret", "model", transport=transport)
            with self.assertRaises(RetrievalError) as caught:
                await reranker.rerank("query", [chunk(0)])
            self.assertNotIn("private", str(caught.exception))
            self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
