"""Copy only tokenizer files, verifying each against the Step 11 model manifest."""
import argparse
import hashlib
import json
import os
from pathlib import Path

FILES = ("config.json", "tokenizer_config.json", "special_tokens_map.json",
         "tokenizer.json", "vocab.txt")


def prepare(source, target, manifest):
    if manifest.get("model") != "BAAI/bge-base-en-v1.5":
        raise ValueError("Expected the existing BGE base en v1.5 manifest")
    source, target = source.resolve(), target.resolve()
    if source == target or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Tokenizer destination must be separate from the model folder")
    payloads = {}
    for name in FILES:
        path = (source / name).resolve()
        if not path.is_relative_to(source):
            raise ValueError("Tokenizer file points outside model folder: " + name)
        data = path.read_bytes()
        expected = manifest["files"].get(name)
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Tokenizer differs from Step 11 contract: " + name)
        payloads[name] = data
    # Refuse an existing directory containing weights or unexpected files.
    if target.exists() and any(path.name not in FILES or not path.is_file() or path.is_symlink()
                               for path in target.iterdir()):
        raise ValueError("Tokenizer destination contains unexpected files; choose an empty destination")
    for name, data in payloads.items():
        path = target / name
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Existing tokenizer copy differs: " + name)
    target.mkdir(parents=True, exist_ok=True)
    for name, data in payloads.items():
        path = target / name
        if not path.exists():
            temporary = target / (name + ".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, path)
    print("Worker tokenizer verified:", target)
    print("Tokenizer bytes:", sum(map(len, payloads.values())), "(no model weights copied)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default="services/rag-service/models/BAAI--bge-base-en-v1.5")
    parser.add_argument("--destination", default="services/rag-service/data/tokenizers/BAAI--bge-base-en-v1.5")
    args = parser.parse_args()
    manifest = json.loads(Path("services/embedding-service/model-manifest.json").read_text())
    prepare(Path(args.model_dir), Path(args.destination), manifest)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
