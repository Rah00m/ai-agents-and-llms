"""FastAPI application.   Run (from backend/):  uvicorn app.main:app --reload --port 8000

Interactive docs (Swagger UI): http://localhost:8000/docs

GET  /health              is the server up
GET  /llm/status          is Ollama running and the model installed
GET  /overview            counts + last run, for the dashboard home
GET  /jobs                job requirements from jobs.csv
POST /analyze-cv          check ONE uploaded PDF against ONE job (multipart form), answers at once
POST /analyze             start a run (returns at once; the work happens in the background)
GET  /results/{run_id}    live stage status while running, the full result when done
GET  /runs                recent runs
GET  /reports/{run_id}    the CSV report of a finished run
"""
import re
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.actions import report as report_mod
from app.config import settings
from app.llm import LLMError, LLMInvalidOutput, LLMTimeout, check_ollama
from app.orchestrator.pipeline import run_retrieval
from app.retrievers.cv_retriever import CvError
from app.runs import RunManager
from app.single_cv import analyze_single_cv

app = FastAPI(title="Recruitment Agent API", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

manager = RunManager()
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def error(status: int, code: str, message: str, **extra) -> HTTPException:
    """Every error has the same shape: {"detail": {"code": ..., "message": ...}}."""
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


class AnalyzeRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$", examples=["J1"])
    mode: Literal["mock", "ollama"] | None = Field(
        default=None,
        description="'ollama' uses the local LLM. 'mock' is a rule-based parser with no model. "
                    "Defaults to LLM_MODE from .env.")


def llm_info(status: dict | None = None) -> dict:
    return {"configured_mode": settings.llm_mode, "model": settings.ollama_model,
            "host": settings.ollama_host, "github_mode": settings.github_mode, **(status or {})}


def checked_run_id(run_id: str) -> str:
    if not RUN_ID.match(run_id):
        raise error(400, "invalid_run_id", "Run ids contain only letters, digits, '-' and '_'.")
    return run_id


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/llm/status")
async def llm_status():
    return llm_info(await check_ollama())


@app.get("/jobs")
async def list_jobs():
    retrieval = await run_retrieval()
    if not retrieval.jobs:
        raise error(500, "no_jobs", "No jobs could be loaded.", problems=retrieval.errors)
    return [j.model_dump() for j in retrieval.jobs]


@app.get("/overview")
async def overview():
    retrieval = await run_retrieval()
    runs = manager.summaries()
    last = next((r for r in runs if r["status"] == "done"), None)
    return {
        "candidates": len(retrieval.candidates),
        "jobs": len(retrieval.jobs),
        "github_profiles": retrieval.counts.get("github_profiles", 0),
        "runs": len(runs),
        "last_run": last,
        "active_run": (manager.active().run_id if manager.active() else None),
        "llm": llm_info(),
        "data_errors": retrieval.errors,
        "data_warnings": retrieval.warnings,
    }


@app.post("/analyze", status_code=202)
async def analyze(req: AnalyzeRequest):
    mode = req.mode or settings.llm_mode

    active = manager.active()
    if active:
        raise error(409, "run_in_progress",
                    f"Run {active.run_id} is still in progress. Wait for it to finish.",
                    run_id=active.run_id)

    retrieval = await run_retrieval()
    known = [j.job_id for j in retrieval.jobs]
    if req.job_id not in known:
        raise error(404, "job_not_found", f"Unknown job '{req.job_id}'. Available jobs: {', '.join(known) or 'none'}.",
                    available=known)
    if not retrieval.candidates:
        raise error(422, "no_candidates", "No CVs could be read, so there is nothing to analyze.",
                    problems=retrieval.errors)

    if mode == "ollama":
        status = await check_ollama()
        if not status["reachable"]:
            raise error(503, "ollama_unavailable",
                        f"Cannot reach Ollama at {settings.ollama_host}. Start it with `ollama serve`, "
                        "or choose the rule-based mode.")
        if not status["model_installed"]:
            raise error(503, "model_missing",
                        f"Model '{settings.ollama_model}' is not installed. Run: ollama pull {settings.ollama_model}")

    state = manager.start(req.job_id, mode)
    return {"run_id": state.run_id, "status": state.status, "job_id": state.job_id, "mode": state.mode}


CV_ERROR_STATUS = {"unsupported_type": 415, "too_large": 413}


@app.post("/analyze-cv")
async def analyze_cv(
    file: UploadFile = File(..., description="One CV as a PDF"),
    job_id: str = Form(..., min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$"),
    mode: Literal["mock", "ollama"] | None = Form(default=None),
):
    """Check one uploaded CV against the chosen job. The answer is not stored and does not touch batch runs."""
    mode = mode or settings.llm_mode
    retrieval = await run_retrieval()
    job = next((j for j in retrieval.jobs if j.job_id == job_id), None)
    if job is None:
        known = [j.job_id for j in retrieval.jobs]
        raise error(404, "job_not_found", f"Unknown job '{job_id}'. Available jobs: {', '.join(known) or 'none'}.",
                    available=known)

    limit = int(settings.max_upload_mb * 1024 * 1024)
    data = await file.read(limit + 1)             # never read more than the limit plus one byte
    filename = file.filename or "upload.pdf"

    if mode == "ollama" and data and len(data) <= limit and filename.lower().endswith(".pdf"):
        status = await check_ollama()             # say so first, instead of after a long wait
        if not status["reachable"]:
            raise error(503, "ollama_unavailable",
                        f"Cannot reach Ollama at {settings.ollama_host}. Start it with `ollama serve`, "
                        "or choose the rule-based mode.")
        if not status["model_installed"]:
            raise error(503, "model_missing",
                        f"Model '{settings.ollama_model}' is not installed. Run: ollama pull {settings.ollama_model}")

    try:
        result = await analyze_single_cv(data, filename, job, mode=mode)
    except CvError as exc:
        raise error(CV_ERROR_STATUS.get(exc.code, 422), exc.code, str(exc)) from exc
    except LLMTimeout as exc:
        raise error(504, exc.code, str(exc)) from exc
    except LLMInvalidOutput as exc:
        raise error(502, exc.code, f"The model did not return usable output. {exc}") from exc
    except LLMError as exc:
        raise error(503, exc.code, str(exc)) from exc
    return result.model_dump()


@app.get("/results/{run_id}")
async def results(run_id: str):
    state = manager.get(checked_run_id(run_id))
    if state is None:
        raise error(404, "run_not_found", f"No run with id '{run_id}'.")
    return state.model_dump()


@app.get("/runs")
async def runs():
    return manager.summaries()


@app.get("/reports/{run_id}")
async def report(run_id: str):
    state = manager.get(checked_run_id(run_id))
    if state is None:
        raise error(404, "run_not_found", f"No run with id '{run_id}'.")
    if state.status == "running":
        raise error(409, "run_in_progress", "The run is still in progress; the report is written at the end.")
    if state.status == "failed":
        raise error(409, "run_failed", "This run failed, so there is no report.")
    path = report_mod.report_path(run_id)
    if not path.exists():
        raise error(404, "report_missing", "The report file for this run does not exist.")
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename=f"recruitment-report-{run_id}.csv")
