"""QA Agent: review the extraction + match for ONE candidate before it is accepted.

It never invents data to fill a gap - it records a warning instead. Checks:
  * every claimed skill really appears in the CV text (otherwise it is removed + warned)
  * every skill has evidence, and the evidence is text that really exists in the CV
  * the extracted years do not contradict the years the CV states
  * missing data (no skills, no years, no education, very short CV)
  * the match result does not rely on a skill that was removed

status: "rejected"               -> output unusable/contradictory; the orchestrator retries extraction
        "approved_with_warnings" -> usable, but something is missing or was corrected
        "approved"               -> clean
"""
import re

from app.models import ExtractedProfile, MatchResult, QAIssue, QAReport
from app.skills import key, mentioned_in

STATED_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*years?\s*total", re.I)
MIN_CV_CHARS = 200


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def review(
    cv_text: str, profile: ExtractedProfile, match: MatchResult | None = None
) -> tuple[QAReport, ExtractedProfile]:
    """Returns (report, cleaned_profile). `cleaned_profile` has unsupported skills removed."""
    issues: list[QAIssue] = []
    removed: list[str] = []
    cv_norm = _norm(cv_text)

    def add(sev: str, code: str, msg: str) -> None:
        issues.append(QAIssue(severity=sev, code=code, message=msg))

    if len(cv_text.strip()) < MIN_CV_CHARS:
        add("warning", "thin_cv", "The CV contains very little text; results may be unreliable.")

    kept: list[str] = []
    for skill in profile.skills:
        if not mentioned_in(skill, cv_text):
            removed.append(skill)
            add("warning", "unsupported_skill",
                f"'{skill}' is not mentioned anywhere in the CV, so it was removed.")
            continue
        kept.append(skill)
        ev = profile.evidence.get(skill, "").strip()
        if not ev:
            add("warning", "missing_evidence", f"No evidence was given for '{skill}'.")
        elif _norm(ev) not in cv_norm:
            add("warning", "evidence_not_in_cv",
                f"Evidence for '{skill}' is not a quote from the CV: \"{ev[:80]}\".")

    if not kept:
        add("error", "no_skills", "No supported skills could be extracted from this CV.")

    years = profile.experience_years
    stated = STATED_YEARS.search(cv_text)
    if years is None:
        add("warning", "experience_unknown", "Years of experience could not be determined.")
    elif years < 0 or years > 50:
        add("error", "implausible_years", f"Extracted experience of {years:g} years is not plausible.")
    elif stated and abs(float(stated.group(1)) - years) > 1:
        add("error", "years_contradiction",
            f"Extracted {years:g} years, but the CV states {stated.group(1)} years in total.")

    if not profile.education:
        add("warning", "education_missing", "No education information was found.")

    if match is not None:
        kept_keys = {key(s) for s in kept}
        used = match.matched_required + match.partial_required + match.matched_preferred
        stale = [s for s in used if key(s) not in kept_keys]
        if stale:
            add("warning", "match_uses_unsupported_skill",
                f"The match counted unsupported skills ({', '.join(stale)}); it must be recomputed.")
        if not 0 <= match.score <= 100:
            add("error", "score_out_of_range", f"Score {match.score} is outside 0-100.")

    if any(i.severity == "error" for i in issues):
        status = "rejected"
    elif issues:
        status = "approved_with_warnings"
    else:
        status = "approved"

    cleaned = profile.model_copy(
        update={
            "skills": kept,
            "evidence": {s: e for s, e in profile.evidence.items() if s in kept},
        }
    )
    return QAReport(status=status, issues=issues, removed_skills=removed), cleaned
