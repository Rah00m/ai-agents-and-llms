"""Check ONE uploaded CV against ONE chosen job.

It reuses the same agents and the same score formula as the batch workflow (extractor -> matcher ->
QA with one retry), then adds a verdict (app/decision.py). It does not touch the run manager, the saved
runs or the CSV reports, so it cannot change anything the batch workflow shows.

GitHub is not consulted here: a single upload has no GitHub lookup. The result says so.
"""
import asyncio
import time

from app.agents.extractor import extract_profile
from app.agents.matcher import DEFAULT_WEIGHTS, Weights, match_candidate
from app.agents.qa import review
from app.config import settings
from app.decision import SCORE_NOTE, decide
from app.llm import LLMError, LLMTimeout
from app.logs import get_logger
from app.models import JobRequirement, QAReport, SingleCvResult
from app.retrievers.cv_retriever import parse_cv_bytes

log = get_logger("single_cv")


async def analyze_single_cv(
    data: bytes,
    filename: str,
    job: JobRequirement,
    *,
    mode: str | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
    max_attempts: int = 2,
    timeout: float | None = None,
) -> SingleCvResult:
    """Raises CvError (unusable file), LLMError (model problem) or LLMTimeout (took too long)."""
    mode = mode or settings.llm_mode
    if mode not in ("ollama", "mock"):
        raise ValueError(f"Unknown LLM mode '{mode}' (use 'ollama' or 'mock')")
    limit = settings.single_cv_timeout if timeout is None else timeout
    t0 = time.perf_counter()

    t_parse = time.perf_counter()
    cv = parse_cv_bytes(data, filename)          # raises CvError before any model is used
    log.info("parsed PDF in %.2fs: %d characters, mode=%s, job=%s", time.perf_counter() - t_parse,
             len(cv.raw_text), mode, job.job_id)
    stage = {"now": "reading the CV"}            # where the analysis is, for the timeout message
    notes: list[str] = []

    async def work() -> SingleCvResult:
        feedback: str | None = None
        attempts = 0
        kept = None                              # the first complete answer, kept in case a retry cannot finish
        first_seconds = 0.0
        while True:
            attempts += 1
            stage["now"] = f"waiting for the extraction (attempt {attempts})"
            t_try = time.perf_counter()
            if attempts == 1:
                profile = await extract_profile(cv.raw_text, mode=mode, feedback=feedback)
                first_seconds = time.perf_counter() - t_try
            else:
                # A retry is a second chance, not a requirement: it must never turn the answer we already
                # have into an error. Give it only the time that is left, and keep attempt 1 if it cannot finish.
                left = limit - (time.perf_counter() - t0)
                if left < 1.5 * first_seconds:
                    notes.append(f"The quality check asked for a second extraction, but there was not enough time left "
                                 f"({left:.0f}s). The first answer is shown and needs a person to check it.")
                    log.warning("skipping the retry: %.1fs left, first attempt took %.1fs", left, first_seconds)
                    attempts -= 1
                    profile, match, report, cleaned = kept
                    break
                try:
                    profile = await asyncio.wait_for(
                        extract_profile(cv.raw_text, mode=mode, feedback=feedback), timeout=left)
                except (asyncio.TimeoutError, LLMError) as exc:
                    notes.append("The quality check asked for a second extraction, but it failed "
                                 f"({type(exc).__name__}). The first answer is shown and needs a person to check it.")
                    log.warning("retry failed (%s) after %.1fs; keeping the first answer", type(exc).__name__,
                                time.perf_counter() - t_try)
                    attempts -= 1
                    profile, match, report, cleaned = kept
                    break
            stage["now"] = "checking the result"
            match = match_candidate("UPLOAD", profile, job, [], weights)
            report, cleaned = review(cv.raw_text, profile, match)
            log.info("attempt %d: extraction %.1fs, QA status=%s", attempts, time.perf_counter() - t_try, report.status)
            kept = (profile, match, report, cleaned)
            if report.status != "rejected" or attempts >= max_attempts:
                break
            feedback = "\n".join(f"- {i.message}" for i in report.issues if i.severity == "error")

        if report.status != "rejected" and report.removed_skills:
            # the score must not rely on skills QA removed (same rule as the batch workflow)
            profile = cleaned
            match = match_candidate("UPLOAD", profile, job, [], weights)
            report = QAReport(
                status="approved_with_warnings",
                issues=[i for i in report.issues if i.code != "match_uses_unsupported_skill"],
                removed_skills=report.removed_skills)

        decision = decide(job, profile, match, report, cv.raw_text)
        return SingleCvResult(
            job=job, mode=mode, model=settings.ollama_model if mode == "ollama" else None,
            filename=cv.source_file, candidate_name=cv.name, profile=profile, match=match, qa=report,
            decision=decision, attempts=attempts, score_note=SCORE_NOTE,
            weights={"required": weights.required, "experience": weights.experience,
                     "preferred": weights.preferred},
            warnings=["GitHub was not checked for single-CV uploads.", *notes])

    try:
        result = await asyncio.wait_for(work(), timeout=limit)
    except asyncio.TimeoutError as exc:
        log.warning("whole analysis stopped after %.1fs (limit %gs) while %s", time.perf_counter() - t0, limit, stage["now"])
        raise LLMTimeout(f"The analysis took longer than {limit:g}s and was stopped while {stage['now']}. "
                         "Try a smaller model or raise SINGLE_CV_TIMEOUT.") from exc
    result.seconds = round(time.perf_counter() - t0, 3)
    log.info("finished in %.1fs: decision=%s attempts=%d", result.seconds, result.decision.label, result.attempts)
    return result
