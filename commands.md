# 1. Install uv
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Install PostgreSQL (download installer manually if not already done)
# https://www.postgresql.org/download/windows/

# 3. Confirm Postgres service is running
Get-Service -Name postgresql*
Start-Service -Name postgresql-x64-16

# 4. Create the database
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE ai_platform;"

# 5. cd into project
cd ai-platform

# 6. Install project dependencies
uv sync --locked

# 7. Copy env file
copy .env.example .env

# 8. Edit .env manually and set:
# DATABASE_URL=postgresql+asyncpg://postgres:<your-password>@localhost:5432/ai_platform

# 9. Generate JWT keypair (use Git Bash, or WSL, or install OpenSSL for Windows)
mkdir secrets
openssl genrsa -out secrets/private_key.pem 2048
openssl rsa -in secrets/private_key.pem -pubout -out secrets/public_key.pem

# 10. Run database migrations
uv run alembic upgrade head

# 11. Start the application
uv run uvicorn app.main:app --reload

# 12. Run tests (in a separate terminal)
uv run pytest app/tests/ -v

# 13. Verify server health
curl http://localhost:8000/health

# Create super user
uv run python -m app.cli.create_superuser
*** or non-interactive:
uv run python -m app.cli.create_superuser --email admin@example.com --password "AdminPass123!"

# Download Models
uv run python -m app.cli.download_models --force


# Run this inside the psql cmd 
***
It creates a (dedicated databse user) user-role for each schema, providing the auth service only ot auth_service_role 
following the principle of least privilege security,
Instead of connecting using th superuser i.e. postgres [security_concerns], now connect to dedicated db/schema using role specific user_role 
Isolation: Your auth service can only access and modify the auth schema. It cannot touch your rag schema, your user data tables elsewhere, or system settings.
Security Containment: If your authentication backend's database credentials ever leak, an attacker only gains access to the authentication tables—they won't be able to drop or compromise your entire database.
***
CREATE SCHEMA auth;
CREATE SCHEMA rag;

CREATE ROLE auth_service_role LOGIN PASSWORD 'your_secure_password';
GRANT USAGE, CREATE ON SCHEMA auth TO auth_service_role;

CREATE ROLE rag_service_role LOGIN PASSWORD 'your_secure_password';
GRANT USAGE, CREATE ON SCHEMA rag TO rag_service_role;