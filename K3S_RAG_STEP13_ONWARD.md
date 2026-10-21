# K3s on WSL2 — RAG Project Migration (From README Step 13)

**Scope:** Continue the original K3s WSL2 README after completing its Step 12. This document uses the Docker image names visible in the supplied Docker Desktop screenshot. It is a **safe, incremental local-learning plan**, not an automatic conversion of Docker Compose into production-grade Kubernetes.

**Important:** The screenshot does not show the full Docling and MinIO image tags or the container environment variables and startup commands. Those values must be discovered before completing the Kubernetes manifests. Do **not** paste real passwords or API keys into chat or commit them to Git.

## 0. What is currently available

| Existing container | Docker image from screenshot | K3s resource | Internal application port | Existing Docker host port |
|---|---|---|---|---|
| `rag-service-1` | `rag-platform/rag-service:local` | Deployment + ClusterIP Service | 8000 | 8000 |
| `rag-worker-1` | `rag-platform/rag-worker:local` | Deployment, **1 replica** | No public HTTP port assumed | — |
| `auth-service-1` | `rag-platform/auth-service:local` | Deployment + ClusterIP Service | 8000 | 8001 |
| `docling-server-1` | `docling-project/docling-serve-cpu:<exact-tag-required>` | Deployment + Service | 5001 | 5001 |
| `embedding-service-1` | `rag-platform/embedding-service:local` | Deployment + Service | 8000 | 5002 |
| `minio-1` | `rag-platform/minio:<exact-tag-required>` | StatefulSet + PVC + Service **or retained Docker dependency** | 9000 (API; verify console port) | 9000 |
| `redis` | `redis:7-alpine` | StatefulSet + PVC + Service **or retained Docker dependency** | 6379 | 6379 |
| `pgvector` | `ankane/pgvector` | StatefulSet + PVC + Service **or retained Docker dependency** | 5432 | 5435 |
| `minio-init-1` | RAG service image | **One-time Job** (exact `command` and `args` required) | — | — |

**Do not start two PostgreSQL instances against the same data directory.** Importing images copies container images only, **not Docker volumes or database data**.

**Recommended path for your first WSL migration:** keep your working PostgreSQL, Redis, and MinIO Docker containers running; move the API, auth, Docling, embedding, and worker to K3s after verifying their external dependency connectivity from *inside K3s Pods*. Later move stateful dependencies only after backups and a migration plan. If cross-runtime networking proves difficult, an all-in-K3s local lab is an alternative, but requires additional storage/initialization manifests and database migration.

## Step 13 — Import your **actual** Docker images into K3s

**Terminal:** Ubuntu WSL2, with Docker Desktop WSL integration enabled (if using Docker Desktop).

### 13.1 Verify both runtimes

```bash
kubectl get nodes
sudo k3s crictl images | head
docker version
docker image ls
```

### 13.2 List **full** image names (the screenshot truncates two tags)

```bash
docker image ls --format '{{.Repository}}:{{.Tag}}' | sort
```

Also inspect running/stopped container names and images:

```bash
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

Record the complete image tags for `docling-project/docling-serve-cpu` and `rag-platform/minio`.

### 13.3 Export and import the six precisely identified images

```bash
mkdir -p "$HOME/k3s-images"

images=(
  'rag-platform/rag-service:local'
  'rag-platform/rag-worker:local'
  'rag-platform/auth-service:local'
  'rag-platform/embedding-service:local'
  'redis:7-alpine'
  'ankane/pgvector'
)

for image in "${images[@]}"; do
  echo "Checking $image"
  docker image inspect "$image" >/dev/null || {
    echo "MISSING Docker image: $image"
    continue
  }
  tar_path="$HOME/k3s-images/$(echo "$image" | tr '/:' '___').tar"
  echo "Exporting $image -> $tar_path"
  docker save -o "$tar_path" "$image"
  echo "Importing $image into K3s containerd"
  sudo k3s ctr -n k8s.io images import "$tar_path" || break
done
```

This may take a while and use substantial disk space. Do not delete the tar files until the imports have succeeded.

### 13.4 Import Docling and MinIO after confirming full tags

Replace the angle-bracket placeholders below with **exact** tags shown by Step 13.2:

```bash
DOCLING_IMAGE='docling-project/docling-serve-cpu:<EXACT_TAG>'
MINIO_IMAGE='rag-platform/minio:<EXACT_TAG>'

docker image inspect "$DOCLING_IMAGE" "$MINIO_IMAGE"

docker save -o "$HOME/k3s-images/docling.tar" "$DOCLING_IMAGE"
sudo k3s ctr -n k8s.io images import "$HOME/k3s-images/docling.tar"

docker save -o "$HOME/k3s-images/minio.tar" "$MINIO_IMAGE"
sudo k3s ctr -n k8s.io images import "$HOME/k3s-images/minio.tar"
```

**Do not import `minio-init` as a separate image:** your screenshot shows it reuses `rag-platform/rag-service:local`.

### 13.5 Verify imports

```bash
sudo k3s crictl images | grep -E 'rag-platform|redis|pgvector|docling|ankane'
```

For **local, imported** images, Kubernetes manifests can use the corresponding image name and `imagePullPolicy: IfNotPresent` (or `Never` if you explicitly want no remote pulling). Use the same image reference displayed by the K3s image inventory.

**Why:** Docker Desktop and K3s use separate image stores, even when they are on the same Windows machine. [K3s image import documentation](https://docs.k3s.io/add-ons/import-images).

## Step 14 — Determine your actual environment variables

### 14.1 Is `env.compose` enough?

**Not necessarily.** There are two distinct Docker Compose mechanisms:

1. `docker compose --env-file env.compose ...` supplies values for Compose-file **interpolation** (e.g., `${POSTGRES_USER}`). These values are not automatically injected into every container.
2. `env_file:` and `environment:` under an individual Compose service determine the environment actually passed to that container. `environment:` overrides `env_file:` for the same key.

Consequently, **`env.compose` is your starting point**, but we must inspect your Compose YAML and any referenced files to identify the actual environment of every service.

[Docker official explanation](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/).

### 14.2 Identify Compose files, service names and image names

Run from your existing `rag-service` repository directory:

```bash
pwd
ls -la | grep -E 'compose|env'
```

If your actual Compose file is `compose.yaml`, run:

```bash
docker compose --env-file env.compose -f compose.yaml config --services
docker compose --env-file env.compose -f compose.yaml config --images
```

**Replace `compose.yaml` with the real filename.** For example, it could be `docker-compose.yml` or `compose.local.yml`. If you normally use multiple `-f` files, use the same file set and order as your working setup.

**Do not paste `docker compose config` output into chat.** It may resolve and expose secret values. `config --services` and `config --images` do not print environment values.

### 14.3 Find referenced env files and startup overrides

Check the actual Compose YAML for:

- `env_file:` and `environment:` (runtime variables)
- `command:` / `entrypoint:` (especially Docling, worker, auth, MinIO init)
- `volumes:` and database initialization scripts
- `ports:` and `healthcheck:`
- `depends_on:` and separate database migrations / MinIO bootstrap steps

Do **not** assume that every container shares exactly the same env file or credentials.

### 14.4 ConfigMap vs Secret vs Kubernetes infrastructure

| Category | Destination | Examples (illustrative; preserve your application's real variable names) |
|---|---|---|
| Nonsecret application behavior | ConfigMap | generation enabled, strategy, model names, batch size, embedding URL, Docling URL |
| Credentials | Secret | `GROQ_API_KEY`, other provider keys, signing secrets, database passwords, MinIO access/secret keys |
| Connection string containing password | Secret | `DATABASE_URL`, auth DB URL, password-bearing Redis URL |
| Nonsecret internal endpoint | ConfigMap | `http://embedding-service:8000`, `http://docling-server:5001` after those Services exist |
| Kubernetes structure | YAML/Helm spec | namespace, image name, imagePullPolicy, replicas, resources, container ports, volumes |
| Docker Compose host-specific values | Usually removed or recalculated | `${HOST_PORT}`, Compose project name, `host.docker.internal` (unless independently verified from Pods) |
| PostgreSQL container initialization | Secret + StatefulSet/Job | `POSTGRES_USER`, `POSTGRES_PASSWORD`, database creation/init scripts |

Avoid passing a single catch-all `rag-secrets` Secret into all Pods if it gives unnecessary API-key/database credentials to unrelated services. Prefer **per-service Secrets** such as `rag-api-secrets`, `auth-secrets`, `worker-secrets`, and storage/database Secrets. For your first lab, the existing `rag-secrets` from Step 12 can be retained while you reorganize, but it must not contain untouched `REPLACE_ME` placeholders.

### 14.5 Example new configuration files (illustrative only)

`rag-runtime.env` (nonsecret):

```dotenv
RAG_GENERATION_ENABLED=true
RAG_GENERATION_STRATEGY=standard
RAG_LLM_PROVIDER=groq
# Use the ACTUAL setting name your code expects:
# EMBEDDING_SERVICE_URL=http://embedding-service:8000
# DOCLING_SERVE_URL=http://docling-server:5001
```

`rag-api-secrets.env` (private):

```dotenv
GROQ_API_KEY=ACTUAL_PRIVATE_VALUE
# Database URLs and auth/JWKS credentials, using the names expected by your application
```

> Do not literally paste `ACTUAL_PRIVATE_VALUE` into a deployment. These samples demonstrate the file layout and **not** a complete set of RAG settings.

To create the Kubernetes ConfigMap (after finalizing actual keys):

```bash
kubectl create configmap rag-runtime \
  --from-env-file=rag-runtime.env \
  -n rag-dev --dry-run=client -o yaml | kubectl apply -f -
```

To create a per-service Secret, without storing the plaintext Secret in a YAML manifest:

```bash
chmod 600 rag-api-secrets.env
kubectl create secret generic rag-api-secrets \
  --from-env-file=rag-api-secrets.env \
  -n rag-dev --dry-run=client -o yaml | kubectl apply -f -
```

Keep private `.env` files out of Git and restrict local access. These commands send credentials to Kubernetes; ensure you are using the expected development context:

```bash
kubectl config current-context
kubectl get namespace rag-dev
```

### 14.6 How host port mappings change after migration

Your Docker Compose `HOST:CONTAINER` mappings are **not** the ports Pods should use for internal calls:

| Docker published port | App container port | Typical in-K3s URL once its Service exists |
|---|---|---|
| API `8000:8000` | 8000 | `http://rag-service:8000` |
| Auth `8001:8000` | 8000 | `http://auth-service:8000` |
| Docling `5001:5001` | 5001 | `http://docling-server:5001` |
| Embeddings `5002:8000` | 8000 | `http://embedding-service:8000` |
| PostgreSQL `5435:5432` | 5432 | `postgres:5432` |
| Redis `6379:6379` | 6379 | `redis:6379` |
| MinIO `9000:9000` | 9000 | `http://minio:9000` |

Only use the DNS names in the right column **after you create the corresponding Kubernetes Services** and the services are inside the same namespace. Retained Docker dependencies need **different, tested reachable endpoints**, not fake Kubernetes hostnames.

`localhost` inside a Pod refers to that Pod, not Windows or the Docker Desktop host. `host.docker.internal` is **not guaranteed** to resolve or work in K3s Pods; test it.

### 14.7 Check connectivity before migrating stateful services

Keep your existing Docker dependencies running. From a separate Ubuntu WSL2 terminal:

```bash
kubectl run external-net-test \
  -n rag-dev --rm -it \
  --restart=Never \
  --image=curlimages/curl \
  -- sh
```

Inside the temporary Pod, try:

```sh
nslookup host.docker.internal
curl -v --connect-timeout 5 http://host.docker.internal:9000/minio/health/live
```

Expected: a resolvable host and a successful MinIO health response **if** Docker Desktop's host bridge is reachable from K3s. Failure means we need to determine another reachable endpoint; do not assume every WSL configuration behaves identically.

Exit the Pod with `exit`. This tests **one** dependency only; database and Redis connectivity need separate tests, and appropriate authentication.

## Step 15 — Deployment plan, conditional on the real project files

Do not blindly run Step 15 from the old README with example `rag-service:dev` images. The confirmed image tags are different. The eventual Deployment specs should use these exact images:

```yaml
# Illustration of image fields, NOT a complete Deployment manifest
# rag-service Pod:
image: rag-platform/rag-service:local
imagePullPolicy: IfNotPresent

# worker Pod (1 replica):
image: rag-platform/rag-worker:local
imagePullPolicy: IfNotPresent

# auth Pod:
image: rag-platform/auth-service:local
imagePullPolicy: IfNotPresent

# embedding Pod:
image: rag-platform/embedding-service:local
imagePullPolicy: IfNotPresent
```

Docling and MinIO need the actual, untruncated tags. `minio-init` needs its original Compose command/entrypoint, and should run as a Kubernetes **Job**, not an always-on Deployment. The worker should retain its working Redis Streams consumer semantics and existing command.

### 15.1 Validate prerequisites before deploying

```bash
kubectl get namespace rag-dev
kubectl get configmap -n rag-dev
kubectl get secret -n rag-dev
sudo k3s crictl images | grep -E 'rag-platform|docling'
```

Before generating final manifests, establish:

1. Exact image references and platform architecture.
2. The original `command`, `entrypoint`, `working_dir`, health checks and environment per Compose service.
3. Where PostgreSQL, Redis, MinIO run: **in K3s** or **still in Docker**.
4. Correct reachable URLs for `rag-service`, auth, embedding, and Docling.
5. Persistent data migration / backups if moving stateful containers.
6. Which migrations and MinIO init steps must run before API/worker startup.

Only then create `rag-workloads.yaml`, `rag-services.yaml`, stateful manifests, Secrets, and Jobs, or corresponding Helm templates.

### 15.2 Avoid the Docker 8000 port collision during testing

Your Docker Compose API currently publishes Windows/WSL host port **8000**. If that container is still running, the following **local port 18000** is safer for a K3s API test:

```bash
kubectl port-forward -n rag-dev svc/rag-service 18000:8000
```

Then open `http://localhost:18000/docs` if your FastAPI app serves docs there. This requires the `rag-service` Service and a healthy backing Pod. Use local port 15002 for embedding tests if 5002 is already taken.

## Step 16 — Helm once manifests work

After validating deployments using plain manifests, move them into your existing Helm chart (`deploy/k8s/charts/rag-platform` or your chosen path). Avoid taking ownership of preexisting resources until you've planned migration.

Use separate values for environments:

```text
deploy/k8s/
  charts/rag-platform/
    Chart.yaml
    values.yaml
    templates/
  environments/
    values-wsl.yaml
    values-ec2.yaml
```

Useful commands (run from the repository root, after creating or adapting the chart):

```bash
helm lint deploy/k8s/charts/rag-platform
helm template rag-platform deploy/k8s/charts/rag-platform \
  -n rag-dev -f deploy/k8s/environments/values-wsl.yaml
```

Then install only after reviewing output and removing conflicting unmanaged resources:

```bash
helm upgrade --install rag-platform \
  deploy/k8s/charts/rag-platform \
  -n rag-dev \
  -f deploy/k8s/environments/values-wsl.yaml
```

## Step 17 — Validation and debugging

```bash
kubectl get pods -A -o wide
kubectl get deployments,services -n rag-dev
kubectl get pvc -A
kubectl get events -n rag-dev --sort-by=.lastTimestamp
kubectl top nodes
```

For a failing Pod:

```bash
kubectl describe pod POD_NAME -n rag-dev
kubectl logs POD_NAME -n rag-dev --previous
```

Expected end-to-end functional tests (once configured): upload → Redis Stream job → Docling conversion → embedding request → pgvector insertion → retrieval → generation → chat; plus authentication, revocation, and owner deletion cleanup.

## What I need from you before I can write working manifests and exact ConfigMaps/Secrets

Please upload:

1. **`env.compose`**, with every API key, password, token, private key, secret and credential value replaced with `REDACTED`. **Preserve variable names and harmless non-secret settings.**
2. **All Compose YAML files** used when your stack starts (e.g., `compose.yaml`, `docker-compose.yml`, any override files). Redact any inline credentials.
3. **Any additional `env_file:` files** referenced by Compose, also redacted. `env.compose` alone may not represent the actual runtime environment.
4. **The Dockerfiles / relevant entrypoint scripts for the API, worker, auth and embedding images** if the Compose YAML doesn't reveal how they start.
5. **Database and MinIO initialization/migration scripts** if those are invoked during startup (file names and relevant content). This matters for preserving your `rag` and `auth` schemas and reproducing `minio-init`.

If sending files is inconvenient, provide at least the redacted Compose YAML and the **keys only** from `env.compose` and any service env files. Then we can construct the exact service-to-Service URLs and Secrets without guessing.

### Summary of safety constraints

- Importing images does **not** copy databases, Redis Streams, MinIO buckets, or Docker volumes.
- Keep the existing Docker stack available until corresponding K3s components pass validation.
- Don't reuse `localhost`, `host.docker.internal`, or `5435` inside Kubernetes without understanding the actual destination; in-cluster PostgreSQL commonly listens at port `5432`.
- Never ship plaintext credentials inside tracked `ConfigMap` YAML or a Git repository.
- Do not delete Compose volumes or restart database containers using the same volume from two runtimes.
- A complete RAG Kubernetes conversion requires working health checks, initialization jobs, storage and environment setup—not image imports alone.

## References

- [K3s: import local images](https://docs.k3s.io/add-ons/import-images)
- [Docker Compose: runtime environment variables](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)
- [Docker Compose: variable interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
- [K3s: storage](https://docs.k3s.io/storage)
