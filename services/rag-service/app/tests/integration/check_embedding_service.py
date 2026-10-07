"""Live numerical/retrieval parity gate. No DB/Redis/MinIO writes."""
import argparse
import asyncio
import httpx
import numpy as np
from app.core.config import get_settings
from app.rag.ingestion.embeddings.sentence_transformers_embedder import SentenceTransformersEmbedder
from app.rag.ingestion.model_paths import require_local_model
from app.rag.embeddings.client import HttpEmbeddingGenerator

PASSAGES=[
    'Redis Streams provide consumer groups and pending message recovery.',
    'BGE base embeddings use a 768 dimensional representation.',
    'MinIO stores uploaded document source files in an object bucket.',
    'PostgreSQL pgvector enables vector similarity search.',
    'The report shows Q2 revenue of 120 million rupees.',
    'Docling converts PDFs into structured document representations.',
]
QUERIES=['How are queued ingestion jobs recovered?', 'Where are uploaded files stored?', 'What was revenue in Q2?']
EDGE=['', '  Mixed CASE with trailing spaces  ', 'हिंदी मराठी café naïve İstanbul 😀',
      'line one\nline two\tindented', 'long passage ' * 800]

async def main(args):
    settings=get_settings()
    if args.url:settings=settings.model_copy(update={'EMBEDDING_SERVICE_URL':args.url})
    if not settings.EMBEDDING_SERVICE_REVISION:raise SystemExit('Missing model contract revision')
    headers={}
    secret=settings.EMBEDDING_SERVICE_API_KEY.get_secret_value()
    if secret:headers['X-Api-Key']=secret
    async with httpx.AsyncClient(timeout=20,trust_env=False) as client:
        response=await client.get(settings.EMBEDDING_SERVICE_URL+'/v1/model',headers=headers)
        response.raise_for_status();info=response.json()
    if (info['revision']!=settings.EMBEDDING_SERVICE_REVISION or info['query_prefix']!=''
            or info['document_prefix']!='' or info['max_length']!=512 or info['pooling']!='cls'):
        raise SystemExit('Service behavior identity differs from this migration baseline')
    baseline=await asyncio.to_thread(SentenceTransformersEmbedder,
        require_local_model(settings.RAG_EMBEDDING_MODEL,settings),768,32,'cpu')
    texts=PASSAGES+QUERIES+EDGE
    old=np.asarray(await baseline.embed(texts),dtype=np.float64)
    doc=HttpEmbeddingGenerator(settings,'document');query=HttpEmbeddingGenerator(settings,'query')
    new=np.asarray(await doc.embed(texts),dtype=np.float64)
    q=np.asarray(await query.embed(texts),dtype=np.float64)
    if old.shape!=new.shape or old.shape!=(len(texts),768):raise SystemExit('Shape mismatch')
    cosine=np.sum(old*new,axis=1)/(np.linalg.norm(old,axis=1)*np.linalg.norm(new,axis=1))
    maximum=np.max(np.abs(old-new));norms=np.linalg.norm(new,axis=1)
    print('Minimum old/new cosine:',float(cosine.min()),'; maximum absolute difference:',float(maximum))
    if (not np.isfinite(new).all() or cosine.min()<0.99999 or maximum>0.0001
            or np.max(np.abs(norms-1))>0.00001):raise SystemExit('FAILED: numerical parity; keep current backend')
    if np.max(np.abs(q-new))>0.00001:raise SystemExit('FAILED: unexpected query/document prefix behavior')
    singles=np.asarray([(await doc.embed([t]))[0] for t in texts],dtype=np.float64)
    if np.max(np.abs(singles-new))>0.0001:raise SystemExit('FAILED: batch/single parity')
    n=len(PASSAGES)
    old_rank=np.argsort(-(old[n:n+len(QUERIES)]@old[:n].T),axis=1)[:,:3]
    new_rank=np.argsort(-(new[n:n+len(QUERIES)]@new[:n].T),axis=1)[:,:3]
    if not np.array_equal(old_rank,new_rank):raise SystemExit('FAILED: fixed-corpus top-3 retrieval parity')
    print('Model revision:',info['revision'])
    print('CLS / normalization / Unicode / 512-token truncation / batch / query / top-3 rankings: OK')
    print('Embedding service parity: PASSED')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url')
    asyncio.run(main(parser.parse_args()))
