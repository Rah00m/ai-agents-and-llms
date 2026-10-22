"""Day-1 orchestration: the retrieval stage.

Stage 1 (parallel):  CV retriever  ||  Jobs retriever
Stage 2 (parallel):  one GitHub lookup per candidate (needs usernames from stage 1)

`emit` is an optional async callback so the API can stream live progress to the UI (Day 3).
"""
import time
from collections.abc import Awaitable, Callable

import asyncio

from app.config import settings
from app.models import RetrievalResult
from app.orchestrator.candidates import build_candidates
from app.retrievers.cv_retriever import retrieve_cvs
from app.retrievers.github_retriever import retrieve_github
from app.retrievers.jobs_retriever import retrieve_jobs

Emit = Callable[[dict], Awaitable[None]]


async def _noop(_: dict) -> None:
    return None


async def run_retrieval(emit: Emit = _noop) -> RetrievalResult:
    timings: dict[str, float] = {}
    errors: list[str] = []
    t_total = time.perf_counter()

    # ---- Stage 1: CVs and Jobs in parallel ----
    await emit({"stage": "retrieval", "status": "started", "detail": "Reading CVs and job requirements"})

    async def timed(name: str, coro):
        t0 = time.perf_counter()
        out = await coro
        timings[name] = round(time.perf_counter() - t0, 3)
        return out

    (cvs, cv_err), (jobs, job_err) = await asyncio.gather(
        timed("cv_retriever", retrieve_cvs(settings.cv_dir)),
        timed("jobs_retriever", retrieve_jobs(settings.jobs_source)),
    )
    errors += cv_err + job_err
    await emit({"stage": "retrieval", "status": "progress",
                "detail": f"Loaded {len(cvs)} CVs and {len(jobs)} jobs"})

    # ---- Stage 2: GitHub lookups in parallel (depends on CV parsing) ----
    usernames = sorted({c.github_username for c in cvs if c.github_username})
    github, gh_err = await timed("github_retriever", retrieve_github(usernames))
    errors += gh_err
    await emit({"stage": "retrieval", "status": "progress",
                "detail": f"Fetched {len(github)} GitHub profiles"})

    # ---- Merge into unified Candidate records + consistency checks ----
    candidates, merge_err, warnings = build_candidates(cvs, github)
    errors += merge_err

    timings["retrieval_total"] = round(time.perf_counter() - t_total, 3)
    counts = {
        "candidates": len(candidates),
        "jobs": len(jobs),
        "github_profiles": sum(1 for c in candidates if c.github_profile),
        "errors": len(errors),
        "warnings": len(warnings),
    }
    await emit({"stage": "retrieval", "status": "done",
                "detail": f"{counts['candidates']} candidates, {counts['jobs']} jobs, "
                          f"{counts['errors']} errors, {counts['warnings']} warnings "
                          f"in {timings['retrieval_total']}s"})
    return RetrievalResult(candidates=candidates, jobs=jobs, timings=timings,
                           counts=counts, errors=errors, warnings=warnings)
