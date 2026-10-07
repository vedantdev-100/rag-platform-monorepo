import json
import unittest
import httpx
from app.core.config import Settings
from app.rag.embeddings.client import HttpEmbeddingGenerator, EmbeddingServiceError

REV='bge-onnx-v1:'+'a'*64

def vector(index=0):
    values=[0.]*768;values[index]=1.;return values

class ClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings=Settings(_env_file=None,DATABASE_URL='postgresql+asyncpg://t:t@localhost/t',
            RAG_EMBEDDING_BACKEND='http',EMBEDDING_SERVICE_REVISION=REV)
        self.calls=[]
    def client(self,*,change=None,status=200,input_type='document'):
        def handler(request):
            value=json.loads(request.content);self.calls.append(value)
            result={'model':value['model'],'revision':REV,'dimension':768,
                    'input_type':input_type,'vectors':[vector(int(t)%768) for t in value['texts']]}
            if change:result.update(change)
            return httpx.Response(status,content=json.dumps(result),headers={'content-type':'application/json'})
        return HttpEmbeddingGenerator(self.settings,input_type,transport=httpx.MockTransport(handler))
    async def test_batch_split_count_and_order(self):
        values=await self.client().embed([str(i) for i in range(35)])
        self.assertEqual([len(v['texts']) for v in self.calls],[32,3])
        self.assertEqual([v.index(1.) for v in values],list(range(35)))
    async def test_query_mode_has_no_client_prefix(self):
        await self.client(input_type='query').embed(['1'])
        self.assertEqual(self.calls[0]['input_type'],'query');self.assertEqual(self.calls[0]['texts'],['1'])
    async def test_empty_input_no_network(self):
        self.assertEqual(await self.client().embed([]),[]);self.assertEqual(self.calls,[])
    async def test_response_identity_must_match(self):
        for changes in ({'revision':'wrong'},{'dimension':384},{'model':'other'},{'input_type':'query'},{'vectors':[]}):
            with self.subTest(changes=changes),self.assertRaises(EmbeddingServiceError):
                await self.client(change=changes).embed(['1'])
    async def test_invalid_vectors_rejected(self):
        bad=vector();bad[0]=True
        nan=vector();nan[0]=float('nan')
        for value in (bad,nan,[0.]*768,[1.]*768,[1.]*384):
            with self.subTest(kind=str(value[:2])),self.assertRaises(EmbeddingServiceError):
                await self.client(change={'vectors':[value]}).embed(['1'])
    async def test_outages_and_contract_errors_no_fallback(self):
        for status in (401,409,429,500,503):
            with self.subTest(status=status),self.assertRaises(EmbeddingServiceError):
                await self.client(status=status).embed(['1'])
    async def test_transport_error_sanitized(self):
        def handler(request):raise httpx.ConnectError('private',request=request)
        with self.assertRaises(EmbeddingServiceError) as caught:
            await HttpEmbeddingGenerator(self.settings,transport=httpx.MockTransport(handler)).embed(['1'])
        self.assertNotIn('private',str(caught.exception))


class HybridOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_vector_embedding_and_read_before_keyword_read(self):
        from app.rag.retrieval.hybrid_retriever import HybridRetriever
        order=[]
        class Vector:
            async def retrieve(self,*args,**kwargs):order.append('vector');return []
        class Keyword:
            async def retrieve(self,*args,**kwargs):order.append('keyword');return []
        self.assertEqual(await HybridRetriever(Vector(),Keyword()).retrieve('query',owner_id='owner'),[])
        self.assertEqual(order,['vector','keyword'])
    async def test_embedding_outage_does_not_start_keyword_transaction(self):
        from app.rag.retrieval.hybrid_retriever import HybridRetriever
        order=[]
        class Vector:
            async def retrieve(self,*args,**kwargs):raise EmbeddingServiceError('offline')
        class Keyword:
            async def retrieve(self,*args,**kwargs):order.append('keyword');return []
        with self.assertRaises(EmbeddingServiceError):
            await HybridRetriever(Vector(),Keyword()).retrieve('query',owner_id='owner')
        self.assertEqual(order,[])
