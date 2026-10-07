"""Shared ingestion/query embedding client. Output identity is mandatory."""
import json
import math
import httpx
from app.rag.ingestion.base import EmbeddingGenerator

class EmbeddingServiceError(RuntimeError):
    pass

class HttpEmbeddingGenerator(EmbeddingGenerator):
    def __init__(self,settings,input_type='document',*,transport=None):
        self.settings=settings;self.input_type=input_type;self.transport=transport
        if input_type not in {'document','query'}:raise ValueError('Unknown embedding input type')

    @property
    def dimensions(self):return 768

    async def embed(self,texts):
        if not texts:return []
        vectors=[];s=self.settings
        headers={}
        secret=s.EMBEDDING_SERVICE_API_KEY.get_secret_value()
        if secret:headers['X-Api-Key']=secret
        timeout=httpx.Timeout(s.EMBEDDING_SERVICE_TIMEOUT_SECONDS,connect=5,write=10,pool=5)
        try:
            async with httpx.AsyncClient(base_url=s.EMBEDDING_SERVICE_URL.rstrip('/')+'/',
                    headers=headers,timeout=timeout,follow_redirects=False,trust_env=False,
                    transport=self.transport) as client:
                for start in range(0,len(texts),32):
                    batch=texts[start:start+32]
                    if any(not isinstance(t,str) or len(t)>20000 for t in batch):
                        raise EmbeddingServiceError('Invalid embedding input')
                    payload={'model':s.RAG_EMBEDDING_MODEL,'revision':s.EMBEDDING_SERVICE_REVISION,
                             'input_type':self.input_type,'texts':batch}
                    body=json.dumps(payload,ensure_ascii=False).encode()
                    if len(body)>512*1024:raise EmbeddingServiceError('Embedding batch exceeds size limit')
                    async with client.stream('POST','v1/embeddings',content=body,
                            headers={'Content-Type':'application/json'}) as response:
                        if response.status_code!=200:
                            raise EmbeddingServiceError('Embedding service HTTP '+str(response.status_code))
                        content=bytearray()
                        async for part in response.aiter_bytes():
                            if len(content)+len(part)>2*1024*1024:
                                raise EmbeddingServiceError('Embedding response too large')
                            content.extend(part)
                        data=json.loads(content)
                    if (not isinstance(data,dict) or data.get('model')!=s.RAG_EMBEDDING_MODEL
                            or data.get('revision')!=s.EMBEDDING_SERVICE_REVISION
                            or data.get('dimension')!=768 or data.get('input_type')!=self.input_type):
                        raise EmbeddingServiceError('Embedding response contract mismatch')
                    result=data.get('vectors')
                    if not isinstance(result,list) or len(result)!=len(batch):
                        raise EmbeddingServiceError('Embedding response count mismatch')
                    for vector in result:
                        if (not isinstance(vector,list) or len(vector)!=768
                                or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vector)
                                or abs(math.sqrt(sum(x*x for x in vector))-1)>0.001):
                            raise EmbeddingServiceError('Invalid embedding vector')
                    vectors.extend(result)
        except (httpx.RequestError,ValueError,TypeError,KeyError) as exc:
            raise EmbeddingServiceError('Embedding transport or response error') from exc
        return vectors
