#!/usr/bin/env bash
set -euo pipefail
# Run from repository root. Host tests include the small auth compatibility patch.
repo_root="$(pwd)"
cd services/rag-service
DATABASE_URL=postgresql+asyncpg://offline:offline@127.0.0.1/offline \
RAG_GENERATION_ENABLED=false RAG_RUNTIME_ROLE=development \
uv run --locked --extra generation --group dev python -m pytest \
  app/tests/unit/test_chat.py \
  app/tests/unit/test_chat_auth.py \
  app/tests/unit/test_generation.py \
  app/tests/unit/test_generation_api.py \
  app/tests/unit/test_generation_auth.py \
  app/tests/unit/test_document_events.py \
  app/tests/unit/test_retrieval_finalization.py -q
cd "$repo_root"
