from platform_auth.dependencies import get_current_user_dependency

from app.rag.generation.types import GenerationError


def authorization_guard(request, owner_id):
    """Reverify expiry, signature, scopes and Redis blacklist through platform-auth v1.0.0."""
    token = request.headers.get("authorization", "").partition(" ")[2]
    dependency = get_current_user_dependency()

    async def guard():
        try:
            if await request.is_disconnected():
                raise GenerationError("client_disconnected", 499)
            user = await dependency(request, token=token)
            if str(user.id) != owner_id or not user.has_scope("rag:query"):
                raise GenerationError("authorization_lost", 401)
        except GenerationError:
            raise
        except Exception as exc:
            raise GenerationError("authorization_lost", 401) from exc

    return guard
