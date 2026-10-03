# platform-auth

Shared, installable package every service in this platform depends on
for JWT verification and RBAC. It does NOT contain token-issuing logic
(no private key, no login/register) — only auth-service does that.

## Install

Git dependency (fastest to start):
```toml
dependencies = ["platform-auth @ git+https://github.com/yourorg/platform-auth.git@v1.0.0"]
```

Once stable, switch to a private package index (GitHub Packages, AWS
CodeArtifact) and pin a plain version instead — proper `uv.lock`
resolution, no full git history on every install.

## Use

```python
# main.py
from platform_auth import setup_auth
app = FastAPI()
setup_auth(app)
```

```python
# any endpoint
from platform_auth import require_scopes, AuthenticatedUser

@router.post("/documents")
async def upload(current_user: AuthenticatedUser = Depends(require_scopes("rag:ingest"))):
    ...
```
