[project]
name = "auth-service"
version = "0.1.0"
description = "Auth microservice: issues and manages JWTs, owns users/refresh_tokens"
requires-python = "==3.12.*"
dependencies = [
    "platform-auth",
    "fastapi==0.115.0",
    "uvicorn[standard]==0.30.6",
    "pydantic==2.9.2",
    "pydantic-settings==2.5.2",
    "email-validator==2.2.0",
    "sqlalchemy[asyncio]==2.0.35",
    "asyncpg==0.29.0",
    "alembic==1.13.2",
    "passlib[bcrypt]==1.7.4",
    "bcrypt==4.0.1",
    "python-jose[cryptography]==3.3.0",
    "python-multipart==0.0.9",
    "slowapi==0.1.9",
    "structlog==24.4.0",
    "python-dotenv==1.0.1",
    "tenacity==9.0.0",
    "pgvector>=0.5.0",
    "platform-auth[redis]",
]

[dependency-groups]
dev = ["pytest==8.3.3", "pytest-asyncio==0.24.0", "httpx==0.27.2", "ruff==0.7.0", "mypy==1.13.0"]

[tool.pytest.ini_options]
asyncio_mode = "strict"
asyncio_default_fixture_loop_scope = "function"

[tool.uv]
resolution = "highest"
prerelease = "disallow"
exclude-newer = "7 days"
default-groups = ["dev"]

[tool.uv.sources]
platform-auth = { path = "../../packages/platform-auth", editable = true}