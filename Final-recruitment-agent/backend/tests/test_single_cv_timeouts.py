"""Regression tests for the 504 on POST /analyze-cv.

The fake Ollama is an httpx MockTransport with an async handler, so "slow" and "never finishes" are real
waiting (asyncio.sleep) inside the real llm.py and single_cv.py code, with limits scaled down to about a second.
"""
import asyncio
import dataclasses
import io
import json
import logging
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

from app import llm, main, runs, single_cv
from app.agents import extractor
from app.config import settings
from app.llm import LLMInvalidOutput, LLMTimeout, chat_json
from app.models import ExtractedProfile
from app.orchestrator.pipeline import run_retrieval



def make_cv_pdf() -> bytes:
    """A small, real, structured CV PDF built here, so the tests do not depend on any file in data/.
    It has the layout the parser reads (Skills / Experience (N years total) / Education) and contains every phrase
    that GOOD below quotes as evidence, so the QA agent approves GOOD and rejects CONTRADICTS_CV."""
    st = getSampleStyleSheet()
    lines = [
        ("Title", "Laila Mansour"), ("Normal", "Email: laila.mansour@example.com"),
        ("Heading2", "Backend Engineer"),
        ("Normal", "Backend engineer with 5 years building APIs and data services."),
        ("Heading2", "Skills"), ("Normal", "Python, FastAPI, SQL, Docker, PostgreSQL, Git"),
        ("Heading2", "Experience (5 years total)"),
        ("Normal", "- Backend Engineer, CloudPay (2021-2026): built FastAPI services on PostgreSQL and shipped "
                   "them as Docker images."),
        ("Normal", "- Software Engineer, DataWorks (2020-2021): wrote Python and SQL reports."),
        ("Heading2", "Education"), ("Normal", "B.Sc. Computer Science, Cairo University (2020)"),
    ]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, title="CV").build([Paragraph(t, st[k]) for k, t in lines])
    return buf.getvalue()


CV = make_cv_pdf()

GOOD = {"skills": ["Python", "FastAPI", "SQL", "Docker"], "experience_years": 5,
        "experience": ["Backend Engineer, CloudPay: built FastAPI services on PostgreSQL"],
        "education": ["B.Sc. Computer Science, Cairo University"], "projects": [],
        "evidence": {"Python": "Python", "FastAPI": "built FastAPI services", "SQL": "SQL", "Docker": "Docker images"}}
# 30 years of experience in a CV that says 5: the QA agent rejects it and asks for a second extraction
CONTRADICTS_CV = {**GOOD, "experience_years": 30}


def job():
    return next(j for j in asyncio.run(run_retrieval()).jobs if j.job_id == "J1")


def install_fake(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    async def via_fake(system, user, schema, **kw):
        return await chat_json(system, user, schema, transport=transport, **kw)

    monkeypatch.setattr(extractor, "chat_json", via_fake)


def reply(obj, **extra):
    return httpx.Response(200, json={"message": {"content": json.dumps(obj)}, **extra})


# ---------------------------------------------------------------- a hanging retry must not become a 504

def hanging_second_call():
    calls = {"n": 0}

    async def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return reply(CONTRADICTS_CV)
        await asyncio.sleep(30)                   # the model "hangs" on the retry
        return reply(GOOD)

    return handler, calls


def test_retry_that_hangs_keeps_the_first_answer_instead_of_timing_out(monkeypatch):
    handler, calls = hanging_second_call()
    install_fake(monkeypatch, handler)
    t = time.perf_counter()
    res = asyncio.run(single_cv.analyze_single_cv(CV, "s01.pdf", job(), mode="ollama", timeout=1.5))
    assert time.perf_counter() - t < 4                       # stopped by the remaining-time limit, not by the sleep
    assert calls["n"] == 2 and res.attempts == 1
    assert res.decision.label == "needs_review"              # the unverified answer goes to a person
    assert any("second extraction" in w for w in res.warnings)


def test_no_retry_is_started_when_there_is_not_enough_time_left(monkeypatch):
    calls = {"n": 0}

    async def handler(request):
        calls["n"] += 1
        await asyncio.sleep(0.5)                              # the first attempt takes 0.5s ...
        return reply(CONTRADICTS_CV)

    install_fake(monkeypatch, handler)
    res = asyncio.run(single_cv.analyze_single_cv(CV, "s01.pdf", job(), mode="ollama", timeout=0.9))
    assert calls["n"] == 1                                    # ... so 0.4s left is too little for a second one
    assert res.decision.label == "needs_review" and any("not enough time" in w for w in res.warnings)


def test_a_retry_that_has_time_still_runs_and_can_fix_the_answer(monkeypatch):
    calls = {"n": 0}

    async def handler(request):
        calls["n"] += 1
        return reply(CONTRADICTS_CV if calls["n"] == 1 else GOOD)

    install_fake(monkeypatch, handler)
    res = asyncio.run(single_cv.analyze_single_cv(CV, "s01.pdf", job(), mode="ollama", timeout=30))
    assert calls["n"] == 2 and res.attempts == 2 and res.decision.label == "suitable"


def test_first_attempt_that_never_answers_is_a_timeout_that_says_where(monkeypatch):
    async def handler(request):
        await asyncio.sleep(30)

    install_fake(monkeypatch, handler)
    with pytest.raises(LLMTimeout) as exc:
        asyncio.run(single_cv.analyze_single_cv(CV, "s01.pdf", job(), mode="ollama", timeout=0.4))
    assert "waiting for the extraction (attempt 1)" in str(exc.value)


# ---------------------------------------------------------------- runaway generation

def test_every_request_caps_the_length_of_the_answer(monkeypatch):
    seen = []

    async def handler(request):
        seen.append(json.loads(request.content))
        return reply(GOOD)

    install_fake(monkeypatch, handler)
    asyncio.run(single_cv.analyze_single_cv(CV, "s01.pdf", job(), mode="ollama"))
    assert seen[0]["options"]["num_predict"] == settings.llm_max_tokens == 2500
    assert seen[0]["options"]["temperature"] == 0


def test_an_answer_cut_off_by_the_limit_fails_at_once_with_a_clear_message():
    seen = []

    async def handler(request):
        seen.append(1)
        return httpx.Response(200, json={"message": {"content": '{"skills": ["Python",\n\n\n\n\n'},
                                         "done_reason": "length", "eval_count": 2500})

    with pytest.raises(LLMInvalidOutput) as exc:
        asyncio.run(chat_json("s", "u", ExtractedProfile, transport=httpx.MockTransport(handler)))
    assert len(seen) == 1                                    # no pointless repeat of a runaway generation
    assert "cut off after 2500 tokens" in str(exc.value) and "LLM_MAX_TOKENS" in str(exc.value)


def test_a_complete_answer_is_accepted_even_if_ollama_reports_length():
    async def handler(request):
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD)}, "done_reason": "length"})

    out = asyncio.run(chat_json("s", "u", ExtractedProfile, transport=httpx.MockTransport(handler)))
    assert out.skills[:2] == ["Python", "FastAPI"]


def test_prompt_tells_the_model_to_reply_with_json_only():
    assert "ONLY one JSON object" in extractor.SYSTEM_PROMPT


# ---------------------------------------------------------------- evidence for the next failure

def test_timing_logs_exist_and_contain_no_cv_content(monkeypatch, caplog):
    async def handler(request):
        return httpx.Response(200, json={"message": {"content": json.dumps(GOOD)}, "done_reason": "stop",
                                         "prompt_eval_count": 812, "eval_count": 190})

    install_fake(monkeypatch, handler)
    with caplog.at_level(logging.INFO, logger="recruitment"):
        asyncio.run(single_cv.analyze_single_cv(CV, "s01.pdf", job(), mode="ollama"))
    text = caplog.text
    assert "parsed PDF in" in text and "ollama attempt 1 answered in" in text
    assert "prompt_tokens=812 answer_tokens=190 done_reason=stop" in text and "finished in" in text
    for private in ("Laila", "Mansour", "laila.mansour@example.com", "CloudPay", "Cairo University"):
        assert private not in text


# ---------------------------------------------------------------- through the real endpoint

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "manager", runs.RunManager())

    async def ready(**kw):
        return {"reachable": True, "model_installed": True, "models": []}

    monkeypatch.setattr(main, "check_ollama", ready)
    with TestClient(main.app) as c:
        yield c


def post(client):
    return client.post("/analyze-cv", data={"job_id": "J1", "mode": "ollama"},
                       files={"file": ("s01.pdf", CV, "application/pdf")})


def test_endpoint_returns_200_when_the_retry_hangs(client, monkeypatch):
    handler, _ = hanging_second_call()
    install_fake(monkeypatch, handler)
    monkeypatch.setattr(single_cv, "settings", dataclasses.replace(settings, single_cv_timeout=1.5))
    r = post(client)
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["label"] == "needs_review" and "second extraction" in " ".join(r.json()["warnings"])


def test_endpoint_504_names_the_stage_when_the_first_attempt_hangs(client, monkeypatch):
    async def handler(request):
        await asyncio.sleep(30)

    install_fake(monkeypatch, handler)
    monkeypatch.setattr(single_cv, "settings", dataclasses.replace(settings, single_cv_timeout=0.4))
    r = post(client)
    assert r.status_code == 504 and r.json()["detail"]["code"] == "llm_timeout"
    assert "waiting for the extraction (attempt 1)" in r.json()["detail"]["message"]


def test_endpoint_runaway_answer_is_502_not_a_hang(client, monkeypatch):
    async def handler(request):
        return httpx.Response(200, json={"message": {"content": "{\n\n\n"}, "done_reason": "length", "eval_count": 2500})

    install_fake(monkeypatch, handler)
    r = post(client)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "llm_invalid_output"
    assert "cut off" in r.json()["detail"]["message"]
