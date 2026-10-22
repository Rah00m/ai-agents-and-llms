"""Runs the whole evaluation and returns one plain dict (saved as JSON, rendered by evaluation/report.py)."""
import asyncio
import contextlib
import csv
import json
import platform
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from app import single_cv
from app.actions import report as report_mod
from app.config import BACKEND_DIR, settings
from app.llm import check_ollama, reset_stats, stats as llm_stats
from app.models import SingleCvResult, WorkflowResult
from app.orchestrator import pipeline, store
from app.orchestrator.workflow import run_recruitment_workflow
from evaluation import ground_truth as gt
from evaluation import metrics
from evaluation.scenarios import _patched, run_scenarios

TRUTH = BACKEND_DIR / "data" / "ground_truth.json"
REFERENCE = BACKEND_DIR / "data" / "eval" / "reference_single_cv.json"
EVAL_CVS = BACKEND_DIR / "data" / "eval" / "single_cv"
KS = (1, 2, 3)
NDCG_K = 3
DECISIONS = ["suitable", "needs_review", "not_suitable"]


def _valid_workflow(res: WorkflowResult) -> list[str]:
    """Reasons why a workflow output is NOT valid (empty list = valid)."""
    problems = []
    try:
        WorkflowResult.model_validate(json.loads(res.model_dump_json()))
    except Exception as exc:
        return [f"schema: {exc}"]
    ids = [r.candidate_id for r in res.results]
    if len(ids) != len(set(ids)):
        problems.append("duplicate candidate ids")
    ranks = sorted(r.rank for r in res.results if r.rank is not None)
    if ranks != list(range(1, len(ranks) + 1)):
        problems.append("ranks are not 1..n")
    for r in res.results:
        if r.status == "ranked" and not (r.match and r.qa and r.profile and 0 <= r.match.score <= 100):
            problems.append(f"{r.candidate_id}: ranked without a valid match")
    return problems


def _valid_single(res: SingleCvResult) -> list[str]:
    try:
        SingleCvResult.model_validate(json.loads(res.model_dump_json()))
    except Exception as exc:
        return [f"schema: {exc}"]
    problems = []
    if res.decision.label not in DECISIONS:
        problems.append("unknown decision label")
    if not 0 <= res.match.score <= 100:
        problems.append("score out of range")
    if not res.decision.summary or not res.decision.reasons and res.decision.label != "needs_review":
        problems.append("decision has no explanation")
    return problems


def _csv_matches_results(res: WorkflowResult, path: Path) -> list[str]:
    """The CSV must show exactly what the dashboard shows (rank, score, status per candidate)."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    problems = []
    if len(rows) != len(res.results):
        problems.append(f"{len(rows)} CSV rows for {len(res.results)} candidates")
    for row, r in zip(rows, res.results):
        if row["Candidate ID"] != r.candidate_id:
            problems.append(f"order differs at {r.candidate_id}")
        elif r.status == "ranked" and (row["Rank"] != str(r.rank) or float(row["Match Score"]) != r.match.score):
            problems.append(f"{r.candidate_id}: rank/score differ")
        elif r.status != "ranked" and row["Match Score"] != "":
            problems.append(f"{r.candidate_id}: unranked candidate has a score in the CSV")
    return problems


async def evaluate_mode(mode: str, repeats: int) -> dict:
    """Batch ranking metrics + single-CV decisions for one mode ("mock" = rule-based parser, "ollama" = local LLM)."""
    retrieval = await pipeline.run_retrieval()
    jobs = {j.job_id: j for j in retrieval.jobs}
    truth = gt.load(TRUTH)
    reset_stats()
    out: dict = {"mode": mode, "model": settings.ollama_model if mode == "ollama" else None, "repeats": repeats}

    # ------------------------------------------------------------ batch workflow, per job
    batch, runs_total, runs_ok, validity, csv_checks = {}, 0, 0, [], []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with _patched(store, runs_dir=lambda: tmp), _patched(report_mod, reports_dir=lambda: tmp):
            for job_id, job in jobs.items():
                seconds, last, failures = [], None, 0
                for i in range(repeats):
                    runs_total += 1
                    try:
                        res = await run_recruitment_workflow(job_id, mode=mode, save=False, run_id=f"eval-{job_id}-{i}")
                    except Exception as exc:
                        failures += 1
                        batch.setdefault(job_id, {}).setdefault("run_errors", []).append(f"{type(exc).__name__}: {exc}")
                        continue
                    ok = all(s == "done" for s in res.stage_status.values())
                    runs_ok += ok
                    seconds.append(res.total_seconds)
                    validity.append(_valid_workflow(res))
                    if res.report_file:
                        csv_checks.append(_csv_matches_results(res, tmp / res.report_file))
                    last = res
                entry = batch.setdefault(job_id, {})
                entry["latency"] = metrics.summarize(seconds)
                if last is None:
                    continue
                system = [r.candidate_id for r in last.results if r.status == "ranked"]
                ref = truth[job_id]["ranking"]
                accepted = truth[job_id]["accepted"]
                entry.update(
                    title=job.title, system_ranking=system, reference_ranking=ref, accepted=accepted,
                    scores={r.candidate_id: r.match.score for r in last.results if r.match},
                    unranked={r.candidate_id: (r.error or r.status) for r in last.results if r.status != "ranked"},
                    ndcg={f"@{NDCG_K}": metrics.ndcg_at_k(system, ref, NDCG_K)},
                    precision={f"@{k}": metrics.precision_at_k(system, accepted, k) for k in KS},
                    recall={f"@{k}": metrics.recall_at_k(system, accepted, k) for k in KS},
                    candidates_failed=sum(1 for r in last.results if r.status == "failed"),
                    candidates_needs_review=sum(1 for r in last.results if r.status == "needs_review"),
                )
    out["batch"] = batch
    scored = [b for b in batch.values() if "ndcg" in b]
    out["batch_summary"] = {
        "ndcg_mean": sum(b["ndcg"][f"@{NDCG_K}"] for b in scored) / len(scored) if scored else None,
        "precision_mean": {f"@{k}": sum(b["precision"][f"@{k}"] for b in scored) / len(scored) for k in KS} if scored else {},
    }
    out["workflow"] = {"runs": runs_total, "succeeded": runs_ok,
                       "success_rate": runs_ok / runs_total if runs_total else None}
    out["validity"] = {"outputs": len(validity), "valid": sum(1 for p in validity if not p),
                       "problems": [p for p in validity if p]}
    out["csv_consistency"] = {"reports": len(csv_checks), "consistent": sum(1 for p in csv_checks if not p),
                              "problems": [p for p in csv_checks if p]}

    # ------------------------------------------------------------ single CV vs reference decisions
    ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
    cases, seconds, single_valid = [], [], []
    for c in ref["cases"]:
        data = (EVAL_CVS / c["file"]).read_bytes()
        row = {"id": c["id"], "file": c["file"], "job_id": c["job_id"], "reference": c["reference_decision"],
               "layout": c["layout"], "rationale": c["rationale"]}
        try:
            r = await single_cv.analyze_single_cv(data, c["file"], jobs[c["job_id"]], mode=mode)
            problems = _valid_single(r)
            single_valid.append(problems)
            seconds.append(r.seconds)
            row.update(system=r.decision.label, score=r.match.score, seconds=r.seconds, years=r.decision.years_found,
                       summary=r.decision.summary, missing=r.decision.missing_required,
                       missing_information=r.decision.missing_information, qa=r.qa.status)
        except Exception as exc:
            single_valid.append([f"no result: {type(exc).__name__}"])
            row.update(system="error", error=f"{type(exc).__name__}: {exc}")
        row["agree"] = row["system"] == row["reference"]
        cases.append(row)
    out["single"] = {
        "cases": cases,
        "classification": metrics.classification_report([c["reference"] for c in cases], [c["system"] for c in cases]),
        "latency": metrics.summarize(seconds),
        "validity": {"outputs": len(single_valid), "valid": sum(1 for p in single_valid if not p),
                     "problems": [p for p in single_valid if p]},
        "by_layout": {lay: {"total": sum(1 for c in cases if c["layout"] == lay),
                            "agree": sum(1 for c in cases if c["layout"] == lay and c["agree"])}
                      for lay in sorted({c["layout"] for c in cases})},
    }
    if mode == "ollama":
        out["llm_calls"] = dict(llm_stats)       # how many model answers were valid first time / repaired / failed
    return out


async def evaluate(mode: str = "mock", repeats: int = 3) -> dict:
    """mode: "mock", "ollama" or "both" (both = rule-based AND local LLM, LLM skipped if Ollama is not ready)."""
    truth = gt.load(TRUTH)
    retrieval = await pipeline.run_retrieval()
    result: dict = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "environment": {"python": sys.version.split()[0], "platform": platform.platform(),
                        "ollama_model_configured": settings.ollama_model, "github_mode": settings.github_mode},
        "data": {"candidates": len(retrieval.candidates), "jobs": len(retrieval.jobs),
                 "single_cv_cases": len(json.loads(REFERENCE.read_text(encoding="utf-8"))["cases"])},
        "ground_truth": gt.validate(truth, retrieval.jobs, retrieval.candidates),
        "modes": {}, "skipped": {},
    }
    bad = [j for j, v in result["ground_truth"].items() if not v["ok"]]
    if bad:
        result["aborted"] = f"ground_truth.json is invalid for {', '.join(bad)}; ranking metrics were not computed."
        return result

    wanted = ["mock", "ollama"] if mode == "both" else [mode]
    for m in wanted:
        if m == "ollama":
            status = await check_ollama()
            if not (status["reachable"] and status["model_installed"]):
                reason = ("Ollama is not reachable at " + settings.ollama_host if not status["reachable"]
                          else f"model '{settings.ollama_model}' is not installed")
                result["skipped"]["ollama"] = f"Not run: {reason}."
                continue
        result["modes"][m] = await evaluate_mode(m, repeats if m == "mock" else max(1, min(repeats, 1)))
    result["error_handling"] = await run_scenarios()
    rows = result["error_handling"]
    result["error_handling_summary"] = {"total": len(rows), "handled": sum(1 for r in rows if r["handled"]),
                                        "rate": sum(1 for r in rows if r["handled"]) / len(rows)}
    return result


def save(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
