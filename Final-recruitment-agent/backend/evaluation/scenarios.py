"""Error-handling scenarios, each executed for real against the code (nothing is assumed).

A scenario counts as HANDLED when the system answers with a clear, specific error (or finishes the run
without the bad item) instead of crashing, hanging, or returning a result built on nothing.

The LLM failure scenarios use the real `app/llm.py` talking to a FAKE Ollama server (httpx.MockTransport)
because the point is to test how the system reacts to a timeout, an HTTP error or non-JSON text.
They say nothing about how often a real model fails.
"""
import asyncio
import contextlib
import dataclasses
import io
import json
import shutil
import tempfile
from pathlib import Path

import httpx
from pypdf import PdfWriter

from app import single_cv
from app.actions import report as report_mod
from app.agents import extractor
from app.config import BACKEND_DIR, settings
from app.llm import LLMError, LLMInvalidOutput, LLMTimeout, LLMUnavailable, chat_json
from app.orchestrator import pipeline, store
from app.orchestrator import workflow as workflow_mod
from app.orchestrator.workflow import run_recruitment_workflow
from app.retrievers import cv_retriever
from app.retrievers.cv_retriever import CvError

GOOD_CV = next((BACKEND_DIR / "data" / "eval" / "single_cv").glob("s01_*.pdf"))


def _pdf(encrypt: str | None = None, blank=True) -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    if encrypt:
        w.encrypt(encrypt)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@contextlib.contextmanager
def _patched(module, **attrs):
    old = {k: getattr(module, k) for k in attrs}
    for k, v in attrs.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(module, k, v)


def _fake_llm(handler):
    transport = httpx.MockTransport(handler)

    async def via_fake(system, user, schema, **kw):
        return await chat_json(system, user, schema, transport=transport, **kw)

    return via_fake


async def _job(job_id: str = "J1"):
    retrieval = await pipeline.run_retrieval()
    return next(j for j in retrieval.jobs if j.job_id == job_id)


def _row(name: str, group: str, expected: str, handled: bool, observed: str) -> dict:
    return {"name": name, "group": group, "expected": expected, "handled": handled, "observed": observed}


async def _single_file(name: str, data: bytes, filename: str, code: str, job, **settings_patch) -> dict:
    expected = f"error '{code}' with a message naming the file"
    try:
        with _patched(cv_retriever, settings=dataclasses.replace(settings, **settings_patch)) if settings_patch \
                else contextlib.nullcontext():
            await single_cv.analyze_single_cv(data, filename, job, mode="mock")
        return _row(name, "File errors (single CV)", expected, False, "no error: the file was accepted")
    except CvError as exc:
        ok = exc.code == code and Path(filename).name in str(exc)
        return _row(name, "File errors (single CV)", expected, ok, f"{exc.code}: {exc}")
    except Exception as exc:  # anything else is a crash from the user's point of view
        return _row(name, "File errors (single CV)", expected, False, f"crashed: {type(exc).__name__}: {exc}")


async def _single_llm(name: str, handler, expected_exc: type[LLMError], job) -> dict:
    expected = f"{expected_exc.__name__} (code '{expected_exc.code}')"
    try:
        with _patched(extractor, chat_json=_fake_llm(handler)):
            await single_cv.analyze_single_cv(GOOD_CV.read_bytes(), "s01.pdf", job, mode="ollama")
        return _row(name, "LLM failures (simulated server)", expected, False, "no error was raised")
    except LLMError as exc:
        return _row(name, "LLM failures (simulated server)", expected, type(exc) is expected_exc,
                    f"{exc.code}: {str(exc)[:110]}")
    except Exception as exc:
        return _row(name, "LLM failures (simulated server)", expected, False, f"crashed: {type(exc).__name__}: {exc}")


def _raise_timeout(req):
    raise httpx.ReadTimeout("simulated timeout", request=req)


def _raise_connect(req):
    raise httpx.ConnectError("simulated: connection refused", request=req)


async def run_scenarios() -> list[dict]:
    rows: list[dict] = []
    job = await _job("J1")
    good = GOOD_CV.read_bytes()

    # ---- unusable single-CV files
    rows += [
        await _single_file("Unsupported type (.txt)", b"Python FastAPI SQL", "cv.txt", "unsupported_type", job),
        await _single_file("Unsupported type (.docx)", b"PK\x03\x04 zip", "cv.docx", "unsupported_type", job),
        await _single_file("Empty file (0 bytes)", b"", "empty.pdf", "empty_file", job),
        await _single_file("Text renamed to .pdf", b"just some text", "fake.pdf", "not_a_pdf", job),
        await _single_file("Corrupt PDF", b"%PDF-1.4\n1 0 obj <<>>\ngarbage", "broken.pdf", "corrupt_pdf", job),
        await _single_file("PDF with no text (like a scan)", _pdf(), "scan.pdf", "no_text", job),
        await _single_file("File over the size limit", good, "big.pdf", "too_large", job, max_upload_mb=0.0001),
    ]
    try:
        rows.append(await _single_file("Password-protected PDF", _pdf("secret"), "locked.pdf", "pdf_encrypted", job))
    except Exception as exc:
        rows.append(_row("Password-protected PDF", "File errors (single CV)", "error 'pdf_encrypted'", False,
                         f"could not build the test file: {exc}"))

    # ---- LLM failures in single-CV mode
    ok_json = json.dumps({"skills": ["Python"], "experience_years": 5, "experience": [], "education": [],
                          "projects": [], "evidence": {}})
    rows += [
        await _single_llm("Model timeout", _raise_timeout, LLMTimeout, job),
        await _single_llm("Ollama not reachable (connection refused)", _raise_connect, LLMUnavailable, job),
        await _single_llm("Ollama HTTP 500", lambda r: httpx.Response(500, text="boom"), LLMUnavailable, job),
        await _single_llm("Model not installed (HTTP 404)", lambda r: httpx.Response(404), LLMUnavailable, job),
        await _single_llm("Non-JSON answer",
                          lambda r: httpx.Response(200, json={"message": {"content": "Sure! Here is the answer: {oops"}}),
                          LLMInvalidOutput, job),
        await _single_llm("JSON with the wrong shape",
                          lambda r: httpx.Response(200, json={"message": {"content": '{"skills": "python"}'}}),
                          LLMInvalidOutput, job),
    ]

    # repair path: first answer is not JSON, the second is valid -> the system must recover
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        content = "not json" if calls["n"] == 1 else ok_json
        return httpx.Response(200, json={"message": {"content": content}})

    try:
        with _patched(extractor, chat_json=_fake_llm(flaky)):
            res = await single_cv.analyze_single_cv(good, "s01.pdf", job, mode="ollama")
        rows.append(_row("Non-JSON first, valid JSON after the repair request", "LLM failures (simulated server)",
                         "recovers and returns a decision", res.decision.label in ("suitable", "not_suitable", "needs_review")
                         and calls["n"] >= 2, f"decision={res.decision.label} after {calls['n']} model calls"))
    except Exception as exc:
        rows.append(_row("Non-JSON first, valid JSON after the repair request", "LLM failures (simulated server)",
                         "recovers and returns a decision", False, f"{type(exc).__name__}: {exc}"))

    async def never(*a, **k):
        await asyncio.sleep(10)

    try:
        with _patched(single_cv, extract_profile=never):
            await single_cv.analyze_single_cv(good, "s01.pdf", job, mode="mock", timeout=0.1)
        rows.append(_row("Whole analysis exceeds its time limit", "LLM failures (simulated server)", "LLMTimeout", False,
                         "no error was raised"))
    except LLMTimeout as exc:
        rows.append(_row("Whole analysis exceeds its time limit", "LLM failures (simulated server)", "LLMTimeout (code 'llm_timeout')",
                         True, f"{exc.code}: {exc}"))

    # ---- batch: one bad item must not stop the others
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        out = tmp / "out"
        out.mkdir()
        with _patched(store, runs_dir=lambda: out), _patched(report_mod, reports_dir=lambda: out):
            # (a) a corrupt PDF and an empty file sit next to the 8 good CVs
            cvdir = tmp / "cvs"
            shutil.copytree(settings.cv_dir, cvdir)
            (cvdir / "cv_98_broken.pdf").write_bytes(b"%PDF-1.4 garbage")
            (cvdir / "cv_99_empty.pdf").write_bytes(b"")
            try:
                with _patched(pipeline, settings=dataclasses.replace(settings, cv_dir=cvdir)):
                    res = await run_recruitment_workflow("J1", mode="mock", save=False)
                ranked = sum(1 for r in res.results if r.status == "ranked")
                named = sum(1 for e in res.errors if "cv_98_broken" in e or "cv_99_empty" in e)
                rows.append(_row("Batch: corrupt and empty PDFs among the CVs", "Batch isolation",
                                 "8 good CVs still ranked; both bad files reported by name",
                                 ranked >= 5 and named == 2 and len(res.results) == 8,
                                 f"{len(res.results)} candidates processed, {ranked} ranked, {named}/2 bad files named in errors"))
            except Exception as exc:
                rows.append(_row("Batch: corrupt and empty PDFs among the CVs", "Batch isolation", "run completes", False,
                                 f"crashed: {type(exc).__name__}: {exc}"))

            # (b) the model fails for exactly one candidate
            real = extractor.extract_profile
            for label, exc_obj, code in [("times out", LLMTimeout("simulated timeout"), "llm_timeout"),
                                         ("returns invalid JSON", LLMInvalidOutput("simulated bad JSON"), "llm_invalid_output")]:
                async def flaky_extract(cv_text, *, mode, feedback=None, _e=exc_obj):
                    if cv_text.splitlines()[0].strip() == "Sara Ahmed":
                        raise _e
                    return await real(cv_text, mode=mode, feedback=feedback)

                with _patched(workflow_mod, extract_profile=flaky_extract):
                    res = await run_recruitment_workflow("J1", mode="mock", save=False)
                failed = [r for r in res.results if r.status == "failed"]
                ranked = [r for r in res.results if r.status == "ranked"]
                rows.append(_row(f"Batch: the model {label} for one candidate", "Batch isolation",
                                 f"that candidate 'failed' with code '{code}'; the other 7 are processed; the report is written",
                                 len(failed) == 1 and failed[0].error_code == code and len(ranked) >= 5
                                 and res.stage_status.get("report") == "done",
                                 f"failed={[f.candidate_id for f in failed]} code={failed[0].error_code if failed else None}, "
                                 f"ranked={len(ranked)}, report={res.stage_status.get('report')}"))
    return rows
