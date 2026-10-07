"""Offline tests for dependency edits, startup roles and tokenizer-copy protection."""
import hashlib
import importlib.util
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply = load("step12_apply", "scripts/apply_step12.py")
copy = load("step12_copy", "scripts/prepare_step12_tokenizer.py")
roles = load("step12_roles", "services/rag-service/app/core/runtime_roles.py")
compose = load("step12_compose", "scripts/check_step12_compose.py")


class SetupTests(unittest.TestCase):
    def test_dependency_split_preserves_project_and_sources(self):
        original = '''[project]
name = "rag-service"
version = "0.1.0"
dependencies = [
    "fastapi==0.115.0",
    "docling==2.87.0",
    "docling-core[chunking]==2.74.0",
    "sentence-transformers==3.3.1",
    "huggingface-hub==0.36.2",
    "platform-auth[redis]",
]
[dependency-groups]
dev = ["pytest==8.3.3", "transformers==4.57.6", "tokenizers==0.22.2", "pillow==12.3.0"]
[tool.uv.sources]
platform-auth = {git="https://github.com/vedantdev-100/platform-auth.git", tag="v1.0.0"}
'''
        updated = apply.patch_project(original)
        data = tomllib.loads(updated)
        self.assertEqual(data["project"]["dependencies"], ["fastapi==0.115.0", "platform-auth[redis]"])
        self.assertEqual(data["project"]["optional-dependencies"]["worker"], apply.WORKER)
        self.assertEqual(data["tool"]["uv"]["sources"], tomllib.loads(original)["tool"]["uv"]["sources"])
        self.assertEqual(apply.patch_project(updated), updated)
        with self.assertRaises(ValueError):
            apply.patch_project(original.replace("docling==2.87.0", "docling==2.88.0"))

    def test_slim_roles_reject_local_inference_and_wrong_consumer(self):
        settings = SimpleNamespace(RAG_RUNTIME_ROLE="api", RAG_EMBEDDING_BACKEND="http",
                                   RAG_PARSER_BACKEND="docling_serve", RAG_RERANKER_ENABLED=False,
                                   RAG_RERANKER_BACKEND="local", RUN_LIFECYCLE_CONSUMER=False)
        self.assertIs(roles.validate_runtime_role(settings), settings)
        for field, bad in (("RAG_EMBEDDING_BACKEND", "sentence_transformers"),
                           ("RAG_PARSER_BACKEND", "docling"), ("RUN_LIFECYCLE_CONSUMER", True),
                           ("RAG_RERANKER_ENABLED", True)):
            good = getattr(settings, field)
            setattr(settings, field, bad)
            with self.assertRaises(ValueError):
                roles.validate_runtime_role(settings)
            setattr(settings, field, good)
        settings.RAG_RUNTIME_ROLE = "worker"
        with self.assertRaises(ValueError):
            roles.validate_runtime_role(settings)
        settings.RUN_LIFECYCLE_CONSUMER = True
        self.assertIs(roles.validate_runtime_role(settings), settings)
        settings.RAG_RUNTIME_ROLE = "development"
        settings.RAG_EMBEDDING_BACKEND = "sentence_transformers"
        self.assertIs(roles.validate_runtime_role(settings), settings)

    def test_copy_checks_every_hash_before_writing_and_excludes_weights(self):
        with tempfile.TemporaryDirectory() as root:
            source, target = Path(root)/"original", Path(root)/"tokenizer"
            source.mkdir()
            manifest = {"model": "BAAI/bge-base-en-v1.5", "files": {}}
            for name in copy.FILES:
                data = name.encode()
                (source/name).write_bytes(data)
                manifest["files"][name] = hashlib.sha256(data).hexdigest()
            (source/"model.safetensors").write_bytes(b"weights")
            manifest["files"]["vocab.txt"] = "0"*64
            with self.assertRaises(ValueError):
                copy.prepare(source, target, manifest)
            self.assertFalse(target.exists())
            manifest["files"]["vocab.txt"] = hashlib.sha256(b"vocab.txt").hexdigest()
            copy.prepare(source, target, manifest)
            self.assertEqual({p.name for p in target.iterdir()}, set(copy.FILES))
            copy.prepare(source, target, manifest)
            (target/"model.onnx").write_bytes(b"unexpected weights")
            with self.assertRaises(ValueError):
                copy.prepare(source, target, manifest)

    def test_config_patch_is_idempotent_and_preserves_other_settings(self):
        original = '''class Settings:
    APP_NAME: str = "rag-service"
    EMBEDDING_SERVICE_REVISION: str = ""
    DOCLING_SERVE_URL: str = "http://docling-serve:5001"
    DEBUG: bool = False
'''
        updated = apply.patch_config(original)
        self.assertIn('    DEBUG: bool = False', updated)
        self.assertEqual(apply.patch_config(updated), updated)

    def test_compose_compares_client_revision_to_server_manifest(self):
        services = {}
        for name, role in (("rag-service", "api"), ("rag-worker", "worker")):
            services[name] = {
                "build": {"target": role, "dockerfile": "services/rag-service/Dockerfile.runtime"},
                "image": name + ":local", "volumes": [],
                "environment": {"RAG_RUNTIME_ROLE": role, "RAG_EMBEDDING_BACKEND": "http",
                                "RAG_PARSER_BACKEND": "docling_serve", "EMBEDDING_SERVICE_REVISION": "revision",
                                "RUN_LIFECYCLE_CONSUMER": "true" if role == "worker" else "false"}}
        services["rag-worker"]["volumes"] = [{"target": "/workspace/services/rag-service/models",
                                               "source": "/repo/services/rag-service/data/tokenizers",
                                               "read_only": True}]
        services["embedding-service"] = {"volumes": [{"target": "/config/model-manifest.json",
            "source": "/repo/services/embedding-service/model-manifest.json", "read_only": True}]}
        compose.check({"services": services}, "revision")
        with self.assertRaises(ValueError):
            compose.check({"services": services}, "changed-revision")
        services["rag-service"]["volumes"] = services["rag-worker"]["volumes"]
        with self.assertRaises(ValueError):
            compose.check({"services": services}, "revision")


if __name__ == "__main__":
    unittest.main(verbosity=2)
