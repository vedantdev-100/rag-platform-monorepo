# K3s on Windows WSL2 — Complete Hands-On README

**Target:** Windows 11 + WSL2 + Ubuntu 24.04 + a **single-node K3s** cluster  
**Scope:** K3s installation, `kubectl`, deployments, Helm, Traefik Ingress, PVCs, DNS, secrets, local container images, and preparation for the existing RAG microservices  
**Updated:** 15 October 2026  
**Audience:** Familiar with Kubernetes fundamentals and `kind`; learning to operate K3s  
**Status:** Steps 1–13 are self-contained learning exercises. Steps 14–17 prepare your real RAG application and require application-specific configuration.

> **How to use this document:** Open it in VS Code or a Markdown viewer. Copy **only the commands**, one block at a time. Watch the terminal labels: **Windows PowerShell** and **Ubuntu WSL2** are not interchangeable. This guide is for local development, **not a hardened production deployment**.

## Table of contents

1. [Architecture and prerequisites](#1-architecture-and-prerequisites)
2. [Install/verify WSL2 and Ubuntu](#2-installverify-wsl2-and-ubuntu)
3. [Prepare Ubuntu and enable systemd](#3-prepare-ubuntu-and-enable-systemd)
4. [Optional: allocate WSL resources](#4-optional-allocate-wsl-resources)
5. [Install K3s](#5-install-k3s)
6. [Set up kubectl](#6-set-up-kubectl)
7. [Deploy, expose, scale, and test Nginx](#7-deploy-expose-scale-and-test-nginx)
8. [Install Helm and a test chart](#8-install-helm-and-a-test-chart)
9. [Configure and test Traefik Ingress](#9-configure-and-test-traefik-ingress)
10. [Create and test persistent storage](#10-create-and-test-persistent-storage)
11. [Test Kubernetes DNS](#11-test-kubernetes-dns)
12. [Create RAG namespace, ConfigMap, and Secret](#12-create-rag-namespace-configmap-and-secret)
13. [Load local Docker images into K3s](#13-load-local-docker-images-into-k3s)
14. [Plan the RAG service dependencies](#14-plan-the-rag-service-dependencies)
15. [Deploy RAG application workload templates](#15-deploy-rag-application-workload-templates)
16. [Create a starter Helm chart](#16-create-a-starter-helm-chart)
17. [Debugging, restarting, and cleanup](#17-debugging-restarting-and-cleanup)
18. [Next steps for a production-like RAG cluster](#18-next-steps-for-a-production-like-rag-cluster)
19. [Official references](#19-official-references)

---

## 1. Architecture and prerequisites

### What you're creating

```text
Windows browser / PowerShell
           |
           | localhost forwarding
           v
Ubuntu 24.04 on WSL2
  └── K3s (single Linux node)
        ├── API server / scheduler / controller manager
        ├── SQLite cluster datastore (default single-server install)
        ├── containerd (separate from Docker Desktop's engine)
        ├── CoreDNS
        ├── Flannel CNI
        ├── Traefik Ingress + ServiceLB
        ├── Local-path storage provisioner
        └── Your application Pods
```

**K3s vs kind:** With kind, nodes run inside containers. Here, the K3s server runs as a Linux **systemd service in WSL2**. One K3s server is a complete working Kubernetes cluster.

**Requirements:**

- Windows 11 with virtualization available; Windows 10 may also work with a supported WSL2 version.
- Ubuntu 24.04 running under WSL2 (or an existing modern Ubuntu WSL2 distribution).
- At least ~20 GB of free disk space; 8 GB+ overall system RAM recommended for the labs.
- Internet access for installing K3s and downloading test images.
- A terminal for Windows PowerShell and a terminal for Ubuntu.
- To deploy the **whole RAG stack**, plan significantly more RAM/CPU, especially for Docling and ONNX embeddings.

> **Safety:** Do not run these labs against an existing production Kubernetes context. The exercises create and delete test namespaces, Pods and volumes.

---

## 2. Install/verify WSL2 and Ubuntu

**Terminal: Windows PowerShell (Administrator)**

```powershell
wsl --version
wsl --list --verbose
```

If WSL needs updating:

```powershell
wsl --update
```

If Ubuntu 24.04 is **not** installed:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart Windows if prompted, launch Ubuntu, and create your Linux username/password.

Confirm that Ubuntu is version **2**:

```powershell
wsl --list --verbose
```

Only if Ubuntu 24.04 shows WSL version `1`:

```powershell
wsl --set-version Ubuntu-24.04 2
```

**Expected:** `Ubuntu-24.04 ... VERSION 2` (the distribution name may differ if you installed Ubuntu earlier).

> **Already running Ubuntu WSL2?** Keep your existing distribution. You do not need to install another copy just for K3s.

---

## 3. Prepare Ubuntu and enable systemd

**Terminal: Ubuntu WSL2**

Update packages and install basic utilities:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y curl wget git ca-certificates iptables nano jq
```

Inspect Linux and the current init process:

```bash
cat /etc/os-release
uname -a
ps -p 1 -o comm=
```

If the last command prints `systemd`, continue to step 4.

Otherwise, edit the WSL configuration:

```bash
sudo nano /etc/wsl.conf
```

Add these lines **without deleting other existing sections**:

```ini
[boot]
systemd=true
```

Save with `Ctrl+O`, Enter, `Ctrl+X`.

**Switch to Windows PowerShell:**

```powershell
wsl --shutdown
```

Reopen Ubuntu and verify:

```bash
ps -p 1 -o comm=
systemctl list-units --type=service --no-pager | head
```

**Expected:** The first command prints `systemd`. WSL2 supports systemd, but systemd services alone **do not keep WSL running indefinitely** after the distribution stops.

---

## 4. Optional: allocate WSL resources

**Terminal: Windows PowerShell**

Do this only if your laptop has enough memory. For example, on a **16 GB or larger** Windows machine:

```powershell
notepad $env:USERPROFILE\.wslconfig
```

Merge the following with any existing `[wsl2]` settings:

```ini
[wsl2]
memory=8GB
processors=4
swap=4GB
```

Apply the settings:

```powershell
wsl --shutdown
```

Reopen Ubuntu and verify:

```bash
free -h
nproc
```

> These are **WSL VM limits**, not Kubernetes requests or limits. For the complete RAG stack, tune memory after measuring Docling and ONNX workload use. Keep enough RAM available for Windows.

---

## 5. Install K3s

**Terminal: Ubuntu WSL2**

If you **already installed K3s**, do **not** reinstall it; start at the verification commands.

Install the single-node **server** with Kubernetes Secrets encryption at rest:

```bash
curl -sfL https://get.k3s.io | sudo sh -s - server --secrets-encryption
```

The script installs the K3s executable and sets up a systemd service named `k3s`.

Verify:

```bash
sudo systemctl status k3s --no-pager
sudo k3s --version
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get pods -A
```

**Expected:** One node with `STATUS=Ready`; system Pods may take a short time to start.

Inspect basic Kubernetes components:

```bash
sudo k3s kubectl get pods -n kube-system
sudo k3s kubectl get svc -A
sudo k3s kubectl get storageclass
sudo k3s kubectl get ingressclass
```

Typical built-ins: CoreDNS, Traefik, local-path-provisioner, Metrics Server and networking components.

Useful service commands:

```bash
sudo systemctl restart k3s
sudo systemctl stop k3s
sudo systemctl start k3s
sudo journalctl -u k3s -n 100 --no-pager
```

**Important K3s paths:**

| Path | Meaning |
|---|---|
| `/etc/rancher/k3s/k3s.yaml` | Admin kubeconfig |
| `/etc/rancher/k3s/config.yaml` | Optional persistent K3s configuration |
| `/var/lib/rancher/k3s/` | Local K3s data directory |
| `/var/lib/rancher/k3s/server/node-token` | Sensitive cluster join token |
| `/usr/local/bin/k3s-uninstall.sh` | Destructive uninstall script |

> For production, pin a tested K3s version (`INSTALL_K3S_VERSION=...`) instead of blindly upgrading to whatever the installer considers stable. Do not post the join token or kubeconfig publicly.

---

## 6. Set up kubectl

**Terminal: Ubuntu WSL2**

The K3s CLI includes `kubectl`. Copy the root-owned kubeconfig to your user account so plain `kubectl` works:

```bash
mkdir -p "$HOME/.kube"
chmod 700 "$HOME/.kube"

sudo install -m 600 \
  -o "$(id -un)" \
  -g "$(id -gn)" \
  /etc/rancher/k3s/k3s.yaml \
  "$HOME/.kube/config"
```

Verify the correct context:

```bash
command -v kubectl
kubectl config current-context
kubectl get nodes
kubectl get pods -A
kubectl cluster-info
```

If you also use kind, check your context **before any destructive command**:

```bash
kubectl config get-contexts
kubectl config current-context
```

If another tool shadows the K3s `kubectl`, you can explicitly use the K3s binary:

```bash
sudo k3s kubectl get nodes
```

> The copied kubeconfig has **cluster-admin** access. Keep its permissions private; never commit it to Git.

---

## 7. Deploy, expose, scale, and test Nginx

**Objective:** Exercise Deployment, ClusterIP Service, Pod replicas, rolling status, and `port-forward`.

```bash
kubectl create namespace demo

kubectl create deployment nginx \
  --image=nginx:stable-alpine \
  --namespace demo

kubectl expose deployment nginx \
  --port=80 \
  --target-port=80 \
  --type=ClusterIP \
  --namespace demo
```

Inspect:

```bash
kubectl get deployments,pods,svc -n demo
kubectl rollout status deployment/nginx -n demo
```

Expose the Service temporarily on the Ubuntu localhost:

```bash
kubectl port-forward -n demo svc/nginx 8080:80
```

**Keep this terminal open.** In your **Windows browser**, open:

```text
http://localhost:8080
```

You should see the Nginx welcome page. Press `Ctrl+C` to stop forwarding.

Scale replicas:

```bash
kubectl scale deployment nginx --replicas=3 -n demo
kubectl get pods -n demo -o wide
```

Scale back down:

```bash
kubectl scale deployment nginx --replicas=1 -n demo
```

**Note:** WSL2 `localhost` forwarding usually works automatically on recent Windows versions. If Windows cannot reach the forwarded port, first test it **inside Ubuntu** using `curl http://127.0.0.1:8080`.

---

## 8. Install Helm and a test chart

**Objective:** Learn chart installation, release inspection, values, and rollback/history.

**Terminal: Ubuntu WSL2**

Install **Helm 4**, the current stable major version, with the official script:

```bash
cd "$HOME"
curl -fsSL -o get_helm.sh \
  https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-4

less get_helm.sh
chmod 700 get_helm.sh
./get_helm.sh
```

Verify:

```bash
helm version
helm list -A
```

Create a lab namespace and install **Podinfo**, a lightweight HTTP test service:

```bash
kubectl create namespace k3s-lab

helm upgrade --install my-podinfo \
  oci://ghcr.io/stefanprodan/charts/podinfo \
  --version 6.14.1 \
  --namespace k3s-lab \
  --wait
```

Inspect the installed chart:

```bash
helm list -n k3s-lab
helm status my-podinfo -n k3s-lab
helm history my-podinfo -n k3s-lab
helm get values my-podinfo -n k3s-lab
kubectl get deployment,pods,svc -n k3s-lab
```

Expose Podinfo locally:

```bash
kubectl port-forward -n k3s-lab svc/my-podinfo 9898:9898
```

In Windows, open `http://localhost:9898` while port-forwarding is active. Podinfo normally returns an HTTP response; `/` may display a small UI or JSON depending on the application version.

Inspect the Kubernetes YAML rendered by Helm:

```bash
helm get manifest my-podinfo -n k3s-lab
```

Inspect chart defaults without installing another instance:

```bash
helm show values \
  oci://ghcr.io/stefanprodan/charts/podinfo \
  --version 6.14.1
```

---

## 9. Configure and test Traefik Ingress

**Objective:** Route incoming HTTP requests to a Kubernetes Service based on a hostname.

K3s normally ships with **Traefik Ingress** enabled. Verify:

```bash
kubectl get deployment traefik -n kube-system
kubectl get svc traefik -n kube-system
kubectl get ingressclass
```

Create the lab folder and an Ingress manifest:

```bash
mkdir -p "$HOME/k3s-learning"
cd "$HOME/k3s-learning"

cat > podinfo-ingress.yaml <<'YAML'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: podinfo-ingress
  namespace: k3s-lab
spec:
  ingressClassName: traefik
  rules:
    - host: podinfo.k3s.test
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-podinfo
                port:
                  number: 9898
YAML
```

Apply and inspect:

```bash
kubectl apply -f podinfo-ingress.yaml
kubectl get ingress -n k3s-lab
kubectl describe ingress podinfo-ingress -n k3s-lab
```

Forward **Traefik** to a high localhost port:

```bash
kubectl port-forward -n kube-system svc/traefik 8081:80
```

**Leave this running. Switch to Windows PowerShell:**

```powershell
curl.exe -H "Host: podinfo.k3s.test" http://localhost:8081/
```

**Expected:** Podinfo responds. The HTTP `Host` header matches the rule in the Ingress resource.

```text
Windows localhost:8081
  -> kubectl port-forward
  -> Traefik Service
  -> Ingress host rule podinfo.k3s.test
  -> my-podinfo Service :9898
  -> Podinfo Pod
```

**Optional browser hostname:** Open Notepad as Windows Administrator, edit `C:\Windows\System32\drivers\etc\hosts`, and add:

```text
127.0.0.1 podinfo.k3s.test
```

Then visit `http://podinfo.k3s.test:8081` **while the Traefik port-forward is running**.

> For this local lab, we deliberately use HTTP + port-forward. Production external Ingress needs appropriate routing, public/private DNS, TLS, and firewall rules. K3s ServiceLB is **not** the same as an AWS-managed load balancer.

---

## 10. Create and test persistent storage

**Objective:** Demonstrate a `PersistentVolumeClaim` (PVC) surviving Pod recreation.

Check the StorageClass:

```bash
kubectl get storageclass
```

The default is generally `local-path`, which stores data on the K3s node's filesystem.

**Terminal: Ubuntu WSL2**

```bash
cd "$HOME/k3s-learning"

cat > storage-demo.yaml <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: demo-pvc
  namespace: k3s-lab
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: storage-test
  namespace: k3s-lab
spec:
  containers:
    - name: busybox
      image: busybox:1.36
      command: ["sh", "-c", "sleep 3600"]
      volumeMounts:
        - name: storage
          mountPath: /data
  volumes:
    - name: storage
      persistentVolumeClaim:
        claimName: demo-pvc
YAML

kubectl apply -f storage-demo.yaml
kubectl get pvc,pods -n k3s-lab
kubectl get pv
```

**Note:** Some StorageClasses use delayed binding, so a PVC can be pending until its consuming Pod is scheduled.

Wait for the Pod:

```bash
kubectl wait --for=condition=Ready pod/storage-test \
  -n k3s-lab --timeout=120s
```

Write a file to the mounted volume:

```bash
kubectl exec -n k3s-lab storage-test -- \
  sh -c 'echo "K3s persistent storage works" > /data/test.txt'

kubectl exec -n k3s-lab storage-test -- cat /data/test.txt
```

Now **delete only the Pod**:

```bash
kubectl delete pod storage-test -n k3s-lab
```

Recreate it from the same manifest, wait for readiness and read the file:

```bash
kubectl apply -f storage-demo.yaml
kubectl wait --for=condition=Ready pod/storage-test \
  -n k3s-lab --timeout=120s
kubectl exec -n k3s-lab storage-test -- cat /data/test.txt
```

**Expected:** The original text is still present. The PVC outlives the Pod.

> `local-path` is appropriate for learning, but it is **not replicated storage**. Deleting the PVC or its namespace can remove the associated data. It is not an HA PostgreSQL storage solution.

---

## 11. Test Kubernetes DNS

**Objective:** See how Services become discoverable by DNS instead of fixed Pod IP addresses.

Start an ephemeral test Pod and query CoreDNS:

```bash
kubectl run dns-test \
  --namespace k3s-lab \
  --image=busybox:1.36 \
  --restart=Never \
  --command -- \
  nslookup my-podinfo.k3s-lab.svc.cluster.local
```

Read its output and clean up:

```bash
kubectl logs dns-test -n k3s-lab
kubectl delete pod dns-test -n k3s-lab
```

Kubernetes Service DNS typically looks like:

```text
<SERVICE>.<NAMESPACE>.svc.cluster.local
```

Inside the same namespace, a client can usually use just `<SERVICE>`.

---

## 12. Create RAG namespace, ConfigMap, and Secret

**Objective:** Separate RAG workloads from labs and configure non-secret vs secret environment variables.

Create the namespace:

```bash
kubectl create namespace rag-dev
```

Create a small **ConfigMap** for non-secret generation settings:

```bash
cd "$HOME/k3s-learning"

cat > rag-config.yaml <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata:
  name: rag-config
  namespace: rag-dev
data:
  RAG_GENERATION_ENABLED: "true"
  RAG_GENERATION_STRATEGY: "standard"
  RAG_LLM_PROVIDER: "groq"
  RAG_LLM_FREE_ONLY: "true"
YAML

kubectl apply -f rag-config.yaml
kubectl get configmap rag-config -n rag-dev
```

### Create a Secret safely

Create a local private env file (**example names/values only**):

```bash
umask 077
nano "$HOME/k3s-learning/.env.k3s-secrets"
```

Example **content**, not a command:

```dotenv
DATABASE_URL=postgresql+asyncpg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME
REDIS_URL=redis://REDIS_HOST:6379/0
GROQ_API_KEY=REPLACE_WITH_REAL_VALUE
```

Add the other values expected by your repository: separate auth database connection if required, platform-auth Redis URL, MinIO/S3 endpoint and credentials, JWKS/auth settings, embedding base URL, and model names. Do **not** assume this short sample covers your app.

Create the Secret:

```bash
chmod 600 "$HOME/k3s-learning/.env.k3s-secrets"

kubectl create secret generic rag-secrets \
  --from-env-file="$HOME/k3s-learning/.env.k3s-secrets" \
  --namespace rag-dev

kubectl get secret rag-secrets -n rag-dev
```

For subsequent updates to the file, use a controlled recreate command in your lab:

```bash
kubectl create secret generic rag-secrets \
  --from-env-file="$HOME/k3s-learning/.env.k3s-secrets" \
  -n rag-dev --dry-run=client -o yaml | kubectl apply -f -
```

**Security reminders:**

- Add `.env.k3s-secrets` to `.gitignore`; do not print secret values in screenshots.
- Use Kubernetes Secret rather than ConfigMap for credentials.
- Kubernetes `Secret` alone is not a complete production secrets-management solution.
- K3s installation in step 5 enabled encryption at rest; your cluster still needs reasonable RBAC and backups.

---

## 13. Load local Docker images into K3s

K3s has a **separate containerd image store**, so a Docker Desktop image built on Windows or within a Docker-integrated WSL distribution is **not automatically visible to K3s**.

### Option A: import a locally built image (easy single-node lab)

**Terminal: Ubuntu WSL2 — only if Docker Desktop WSL integration is configured**

```bash
docker --version
docker images
```

Assume you have successfully built these exact image tags:

```text
rag-service:dev
ingestion-worker:dev
embedding-service:dev
```

Export and import each image:

```bash
docker save -o /tmp/rag-service.tar rag-service:dev
sudo k3s ctr -n k8s.io images import /tmp/rag-service.tar

docker save -o /tmp/ingestion-worker.tar ingestion-worker:dev
sudo k3s ctr -n k8s.io images import /tmp/ingestion-worker.tar

docker save -o /tmp/embedding-service.tar embedding-service:dev
sudo k3s ctr -n k8s.io images import /tmp/embedding-service.tar
```

Verify:

```bash
sudo k3s crictl images | grep -E 'rag-service|ingestion-worker|embedding-service'
```

**Important:** These commands fail if the specified images do not already exist. Use the exact names/tags you build in your existing repo. Check the Docker Compose files and build contexts first.

In a Deployment, use a matching image and `imagePullPolicy: IfNotPresent` so the already-imported image is used.

### Option B: use a registry (best for future multi-node/EC2)

Push built images to GHCR or another registry, then use fully qualified references in Kubernetes:

```text
ghcr.io/YOUR_ORG/rag-service:YOUR_VERSION
ghcr.io/YOUR_ORG/ingestion-worker:YOUR_VERSION
ghcr.io/YOUR_ORG/embedding-service:YOUR_VERSION
```

Private registries require credentials (`imagePullSecrets`) or an appropriate K3s containerd registry configuration. Prefer immutable version or digest tags for non-lab deployment.

---

## 14. Plan the RAG service dependencies

Your current project has more than three services. **Deploying only the following three application Deployments is not enough to make the whole system work:**

```text
React frontend
    |
    v
rag-service (FastAPI) <------> platform-auth
    |  \ \
    |   \ +--------------> embedding-service (BGE + ONNX)
    |    +---------------> PostgreSQL + pgvector (rag & auth schemas)
    +--------------------> Redis (Streams + blacklist + rate limits)
                                 |
                                 v
                        ingestion-worker (single Docling worker)
                                 |
                                 v
                              MinIO / S3
```

### Recommended approach for your first local Kubernetes migration

1. **Initially keep known-good dependencies running** (PostgreSQL + pgvector, Redis, MinIO, platform-auth) while you learn to deploy the API, worker and embedding services to K3s.
2. Decide how the K3s Pods reach those dependency endpoints: in-cluster Kubernetes Service, a reachable network address, or (only for local experiments) a WSL/Docker Desktop bridge address verified from *inside a Pod*.
3. **Do not hardcode `localhost`** in a Pod for a dependency running outside that Pod. Inside a Pod, `localhost` means that Pod's own network namespace.
4. `host.docker.internal` may work for Docker Desktop containers but must **not** be assumed to work in K3s Pods. Check DNS/connectivity from a Pod before adopting it.
5. Later migrate PostgreSQL, Redis, and MinIO to Kubernetes stateful workloads with PVCs **or** to managed/external services. Preserve your `rag` and `auth` schemas and existing Redis stream semantics.

If deployed as Kubernetes Services **in namespace `rag-dev`**, example DNS values are:

| Dependency | Example in-cluster address | Notes |
|---|---|---|
| Redis | `redis.rag-dev.svc.cluster.local:6379` | Requires an actual Redis Service |
| PostgreSQL | `postgres.rag-dev.svc.cluster.local:5432` | Requires actual PostgreSQL Service with pgvector |
| MinIO | `http://minio.rag-dev.svc.cluster.local:9000` | Requires actual MinIO Service |
| Embedding | `http://embedding-service.rag-dev.svc.cluster.local:8000` | Defined in step 15 |
| RAG API | `http://rag-service.rag-dev.svc.cluster.local:8000` | Defined in step 15 |

**Do not copy these URLs into production env files until those Services exist.**

### RAG-specific requirements to preserve

- One **ingestion-worker** instance initially; Redis Streams consumer groups, pending-job recovery, idempotency and acknowledgment remain application responsibilities.
- PostgreSQL + pgvector preserving isolated `rag` and `auth` schemas.
- ONNX Runtime CPU embeddings, model initialization, batching and resource limits.
- MinIO source document object paths and lifecycle deletion semantics.
- Authentication/JWKS access and Redis blacklist/user-deletion streams.
- Migrations should be a **separately controlled Job/process**, not executed concurrently by every API Pod.

---

## 15. Deploy RAG application workload templates

**This is a starting Kubernetes template, not a guaranteed working deployment for your current codebase.** Correct the image tags, Python entrypoints/ports, required env vars and networking first. The real database, Redis, MinIO and auth endpoints must be available.

Create a manifest:

```bash
cd "$HOME/k3s-learning"

cat > rag-workloads.yaml <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-service
  namespace: rag-dev
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rag-service
  template:
    metadata:
      labels:
        app: rag-service
    spec:
      containers:
        - name: rag-service
          image: rag-service:dev
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: rag-config
            - secretRef:
                name: rag-secrets
          resources:
            requests:
              cpu: 200m
              memory: 512Mi
            limits:
              memory: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: rag-service
  namespace: rag-dev
spec:
  type: ClusterIP
  selector:
    app: rag-service
  ports:
    - port: 8000
      targetPort: 8000
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: embedding-service
  namespace: rag-dev
spec:
  replicas: 1
  selector:
    matchLabels:
      app: embedding-service
  template:
    metadata:
      labels:
        app: embedding-service
    spec:
      containers:
        - name: embedding-service
          image: embedding-service:dev
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 3Gi
---
apiVersion: v1
kind: Service
metadata:
  name: embedding-service
  namespace: rag-dev
spec:
  type: ClusterIP
  selector:
    app: embedding-service
  ports:
    - port: 8000
      targetPort: 8000
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingestion-worker
  namespace: rag-dev
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ingestion-worker
  template:
    metadata:
      labels:
        app: ingestion-worker
    spec:
      containers:
        - name: ingestion-worker
          image: ingestion-worker:dev
          imagePullPolicy: IfNotPresent
          envFrom:
            - configMapRef:
                name: rag-config
            - secretRef:
                name: rag-secrets
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              memory: 4Gi
YAML
```

**Before applying**, verify:

- The three images are imported or accessible via a registry.
- Container ports and entrypoints match the Dockerfiles.
- The API, worker, and embedding service receive their **own appropriate environment variables**. This simple shared Secret may need to be split into service-specific Secrets/ConfigMaps.
- The embedding service listens on a Pod-accessible interface such as `0.0.0.0`, not only `127.0.0.1`.
- PostgreSQL/Redis/MinIO/auth are reachable.
- Memory settings fit your WSL allocation (these are only initial estimates).

Validate Kubernetes object syntax (this does **not** validate your app config):

```bash
kubectl apply --dry-run=client -f rag-workloads.yaml
```

Apply only when ready:

```bash
kubectl apply -f rag-workloads.yaml
kubectl get deployments,pods,svc -n rag-dev
kubectl get events -n rag-dev --sort-by=.lastTimestamp
```

Inspect logs:

```bash
kubectl logs -n rag-dev deployment/rag-service --tail=100
kubectl logs -n rag-dev deployment/embedding-service --tail=100
kubectl logs -n rag-dev deployment/ingestion-worker --tail=100
```

If the API is healthy, forward its Service port:

```bash
kubectl port-forward -n rag-dev svc/rag-service 8000:8000
```

In Windows, visit `http://localhost:8000/docs` **if your FastAPI app exposes Swagger at `/docs`**.

### Test Pod-to-Service networking

From a temporary Pod in the same namespace:

```bash
kubectl run curl-test \
  --namespace rag-dev \
  --image=curlimages/curl \
  --restart=Never \
  --rm -it -- \
  curl -v http://embedding-service:8000/
```

An HTTP `404` at `/` can still prove that the connection worked; for health use the embedding service's actual implemented health endpoint.

### Full end-to-end RAG acceptance tests

Run these only after **all** dependencies are configured and reachable:

1. Sign up/login or obtain a valid authentication token.
2. Upload a small text document through your actual document upload endpoint.
3. Confirm the Redis ingestion job is consumed and marked complete.
4. Confirm MinIO contains the source object, and PostgreSQL contains document/chunk/vector records.
5. Run retrieval and generation, inspect citations, and verify the embedding service was called.
6. Test conversation creation, follow-up messages, and document selection.
7. Test user-delete/revoke events and ensure your established deletion semantics still work.

> **Do not interpret `kubectl get pods` showing `Running` as proof of a successful RAG system.** Application-level integration tests are essential.

---

## 16. Create a starter Helm chart

Helm organizes Deployments, Services, and other Kubernetes resources into a **chart** with templates and values. First create a working sample chart; later transform it into a real `rag-platform` chart.

**Terminal: Ubuntu WSL2**

```bash
mkdir -p "$HOME/k3s-learning/charts"
cd "$HOME/k3s-learning/charts"

helm create nginx-lab
```

Inspect:

```bash
find nginx-lab -maxdepth 2 -type f | sort
```

Validate and render the **generated starter chart**:

```bash
helm lint ./nginx-lab
helm template test-nginx ./nginx-lab --namespace demo
```

If the default chart is still unmodified, it normally deploys a test Nginx-like HTTP application. Install into the `demo` namespace you created in step 7:

```bash
helm upgrade --install test-nginx ./nginx-lab \
  --namespace demo --wait

helm status test-nginx -n demo
helm list -n demo
```

To iterate with values:

```bash
helm show values ./nginx-lab
```

> **For the actual RAG Helm chart**, generate a new `rag-platform` chart, replace starter templates with templates for your API, single ingestion worker, embedding service and ingress, then use values files like `values-dev.yaml` and `values-prod.yaml`. A custom `values.yaml` key is inert until a template references it.

Suggested eventual repo structure:

```text
rag-service/
└── deploy/
    └── k8s/
        ├── charts/
        │   └── rag-platform/
        │       ├── Chart.yaml
        │       ├── values.yaml
        │       └── templates/
        │           ├── rag-api.yaml
        │           ├── ingestion-worker.yaml
        │           ├── embedding-service.yaml
        │           ├── services.yaml
        │           └── ingress.yaml
        └── environments/
            ├── values-dev.yaml
            └── values-prod.yaml
```

**Helm ownership warning:** If you already deployed `rag-service` and the other resources via `kubectl apply`, do not install a Helm chart over them without planning resource ownership. First experiment in a separate namespace or clean up only your disposable test resources.

---

## 17. Debugging, restarting, and cleanup

### Day-to-day diagnostics

```bash
# Infrastructure
kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl top nodes
kubectl top pods -A
kubectl get events -A --sort-by=.lastTimestamp

# K3s service
sudo systemctl status k3s --no-pager
sudo journalctl -u k3s -f

# Helm
helm list -A

# Storage and HTTP routing
kubectl get pvc -A
kubectl get pv
kubectl get ingress -A
```

### Debug a failing Pod

```bash
kubectl describe pod POD_NAME -n rag-dev
kubectl logs POD_NAME -n rag-dev --tail=100
kubectl logs POD_NAME -n rag-dev --previous --tail=100
```

Replace `POD_NAME` with an actual Pod name from `kubectl get pods -n rag-dev`.

| Symptom | First checks |
|---|---|
| `ImagePullBackOff` | Exact tag? Imported into K3s containerd? Registry credentials? |
| `CrashLoopBackOff` | Application logs, entrypoint, secrets, dependency URL, OOMKilled? |
| `Pending` | Node memory/CPU limits, volume binding, node selectors and events |
| Ingress returns 404 | `Host` header, matching Ingress hostname, Service name and port |
| PVC `Pending` | Local-path provisioner running? Consuming Pod scheduled? |
| Windows cannot reach `localhost` | Is port-forward still running? Does the port work from Ubuntu? |
| `kubectl` connects to wrong cluster | `kubectl config current-context` and `kubectl config get-contexts` |
| K3s stops after WSL shutdown | Reopen WSL, check systemd and `sudo systemctl start k3s` |

### Safe cleanup of labs

First **stop any active port-forwards** with `Ctrl+C`.

Delete the Helm-managed Podinfo lab and its Ingress:

```bash
helm uninstall my-podinfo -n k3s-lab
kubectl delete -f "$HOME/k3s-learning/podinfo-ingress.yaml" --ignore-not-found
```

Delete the complete **test namespace** (including its PVC and test data):

```bash
kubectl delete namespace k3s-lab
```

Delete the Nginx Helm lab, then the `demo` namespace:

```bash
helm uninstall test-nginx -n demo
kubectl delete namespace demo
```

**Optional: only if you intentionally deployed the RAG example workload templates:**

```bash
kubectl delete -f "$HOME/k3s-learning/rag-workloads.yaml"
```

**Do not delete `rag-dev`** if you have configuration/data to retain.

### Full K3s uninstall — DESTRUCTIVE

Only run if you want to remove the local K3s cluster and its local cluster data:

```bash
sudo /usr/local/bin/k3s-uninstall.sh
```

This is **not** a normal cleanup command. Local Kubernetes resources and local storage can be lost.

---

## 18. Next steps for a production-like RAG cluster

Once the WSL2 labs pass:

1. **Service configuration:** Decide what remains in Docker Compose vs what moves into K3s. Make all dependency URLs/health checks explicit.
2. **Real storage:** Migrate PostgreSQL + pgvector, Redis Streams, and MinIO to appropriately backed-up stateful services; avoid treating local-path storage as production HA.
3. **Health checks:** Add appropriate startup/readiness/liveness probes, especially for model loading and database failures.
4. **Resource sizing:** Measure ONNX batches, model memory, PDF conversion peaks, and Postgres/Redis usage before allocating replicas/limits.
5. **Chart packaging:** Make a fully working `rag-platform` Helm chart with independent deployments and environment-specific values.
6. **Ingress/TLS:** Configure a real endpoint and TLS; keep PostgreSQL, Redis and embedding services internal.
7. **Observability:** Metrics Server initially, then Prometheus/Grafana, logs, OpenTelemetry and ingestion queue metrics.
8. **Migrations:** Run Alembic as a controlled job/process, not in every API container.
9. **Backups and recovery:** Back up cluster datastore **and** application data independently.
10. **Multi-node/EC2:** Deploy a separate multi-node K3s cluster once the WSL2 app flow works; consider HA control plane and the proper AWS networking/storage integration.

**Do not use WSL2 itself as a production Kubernetes host.** Its networking, service lifecycle, storage and availability do not match dedicated Linux/EC2 nodes.

---

## 19. Official references

- [K3s Quick-Start](https://docs.k3s.io/quick-start)
- [K3s Configuration Options](https://docs.k3s.io/installation/configuration)
- [K3s Secrets Encryption](https://docs.k3s.io/security/secrets-encryption)
- [K3s Networking Services](https://docs.k3s.io/networking/networking-services)
- [K3s Private Registries](https://docs.k3s.io/installation/private-registry)
- [K3s Air-Gap and Image Import](https://docs.k3s.io/installation/airgap)
- [Microsoft: Systemd in WSL](https://learn.microsoft.com/windows/wsl/systemd)
- [Microsoft: WSL Advanced Configuration](https://learn.microsoft.com/windows/wsl/wsl-config)
- [Helm Installation](https://helm.sh/docs/intro/install/)
- [Helm Quickstart](https://helm.sh/docs/intro/quickstart/)
- [Podinfo Helm Chart](https://github.com/stefanprodan/podinfo/tree/master/charts/podinfo)

---

## Completion checklist

- [ ] WSL2 / Ubuntu working
- [ ] systemd enabled
- [ ] K3s installed; node `Ready`
- [ ] `kubectl` configured without `sudo`
- [ ] Nginx Pod, Service and scaling tested
- [ ] Helm installed; Podinfo release deployed
- [ ] Traefik Ingress responding from Windows
- [ ] PVC write/delete/recreate persistence tested
- [ ] Kubernetes DNS tested
- [ ] RAG namespace, ConfigMap and Secret prepared
- [ ] Application images imported or registry configured
- [ ] RAG dependencies connected and validated
- [ ] API, embedding, and worker workloads healthy
- [ ] End-to-end RAG upload → ingestion → retrieval → chat verified
- [ ] Helm chart prepared for reproducible releases

**End of README.**
