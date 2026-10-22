"""Skill Extractor Agent: CV text -> structured profile with textual evidence.

mode="ollama": a local LLM does the extraction (JSON schema enforced, invalid output repaired).
mode="mock"  : deterministic parser of the CV sections - no model needed (tests, quick demos).
Both return the same `ExtractedProfile`, so the rest of the pipeline cannot tell them apart.
"""
import re

from app.llm import chat_json
from app.models import ExtractedProfile
from app.skills import mentioned_in

MAX_CV_CHARS = 12_000  # keep small local models inside their context window

SYSTEM_PROMPT = """You are a precise recruiting assistant. Extract structured data from ONE candidate CV.

Rules:
- Use ONLY information written in the CV. Never guess or add skills that are not in the text.
- "skills": technical and professional skills mentioned in the CV (tools, languages, frameworks, methods).
  If the CV says a skill is basic (e.g. "React (basics)"), keep that qualifier in brackets.
- "experience_years": total years of professional experience as a number. Use the CV's own statement
  if it has one. If it cannot be determined, use null. Do not invent a number.
- "experience": one short line per job/role. "education": one line per degree.
  "projects": notable projects, if the CV has any (otherwise an empty list).
- "evidence": for EVERY skill, copy one short phrase (max 25 words) EXACTLY as written in the CV that
  supports it. Copy it word for word; do not paraphrase.
- If the CV has little or no information, return empty lists and null. That is a valid answer.

Reply with ONLY one JSON object that follows the given schema. No text before or after it."""


async def extract_profile(
    cv_text: str, *, mode: str, feedback: str | None = None
) -> ExtractedProfile:
    if mode == "mock":
        return _extract_mock(cv_text)

    user = f"CV TEXT:\n\"\"\"\n{cv_text[:MAX_CV_CHARS]}\n\"\"\""
    if feedback:
        user += (
            "\n\nA reviewer rejected your previous answer for these reasons:\n"
            f"{feedback}\nFix these problems. Use only skills and phrases that really appear in the CV text."
        )
    return await chat_json(SYSTEM_PROMPT, user, ExtractedProfile)


# ------------------------------------------------------------------ mock mode

_SECTION = re.compile(r"^(skills|experience|education|projects)\b", re.I)


def _sections(cv_text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for line in (ln.strip() for ln in cv_text.splitlines()):
        if not line:
            continue
        m = _SECTION.match(line)
        if m and len(line) < 40:           # a heading, not a sentence starting with "Experience"
            current = m.group(1).lower()
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def _clauses(texts: list[str]) -> list[str]:
    """Split sentences/bullets into short clauses that can serve as evidence quotes."""
    out: list[str] = []
    for t in texts:
        out += [c.strip() for c in re.split(r"(?<=[.;])\s+", " ".join(t.split())) if c.strip()]
    return out


def _preamble(cv_text: str) -> list[str]:
    """Header lines before the first section: name, contact lines, title, summary."""
    lines: list[str] = []
    for line in (ln.strip() for ln in cv_text.splitlines() if ln.strip()):
        if _SECTION.match(line) and len(line) < 40:
            break
        lines.append(line)
    # drop the name (first line) and contact lines, keep the title + summary
    return [ln for ln in lines[1:] if not re.match(r"(email|github|phone|linkedin)\b", ln, re.I)]


def _extract_mock(cv_text: str) -> ExtractedProfile:
    sec = _sections(cv_text)
    skills = [s.strip() for s in " ".join(sec.get("skills", [])).split(",") if s.strip()]

    years = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*years?\s*total", cv_text, re.I) or \
        re.search(r"(\d+(?:\.\d+)?)\s*years?", cv_text, re.I)
    if m:
        years = float(m.group(1))

    # experience: merge wrapped lines back into one entry per bullet
    experience: list[str] = []
    for line in sec.get("experience", []):
        if line.startswith("-") or not experience:
            experience.append(line.lstrip("- ").strip())
        else:
            experience[-1] += " " + line

    skills_line = " ".join(sec.get("skills", []))
    # Evidence comes from where skills are actually used: the summary, jobs and projects.
    # A skill that is only listed in the Skills section falls back to that list.
    clauses = _clauses(_preamble(cv_text) + experience + sec.get("projects", []))
    evidence: dict[str, str] = {}
    for skill in skills:
        hit = next((c for c in clauses if mentioned_in(skill, c)), None)
        evidence[skill] = hit[:200] if hit else skills_line[:200]

    return ExtractedProfile(
        skills=skills,
        experience_years=years,
        experience=experience,
        education=list(sec.get("education", [])),
        projects=list(sec.get("projects", [])),
        evidence=evidence,
    )
