"""Hash and validate the existing model. No download/export or app edits."""
import argparse
import hashlib
import json
from pathlib import Path

SEMANTICS={'dimension':768,'max_length':512,'pooling':'cls','normalization':'l2-twice',
           'strip':True,'lowercase':True,'query_prefix':'','document_prefix':'',
           'padding':'right-longest','adapter':'bge-onnx-1'}

def digest(path):
    hash=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''): hash.update(block)
    return hash.hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-dir',default='services/rag-service/models/BAAI--bge-base-en-v1.5')
    args=parser.parse_args();root=Path(args.model_dir).resolve()
    baseline=json.loads(Path('docs/step11_model_baseline.json').read_text())
    files={}
    for item in baseline['model_files']:
        if item['path'] in {'model.safetensors','pytorch_model.bin'}:continue
        path=(root/item['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise SystemExit('Missing model file: '+item['path'])
        actual=digest(path)
        if item.get('sha256') and actual!=item['sha256']:
            raise SystemExit('Model file differs from uploaded baseline: '+item['path']+'; review before switching')
        files[item['path']]=actual
    manifest={'model':'BAAI/bge-base-en-v1.5','semantics':SEMANTICS,'files':files}
    manifest['revision']='bge-onnx-v1:'+hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    target=Path('services/embedding-service/model-manifest.json')
    if target.exists() and json.loads(target.read_text())!=manifest:
        raise SystemExit('Existing model manifest differs. Review the changed artifacts before replacing it.')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(manifest,indent=2)+'\n')
    Path('services/embedding-service/contract.env').write_text('EMBEDDING_SERVICE_REVISION='+manifest['revision']+'\n')
    print('Model verified; manifest and contract.env created. Weights remain in their existing folder.')
    print('Revision:',manifest['revision'])
if __name__=='__main__':main()
