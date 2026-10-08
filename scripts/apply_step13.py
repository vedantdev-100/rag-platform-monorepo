"""Guarded, repeatable patch application/rollback from the monorepo root."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    bundle = Path(__file__).resolve().parents[1] / "refactor/step13"
    if not (root / "services/rag-service/pyproject.toml").is_file():
        raise SystemExit("Run this script from the monorepo root")
    changes = []
    for record in json.loads((bundle / "patch-manifest.json").read_text(encoding="utf-8")):
        relative = record["path"]
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise SystemExit("Invalid patch target")
        updated = (bundle / "patches" / relative).read_text(encoding="utf-8")
        ast.parse(updated)
        if digest(updated) != record["after"]:
            raise SystemExit("Patch payload changed: " + relative)
        original = None
        if record["before"] is not None:
            original = (bundle / "originals" / relative).read_text(encoding="utf-8")
            if digest(original) != record["before"]:
                raise SystemExit("Original payload changed: " + relative)
        current = target.read_text(encoding="utf-8") if target.exists() else None
        current_hash = digest(current) if current is not None else None
        if current_hash not in {record["before"], record["after"]}:
            raise SystemExit("Current file differs from the reviewed ZIP: " + relative +
                             ". Send that file for merging; no files have been changed.")
        desired = original if args.rollback else updated
        if current != desired:
            changes.append((target, current, desired))
    # Every target and source is checked before the first mutation.
    for target, current, desired in changes:
        if desired is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if current is not None and not args.rollback:
                backup = target.with_name(target.name + ".step13.bak")
                if not backup.exists():
                    backup.write_text(current, encoding="utf-8")
            target.write_text(desired, encoding="utf-8")
    print(("Step 13 rolled back" if args.rollback else "Step 13 applied") +
          f"; {len(changes)} files changed. Existing unrelated code/settings retained.")


if __name__ == "__main__":
    main()
