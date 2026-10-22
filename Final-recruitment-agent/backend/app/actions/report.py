"""Automated action: write the ranking of a finished run as a CSV report.

The report is built from the same `CandidateResult` objects the dashboard shows, so the two
cannot disagree. Every candidate appears: ranked ones first, then the ones that need manual
review or failed (with no score, and the reason in the Explanation column).
"""
import csv
import io
from pathlib import Path

from app.config import settings
from app.models import CandidateResult, JobRequirement

COLUMNS = [
    "Rank", "Candidate ID", "Name", "Job ID", "Match Score",
    "Matching Skills", "Partial Skills", "Missing Skills", "QA Status", "Explanation",
]


def reports_dir() -> Path:
    d = settings.outputs_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def report_path(run_id: str) -> Path:
    return reports_dir() / f"{run_id}.csv"


def _safe(text: str) -> str:
    """Stop CSV/formula injection: Excel runs cells that start with = + - @ as formulas.

    Candidate names and explanations come from CVs (untrusted text), so they are neutralised.
    """
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _join(items: list[str]) -> str:
    return _safe("; ".join(items))


def build_rows(job: JobRequirement, results: list[CandidateResult]) -> list[dict[str, str]]:
    rows = []
    for r in results:
        row = {"Rank": "", "Candidate ID": r.candidate_id, "Name": _safe(r.name), "Job ID": job.job_id,
               "Match Score": "", "Matching Skills": "", "Partial Skills": "", "Missing Skills": "",
               "QA Status": "", "Explanation": ""}
        if r.status == "ranked" and r.match and r.qa:
            m = r.match
            row.update({
                "Rank": str(r.rank),
                "Match Score": f"{m.score:.1f}",
                "Matching Skills": _join(m.matched_required + m.matched_preferred),
                "Partial Skills": _join(m.partial_required),
                "Missing Skills": _join(m.missing_required),
                "QA Status": r.qa.status,
                "Explanation": _safe(m.explanation),
            })
        elif r.status == "needs_review":
            reasons = "; ".join(i.message for i in (r.qa.issues if r.qa else []) if i.severity == "error")
            row.update({
                "QA Status": "rejected",
                "Explanation": _safe("Not ranked - needs manual review. " + reasons),
            })
        else:  # failed
            row.update({"QA Status": "not_reviewed", "Explanation": _safe("Not ranked - " + (r.error or "failed"))})
        rows.append(row)
    return rows


def render_csv(job: JobRequirement, results: list[CandidateResult]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(build_rows(job, results))
    return buf.getvalue()


def write_report(run_id: str, job: JobRequirement, results: list[CandidateResult]) -> Path:
    path = report_path(run_id)
    # utf-8 with BOM so Excel shows non-English names correctly
    path.write_text(render_csv(job, results), encoding="utf-8-sig", newline="")
    return path
