"""Validate data/ground_truth.json per job, and state what "suitable" means for each job.

Errors make the ranking metrics unreliable (they stop the evaluation). Warnings are things a person
should look at: for example a candidate the reference calls suitable whose CV text does not mention a
required skill. The check reads the raw CV text with simple word matching, independently of the Skill
Extractor, so it is not graded by the system it is meant to judge.
"""
import json
import re
from pathlib import Path

from app.models import Candidate, JobRequirement
from app.skills import mentioned_in

YEARS_RE = re.compile(r"experience\s*\((\d+(?:\.\d+)?)\s*years", re.I)


def definition(job: JobRequirement) -> str:
    return (f"Suitable for {job.job_id} ({job.title}): the CV shows all of [{', '.join(job.required_skills)}] "
            f"and at least {job.min_years_experience} years of experience.")


def cv_years(text: str) -> float | None:
    m = YEARS_RE.search(text)
    return float(m.group(1)) if m else None


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(truth: dict, jobs: list[JobRequirement], candidates: list[Candidate]) -> dict:
    by_id = {c.candidate_id: c for c in candidates}
    out: dict[str, dict] = {}
    for job in jobs:
        errors: list[str] = []
        warnings: list[str] = []
        entry = truth.get(job.job_id)
        info = {"definition": definition(job), "ranking": [], "accepted": [], "errors": errors,
                "warnings": warnings, "ok": False}
        out[job.job_id] = info
        if entry is None:
            errors.append(f"No entry for {job.job_id} in ground_truth.json.")
            continue
        ranking, accepted = entry.get("ranking", []), entry.get("accepted", [])
        info.update(ranking=ranking, accepted=accepted)
        if not ranking:
            errors.append("The reference ranking is empty.")
        if len(set(ranking)) != len(ranking):
            errors.append("The reference ranking contains duplicate candidate ids.")
        for cid in ranking + accepted:
            if cid not in by_id:
                errors.append(f"{cid} is not a candidate in data/cvs.")
        if not set(accepted) <= set(ranking):
            errors.append("Every accepted candidate must also be in the ranking.")
        elif set(ranking[:len(accepted)]) != set(accepted):
            errors.append("Accepted candidates must be the top of the ranking.")
        if not accepted:
            warnings.append("No candidate is accepted, so Precision@K will always be 0.")

        # independent check against the raw CV text
        for cid in dict.fromkeys(ranking):
            c = by_id.get(cid)
            if c is None:
                continue
            missing = [s for s in job.required_skills if not mentioned_in(s, c.cv_text)]
            years = cv_years(c.cv_text)
            short = years is not None and years < job.min_years_experience
            meets = not missing and not short and (years is not None or job.min_years_experience == 0)
            if cid in accepted and not meets:
                why = (f"does not mention {', '.join(missing)}" if missing else
                       f"states {years:g} years (< {job.min_years_experience})" if short else "does not state years")
                warnings.append(f"{cid} is accepted but the CV {why}.")
            if cid not in accepted and meets:
                warnings.append(f"{cid} meets the definition of suitable but is not in the accepted list.")
        info["ok"] = not errors
    for job_id in truth:
        if job_id not in out:
            out[job_id] = {"definition": "", "ranking": [], "accepted": [], "ok": False, "warnings": [],
                           "errors": [f"{job_id} is in ground_truth.json but not in jobs.csv."]}
    return out
