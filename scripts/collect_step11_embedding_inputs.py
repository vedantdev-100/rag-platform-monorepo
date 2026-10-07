"""Collect an explicit embedding handoff. Run from monorepo root; stdlib only.
Does not change app files or collect credentials, documents, model weights or DB.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile

SOURCE_FILES = (
    'services/rag-service/app/rag/ingestion/embeddings/sentence_transformers_embedder.py',
    'services/rag-service/app/rag/retrieval/factory.py',
    'services/rag-service/app/rag/retrieval/vector_retriever.py',
    'services/rag-service/app/rag/retrieval/hybrid_retriever.py',
    'services/rag-service/app/rag/retrieval/base.py',
    'services/rag-service/app/rag/ingestion/model_paths.py',
)
MODEL_CONFIGS = (
    'modules.json', '1_Pooling/config.json', 'sentence_bert_config.json',
    'config_sentence_transformers.json', 'config.json', 'tokenizer_config.json',
    'special_tokens_map.json',
)
SELECTED_SETTINGS = {
    'RAG_EMBEDDING_BACKEND', 'RAG_EMBEDDING_MODEL', 'RAG_EMBEDDING_DEVICE',
    'RAG_EMBEDDING_BATCH_SIZE', 'EMBEDDING_DIMENSIONS', 'MODELS_DIR',
    'RAG_CHUNKER_TOKENIZER', 'RAG_CHUNKER_TOKENIZER_MODEL', 'RAG_CHUNKER_MAX_TOKENS',
    'RAG_RERANKER_ENABLED', 'RAG_RERANKER_BACKEND',
}


def selected_defaults(path):
    values = {}
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in SELECTED_SETTINGS and node.value is not None:
                try:
                    values[node.target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    values[node.target.id] = 'nonliteral default (inspect locally)'
    return values


def selected_env_values(path):
    # Reads only an explicit allowlist; no full .env files are added to the ZIP.
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].lstrip()
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key.strip() in SELECTED_SETTINGS:
            values[key.strip()] = value.strip()
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-root', default='.')
    parser.add_argument('--model-dir', default='services/rag-service/models/BAAI--bge-base-en-v1.5')
    parser.add_argument('--output', default='step11_embedding_inputs.zip')
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    if not (root / 'services/rag-service').is_dir():
        raise SystemExit('Run at repository root, or supply --repo-root.')
    model_dir = Path(args.model_dir)
    if not model_dir.is_absolute():
        model_dir = root / model_dir
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit('Output already exists. Choose another --output or move the earlier ZIP.')
    entries = {}
    manifest = {'sources': [], 'model_files': [], 'settings': {},
                'excluded': ['credentials/full .env files', 'model weights', 'documents', 'database contents']}
    for relative in SOURCE_FILES:
        path = root / relative
        record = {'path': relative, 'present': path.is_file()}
        if path.is_file():
            if path.stat().st_size > 1024 * 1024:
                raise SystemExit('A selected source file exceeds 1 MiB; inspect it before sharing: ' + relative)
            content = path.read_bytes()
            record.update(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
            entries[relative] = content
        manifest['sources'].append(record)
    for relative in MODEL_CONFIGS:
        path = model_dir / relative
        record = {'path': relative, 'present': path.is_file()}
        if path.is_file():
            if path.stat().st_size > 1024 * 1024:
                raise SystemExit('Model configuration is unusually large: ' + relative)
            content = path.read_bytes()
            json.loads(content)
            record.update(size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
            entries['model-config/' + relative] = content
        manifest['model_files'].append(record)
    # Record weights' presence/size only. Tokenizer identity uses a bounded hash.
    for relative in ('onnx/model.onnx', 'model.safetensors', 'pytorch_model.bin', 'tokenizer.json', 'vocab.txt'):
        path = model_dir / relative
        record = {'path': relative, 'present': path.is_file()}
        if path.is_file():
            record['size_bytes'] = path.stat().st_size
            if relative in {'tokenizer.json', 'vocab.txt'} and path.stat().st_size <= 20 * 1024 * 1024:
                record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest['model_files'].append(record)
    config = root / 'services/rag-service/app/core/config.py'
    if config.is_file():
        manifest['settings']['code_defaults'] = selected_defaults(config)
    for relative in ('services/rag-service/.env', '.env.compose'):
        path = root / relative
        if path.is_file():
            manifest['settings'][relative + ':selected_values_only'] = selected_env_values(path)
    entries['manifest.json'] = json.dumps(manifest, indent=2).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    missing = [r['path'] for r in manifest['sources'] if not r['present']]
    print('Created:', output.name)
    print('Included source/config entries:', len(entries) - 1)
    print('Missing source files:', missing or 'none')
    print('No model weights or full .env files included. Review the ZIP, then upload it for Step 11 implementation.')


if __name__ == '__main__':
    main()
