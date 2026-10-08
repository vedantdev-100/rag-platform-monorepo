#!/usr/bin/env bash
# Git Bash/Linux: offline checks using the service's locked API/dev environment.
set -euo pipefail
rag_step14_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$rag_step14_root/services/rag-service"
uv sync --locked --extra generation
uv run --locked --extra generation pytest \
  app/tests/unit/test_generation.py \
  app/tests/unit/test_generation_api.py \
  app/tests/unit/test_generation_auth.py \
  app/tests/unit/test_document_events.py \
  app/tests/unit/test_retrieval_finalization.py \
  app/tests/unit/test_rag_setup_harness.py -q
uv run --locked --extra generation python -m app.cli.check_generation
