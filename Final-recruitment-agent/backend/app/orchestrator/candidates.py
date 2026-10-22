"""Merge CV records and GitHub profiles into unified Candidate records, with consistency checks."""
from app.models import Candidate, CandidateCV, GitHubProfile


def build_candidates(
    cvs: list[CandidateCV], github: dict[str, GitHubProfile]
) -> tuple[list[Candidate], list[str], list[str]]:
    """Returns (candidates, errors, warnings).

    errors   -> data problems that make results unreliable (e.g. duplicate candidate_id)
    warnings -> candidate is usable but incomplete (no GitHub username, profile unavailable)
    """
    errors: list[str] = []
    warnings: list[str] = []
    candidates: list[Candidate] = []
    seen: set[str] = set()

    for cv in cvs:
        if cv.candidate_id in seen:
            errors.append(f"Duplicate candidate_id {cv.candidate_id} ({cv.source_file}) - skipped")
            continue
        seen.add(cv.candidate_id)

        profile = None
        if not cv.github_username:
            warnings.append(f"{cv.candidate_id} ({cv.name}): no GitHub username found in CV")
        else:
            profile = github.get(cv.github_username)
            if profile is None or profile.source == "unavailable":
                warnings.append(f"{cv.candidate_id} ({cv.name}): GitHub profile '{cv.github_username}' unavailable")
                profile = None

        if not cv.email:
            warnings.append(f"{cv.candidate_id} ({cv.name}): no email found in CV")

        candidates.append(
            Candidate(
                candidate_id=cv.candidate_id,
                name=cv.name,
                email=cv.email,
                source_file=cv.source_file,
                cv_text=cv.raw_text,
                github_profile=profile,
            )
        )

    # Profiles fetched but not linked to any candidate would indicate an ID mismatch.
    linked = {c.github_profile.username for c in candidates if c.github_profile}
    for username in github:
        if username not in linked and github[username].source != "unavailable":
            warnings.append(f"GitHub profile '{username}' is not linked to any candidate")

    return candidates, errors, warnings
