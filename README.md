# RAG Platform � Microservices Monorepo

```
packages/platform-auth/   shared JWT verification + RBAC (no private key, no DB)
services/auth-service/    issues tokens, owns users + refresh_tokens
services/rag-service/     multimodal ingestion, hybrid retrieval, generation
k8s/                      Kubernetes manifests for all of the above
```

This script only scaffolds structure + the files that are NEW or
CHANGED vs. the original monolith. See MIGRATION_CHECKLIST.md for the
exact list of files to copy over unchanged from your existing
`ai-platform` monolith repo.

## Local setup, per package/service

No `uv init` needed � pyproject.toml already exists in each one. Just:

```bash
cd packages/platform-auth && uv lock && uv sync
cd ../../services/auth-service && uv lock && uv sync
cd ../rag-service && uv lock && uv sync
```

Each service keeps its own `.venv` and `uv.lock`they are
independently deployable, so independent dependency resolution is
correct here (this is NOT set up as a `uv` workspace on purpose).

## Database

One Postgres instance, two schemas, two least-privilege roles:

```sql
CREATE SCHEMA auth;
CREATE SCHEMA rag;
CREATE ROLE auth_service_role LOGIN PASSWORD '...';
GRANT USAGE, CREATE ON SCHEMA auth TO auth_service_role;
CREATE ROLE rag_service_role LOGIN PASSWORD '...';
GRANT USAGE, CREATE ON SCHEMA rag TO rag_service_role;
```

Each service's `DATABASE_URL` sets `search_path` to its own schema (see
each `.env.example`) and keeps its own Alembic migration history.
