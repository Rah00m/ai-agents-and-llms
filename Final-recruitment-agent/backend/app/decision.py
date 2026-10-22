"""Turns a match into a recruiter-facing verdict for ONE CV and ONE job.

The rules are plain code (no LLM), so the same input always gives the same verdict and every
line of the explanation can be traced back to them.

    needs_review  (checked first)
        - the QA agent rejected the extraction, or the CV has too little text to judge, or
        - the CV lists no skills at all.
    not_suitable
        - at least HALF of the job's required skills are missing (basic-level skills do not count as missing), or
        - the stated experience is below HALF of the job's minimum years.
    suitable
        - every required skill is present at a working level AND
        - the stated experience reaches the job's minimum years.
    needs_review  (everything else)
        - one gap that a human can weigh: a required skill missing or only basic,
          experience somewhat below the minimum, or experience not stated.

These thresholds are design choices, not laws. They are deliberately strict about "suitable" and
about "not suitable", and send the grey zone to a person, because a wrong automatic rejection is
worse than an extra review.
"""
from app.models import Decision, ExtractedProfile, JobRequirement, MatchResult, QAReport
from app.skills import mentioned_in

SCORE_NOTE = (
    "Matching Score = 100 x (0.60 x required skills + 0.25 x experience + 0.15 x preferred skills). "
    "'Required skills' is the share of the job's required skills found in the CV (a skill claimed only at "
    "a basic level counts half). 'Experience' is the years stated in the CV divided by the job's minimum, "
    "capped at 100%, and only counts in proportion to the required skills found. It measures how well the CV "
    "overlaps with this job's listed requirements. It is NOT the probability that the candidate will be accepted."
)

NOT_SUITABLE_MISSING_SHARE = 0.5      # this share (or more) of required skills missing -> not suitable
NOT_SUITABLE_YEARS_SHARE = 0.5        # below this share of the minimum years -> not suitable


def _years(value: float) -> str:
    return f"{value:g} year{'s' if value != 1 else ''}"


def decide(job: JobRequirement, profile: ExtractedProfile, match: MatchResult, qa: QAReport,
           cv_text: str = "") -> Decision:
    required = job.required_skills
    n_req = len(required)
    years = profile.experience_years
    min_years = job.min_years_experience

    relevant = [line for line in profile.experience
                if any(mentioned_in(s, line) for s in match.matched_required + match.partial_required)]

    # -------- what is missing from the CV itself (not the same as a required skill that is absent)
    info: list[str] = []
    if not profile.skills:
        info.append("No skills could be read from the CV.")
    if years is None and min_years > 0:
        info.append(f"The CV does not state how many years of experience the candidate has "
                    f"(this job asks for at least {_years(min_years)}).")
    if not profile.experience:
        info.append("No work experience entries were found.")
    if not profile.education:
        info.append("No education was found.")
    for issue in qa.issues:
        if issue.code == "thin_cv":
            info.append(issue.message)

    reasons: list[str] = []
    if match.matched_required:
        reasons.append(f"Required skills found ({len(match.matched_required)}/{n_req}): "
                       f"{', '.join(match.matched_required)}.")
    if match.partial_required:
        reasons.append(f"Required skills found only at a basic level: {', '.join(match.partial_required)}.")
    if match.missing_required:
        reasons.append(f"Required skills not found: {', '.join(match.missing_required)}.")
    if match.matched_preferred:
        reasons.append(f"Preferred skills found: {', '.join(match.matched_preferred)}.")
    if years is not None:
        verdict = ("meets" if years >= min_years else "is below")
        reasons.append(f"Experience: {_years(years)} stated, which {verdict} the minimum of {_years(min_years)}.")

    def build(label: str, summary: str) -> Decision:
        return Decision(
            label=label, summary=summary, reasons=reasons,
            matched_skills=match.matched_required, partial_skills=match.partial_required,
            missing_required=match.missing_required, matched_preferred=match.matched_preferred,
            relevant_experience=relevant, missing_information=info,
            years_found=years, years_required=min_years)

    # -------- 1. too little / untrustworthy information
    if qa.status == "rejected":
        errors = " ".join(i.message for i in qa.issues if i.severity == "error")
        reasons.append(f"The quality check could not confirm the extracted data: {errors}")
        return build("needs_review", "The extracted data could not be verified, so a person should read the CV.")
    if not profile.skills:
        return build("needs_review", "The CV contains too little information to judge against this job.")
    if any(i.code == "thin_cv" for i in qa.issues):
        return build("needs_review", "The CV contains too little text to judge against this job.")

    # -------- 2. clear mismatch
    if n_req and len(match.missing_required) / n_req >= NOT_SUITABLE_MISSING_SHARE:
        return build("not_suitable",
                     f"Missing {len(match.missing_required)} of the {n_req} required skills for {job.title}.")
    if years is not None and min_years > 0 and years < NOT_SUITABLE_YEARS_SHARE * min_years:
        return build("not_suitable",
                     f"Experience ({_years(years)}) is far below the minimum of {_years(min_years)}.")

    # -------- 3. clear fit
    complete = not match.missing_required and not match.partial_required
    if complete and (min_years == 0 or (years is not None and years >= min_years)):
        return build("suitable", f"Has every required skill and meets the minimum experience for {job.title}.")

    # -------- 4. grey zone
    gaps = []
    if match.missing_required:
        gaps.append(f"missing required skill(s): {', '.join(match.missing_required)}")
    if match.partial_required:
        gaps.append(f"only basic level in: {', '.join(match.partial_required)}")
    if years is None and min_years > 0:
        gaps.append("experience not stated")
    elif years is not None and years < min_years:
        gaps.append(f"experience below the minimum ({_years(years)} of {_years(min_years)})")
    return build("needs_review", "Close, but a person should decide: " + "; ".join(gaps) + ".")
