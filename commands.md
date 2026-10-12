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


# Start the Docker setup
source scripts/dc-step12.sh
dc12 up -d
dc12 down

# (mostly for auth service only)
MSYS_NO_PATHCONV=1 dc12 run --rm --no-deps auth-service /code/.venv/bin/alembic current
MSYS_NO_PATHCONV=1 dc12 run --rm --no-deps auth-service /code/.venv/bin/alembic heads
MSYS_NO_PATHCONV=1 dc12 run --rm --no-deps auth-service /code/.venv/bin/alembic upgrade head

# docker resuouse usage
docker stats --no-stream

# Disk usage, including shared image layer
docker system df -v


# INSTRUCTIONS TO START AFTER GIT CLONE
# Start a new 

source scripts/dc-step12.sh

dc12 config --quiet
dc12 ps

bash scripts/run-chat-backend-harness.sh


### Build the updated images
dc12 build auth-service rag-service rag-worker 

### Stop existing application containers safely
dc12 stop rag-service

dc12 run --rm --no-deps rag-service python -m app.cli.check_ingestion_drained

### After draining completly
dc12 stop rag-worker auth-service

### Check and migrate this laptop’s database
dc12 run --rm --no-deps rag-service alembic current
dc12 run --rm --no-deps rag-service alembic heads

### upgrade to latest head(migration)
dc12 run --rm --no-deps rag-service alembic upgrade head
dc12 run --rm --no-deps rag-service python -m app.cli.check_chat_repository --concurrency

### Restart the updated backend
dc12 up -d --force-recreate auth-service rag-service rag-worker

dc12 ps
dc12 logs --tail=100 auth-service rag-service rag-worker

### Verify the runtime images
dc12 exec rag-service python -m app.cli.check_runtime_image --role api
dc12 exec rag-worker python -m app.cli.check_runtime_image --role worker


### Start the frontend
cd services/rag-web
npm ci

cp .env.example .env.local

### confirms it contains
VITE_RAG_BASE_URL=http://localhost:8000
VITE_AUTH_BASE_URL=http://localhost:8001
VITE_API_PREFIX=/api/v1

npm test
npm run build
npm run dev

# shutdown/startup
### Stop the Compose stack while retaining its volumes
dc12 down

### Start it again
dc12 up -d


# RAG EVALUATION
git clone --depth 1 https://github.com/patronus-ai/financebench.git ../financebench
uv sync --project evals/step15_deepeval --locked  # creates the separate DeepEval environment using its locked versions.

#### Run offline tests — checks the harness, metric integration, caching and compatibility logic without calling your hosted LLM.
uv run --project evals/step15_deepeval --locked python -m unittest discover -s evals/step15_deepeval/tests -v

#### Create the evaluation configuration — copies the settings template; skip this command if .env.evals already exists.
cp evals/step15_deepeval/.env.evals.example .env.evals

#### Check the LM Studio connection — verifies the configured model and structured JSON response support.
uv run --project evals/step15_deepeval --locked python evals/step15_deepeval/run.py doctor

#### Prepare the initial FinanceBench selection — creates the source dataset, PDF inventory and manifest; skip if already prepared
uv run --project evals/step15_deepeval --locked python evals/step15_deepeval/run.py prepare --financebench ../financebench --count 25

#### Create the two-PDF subset — selects the 14 AMD/American Express questions and preserves existing upload IDs; skip if this subset already exists.
python prepare_step15_two_pdfs.py
source scripts/dc-step12.sh
dc12 ps

####  Upload or verify the two PDFs — reuses saved uploads and waits for both documents to reach ingested.
uv run --project evals/step15_deepeval --locked python evals/step15_deepeval/run.py upload --data evals/step15/data-two-pdfs

#### Check capture-source compatibility — verifies the running application files against reviewed versions without making LLM calls.
python evals/step15_deepeval/collect_capture_sources.py --container "$(dc12 ps -q rag-service)"

#### Capture three smoke-test answers — runs retrieval and hosted generation, saving the exact context, answers and errors.
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py capture \
  --data evals/step15/data-two-pdfs \
  --container "$(dc12 ps -q rag-service)" \
  --mode pipeline --split dev --limit 3 \
  --revision "$(git rev-parse HEAD)-two-pdfs-v1" \
  --out evals/step15/results/pipeline-two-pdfs-v1.jsonl

#### Evaluate the smoke-test answers — uses DeepEval and LM Studio to calculate the core metrics locally.
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py judge \
  --data evals/step15/data-two-pdfs \
  --captures evals/step15/results/pipeline-two-pdfs-v1.jsonl \
  --profile core \
  --out evals/step15/results/deepeval-two-pdfs-core-v1

#### Open the smoke-test report — lets you inspect scores and evaluator failures before completing the run.
notepad evals/step15/results/deepeval-two-pdfs-core-v1/report.md

#### Capture all 14 answers — processes the remaining questions while skipping the three already saved
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py capture \
  --data evals/step15/data-two-pdfs \
  --container "$(dc12 ps -q rag-service)" \
  --mode pipeline --split all \
  --revision "$(git rev-parse HEAD)-two-pdfs-v1" \
  --out evals/step15/results/pipeline-two-pdfs-v1.jsonl 

#### Run the final full evaluation — scores all captured answers, adding completeness, citation checks and context-budget recall.
uv run --project evals/step15_deepeval --locked python \
  evals/step15_deepeval/run.py judge \
  --data evals/step15/data-two-pdfs \
  --captures evals/step15/results/pipeline-two-pdfs-v1.jsonl \
  --profile full \
  --out evals/step15/results/deepeval-two-pdfs-full-v1