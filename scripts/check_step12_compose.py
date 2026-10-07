"""Read `dc12 config --format json` on stdin; never print resolved secrets."""
import json
import sys
from pathlib import Path


def check(config, manifest_revision):
    services = config["services"]
    revisions = []
    for name, role in (("rag-service", "api"), ("rag-worker", "worker")):
        service = services[name]
        if service["build"]["target"] != role:
            raise ValueError(name + ": wrong build target")
        if not service["build"]["dockerfile"].endswith("Dockerfile.runtime"):
            raise ValueError(name + ": wrong Dockerfile")
        env = service["environment"]
        expected = {"RAG_RUNTIME_ROLE": role, "RAG_EMBEDDING_BACKEND": "http",
                    "RAG_PARSER_BACKEND": "docling_serve",
                    "RUN_LIFECYCLE_CONSUMER": "true" if role == "worker" else "false"}
        for field, value in expected.items():
            if str(env.get(field)).lower() != value:
                raise ValueError(name + ": check " + field)
        revisions.append(env.get("EMBEDDING_SERVICE_REVISION"))
        mounts = service.get("volumes", [])
        model_mounts = [mount for mount in mounts if mount["target"].endswith("/models")]
        if role == "api" and model_mounts:
            raise ValueError("API still has a model mount; check overlay order")
        if role == "worker":
            if len(model_mounts) != 1 or not model_mounts[0].get("read_only"):
                raise ValueError("Worker must have one read-only tokenizer mount")
            source = model_mounts[0]["source"].replace("\\", "/").rstrip("/")
            if not source.endswith("/services/rag-service/data/tokenizers"):
                raise ValueError("Worker tokenizer source differs from the prepared directory")
    manifest_mounts = [mount for mount in services["embedding-service"].get("volumes", [])
                       if mount["target"] == "/config/model-manifest.json"]
    if (len(manifest_mounts) != 1 or not manifest_mounts[0].get("read_only")
            or not manifest_mounts[0]["source"].replace("\\", "/").endswith(
                "/services/embedding-service/model-manifest.json")):
        raise ValueError("Embedding service must mount the verified Step 11 manifest read-only")
    revisions.append(manifest_revision)
    if not revisions[0] or len(set(revisions)) != 1:
        raise ValueError("API, worker and embedding service must use the same model revision")
    if services["rag-service"]["image"] == services["rag-worker"]["image"]:
        raise ValueError("API and worker still use the same image")


if __name__ == "__main__":
    try:
        manifest = json.loads(Path("services/embedding-service/model-manifest.json").read_text())
        check(json.load(sys.stdin), manifest["revision"])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise SystemExit("Step 12 Compose check failed: " + str(exc)) from exc
    print("Step 12 Compose: separate build targets/images, remote backends, tokenizer-only worker mount, matching revision: OK")
