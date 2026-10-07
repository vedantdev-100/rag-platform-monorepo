"""Run from monorepo root. Preserve unrelated TOML/settings; back up each edit."""
import ast
import re
import tomllib
from pathlib import Path

WORKER = ["docling-core[chunking]==2.74.0", "transformers==4.57.6",
          "tokenizers==0.22.2", "huggingface-hub==0.36.2"]
LOCAL = ["docling==2.87.0", "sentence-transformers==3.3.1", *WORKER]
MOVED = ["docling==2.87.0", "docling-core[chunking]==2.74.0",
         "sentence-transformers==3.3.1", "huggingface-hub==0.36.2"]


def patch_project(text):
    data = tomllib.loads(text)
    extras = data["project"].get("optional-dependencies", {})
    if extras.get("worker") == WORKER and extras.get("local-models") == LOCAL:
        if any(dep in data["project"]["dependencies"] for dep in MOVED):
            raise ValueError("Step 12 extras exist but heavy base dependencies remain")
        return text
    if extras:
        raise ValueError("Existing optional-dependencies need merging; send current pyproject.toml")
    if data["project"]["name"] != "rag-service":
        raise ValueError("Expected the existing rag-service project")
    for dep in MOVED:
        if dep not in data["project"]["dependencies"]:
            raise ValueError("Dependency differs from uploaded baseline: " + dep)
        pattern = r'(?m)^\s*"' + re.escape(dep) + r'",?\s*\n'
        text, count = re.subn(pattern, "\n", text, count=1)
        if count != 1:
            raise ValueError("Dependency line needs manual merging: " + dep)
    # These become worker runtime dependencies, rather than dev-only dependencies.
    for dep in WORKER[1:3]:
        text = text.replace('"' + dep + '",', "")
    marker = "[dependency-groups]"
    if text.count(marker) != 1:
        raise ValueError("Expected one dependency-groups table")
    addition = "[project.optional-dependencies]\n"
    for name, deps in (("worker", WORKER), ("local-models", LOCAL)):
        addition += name + " = [\n" + "".join('    "' + dep + '",\n' for dep in deps) + "]\n"
    text = text.replace(marker, addition + "\n" + marker, 1)
    updated = tomllib.loads(text)
    assert updated["project"]["optional-dependencies"]["worker"] == WORKER
    return text


def patch_config(text):
    marker = "    # Step 12: image runtime role.\n"
    if marker in text:
        ast.parse(text)
        return text
    if "EMBEDDING_SERVICE_REVISION" not in text or "DOCLING_SERVE_URL" not in text:
        raise ValueError("Apply Steps 10B and 11 before Step 12")
    anchor = '    APP_NAME: str = "rag-service"'
    if text.count(anchor) != 1:
        raise ValueError("Settings anchor changed; send current config.py")
    addition = '''
    # Step 12: image runtime role.
    RAG_RUNTIME_ROLE: Literal["development", "api", "worker"] = "development"

    @model_validator(mode="after")
    def _validate_runtime_role(self) -> "Settings":
        from app.core.runtime_roles import validate_runtime_role
        return validate_runtime_role(self)
'''
    text = text.replace(anchor, anchor + "\n" + addition, 1)
    ast.parse(text)
    return text


def main():
    root = Path("services/rag-service")
    changes = []
    for path, patch in ((root / "pyproject.toml", patch_project),
                        (root / "app/core/config.py", patch_config)):
        original = path.read_text(encoding="utf-8")
        changes.append((path, original, patch(original)))
    # Validate both before writing either file.
    for path, original, updated in changes:
        if updated != original:
            backup = path.with_name(path.name + ".step12.bak")
            if not backup.exists():
                backup.write_text(original, encoding="utf-8")
            path.write_text(updated, encoding="utf-8")
    print("Step 12 dependencies/settings applied. Run uv lock in services/rag-service before building.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from exc
