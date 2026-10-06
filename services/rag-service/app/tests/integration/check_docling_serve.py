"""Read-only server compatibility probe. No DB/Redis writes, no embeddings."""
import argparse
import asyncio
from importlib.metadata import version
from pathlib import Path
from app.rag.ingestion.chunking.docling_chunker import DoclingHybridChunker
from app.core.config import get_settings
from app.rag.ingestion.chunking.tokenizers import ApproxTokenizer, build_tokenizer
from app.rag.ingestion.parsers.docling_serve_parser import DoclingServeParser

async def main(args):
    settings = get_settings().model_copy(update={
        'RAG_PARSER_BACKEND': 'docling_serve',
        'DOCLING_SERVE_URL': args.url or get_settings().DOCLING_SERVE_URL,
    })
    settings._validate_docling_serve()
    path = Path(args.file)
    if path.stat().st_size > settings.RAG_MAX_UPLOAD_MB * 1024 * 1024:
        raise SystemExit('Probe input exceeds upload limit')
    parsed = await DoclingServeParser(settings).parse(path.read_bytes(), path.name)
    print('Installed client docling-core:', version('docling-core'))
    print('Remote parser metadata:', parsed.metadata)
    tokenizer = ApproxTokenizer(max_tokens=settings.RAG_CHUNKER_MAX_TOKENS) if args.approx else build_tokenizer(settings)
    chunker = DoclingHybridChunker(tokenizer=tokenizer, merge_peers=settings.RAG_CHUNKER_MERGE_PEERS)
    chunks = chunker.chunk(parsed)
    if not parsed.elements or not chunks:
        raise SystemExit('FAILED: no searchable content')
    labels = sorted({label for chunk in chunks for label in chunk.metadata['labels']})
    pages = sorted({page for chunk in chunks for page in chunk.metadata['pages']})
    print('Parsed elements:', len(parsed.elements), '; chunks:', len(chunks))
    print('Labels:', labels, '; page references:', pages)
    print('Remote conversion -> native decode -> hybrid chunking: OK')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('file', help='Path visible inside this process/container')
    parser.add_argument('--url', help='Host runs use http://127.0.0.1:5001')
    parser.add_argument('--approx', action='store_true', help='Check schema/chunking without downloading a tokenizer')
    asyncio.run(main(parser.parse_args()))
