"""Shared data models (Pydantic) used by every stage of the pipeline."""
from pydantic import BaseModel, Field


class CandidateCV(BaseModel):
    candidate_id: str
    name: str
    email: str | None = None
    github_username: str | None = None
    raw_text: str
    source_file: str


class JobRequirement(BaseModel):
    job_id: str
    title: str
    required_skills: list[str]
    preferred_skills: list[str] = Field(default_factory=list)
    min_years_experience: int = 0
    description: str = ""


class GitHubProfile(BaseModel):
    username: str
    public_repos: int = 0
    top_languages: list[str] = Field(default_factory=list)
    notable_repos: list[dict] = Field(default_factory=list)
    source: str = "unavailable"  # "live" | "mock" | "unavailable"


class Candidate(BaseModel):
    """Unified candidate record handed to the processing layer (CV + GitHub merged).

    `skills`, `experience_years`, `experience` and `education` start empty and are
    filled by the Skill Extractor agent on Day 2.
    """
    candidate_id: str
    name: str
    email: str | None = None
    source_file: str
    cv_text: str
    github_profile: GitHubProfile | None = None
    skills: list[str] = Field(default_factory=list)
    experience_years: float | None = None
    experience: list[dict] = Field(default_factory=list)
    education: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------- Day 2: agents

class ExtractedProfile(BaseModel):
    """Skill Extractor output. `evidence` maps a skill to text copied from the CV."""
    skills: list[str] = Field(default_factory=list)
    experience_years: float | None = None
    experience: list[str] = Field(default_factory=list)    # one short line per role
    education: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)


class MatchResult(BaseModel):
    candidate_id: str
    job_id: str
    score: float                                   # 0-100
    required_score: float                          # each component 0-1
    experience_score: float
    preferred_score: float
    matched_required: list[str] = Field(default_factory=list)
    partial_required: list[str] = Field(default_factory=list)   # claimed only at a basic level
    missing_required: list[str] = Field(default_factory=list)
    matched_preferred: list[str] = Field(default_factory=list)
    missing_preferred: list[str] = Field(default_factory=list)
    github_supported: list[str] = Field(default_factory=list)   # required skills also seen on GitHub
    explanation: str = ""


class QAIssue(BaseModel):
    severity: str          # "warning" | "error"
    code: str              # machine-readable, e.g. "unsupported_skill"
    message: str


class QAReport(BaseModel):
    status: str            # "approved" | "approved_with_warnings" | "rejected"
    issues: list[QAIssue] = Field(default_factory=list)
    removed_skills: list[str] = Field(default_factory=list)


class CandidateResult(BaseModel):
    candidate_id: str
    name: str
    status: str            # "ranked" | "needs_review" | "failed"
    rank: int | None = None
    profile: ExtractedProfile | None = None
    match: MatchResult | None = None
    qa: QAReport | None = None
    attempts: int = 0
    error: str | None = None
    error_code: str | None = None                    # machine-readable: llm_timeout, llm_invalid_output, ...
    github_source: str | None = None                 # "live" | "mock" (sample data) | None (no profile)
    github_languages: list[str] = Field(default_factory=list)


class WorkflowResult(BaseModel):
    run_id: str
    job: JobRequirement
    mode: str              # "ollama" | "mock"
    model: str | None = None
    results: list[CandidateResult]
    stage_timings: dict[str, float] = Field(default_factory=dict)
    stage_status: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    total_seconds: float = 0.0
    report_file: str | None = None      # CSV written by the "report" stage (file name only)
    weights: dict[str, float] = Field(default_factory=dict)   # score weights used for this run


class RetrievalResult(BaseModel):
    candidates: list[Candidate]
    jobs: list[JobRequirement]
    timings: dict[str, float] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)      # something failed
    warnings: list[str] = Field(default_factory=list)    # data is usable but incomplete


# ---------------------------------------------------------------- Day 4: single-CV check

class Decision(BaseModel):
    """A recruiter-facing verdict for ONE CV against ONE job. The rules are in app/decision.py."""
    label: str                                       # "suitable" | "not_suitable" | "needs_review"
    summary: str
    reasons: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)       # required skills found
    partial_skills: list[str] = Field(default_factory=list)       # required, basic level only
    missing_required: list[str] = Field(default_factory=list)
    matched_preferred: list[str] = Field(default_factory=list)
    relevant_experience: list[str] = Field(default_factory=list)  # experience lines that use a required skill
    missing_information: list[str] = Field(default_factory=list)
    years_found: float | None = None
    years_required: int = 0


class SingleCvResult(BaseModel):
    job: JobRequirement
    mode: str                                        # "ollama" | "mock"
    model: str | None = None
    filename: str
    candidate_name: str
    profile: ExtractedProfile
    match: MatchResult
    qa: QAReport
    decision: Decision
    attempts: int = 1
    seconds: float = 0.0
    weights: dict[str, float] = Field(default_factory=dict)
    score_note: str = ""
    warnings: list[str] = Field(default_factory=list)
