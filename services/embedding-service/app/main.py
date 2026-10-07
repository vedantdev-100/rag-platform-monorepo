import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from starlette.responses import JSONResponse
from app.encoder import Encoder

class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: Literal['BAAI/bge-base-en-v1.5']
    revision: str = Field(min_length=1,max_length=128)
    input_type: Literal['query','document']
    texts: list[Annotated[str,StringConstraints(strict=True,max_length=20000)]] = Field(min_length=1,max_length=32)

class QueueFull(Exception):
    pass

class InferenceQueue:
    def __init__(self,encoder,*,capacity=32,batch_size=8):
        self.encoder=encoder
        self.queue=asyncio.Queue(maxsize=capacity)
        self.batch_size=batch_size

    async def submit(self,texts):
        future=asyncio.get_running_loop().create_future()
        try:
            self.queue.put_nowait((texts,future))
        except asyncio.QueueFull as exc:
            raise QueueFull() from exc
        try:
            return await asyncio.wait_for(asyncio.shield(future),timeout=60)
        finally:
            # Native inference stays owned by run() until its thread finishes.
            if not future.done():
                future.cancel()

    async def run(self):
        while True:
            texts,future=await self.queue.get()
            try:
                if future.cancelled():
                    continue
                try:
                    vectors=await asyncio.to_thread(self.encoder.embed,texts,self.batch_size)
                    if not future.done():
                        future.set_result(vectors)
                except Exception as exc:
                    if not future.done():
                        future.set_exception(exc)
            finally:
                self.queue.task_done()

@asynccontextmanager
async def lifespan(app):
    encoder=await asyncio.to_thread(Encoder,os.getenv('MODEL_DIR','/models/bge'),
                                    os.getenv('MODEL_MANIFEST','/config/model-manifest.json'),2)
    app.state.encoder=encoder
    app.state.scheduler=InferenceQueue(encoder)
    task=asyncio.create_task(app.state.scheduler.run())
    app.state.inference_task=task
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)

app=FastAPI(title='BGE CPU ONNX embeddings',lifespan=lifespan)

class BodyLimit:
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']=='http' and scope['method']=='POST':
            chunks=[];size=0
            try:
                while True:
                    message=await asyncio.wait_for(receive(),timeout=10)
                    if message['type']=='http.disconnect': return
                    body=message.get('body',b'');size+=len(body)
                    if size>512*1024:
                        await JSONResponse({'detail':'request_too_large'},status_code=413)(scope,receive,send);return
                    chunks.append(body)
                    if not message.get('more_body',False): break
            except asyncio.TimeoutError:
                await JSONResponse({'detail':'body_timeout'},status_code=408)(scope,receive,send);return
            sent=False
            async def replay():
                nonlocal sent
                if not sent:
                    sent=True;return {'type':'http.request','body':b''.join(chunks),'more_body':False}
                return await receive()
            await self.app(scope,replay,send)
        else:
            await self.app(scope,receive,send)
app.add_middleware(BodyLimit)

def authenticate(key):
    import secrets
    expected=os.getenv('EMBEDDING_SERVICE_API_KEY','')
    if expected and (key is None or not secrets.compare_digest(key,expected)):
        raise HTTPException(401,'invalid_api_key')

@app.get('/health')
async def health(): return {'status':'ok'}

@app.get('/ready')
async def ready():
    if not hasattr(app.state,'encoder') or app.state.inference_task.done():
        raise HTTPException(503,'not_ready')
    return {'status':'ready'}

@app.get('/v1/model')
async def model(x_api_key: str|None=Header(default=None)):
    authenticate(x_api_key)
    return app.state.encoder.info()

@app.post('/v1/embeddings')
async def embeddings(request:EmbeddingRequest,x_api_key: str|None=Header(default=None)):
    authenticate(x_api_key)
    if request.revision!=app.state.encoder.manifest['revision']:
        raise HTTPException(409,'embedding_revision_mismatch')
    if app.state.inference_task.done():
        raise HTTPException(503,'inference_unavailable')
    try:
        vectors=await app.state.scheduler.submit(request.texts)
    except QueueFull:
        raise HTTPException(429,'inference_queue_full',headers={'Retry-After':'2'})
    except Exception:
        raise HTTPException(503,'inference_failed')
    return {'model':request.model,'revision':request.revision,'input_type':request.input_type,
            'dimension':768,'vectors':vectors}
