"""One CPU ONNX session and local fast tokenizer. No torch/transformers."""
import hashlib
import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

SEMANTICS = {'dimension':768, 'max_length':512, 'pooling':'cls',
             'normalization':'l2-twice', 'strip':True, 'lowercase':True,
             'query_prefix':'', 'document_prefix':'', 'padding':'right-longest',
             'adapter':'bge-onnx-1'}

def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()

def revision(manifest):
    value = {key:manifest[key] for key in ('model','semantics','files')}
    return 'bge-onnx-v1:' + hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class Encoder:
    def __init__(self, model_dir, manifest_path, threads=2):
        root = Path(model_dir).resolve()
        manifest = json.loads(Path(manifest_path).read_text())
        if (manifest['semantics'] != SEMANTICS or manifest['model'] != 'BAAI/bge-base-en-v1.5'
                or manifest['revision'] != revision(manifest)):
            raise ValueError('Unsupported model manifest/semantics')
        for name, expected in manifest['files'].items():
            file = (root/name).resolve()
            if not file.is_relative_to(root) or sha256(file) != expected:
                raise ValueError('Model artifact checksum mismatch: '+name)
        for name in ('onnx/model.onnx','tokenizer.json','1_Pooling/config.json','modules.json'):
            if name not in manifest['files']:
                raise ValueError('Missing required manifest entry: '+name)
        self.manifest = manifest
        self.tokenizer = Tokenizer.from_file(str(root/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=512, strategy='longest_first', direction='right')
        self.tokenizer.enable_padding(direction='right',pad_id=self.tokenizer.token_to_id('[PAD]'),
                                      pad_token='[PAD]',pad_type_id=0)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(root/'onnx/model.onnx'), options,
                                             providers=['CPUExecutionProvider'])
        self.inputs = self.session.get_inputs()
        if not {'input_ids','attention_mask'}.issubset({i.name for i in self.inputs}):
            raise ValueError('Graph lacks expected BERT input IDs/mask')
        for item in self.inputs:
            if (item.name not in {'input_ids','attention_mask','token_type_ids'}
                    or item.type not in {'tensor(int64)','tensor(int32)'} or len(item.shape)!=2
                    or any(isinstance(d,int) for d in item.shape)):
                raise ValueError('Graph must have supported dynamic batch/sequence integer inputs')
        output = next((o for o in self.session.get_outputs() if o.name=='last_hidden_state'),None)
        if output is None or output.type!='tensor(float)' or len(output.shape)!=3:
            raise ValueError('Expected float32 last_hidden_state; pooler_output is not CLS pooling')
        self.embed(['startup'],batch_size=1)

    def embed(self, texts, batch_size=8):
        vectors = []
        for start in range(0,len(texts),batch_size):
            encoded = self.tokenizer.encode_batch([text.strip().lower() for text in texts[start:start+batch_size]])
            if any(e.ids[0]!=self.tokenizer.token_to_id('[CLS]') for e in encoded):
                raise ValueError('Tokenizer must put CLS first')
            parts = {'input_ids':[e.ids for e in encoded], 'attention_mask':[e.attention_mask for e in encoded],
                     'token_type_ids':[e.type_ids for e in encoded]}
            inputs = {i.name:np.asarray(parts[i.name],dtype=np.int64 if i.type=='tensor(int64)' else np.int32)
                      for i in self.inputs}
            hidden = self.session.run(['last_hidden_state'],inputs)[0]
            if hidden.ndim!=3 or hidden.shape[0]!=len(encoded) or hidden.shape[2]!=768:
                raise ValueError('Invalid graph output dimensions')
            pooled = np.array(hidden[:,0,:],dtype=np.float32,copy=True)
            for _ in range(2):
                norms = np.linalg.norm(pooled,axis=1,keepdims=True)
                if not np.isfinite(pooled).all() or not np.isfinite(norms).all() or (norms<=0).any():
                    raise ValueError('Invalid or zero embedding')
                pooled /= np.maximum(norms,np.float32(1e-12))
            vectors.extend(pooled.tolist())
        return vectors

    def info(self):
        return {'model':self.manifest['model'], 'revision':self.manifest['revision'],
                **SEMANTICS, 'provider':'CPUExecutionProvider',
                'inputs':[{'name':i.name,'type':i.type,'shape':i.shape} for i in self.inputs]}
