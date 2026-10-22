"""Tests for the Ollama layer. No real model needed: HTTP is faked with httpx.MockTransport."""
import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.config import settings
from app.llm import LLMError, chat_json, check_ollama


class Verdict(BaseModel):
    ok: bool
    score: int


def run(coro):
    return asyncio.run(coro)


def replies_transport(contents: list[str]):
    """Fake Ollama /api/chat that returns the given contents one by one (last one repeats)."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        content = contents[min(len(seen) - 1, len(contents) - 1)]
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    return httpx.MockTransport(handler), seen


def test_valid_json_is_parsed_and_request_is_well_formed():
    transport, seen = replies_transport(['{"ok": true, "score": 7}'])
    out = run(chat_json("sys", "user", Verdict, transport=transport))
    assert out == Verdict(ok=True, score=7)
    body = seen[0]
    assert body["model"] == settings.ollama_model
    assert body["stream"] is False
    assert body["format"]["properties"].keys() == {"ok", "score"}   # JSON schema sent for structured output
    assert body["options"]["temperature"] == 0


def test_invalid_json_is_repaired_on_retry():
    transport, seen = replies_transport(["not json at all", '{"ok": false, "score": 3}'])
    out = run(chat_json("sys", "user", Verdict, transport=transport))
    assert out.score == 3
    assert len(seen) == 2
    assert "ONLY valid JSON" in seen[1]["messages"][-1]["content"]   # model was told what went wrong


def test_wrong_schema_is_treated_as_invalid():
    transport, seen = replies_transport(['{"ok": "maybe"}', '{"ok": true, "score": 1}'])
    assert run(chat_json("s", "u", Verdict, transport=transport)).ok is True
    assert len(seen) == 2


def test_gives_up_after_retries():
    transport, seen = replies_transport(["garbage"])
    with pytest.raises(LLMError, match="invalid JSON after 3 attempts"):
        run(chat_json("s", "u", Verdict, retries=2, transport=transport))
    assert len(seen) == 3


def test_ollama_not_running_gives_actionable_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError, match="ollama serve"):
        run(chat_json("s", "u", Verdict, transport=httpx.MockTransport(handler)))


def test_missing_model_tells_user_to_pull_it():
    transport = httpx.MockTransport(lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(LLMError, match="ollama pull"):
        run(chat_json("s", "u", Verdict, transport=transport))


def test_timeout_gives_actionable_error():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMError, match="did not answer"):
        run(chat_json("s", "u", Verdict, transport=httpx.MockTransport(handler)))


def test_check_ollama_reports_installed_model():
    tags = {"models": [{"name": settings.ollama_model}, {"name": "llama3.2:3b"}]}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=tags))
    status = run(check_ollama(transport=transport))
    assert status["reachable"] and status["model_installed"]


def test_check_ollama_reports_missing_model_and_unreachable():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "other:1b"}]}))
    status = run(check_ollama(transport=transport))
    assert status["reachable"] and not status["model_installed"]

    def down(request):
        raise httpx.ConnectError("refused")

    assert run(check_ollama(transport=httpx.MockTransport(down)))["reachable"] is False
