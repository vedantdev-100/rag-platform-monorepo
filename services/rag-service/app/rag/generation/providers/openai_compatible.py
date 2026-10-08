import json

import httpx

from app.rag.generation.types import GenerationError, ProviderResult

URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}


async def sse_events(lines, max_frame=262144):
    """SSE framing: comments, multiline data, CRLF, bounded frames and EOF."""
    data, count, event = [], 0, "message"
    async for line in lines:
        count += len(line.encode("utf-8"))
        if count > max_frame:
            raise GenerationError("provider_frame_too_large", 502)
        if line == "":
            if data:
                yield event, "\n".join(data)
            data, count, event = [], 0, "message"
        elif line.startswith("event:"):
            event = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        # Other SSE fields/comments are ignored.
    if data:
        yield event, "\n".join(data)


async def sse_data(lines, max_frame=262144):
    async for _, data in sse_events(lines, max_frame):
        yield data


class ChatProvider:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.RAG_LLM_TIMEOUT_SECONDS, connect=10),
            limits=httpx.Limits(
                max_connections=settings.RAG_LLM_MAX_CONCURRENT,
                max_keepalive_connections=settings.RAG_LLM_MAX_CONCURRENT,
            ),
            follow_redirects=False,
        )

    async def close(self):
        await self.client.aclose()

    async def generate(self, messages, emit):
        settings = self.settings
        limit_key = (
            "max_completion_tokens"
            if settings.RAG_LLM_PROVIDER in {"groq", "openai"}
            else "max_tokens"
        )
        body = {
            "model": settings.model,
            "messages": messages,
            "stream": True,
            limit_key: settings.RAG_LLM_MAX_OUTPUT_TOKENS,
        }
        # Avoid unsupported temperature/structured-output options across model families.
        result = ProviderResult(
            provider=settings.RAG_LLM_PROVIDER, model=settings.model
        )
        done, frames, output_bytes = False, 0, 0
        try:
            async with self.client.stream(
                "POST",
                URLS[settings.RAG_LLM_PROVIDER],
                headers={"Authorization": "Bearer " + settings.api_key},
                json=body,
            ) as response:
                if response.status_code != 200:
                    status = response.status_code
                    retry_after = response.headers.get("retry-after", "")
                    retry_after = int(retry_after) if retry_after.isdigit() else None
                    if retry_after is not None:
                        retry_after = min(retry_after, 3600)
                    code = (
                        "provider_rate_limited"
                        if status == 429
                        else (
                            "provider_configuration_error"
                            if status in {400, 401, 402, 403, 404}
                            else "provider_unavailable"
                        )
                    )
                    raise GenerationError(
                        code,
                        429 if status == 429 else 503,
                        status == 429 or status >= 500,
                        retry_after,
                    )
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise GenerationError("invalid_provider_content_type", 502)
                async for data in sse_data(response.aiter_lines()):
                    frames += 1
                    if frames > 20000:
                        raise GenerationError("provider_stream_too_large", 502)
                    if data == "[DONE]":
                        done = True
                        break
                    try:
                        frame = json.loads(data)
                        if not isinstance(frame, dict) or frame.get("error"):
                            raise ValueError("error frame")
                        if isinstance(frame.get("model"), str):
                            result.model = frame["model"][:200]
                        usage = frame.get("usage")
                        if isinstance(usage, dict):
                            result.usage = {
                                k: v
                                for k, v in usage.items()
                                if k
                                in {
                                    "prompt_tokens",
                                    "completion_tokens",
                                    "total_tokens",
                                }
                                and type(v) is int
                                and v >= 0
                            }
                        choices = frame.get("choices", [])
                        if not isinstance(choices, list):
                            raise ValueError("choices")
                        if not choices:
                            continue
                        choice = choices[0]
                        finish = choice.get("finish_reason")
                        if finish is not None:
                            if result.finish_reason and result.finish_reason != finish:
                                raise ValueError("conflicting finish markers")
                            result.finish_reason = finish
                        delta = choice.get("delta", {})
                        text = delta.get("content")
                        if text is not None and not isinstance(text, str):
                            raise ValueError("invalid text")
                        if text:
                            output_bytes += len(text.encode("utf-8"))
                            if output_bytes > 131072:
                                raise GenerationError("provider_output_too_large", 502)
                            result.text += text
                            await emit("delta", {"text": text, "provisional": True})
                    except (ValueError, TypeError, AttributeError, IndexError) as exc:
                        raise GenerationError("invalid_provider_stream", 502) from exc
                if not done or result.finish_reason is None:
                    raise GenerationError("incomplete_generation", 502)
        except httpx.TimeoutException as exc:
            raise GenerationError("provider_timeout", 504, True) from exc
        except httpx.HTTPError as exc:
            raise GenerationError("provider_unavailable", 503, True) from exc
        return result


class FallbackProvider:
    """At most one alternate attempt, only for transient failures before any text."""

    def __init__(self, primary, alternate):
        self.primary, self.alternate = primary, alternate

    async def generate(self, messages, emit):
        emitted = False

        async def track(name, data):
            nonlocal emitted
            if name == "delta" and data.get("text"):
                emitted = True
            await emit(name, data)

        try:
            return await self.primary.generate(messages, track)
        except GenerationError as exc:
            if emitted or not exc.retryable:
                raise
            await emit(
                "stage",
                {
                    "stage": "provider_fallback",
                    "provider": self.alternate.settings.RAG_LLM_PROVIDER,
                },
            )
            return await self.alternate.generate(messages, emit)

    async def close(self):
        await self.primary.close()
        await self.alternate.close()


def build_provider(settings):
    if settings.RAG_LLM_PROVIDER not in URLS:
        raise ValueError("Unsupported provider")
    primary = ChatProvider(settings)
    if not settings.RAG_LLM_FALLBACK_ENABLED:
        return primary
    alternate_settings = settings.model_copy(
        update={
            "RAG_LLM_PROVIDER": settings.RAG_LLM_FALLBACK_PROVIDER,
            "RAG_LLM_FALLBACK_ENABLED": False,
        }
    )
    return FallbackProvider(primary, ChatProvider(alternate_settings))
