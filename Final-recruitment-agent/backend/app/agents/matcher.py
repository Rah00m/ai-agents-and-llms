"""Matcher Agent: compare one candidate profile with one job. Pure rules, no LLM.

A fixed formula makes the score reproducible and explainable (an LLM would give a different
number on every run). The LLM is only used where understanding free text is needed (extraction).

score = 100 * ( w_required * required_score
              + w_experience * experience_score
              + w_preferred * preferred_score )

required_score   share of required skills the candidate has (a skill claimed only at a
                 "basic" level counts 0.5). Skills are compared by exact canonical name, so
                 "Java" never matches "JavaScript" and "SQL" never matches "NoSQL".
experience_score min(years / years_required, 1), scaled by required_score. Years only count
                 in proportion to how much of the required skill set the candidate has, so
                 5 years of unrelated experience do not earn the experience points.
preferred_score  share of preferred skills the candidate has.
                 If a job lists no preferred skills, its weight is shared by the other parts.

Only skills and years are used. Name, email, gender, age, university etc. are never scored.
GitHub languages are reported as supporting evidence but do not change the score.
"""
from dataclasses import dataclass

from app.models import ExtractedProfile, JobRequirement, MatchResult
from app.skills import key, level


@dataclass(frozen=True)
class Weights:
    required: float = 0.60
    experience: float = 0.25
    preferred: float = 0.15


DEFAULT_WEIGHTS = Weights()


def match_candidate(
    candidate_id: str,
    profile: ExtractedProfile,
    job: JobRequirement,
    github_languages: list[str] | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
) -> MatchResult:
    have = {}
    for s in profile.skills:
        k = key(s)
        # keep the strongest claim if a skill appears twice
        if k not in have or level(s) == "standard":
            have[k] = level(s)

    matched, partial, missing = [], [], []
    for req in job.required_skills:
        lvl = have.get(key(req))
        if lvl == "standard":
            matched.append(req)
        elif lvl == "basic":
            partial.append(req)
        else:
            missing.append(req)

    pref_hit = [p for p in job.preferred_skills if key(p) in have]
    pref_miss = [p for p in job.preferred_skills if key(p) not in have]

    n_req = len(job.required_skills)
    required_score = (len(matched) + 0.5 * len(partial)) / n_req if n_req else 1.0

    if job.min_years_experience <= 0:
        year_ratio = 1.0
    elif profile.experience_years is None:
        year_ratio = 0.0
    else:
        year_ratio = min(profile.experience_years / job.min_years_experience, 1.0)
    experience_score = year_ratio * required_score

    preferred_score = len(pref_hit) / len(job.preferred_skills) if job.preferred_skills else 0.0

    w_req, w_exp, w_pref = weights.required, weights.experience, weights.preferred
    if not job.preferred_skills:           # share the unused weight proportionally
        total = w_req + w_exp
        w_req, w_exp, w_pref = w_req / total, w_exp / total, 0.0
    score = 100 * (w_req * required_score + w_exp * experience_score + w_pref * preferred_score)

    gh_keys = {key(lang) for lang in (github_languages or [])}
    gh_supported = [r for r in matched + partial if key(r) in gh_keys]

    result = MatchResult(
        candidate_id=candidate_id,
        job_id=job.job_id,
        score=round(score, 1),
        required_score=round(required_score, 3),
        experience_score=round(experience_score, 3),
        preferred_score=round(preferred_score, 3),
        matched_required=matched,
        partial_required=partial,
        missing_required=missing,
        matched_preferred=pref_hit,
        missing_preferred=pref_miss,
        github_supported=gh_supported,
    )
    result.explanation = _explain(result, profile, job)
    return result


def _explain(m: MatchResult, profile: ExtractedProfile, job: JobRequirement) -> str:
    n_req = len(job.required_skills)
    parts = [f"Required skills: {len(m.matched_required)}/{n_req} matched"
             + (f" ({', '.join(m.matched_required)})" if m.matched_required else "")]
    if m.partial_required:
        parts.append(f"only basic level in {', '.join(m.partial_required)} (counted as half)")
    if m.missing_required:
        parts.append(f"missing {', '.join(m.missing_required)}")

    if job.min_years_experience:
        if profile.experience_years is None:
            parts.append(f"experience not stated (job asks {job.min_years_experience}y)")
        else:
            parts.append(f"experience {profile.experience_years:g}y vs {job.min_years_experience}y required"
                         + (" (reduced: required skills are only partly covered)"
                            if m.required_score < 1 and profile.experience_years >= job.min_years_experience
                            else ""))
    if job.preferred_skills:
        parts.append(f"preferred skills {len(m.matched_preferred)}/{len(job.preferred_skills)}")
    if m.github_supported:
        parts.append(f"GitHub activity supports {', '.join(m.github_supported)}")
    return "; ".join(parts) + "."
