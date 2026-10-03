"""
Single shared slowapi Limiter. Lives in core/ (not in an endpoint module) so
every router — auth, documents, future RAG endpoints — decorates with the
SAME instance that main.py registers on app.state; default_limits therefore
apply app-wide and per-route limits share one storage backend (swap to
Redis here when running multiple replicas — see PRODUCTION_READINESS.md).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

limiter = Limiter(key_func=get_remote_address, default_limits=[get_settings().RATE_LIMIT_DEFAULT])
