# Build context MUST be the monorepo root.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /workspace/services/rag-service
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev git \
    && rm -rf /var/lib/apt/lists/*
# Preserve ../../packages paths referenced by the service's pyproject.toml/uv.lock.
COPY packages/rag-contracts /workspace/packages/rag-contracts
COPY packages/rag-persistence /workspace/packages/rag-persistence
COPY services/rag-service/pyproject.toml services/rag-service/uv.lock services/rag-service/.python-version ./
RUN uv sync --locked --no-dev --no-editable --no-install-project
COPY services/rag-service/ ./
RUN uv sync --locked --no-dev --no-editable
# Catch absent shared dependencies during the image build without connecting to DB/Redis.
RUN .venv/bin/python -c "import rag_contracts, rag_persistence; from rag_persistence.models.document import Document"

FROM python:3.12-slim AS runtime
WORKDIR /workspace/services/rag-service
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /workspace /workspace
ENV PATH="/workspace/services/rag-service/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
