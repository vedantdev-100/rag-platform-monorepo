"""Guarded Step 14 application, dry run and rollback. Run from monorepo root."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import tomllib


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    bundle = Path(__file__).resolve().parents[1] / "refactor/step14"
    if not (root / "services/rag-service/pyproject.toml").is_file():
        raise SystemExit("Run from the monorepo root using Python 3.12")
    changes = []
    for record in json.loads((bundle / "patch-manifest.json").read_text(encoding="utf-8")):
        relative = record["path"]
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise SystemExit("Invalid patch target")
        updated = (bundle / "patches" / relative).read_text(encoding="utf-8")
        if digest(updated) != record["after"]:
            raise SystemExit("Patch payload changed: " + relative)
        if target.suffix == ".py":
            ast.parse(updated)
        elif target.suffix == ".toml" or target.name == "uv.lock":
            tomllib.loads(updated)
        original = None
        if record["before"] is not None:
            original = (bundle / "originals" / relative).read_text(encoding="utf-8")
            if digest(original) != record["before"]:
                raise SystemExit("Original payload changed: " + relative)
        current = target.read_text(encoding="utf-8") if target.exists() else None
        current_hash = digest(current) if current is not None else None
        if current_hash not in {record["before"], record["after"]}:
            raise SystemExit("Current file differs from reviewed ZIP: " + relative +
                             ". No files changed. Send this current file for merging.")
        desired = original if args.rollback else updated
        if current != desired:
            changes.append((target, current, desired))
    if args.check:
        print(f"Step 14 preflight passed; {len(changes)} files would change. Nothing written.")
        return
    # Complete preflight for all sources/targets before any mutation.
    for target, current, desired in changes:
        if desired is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if current is not None and not args.rollback:
                backup = target.with_name(target.name + ".step14.bak")
                if not backup.exists():
                    backup.write_text(current, encoding="utf-8")
            temporary = target.with_name(target.name + ".step14.tmp")
            temporary.write_text(desired, encoding="utf-8")
            temporary.replace(target)
    print(("Step 14 rolled back" if args.rollback else "Step 14 applied") + f"; {len(changes)} files changed.")


if __name__ == "__main__":
    main()
