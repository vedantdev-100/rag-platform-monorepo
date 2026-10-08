"""Build-time dependency gate and live, offline import/tokenizer smoke check."""
import argparse
from importlib import import_module, metadata, util

COMMON = ("fastapi", "sqlalchemy", "asyncpg", "boto3", "platform_auth", "rag_contracts", "rag_persistence")
HEAVY = ("torch", "torchvision", "sentence_transformers", "docling", "onnxruntime", "tensorflow", "cv2")
WORKER = {"docling-core": "2.74.0", "transformers": "4.57.6", "tokenizers": "0.22.2", "huggingface-hub": "0.36.2"}


def check_dependencies(role):
    missing = [name for name in COMMON if util.find_spec(name) is None]
    forbidden = list(HEAVY)
    if role == "api":
        forbidden += ["docling_core", "transformers", "tokenizers", "huggingface_hub"]
    installed = [name for name in forbidden if util.find_spec(name) is not None]
    if missing or installed:
        raise RuntimeError(f"Image dependency check failed: missing={missing}; forbidden={installed}")
    if role == "api":
        import_module("langgraph.graph")
    if role == "worker":
        for package, expected in WORKER.items():
            actual = metadata.version(package)
            if actual != expected:
                raise RuntimeError(f"{package}: expected {expected}, installed {actual}")
        # These imports must work without any model execution framework installed.
        from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
        assert HybridChunker and HuggingFaceTokenizer
    from rag_persistence.models.document import Document
    assert Document.__tablename__ == "documents"
    print(f"{role}: dependency boundary OK; PyTorch/Docling converter/ONNX runtime absent")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("api", "worker"), required=True)
    parser.add_argument("--dependencies-only", action="store_true")
    args = parser.parse_args()
    check_dependencies(args.role)
    if args.dependencies_only:
        return
    from app.core.config import get_settings
    settings = get_settings()
    if settings.RAG_RUNTIME_ROLE != args.role:
        raise RuntimeError("Container runtime role differs from requested check")
    if args.role == "api":
        import_module("app.main")
        import_module("app.rag.retrieval.factory")
        print("API and retrieval imports: OK")
    else:
        import_module("app.worker")
        from app.rag.ingestion.factory import get_document_parser, get_chunker
        get_document_parser()
        get_chunker()
        if settings.RAG_CHUNKER_BACKEND == "docling":
            from app.rag.ingestion.chunking.tokenizers import build_tokenizer
            tokenizer = build_tokenizer(settings)
            count = tokenizer.count_tokens("Step twelve worker tokenizer verification.")
            if count <= 0:
                raise RuntimeError("Tokenizer returned an invalid count")
            print(f"Worker parser/chunker imports and local tokenizer: OK ({count} tokens)")
        else:
            print("Worker parser/chunker imports: OK (simple chunker configured)")
    unexpected = [name for name in HEAVY if name in __import__("sys").modules]
    if unexpected:
        raise RuntimeError("Unexpected heavy runtime imports: " + str(unexpected))
    print("Runtime role/configuration: OK; no DB/Redis mutation or model inference performed")


if __name__ == "__main__":
    main()
