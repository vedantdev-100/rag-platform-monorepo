# MIGRATION_CHECKLIST.md

Files to copy UNCHANGED from your existing `ai-platform` monolith
into this monorepo. A couple need a one-line trim, noted inline.

- [ ] `ai-platform/app/core/security.py`  ->  `services/auth-service/app/core/security.py`
<!-- - [ ] `ai-platform/app/db/base.py`  ->  `services/auth-service/app/db/base.py` -->
<!-- - [ ] `ai-platform/app/db/session.py`  ->  `services/auth-service/app/db/session.py` -->
<!-- - [ ] `ai-platform/app/models/user.py`  ->  `services/auth-service/app/models/user.py` -->
<!-- - [ ] `ai-platform/app/models/refresh_token.py`  ->  `services/auth-service/app/models/refresh_token.py` -->
<!-- - [ ] `ai-platform/app/repositories/user_repository.py`  ->  `services/auth-service/app/repositories/user_repository.py` -->
<!-- - [ ] `ai-platform/app/repositories/refresh_token_repository.py`  ->  `services/auth-service/app/repositories/refresh_token_repository.py` -->
<!-- - [ ] `ai-platform/app/schemas/auth.py`  ->  `services/auth-service/app/schemas/auth.py` -->
<!-- - [ ] `ai-platform/app/schemas/user.py`  ->  `services/auth-service/app/schemas/user.py` -->
<!-- - [ ] `ai-platform/app/services/auth_service.py`  ->  `services/auth-service/app/services/auth_service.py` -->
<!-- - [ ] `ai-platform/app/logging/config.py`  ->  `services/auth-service/app/logging/config.py` -->
<!-- - [ ] `ai-platform/app/logging/__init__.py`  ->  `services/auth-service/app/logging/__init__.py` -->
<!-- - [ ] `ai-platform/app/utils/datetime_utils.py`  ->  `services/auth-service/app/utils/datetime_utils.py`
- [ ] `ai-platform/app/utils/id_utils.py`  ->  `services/auth-service/app/utils/id_utils.py`
- [ ] `ai-platform/app/utils/pagination.py`  ->  `services/auth-service/app/utils/pagination.py`
- [ ] `ai-platform/app/utils/__init__.py`  ->  `services/auth-service/app/utils/__init__.py` -->
<!-- - [ ] `ai-platform/app/cli/create_superuser.py`  ->  `services/auth-service/app/cli/create_superuser.py` -->
<!-- - [ ] `ai-platform/app/api/v1/endpoints/auth.py`  ->  `services/auth-service/app/api/v1/endpoints/auth.py` -->
<!-- - [ ] `ai-platform/alembic/env.py`  ->  `services/auth-service/alembic/env.py` -->
<!-- - [ ] `ai-platform/alembic/script.py.mako`  ->  `services/auth-service/alembic/script.py.mako` -->
<!-- - [ ] `ai-platform/alembic.ini`  ->  `services/auth-service/alembic.ini` -->

# RAG  Service
<!-- - [ ] `ai-platform/app/db/base.py`  ->  `services/rag-service/app/db/base.py` -->
<!-- - [ ] `ai-platform/app/db/session.py`  ->  `services/rag-service/app/db/session.py` -->
<!-- - [ ] `ai-platform/app/models/document.py`  ->  `services/rag-service/app/models/document.py` -->
<!-- - [ ] `ai-platform/app/models/chunk.py`  ->  `services/rag-service/app/models/chunk.py` -->
<!-- - [ ] `ai-platform/app/repositories/document_repository.py`  ->  `services/rag-service/app/repositories/document_repository.py` -->
<!-- - [ ] `ai-platform/app/repositories/chunk_repository.py`  ->  `services/rag-service/app/repositories/chunk_repository.py` -->
<!-- - [ ] `ai-platform/app/schemas/document.py`  ->  `services/rag-service/app/schemas/document.py` -->
<!-- - [ ] `ai-platform/app/schemas/search.py`  ->  `services/rag-service/app/schemas/search.py` -->
<!-- - [ ] `ai-platform/app/core/rate_limit.py`  ->  `services/rag-service/app/core/rate_limit.py` -->
<!-- - [ ] `ai-platform/app/logging/config.py`  ->  `services/rag-service/app/logging/config.py` -->
<!-- - [ ] `ai-platform/app/logging/__init__.py`  ->  `services/rag-service/app/logging/__init__.py` -->
<!-- - [ ] `ai-platform/app/utils/datetime_utils.py`  ->  `services/rag-service/app/utils/datetime_utils.py` -->
<!-- - [ ] `ai-platform/app/utils/id_utils.py`  ->  `services/rag-service/app/utils/id_utils.py` -->
<!-- - [ ] `ai-platform/app/utils/pagination.py`  ->  `services/rag-service/app/utils/pagination.py` -->
<!-- - [ ] `ai-platform/app/utils/__init__.py`  ->  `services/rag-service/app/utils/__init__.py` -->
<!-- - [ ] `ai-platform/app/guardrails/base.py`  ->  `services/rag-service/app/guardrails/base.py` -->
<!-- - [ ] `ai-platform/app/guardrails/__init__.py`  ->  `services/rag-service/app/guardrails/__init__.py` -->
<!-- - [ ] `ai-platform/app/cli/download_models.py`  ->  `services/rag-service/app/cli/download_models.py` -->
<!-- - [ ] `ai-platform/alembic/env.py`  ->  `services/rag-service/alembic/env.py` -->
<!-- - [ ] `ai-platform/alembic/script.py.mako`  ->  `services/rag-service/alembic/script.py.mako` -->
<!-- - [ ] `ai-platform/alembic.ini`  ->  `services/rag-service/alembic.ini` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/base.py`  ->  `services/rag-service/app/rag/ingestion/base.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/source_types.py`  ->  `services/rag-service/app/rag/ingestion/source_types.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/model_paths.py`  ->  `services/rag-service/app/rag/ingestion/model_paths.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/storage.py`  ->  `services/rag-service/app/rag/ingestion/storage.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/factory.py`  ->  `services/rag-service/app/rag/ingestion/factory.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/pipeline.py`  ->  `services/rag-service/app/rag/ingestion/pipeline.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/parsers/docling_parser.py`  ->  `services/rag-service/app/rag/ingestion/parsers/docling_parser.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/chunking/tokenizers.py`  ->  `services/rag-service/app/rag/ingestion/chunking/tokenizers.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/chunking/docling_chunker.py`  ->  `services/rag-service/app/rag/ingestion/chunking/docling_chunker.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/chunking/simple_chunker.py`  ->  `services/rag-service/app/rag/ingestion/chunking/simple_chunker.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/embeddings/stub_embedder.py`  ->  `services/rag-service/app/rag/ingestion/embeddings/stub_embedder.py` -->
<!-- - [ ] `ai-platform/app/rag/ingestion/embeddings/sentence_transformers_embedder.py`  ->  `services/rag-service/app/rag/ingestion/embeddings/sentence_transformers_embedder.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/base.py`  ->  `services/rag-service/app/rag/retrieval/base.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/vector_retriever.py`  ->  `services/rag-service/app/rag/retrieval/vector_retriever.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/keyword_retriever.py`  ->  `services/rag-service/app/rag/retrieval/keyword_retriever.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/hybrid_retriever.py`  ->  `services/rag-service/app/rag/retrieval/hybrid_retriever.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/factory.py`  ->  `services/rag-service/app/rag/retrieval/factory.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/rerankers/cross_encoder_reranker.py`  ->  `services/rag-service/app/rag/retrieval/rerankers/cross_encoder_reranker.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/rerankers/cohere_reranker.py`  ->  `services/rag-service/app/rag/retrieval/rerankers/cohere_reranker.py` -->
<!-- - [ ] `ai-platform/app/rag/retrieval/rerankers/voyage_reranker.py`  ->  `services/rag-service/app/rag/retrieval/rerankers/voyage_reranker.py` -->




## DATABSE MIGRATION SETUP STEPWISE
1. Go to the the database ans open psql terminal: cmd : [ docker exec -it <your_container_name> psql -U postgres -d ai_platform ]
2. Create the schema if does not *EXITS* and schema specific roles for security: cmd: : [ 
    CREATE SCHEMA auth;
    CREATE SCHEMA rag;

    CREATE ROLE auth_service_role LOGIN PASSWORD 'your_secure_password';
    GRANT USAGE, CREATE ON SCHEMA auth TO auth_service_role;

    CREATE ROLE rag_service_role LOGIN PASSWORD 'your_secure_password';
    GRANT USAGE, CREATE ON SCHEMA rag TO rag_service_role;
]
3. Update the postgres  connection url in .env (only the role part)
4. Add the name_service/alembic/env.py => then update the schema name model names in "from app.models import refresh_token, user"
5. Add models in name_service/app/models + Add the base.py file in app.db
6. Add the util files if required + update app.utils.__init__.py
7. Add the name_service/alembic/script.py.mako
8. Add the versions__no__.py files in name_service/alembic/versions
9. Add alembic.ini in root of Service
10. Run the cmds:
    uv run alembic revision --autogenerate -m "create auth tables"
    uv run alembic upgrade head

11. get into psql in containter: cmd: [ docker exec -it rag-postgres psql -U postgres -d ai_platform ]
    Reactivate the vector extension in the schema: [
        DROP EXTENSION IF EXISTS vector;
        CREATE EXTENSION vector WITH SCHEMA auth;
    ]