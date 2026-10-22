"""The only place the project talks to an LLM: a local Ollama server (free, no API key).

Every agent calls `chat_json(...)` and gets back a validated Pydantic object, or an
`LLMError` with a message that says what to fix.
"""
import asyncio
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.logs import get_logger

T = TypeVar("T", bound=BaseModel)
log = get_logger("llm")


class LLMError(RuntimeError):
    """The model is unreachable, missing, too slow, or never returned valid output.

    `code` is machine-readable so the API and the dashboard can say what went wrong.
    """
    code = "llm_error"


class LLMUnavailable(LLMError):
    """Ollama is not running, the model is not installed, or the server answered with an HTTP error."""
    code = "llm_unavailable"


class LLMTimeout(LLMError):
    """The model did not answer within LLM_TIMEOUT."""
    code = "llm_timeout"


class LLMInvalidOutput(LLMError):
    """The model kept answering with something that is not valid JSON for the schema."""
    code = "llm_invalid_output"


# Counters for the evaluation report (Output Validity). Reset with `reset_stats()`.
stats = {"calls": 0, "valid_first_try": 0, "repaired": 0, "failed": 0}


def reset_stats() -> None:
    for k in stats:
        stats[k] = 0


# One semaphore per event loop: limits parallel requests so a laptop is not overloaded.
_semaphores: dict[int, asyncio.Semaphore] = {}


def _semaphore() -> asyncio.Semaphore:
    key = id(asyncio.get_running_loop())
    return _semaphores.setdefault(key, asyncio.Semaphore(max(1, settings.llm_concurrency)))


async def chat_json(
    system: str,
    user: str,
    schema: type[T],
    *,
    retries: int = 2,
    transport: httpx.AsyncBaseTransport | None = None,
) -> T:
    """Ask the model for JSON that matches `schema`. Invalid output is sent back for repair."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_error = ""
    stats["calls"] += 1

    async with _semaphore():
        async with httpx.AsyncClient(
            base_url=settings.ollama_host, timeout=settings.llm_timeout, transport=transport
        ) as client:
            for attempt in range(retries + 1):
                t_req = time.perf_counter()
                try:
                    resp = await client.post(
                        "/api/chat",
                        json={
                            "model": settings.ollama_model,
                            "messages": messages,
                            "stream": False,
                            "format": schema.model_json_schema(),  # structured output
                            # num_predict caps the answer: without it a model that never closes the JSON
                            # keeps generating until the HTTP timeout and the whole request looks "hung"
                            "options": {"temperature": 0, "num_predict": settings.llm_max_tokens},
                        },
                    )
                    resp.raise_for_status()
                except httpx.ConnectError as exc:
                    stats["failed"] += 1
                    raise LLMUnavailable(
                        f"Cannot reach Ollama at {settings.ollama_host}. "
                        "Install it from https://ollama.com and make sure it is running (`ollama serve`)."
                    ) from exc
                except httpx.TimeoutException as exc:
                    log.warning("ollama attempt %d TIMED OUT after %.1fs (limit %.0fs, model %s)",
                                attempt + 1, time.perf_counter() - t_req, settings.llm_timeout, settings.ollama_model)
                    stats["failed"] += 1
                    raise LLMTimeout(
                        f"Ollama did not answer within {settings.llm_timeout:.0f}s. "
                        "Try a smaller model (OLLAMA_MODEL=llama3.2:3b) or raise LLM_TIMEOUT."
                    ) from exc
                except httpx.HTTPStatusError as exc:
                    stats["failed"] += 1
                    if exc.response.status_code == 404:
                        raise LLMUnavailable(
                            f"Model '{settings.ollama_model}' is not installed. "
                            f"Run: ollama pull {settings.ollama_model}"
                        ) from exc
                    raise LLMUnavailable(f"Ollama returned HTTP {exc.response.status_code}") from exc

                body = resp.json()
                content = body.get("message", {}).get("content", "")
                cut_off = body.get("done_reason") == "length"
                log.info("ollama attempt %d answered in %.1fs: prompt_tokens=%s answer_tokens=%s done_reason=%s chars=%d",
                         attempt + 1, time.perf_counter() - t_req, body.get("prompt_eval_count"),
                         body.get("eval_count"), body.get("done_reason"), len(content))
                try:
                    parsed = schema.model_validate_json(content)
                    stats["valid_first_try" if attempt == 0 else "repaired"] += 1
                    return parsed
                except ValidationError as exc:
                    if cut_off:
                        # Asking again with the same prompt would run into the same limit and waste another
                        # full generation, so stop here with a message that says what happened.
                        stats["failed"] += 1
                        raise LLMInvalidOutput(
                            f"The model's answer was cut off after {body.get('eval_count') or settings.llm_max_tokens} "
                            "tokens before the JSON was complete (it kept generating). Try a different model "
                            "(OLLAMA_MODEL) or raise LLM_MAX_TOKENS.") from exc
                    last_error = str(exc)[:300]
                    messages += [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": (
                            "Your reply did not match the required JSON schema "
                            f"({last_error}). Reply again with ONLY valid JSON.")},
                    ]

    stats["failed"] += 1
    raise LLMInvalidOutput(f"Model returned invalid JSON after {retries + 1} attempts: {last_error}")


async def check_ollama(*, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Is Ollama running, and is the configured model installed?"""
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_host, timeout=5, transport=transport) as client:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
    except httpx.HTTPError:
        return {"reachable": False, "model_installed": False, "models": []}

    models = [m["name"] for m in resp.json().get("models", [])]
    want = settings.ollama_model
    installed = any(m == want or m.split(":")[0] == want for m in models)
    return {"reachable": True, "model_installed": installed, "models": models}
