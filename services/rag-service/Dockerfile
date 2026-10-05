# ---- builder stage ----
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/
WORKDIR /code

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY . .
RUN uv sync --locked --no-dev

# ---- runtime stage ----
FROM python:3.12-slim
WORKDIR /code

# Only runtime libs needed — no gcc, no git, no uv itself
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /code /code
ENV PATH="/code/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]





# FROM python:3.12-slim

# COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/
# WORKDIR /code

# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc libpq-dev git libgl1 libglib2.0-0 \
#     && rm -rf /var/lib/apt/lists/*

# COPY pyproject.toml uv.lock .python-version ./
# RUN uv sync --locked --no-dev --no-install-project

# COPY . .
# RUN uv sync --locked --no-dev
# # Bake models into the image for production avoids first-request
# # latency and flaky runtime downloads:
# # RUN uv run python -m app.cli.download_models

# EXPOSE 8000
# CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
