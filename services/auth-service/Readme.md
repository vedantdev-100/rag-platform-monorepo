# For local testing use this package:
    platform-auth @ file:///D:/rag-platform-monorepo/packages/platform-auth
# For production testing use this package: add this to dependencis =[] in pyproj.toml
    "platform-auth @ git+https://github.com/vedantdev-100/platform-auth.git@v1.0.0",

uv cache clean platform-auth
uv sync --reinstall-package platform-auth

# Start REDIS container
docker run -d --name redis -p 6379:6379 redis:7-alpine

# ption B of using the package directly as git dependency
    cd packages/platform-auth
    git add -A && git commit -m "fix: load .env in PlatformAuthSettings"
    git tag -f v1.0.0 && git push origin v1.0.0 --force
    cd ../../services/auth-service
    uv lock --upgrade-package platform-auth && uv sync
Confirm fix : uv run python -c "import platform_auth.config, inspect; print(inspect.getsource(platform_auth.config.PlatformAuthSettings.model_config))"


When you move to Kubernetes later, the only change is the URL value — swap http://localhost:8001 for the cluster-internal DNS name (http://auth-service.rag-platform.svc.cluster.local). Nothing in the code changes, only the .env/Secret value — this is exactly what the JWKS-over-HTTP design was for.


DBSetup
Migration.md file


One honest gap this doesn't close

A user's current access token stays valid until its natural 15-minute expiry even after you hard-delete them — deactivate_user/delete_user revoke refresh tokens immediately, but AuthenticatedUser (from the JWT) doesn't carry a jti that rag-service could blacklist on-demand. This is the same tradeoff you already have on logout, just surfaced again here. Closing it fully means extending platform_auth.AuthenticatedUser to carry jti and giving auth-service write access to the same Redis blacklist platform_auth already reads from — a reasonable next step, but a separate piece of work from what you asked for here.