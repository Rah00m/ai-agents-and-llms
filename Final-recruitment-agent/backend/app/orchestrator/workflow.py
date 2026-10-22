"""The orchestrator: run_recruitment_workflow(job_id)

    Retrieval (parallel: CVs || jobs, then GitHub per candidate)
        -> Skill Extraction   (all candidates in parallel, limited by LLM_CONCURRENCY)
        -> Matching           (rules, per candidate)
        -> QA review          (per candidate; rejected -> re-extract with feedback, up to max_attempts)
        -> Ranking + save

One candidate failing never stops the others: it is marked "failed" (exception) or
"needs_review" (QA still rejects it after the retries) and left out of the ranking.
"""
import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.actions.report import write_report
from app.agents.extractor import extract_profile
from app.agents.matcher import DEFAULT_WEIGHTS, Weights, match_candidate
from app.agents.qa import review
from app.config import settings
from app.llm import LLMError, check_ollama
from app.models import (Candidate, CandidateResult, JobRequirement, QAReport, RetrievalResult,
                        WorkflowResult)
from app.orchestrator.pipeline import run_retrieval
from app.orchestrator.store import save_run

Emit = Callable[[dict], Awaitable[None]]


async def _noop(_: dict) -> None:
    return None


class _Stages:
    """Records the time and status of every stage and tells the UI about it."""

    def __init__(self, emit: Emit):
        self.emit = emit
        self.timings: dict[str, float] = {}
        self.status: dict[str, str] = {}

    async def run(self, name: str, detail: str, coro):
        await self.emit({"stage": name, "status": "started", "detail": detail})
        t0 = time.perf_counter()
        try:
            out = await coro
        except Exception:
            self.status[name] = "failed"
            self.timings[name] = round(time.perf_counter() - t0, 3)
            await self.emit({"stage": name, "status": "failed", "detail": f"{name} failed"})
            raise
        self.status[name] = "done"
        self.timings[name] = round(time.perf_counter() - t0, 3)
        await self.emit({"stage": name, "status": "done", "detail": f"{name} finished in {self.timings[name]}s"})
        return out


def new_run_id(job_id: str) -> str:
    """Unique and sortable: J1-20261020-194100-a3f9 (the suffix avoids clashes within one second)."""
    return f"{job_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def _find_job(retrieval: RetrievalResult, job_id: str) -> JobRequirement:
    for job in retrieval.jobs:
        if job.job_id == job_id:
            return job
    available = ", ".join(j.job_id for j in retrieval.jobs) or "none"
    raise ValueError(f"Unknown job_id '{job_id}'. Available jobs: {available}")


async def run_recruitment_workflow(
    job_id: str,
    *,
    mode: str | None = None,
    emit: Emit = _noop,
    weights: Weights = DEFAULT_WEIGHTS,
    max_attempts: int = 2,
    save: bool = True,
    retrieval: RetrievalResult | None = None,
    run_id: str | None = None,
    report: bool = True,
) -> WorkflowResult:
    mode = mode or settings.llm_mode
    if mode not in ("ollama", "mock"):
        raise ValueError(f"Unknown LLM mode '{mode}' (use 'ollama' or 'mock')")
    t_start = time.perf_counter()
    stages = _Stages(emit)

    # Fail fast with a clear message instead of failing 8 times.
    if mode == "ollama":
        status = await check_ollama()
        if not status["reachable"]:
            raise LLMError(f"Cannot reach Ollama at {settings.ollama_host}. Start it with `ollama serve`, "
                           "or run with LLM_MODE=mock.")
        if not status["model_installed"]:
            raise LLMError(f"Model '{settings.ollama_model}' is not installed. "
                           f"Run: ollama pull {settings.ollama_model}")

    # ---------------------------------------------------------------- 1. retrieval
    if retrieval is None:
        retrieval = await stages.run("retrieval", "Reading CVs, jobs and GitHub profiles", run_retrieval(emit=_noop))
    else:
        stages.status["retrieval"], stages.timings["retrieval"] = "done", 0.0
    job = _find_job(retrieval, job_id)
    errors = list(retrieval.errors)
    warnings = list(retrieval.warnings)

    results: dict[str, CandidateResult] = {
        c.candidate_id: CandidateResult(
            candidate_id=c.candidate_id, name=c.name, status="ranked",
            github_source=c.github_profile.source if c.github_profile else None,
            github_languages=c.github_profile.top_languages if c.github_profile else [])
        for c in retrieval.candidates
    }
    by_id: dict[str, Candidate] = {c.candidate_id: c for c in retrieval.candidates}

    def fail(cid: str, exc: Exception, where: str) -> None:
        results[cid].status = "failed"
        results[cid].error = f"{where}: {exc}"
        errors.append(f"{cid} ({results[cid].name}) failed at {where}: {exc}")

    async def extract(cid: str, feedback: str | None = None) -> None:
        results[cid].attempts += 1
        try:
            results[cid].profile = await extract_profile(by_id[cid].cv_text, mode=mode, feedback=feedback)
        except Exception as exc:  # LLMError, timeouts, anything unexpected
            fail(cid, exc, "extraction")

    def languages(cid: str) -> list[str]:
        gh = by_id[cid].github_profile
        return gh.top_languages if gh else []

    def match(cid: str) -> None:
        r = results[cid]
        r.match = match_candidate(cid, r.profile, job, languages(cid), weights)

    # ---------------------------------------------------------------- 2. extraction (parallel)
    done_count = 0

    async def extract_first(cid: str) -> None:
        nonlocal done_count
        await extract(cid)
        done_count += 1
        await emit({"stage": "extraction", "status": "progress",
                    "detail": f"{results[cid].name} processed ({done_count}/{len(results)})"})

    await stages.run("extraction", f"Extracting skills from {len(results)} CVs ({mode})",
                     asyncio.gather(*(extract_first(cid) for cid in results)))

    # ---------------------------------------------------------------- 3. matching
    async def matching() -> None:
        for cid, r in results.items():
            if r.status != "failed":
                match(cid)

    await stages.run("matching", f"Scoring candidates against {job.job_id} ({job.title})", matching())

    # ---------------------------------------------------------------- 4. QA (+ retry)
    async def qa_one(cid: str) -> None:
        r = results[cid]
        while r.status != "failed":
            report, cleaned = review(by_id[cid].cv_text, r.profile, r.match)
            r.qa = report
            if report.status != "rejected":
                if report.removed_skills:
                    # The score must not rely on skills QA removed: recompute it from the cleaned profile.
                    r.profile = cleaned
                    match(cid)
                    r.qa = QAReport(
                        status="approved_with_warnings",
                        issues=[i for i in report.issues if i.code != "match_uses_unsupported_skill"],
                        removed_skills=report.removed_skills,
                    )
                return
            if r.attempts >= max_attempts:
                r.status = "needs_review"
                return
            feedback = "\n".join(f"- {i.message}" for i in report.issues if i.severity == "error")
            await extract(cid, feedback)
            if r.status == "failed":
                return
            match(cid)

    await stages.run("qa", "Reviewing results (retry on rejection)", asyncio.gather(*(qa_one(c) for c in results)))

    # ---------------------------------------------------------------- 5. ranking
    async def ranking() -> None:
        ranked = [r for r in results.values() if r.status == "ranked"]
        ranked.sort(key=lambda r: (-r.match.score, -(r.profile.experience_years or 0), r.candidate_id))
        for i, r in enumerate(ranked, start=1):
            r.rank = i

    await stages.run("ranking", "Ranking approved candidates", ranking())

    for r in results.values():
        if r.status == "needs_review":
            warnings.append(f"{r.candidate_id} ({r.name}) needs manual review: QA rejected the extraction")
    ordered = sorted(results.values(), key=lambda r: (r.rank is None, r.rank or 0, r.candidate_id))
    run_id = run_id or new_run_id(job.job_id)

    # ---------------------------------------------------------------- 6. report (automated action)
    report_file = None
    if report:
        try:
            report_file = write_report(run_id, job, ordered).name
        except Exception as exc:
            errors.append(f"report: could not write the CSV report: {exc}")
    result = WorkflowResult(
        run_id=run_id,
        report_file=report_file,
        weights={"required": weights.required, "experience": weights.experience, "preferred": weights.preferred},
        job=job,
        mode=mode,
        model=settings.ollama_model if mode == "ollama" else None,
        results=ordered,
        stage_timings=stages.timings,
        stage_status=stages.status,
        warnings=warnings,
        errors=errors,
        total_seconds=round(time.perf_counter() - t_start, 3),
    )
    if save:
        save_run(result)
    await emit({"stage": "workflow", "status": "done",
                "detail": f"Run {result.run_id} finished in {result.total_seconds}s"})
    return result
