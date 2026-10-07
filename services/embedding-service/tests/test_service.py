import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
import onnx
from onnx import TensorProto, helper
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors
from fastapi.testclient import TestClient
from app.encoder import Encoder, SEMANTICS, revision, sha256
from app.main import app, InferenceQueue, QueueFull

REV='bge-onnx-v1:'+'a'*64

class EncoderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'onnx').mkdir();(self.root/'1_Pooling').mkdir()
        tok=Tokenizer(models.WordPiece({'[PAD]':0,'[UNK]':1,'[CLS]':2,'[SEP]':3,'hello':4,'world':5},unk_token='[UNK]'))
        tok.normalizer=normalizers.BertNormalizer(lowercase=True)
        tok.pre_tokenizer=pre_tokenizers.BertPreTokenizer()
        tok.post_processor=processors.BertProcessing(('[SEP]',3),('[CLS]',2))
        tok.save(str(self.root/'tokenizer.json'))
        (self.root/'1_Pooling/config.json').write_text('{}');(self.root/'modules.json').write_text('[]')
        nodes=[helper.make_node('Cast',['input_ids'],['cast'],to=TensorProto.FLOAT),
               helper.make_node('Unsqueeze',['cast','axes'],['expanded']),
               helper.make_node('Add',['expanded','offset'],['last_hidden_state'])]
        inputs=[helper.make_tensor_value_info(n,TensorProto.INT64,['batch','sequence'])
                for n in ('input_ids','attention_mask','token_type_ids')]
        output=helper.make_tensor_value_info('last_hidden_state',TensorProto.FLOAT,['batch','sequence',768])
        graph=helper.make_graph(nodes,'tiny-token-output',inputs,[output],[
            helper.make_tensor('axes',TensorProto.INT64,[1],[2]),
            helper.make_tensor('offset',TensorProto.FLOAT,[768],np.arange(768,dtype=np.float32))])
        model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)]);model.ir_version=10
        onnx.save(model,self.root/'onnx/model.onnx')
        self.manifest={'model':'BAAI/bge-base-en-v1.5','semantics':SEMANTICS,
            'files':{n:sha256(self.root/n) for n in ('onnx/model.onnx','tokenizer.json','1_Pooling/config.json','modules.json')}}
        self.manifest['revision']=revision(self.manifest)
        self.path=self.root/'manifest.json';self.path.write_text(json.dumps(self.manifest))
    def tearDown(self):self.tmp.cleanup()
    def test_real_ort_cls_pooling_norm_and_dynamic_batch(self):
        encoder=Encoder(self.root,self.path,1)
        vectors=np.array(encoder.embed(['HELLO world','hello','word '*700],2))
        expected=np.arange(768,dtype=np.float32)+2
        expected/=np.linalg.norm(expected)
        self.assertEqual(vectors.shape,(3,768))
        np.testing.assert_allclose(vectors[0],expected,atol=1e-7)
        np.testing.assert_allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-6)
        self.assertEqual(encoder.info()['provider'],'CPUExecutionProvider')
        self.assertEqual(len(encoder.tokenizer.encode('word '*700).ids),512)
        np.testing.assert_allclose(encoder.embed(['hello']),encoder.embed(['hello','world'])[:1],atol=1e-7)
    def test_changed_weight_fails_before_inference(self):
        with (self.root/'onnx/model.onnx').open('ab') as file:file.write(b'changed')
        with self.assertRaises(ValueError):Encoder(self.root,self.path)
    def test_changed_semantics_revision_rejected(self):
        self.manifest['semantics']={**SEMANTICS,'pooling':'mean'}
        self.manifest['revision']=revision(self.manifest);self.path.write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):Encoder(self.root,self.path)

class FakeEncoder:
    def __init__(self,*args):self.manifest={'revision':REV}
    def info(self):return {'revision':REV,'dimension':768}
    def embed(self,texts,batch_size=8):return [[1.]+[0.]*767 for _ in texts]

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch('app.main.Encoder',FakeEncoder);self.patch.start()
        self.env=patch.dict(os.environ,{'EMBEDDING_SERVICE_API_KEY':''});self.env.start()
        self.client=TestClient(app);self.client.__enter__()
        self.payload={'model':'BAAI/bge-base-en-v1.5','revision':REV,'input_type':'query','texts':['Hello','world']}
    def tearDown(self):self.client.__exit__(None,None,None);self.env.stop();self.patch.stop()
    def test_contract_order_and_readiness(self):
        result=self.client.post('/v1/embeddings',json=self.payload)
        self.assertEqual(result.status_code,200);self.assertEqual(len(result.json()['vectors']),2)
        self.assertEqual(result.json()['input_type'],'query')
        self.assertEqual(self.client.get('/ready').status_code,200)
    def test_bad_revision_is_409(self):
        self.assertEqual(self.client.post('/v1/embeddings',json={**self.payload,'revision':'other'}).status_code,409)
    def test_invalid_requests_rejected(self):
        for changes in ({'texts':[]},{'texts':['x']*33},{'texts':[1]},{'input_type':'other'},{'extra':'field'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post('/v1/embeddings',json={**self.payload,**changes}).status_code,422)
    def test_body_limit(self):
        response=self.client.post('/v1/embeddings',content=b'x'*(512*1024+1),headers={'content-type':'application/json'})
        self.assertEqual(response.status_code,413)
    def test_api_key(self):
        with patch.dict(os.environ,{'EMBEDDING_SERVICE_API_KEY':'secret'}):
            self.assertEqual(self.client.post('/v1/embeddings',json=self.payload).status_code,401)
            self.assertEqual(self.client.post('/v1/embeddings',json=self.payload,headers={'X-Api-Key':'secret'}).status_code,200)
    def test_inference_failure_sanitized(self):
        with patch.object(app.state.encoder,'embed',side_effect=RuntimeError('private diagnostic')):
            response=self.client.post('/v1/embeddings',json=self.payload)
            self.assertEqual(response.status_code,503);self.assertNotIn('private',response.text)

class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_request_does_not_release_native_inference_early(self):
        entered=threading.Event();release=threading.Event();calls=[]
        class Blocking:
            def embed(self,texts,batch_size):
                calls.append(texts)
                if len(calls)==1:entered.set();release.wait(3)
                return texts
        queue=InferenceQueue(Blocking(),capacity=1)
        runner=asyncio.create_task(queue.run())
        first=asyncio.create_task(queue.submit(['first']))
        try:
            await asyncio.wait_for(asyncio.to_thread(entered.wait,2),3)
            first.cancel();await asyncio.gather(first,return_exceptions=True)
            second=asyncio.create_task(queue.submit(['second']))
            await asyncio.sleep(0)
            self.assertEqual(len(calls),1)
            with self.assertRaises(QueueFull):await queue.submit(['third'])
            release.set();self.assertEqual(await second,['second'])
        finally:
            release.set();runner.cancel();await asyncio.gather(runner,return_exceptions=True)
