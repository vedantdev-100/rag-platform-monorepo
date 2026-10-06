# Step 5: additive ingestion schema migration

Apply after Steps 2–4 on `production-refactor`. Keep `rag-service`, one planned
worker container, existing GitHub platform-auth dependency, and one database
with auth/rag schemas. This update adds schema foundations; it does NOT enable
Redis ingestion, MinIO uploads, outbox publishing or deletion fencing yet.

## What changes

| Location | Addition |
| --- | --- |
| rag.documents | Object bucket/key, checksum, MIME/size, retry/error fields, job/generation/lease/token, parser/task/chunking/model provenance, processed timestamp, processing version |
| rag.chunks | Processing version and unique (document_id, chunk_index, processing_version) |
| rag.outbox | Durable publication/cleanup intent, deduplication key, attempts, due/lease/error/published fields |
| rag.user_lifecycle_state | RAG-local deletion/event state for later fencing |

All historical document columns, vectors, full-text content/indexes, UUIDs,
source_uri values and status strings are retained. New provider provenance is
NULL because historical model revisions must not be invented. Old document and
chunk processing_version values default to `legacy`; this is a compatibility
label, NOT proof that old embeddings came from a particular model/revision.
Retries/generation default to zero. Existing uploads receive the same defaults.
The vector column remains 768-dimensional. Supporting another dimension still
requires a deliberate vector-storage/index migration.

Outbox has no document/user FK that would delete pending cleanup intents with
the document. The lifecycle state table has no FK into auth. Only user.deleted
will create deletion fences when implemented; deactivation still preserves data.
The current API/lifecycle consumer does not write either new table in this step.
Do not rename existing Redis stream/group settings.

Unique versioned chunk positions enable idempotent/versioned writes later.
They are not sufficient on their own: the future worker must use guarded
claims/commits and version-aware retrieval. Current queries are safe with one
legacy version per document; do not create parallel versions manually before
retrieval filtering is implemented. Duplicate legacy positions cause preflight
and migration to stop; no automatic data deletion or renumbering is performed.

## Apply on your development database

1. Preserve your current Step 4 commit and make a database backup.
2. Stop rag-service and any other processes writing the rag schema; allow
   in-progress uploads to finish first. Keep PostgreSQL running.
3. Extract this ZIP into a temporary folder. Add the verification module FIRST:

```text
services/rag-service/app/tests/integration/check_ingestion_schema.py
```

4. From services/rag-service, before copying the new migration/models:

```bash
uv run alembic current
uv run alembic heads
uv run alembic check
uv run python -m app.tests.integration.check_ingestion_schema --before
```

Baseline heads/current must be `ede8cc507e7c`; check must show no unexpected
upgrade operations. Preflight reads old rows and indexes and saves their
hashes/counts in step05_schema_baseline.json. It stores no document contents.
Keep the snapshot for the after check. If the file already exists, choose a
fresh --snapshot path and use the same path for --after; do not overwrite the
original baseline. Do not stage the snapshot as application source.

5. Replace these THREE shared-package files:

```text
packages/rag-persistence/rag_persistence/models/document.py
packages/rag-persistence/rag_persistence/models/chunk.py
packages/rag-persistence/rag_persistence/models/__init__.py
```

Add these THREE files:

```text
packages/rag-persistence/rag_persistence/models/outbox.py
packages/rag-persistence/rag_persistence/models/user_lifecycle_state.py
services/rag-service/alembic/versions/a6f31c9e204b_ingestion_foundations.py
```

Do NOT replace historical migration ede8cc507e7c or service compatibility
model files. No changes to pyproject, lockfiles, env.py, repositories or
pipeline are required. The Step 3 editable install loads these model edits.

6. From services/rag-service, apply the provided revision:

```bash
uv run alembic upgrade a6f31c9e204b
uv run alembic current
uv run alembic heads
uv run alembic check
uv run python -m app.tests.integration.check_ingestion_schema --after
```

Do not generate another revision. Current/heads should show
`a6f31c9e204b (head)` and check should report no new upgrade operations.
After validation compares every historical row's old-column hash plus counts,
statuses and existing index definitions. It checks new compatibility defaults,
empty workflow tables and ORM registration. Stop on any mismatch and share
the output. Do not use Alembic stamp to skip the migration.

The migration uses transactional PostgreSQL DDL and temporarily locks the
existing rag tables. A 10-second lock timeout prevents an indefinite wait.
If a lock/duplicate/permission error occurs, keep the API stopped, address the
reported cause, and retry only after confirming alembic current. The migration
role must own/have DDL permissions for rag tables. It does not alter auth.

7. Restart your API. Check an old document's listing/search, then upload a new
   sample and search it. Existing statuses remain pending/processing/ingested/
   failed and upload remains synchronous. Also run Step 4's regression module:

```bash
uv run python -m app.tests.integration.check_ingestion_transactions
```

This last check uses synthetic temporary database records and cleans them up.
Step 5 schema verification is read-only apart from its local snapshot file.

## Review/commit

Review git diff/status, then stage ONLY the six schema/migration files and
verification module above (plus this guide if copied). Keep the baseline JSON
out of the commit. Suggested message: Add durable ingestion schema foundations.

## Recovery and validation limits

Downgrade is provided as standard migration history, but drops NEW workflow
tables/fields and their contents. It is not a routine verification command;
after worker cutover, it needs a reviewed data-preserving rollback plan. If
rolling back before these features are used, stop the API and restore matching
Step 4 model code after reverting the revision. Do not run the new ORM models
against the old schema.

Local preparation checked Python syntax, preserved historical model columns,
new model/migration column consistency, constraints/index names, revision
linkage and upgrade/downgrade inventory. SQLAlchemy/pgvector/PostgreSQL runtime
validation must run in your development checkout. Successful Alembic check
alone does not prove all check constraints/data invariants; run the included
data-preservation check and transaction regression as well.

Next: Docker/local infrastructure wiring. For that stage provide your current
rag-service Dockerfile, auth-service Dockerfile, service .env.example files
(not .env), and any existing Docker Compose configuration. Those let us wire
the local package builds and current Postgres/Redis volumes without guessing.

References:
https://alembic.sqlalchemy.org/en/latest/ops.html
https://www.postgresql.org/docs/current/sql-altertable.html
