"""Day-2 tests for the skill helpers and the Extractor, Matcher and QA agents."""
import asyncio

import pytest

from app.agents import extractor
from app.agents.extractor import extract_profile
from app.agents.matcher import Weights, match_candidate
from app.agents.qa import review
from app.models import ExtractedProfile, JobRequirement
from app.orchestrator.pipeline import run_retrieval
from app.skills import key, level, mentioned_in


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def cvs():
    return {c.candidate_id: c for c in run(run_retrieval()).candidates}


def job(required, preferred=(), years=3):
    return JobRequirement(job_id="JT", title="Test", required_skills=list(required),
                          preferred_skills=list(preferred), min_years_experience=years)


def profile(skills, years=3.0, education=("B.Sc.",)):
    return ExtractedProfile(skills=list(skills), experience_years=years, education=list(education),
                            evidence={s: s for s in skills})


# ---------------------------------------------------------------- skills helpers

def test_aliases_resolve_to_one_key():
    assert key("sklearn") == key("Scikit-Learn") == key("scikit learn")
    assert key("JS") == key("javascript")
    assert key("Postgres") == key("PostgreSQL")
    assert key("Amazon Web Services") == key("AWS")


def test_level_qualifier():
    assert level("React (basics)") == "basic"
    assert level("React") == "standard"
    assert key("React (basics)") == key("React")


def test_similar_words_do_not_match():
    assert key("Java") != key("JavaScript")
    assert not mentioned_in("Java", "Experienced JavaScript developer")
    assert not mentioned_in("SQL", "Worked with NoSQL stores")
    assert mentioned_in("scikit-learn", "trained models with sklearn")
    assert mentioned_in("Node.js", "APIs built on Node.js and Express")


# ---------------------------------------------------------------- extractor (mock mode)

def test_mock_extractor_full_cv(cvs):
    p = run(extract_profile(cvs["C01"].cv_text, mode="mock"))
    assert {"Python", "FastAPI", "PostgreSQL", "Docker"} <= set(p.skills)
    assert p.experience_years == 4
    assert len(p.experience) == 2 and p.education
    assert set(p.evidence) == set(p.skills)


def test_mock_extractor_evidence_is_quoted_from_cv(cvs):
    cv = cvs["C01"].cv_text
    p = run(extract_profile(cv, mode="mock"))
    flat = " ".join(cv.split()).lower()
    assert all(" ".join(e.split()).lower() in flat for e in p.evidence.values())
    assert "FastAPI microservices" in p.evidence["FastAPI"]    # real sentence, not just the skills list


def test_mock_extractor_incomplete_cv():
    cv = "Jane Doe\nSkills\nPython, SQL\n"
    p = run(extract_profile(cv, mode="mock"))
    assert p.skills == ["Python", "SQL"]
    assert p.experience_years is None and p.education == [] and p.experience == []


def test_mock_extractor_cv_without_information():
    p = run(extract_profile("Just a name\nand a phone number", mode="mock"))
    assert p.skills == [] and p.experience_years is None


def test_llm_mode_sends_cv_and_reviewer_feedback(monkeypatch):
    seen = {}

    async def fake_chat_json(system, user, schema, **kw):
        seen.update(system=system, user=user, schema=schema)
        return ExtractedProfile(skills=["Python"])

    monkeypatch.setattr(extractor, "chat_json", fake_chat_json)
    out = run(extract_profile("CV BODY", mode="ollama", feedback="- years contradict"))
    assert out.skills == ["Python"] and seen["schema"] is ExtractedProfile
    assert "CV BODY" in seen["user"] and "years contradict" in seen["user"]
    assert "Never guess" in seen["system"]


# ---------------------------------------------------------------- matcher

def test_perfect_match_scores_100():
    m = match_candidate("C", profile(["Python", "SQL", "PostgreSQL"], years=4),
                        job(["Python", "SQL"], ["PostgreSQL"]))
    assert m.score == 100 and m.missing_required == []


def test_default_weights_60_25_15():
    # half the required skills, full experience ratio, all preferred
    m = match_candidate("C", profile(["Python", "PostgreSQL"], years=3),
                        job(["Python", "SQL"], ["PostgreSQL"], years=3))
    # required 0.5 -> 30, experience 1.0*0.5 -> 12.5, preferred 1.0 -> 15
    assert m.score == 57.5
    assert (m.required_score, m.experience_score, m.preferred_score) == (0.5, 0.5, 1.0)


def test_weights_are_configurable():
    # all required skills (1.0) but only 1 of 3 required years (0.33): the weights decide the score
    p, j = profile(["Python", "SQL"], years=1), job(["Python", "SQL"], years=3)
    heavy_skills = match_candidate("C", p, j, weights=Weights(0.9, 0.05, 0.05)).score
    heavy_years = match_candidate("C", p, j, weights=Weights(0.1, 0.8, 0.1)).score
    assert heavy_skills > 90 > 50 > heavy_years


def test_basic_level_counts_half():
    m = match_candidate("C", profile(["React (basics)", "CSS"]), job(["React", "CSS"]))
    assert m.partial_required == ["React"] and m.matched_required == ["CSS"]
    assert m.required_score == 0.75


def test_similar_names_get_no_credit():
    m = match_candidate("C", profile(["JavaScript", "NoSQL"]), job(["Java", "SQL"]))
    assert m.matched_required == [] and m.missing_required == ["Java", "SQL"]
    assert m.score == 0


def test_years_do_not_count_without_relevant_skills():
    none = match_candidate("C", profile(["Cobol"], years=20), job(["Python"], years=3))
    assert none.experience_score == 0 and none.score == 0


def test_unknown_years_get_no_experience_points_and_are_explained():
    m = match_candidate("C", profile(["Python"], years=None), job(["Python"], years=3))
    assert m.experience_score == 0
    assert "not stated" in m.explanation


def test_job_without_preferred_skills_shares_weight():
    m = match_candidate("C", profile(["Python"], years=3), job(["Python"], years=3))
    assert m.score == 100                      # not capped at 85 just because there is nothing preferred


def test_score_is_deterministic_and_explained():
    a = match_candidate("C", profile(["Python"]), job(["Python", "SQL"]))
    b = match_candidate("C", profile(["Python"]), job(["Python", "SQL"]))
    assert a == b and "missing SQL" in a.explanation


def test_github_supports_but_does_not_change_score():
    p, j = profile(["Python"]), job(["Python"])
    with_gh = match_candidate("C", p, j, github_languages=["Python"])
    without = match_candidate("C", p, j)
    assert with_gh.score == without.score
    assert with_gh.github_supported == ["Python"] and without.github_supported == []


# ---------------------------------------------------------------- QA

CV = ("Sam Lee " + "x " * 120 + "\nSkills\nPython, Docker\nExperience (4 years total)\n"
      "- Built Python services deployed in Docker containers.\nEducation\nB.Sc. CS")


def good_profile(**kw):
    base = dict(skills=["Python", "Docker"], experience_years=4, education=["B.Sc. CS"],
                evidence={"Python": "Built Python services", "Docker": "deployed in Docker containers"})
    base.update(kw)
    return ExtractedProfile(**base)


def codes(report):
    return {i.code for i in report.issues}


def test_qa_approves_clean_output():
    report, cleaned = review(CV, good_profile())
    assert report.status == "approved" and report.issues == []
    assert cleaned.skills == ["Python", "Docker"]


def test_qa_removes_unsupported_skill_with_warning():
    report, cleaned = review(CV, good_profile(skills=["Python", "Docker", "Kubernetes"]))
    assert report.status == "approved_with_warnings"
    assert report.removed_skills == ["Kubernetes"] and "Kubernetes" not in cleaned.skills
    assert "unsupported_skill" in codes(report)


def test_qa_flags_missing_and_fabricated_evidence():
    report, _ = review(CV, good_profile(evidence={"Python": "led a team of 50 engineers"}))
    assert {"evidence_not_in_cv", "missing_evidence"} <= codes(report)
    assert report.status == "approved_with_warnings"      # skill itself is real, so it is kept


def test_qa_treats_empty_evidence_as_warning_without_rejection():
    report, cleaned = review(CV, good_profile(evidence={"Python": "", "Docker": "deployed in Docker containers"}))
    assert report.status == "approved_with_warnings"
    assert "missing_evidence" in codes(report)
    assert cleaned.skills == ["Python", "Docker"]


def test_qa_treats_na_evidence_as_unquoted_warning_without_rejection():
    report, cleaned = review(CV, good_profile(evidence={"Python": "N/A", "Docker": "deployed in Docker containers"}))
    assert report.status == "approved_with_warnings"
    assert "evidence_not_in_cv" in codes(report)
    assert cleaned.skills == ["Python", "Docker"]


def test_qa_rejects_years_contradiction():
    report, _ = review(CV, good_profile(experience_years=9))
    assert report.status == "rejected" and "years_contradiction" in codes(report)


def test_qa_rejects_implausible_years():
    report, _ = review(CV, good_profile(experience_years=120))
    assert report.status == "rejected" and "implausible_years" in codes(report)


def test_qa_rejects_when_no_skill_is_supported():
    report, _ = review(CV, good_profile(skills=["Rust", "Go"], evidence={}))
    assert report.status == "rejected" and "no_skills" in codes(report)


def test_qa_warns_about_missing_data_instead_of_inventing_it():
    report, cleaned = review(CV, good_profile(experience_years=None, education=[]))
    assert {"experience_unknown", "education_missing"} <= codes(report)
    assert cleaned.experience_years is None and cleaned.education == []     # nothing was filled in


def test_qa_warns_on_very_short_cv():
    report, _ = review("Python dev", ExtractedProfile(skills=["Python"], evidence={"Python": "Python dev"}))
    assert "thin_cv" in codes(report)


def test_qa_detects_match_that_used_removed_skill():
    p = good_profile(skills=["Python", "Docker", "Kubernetes"])
    stale = match_candidate("C", p, job(["Python", "Kubernetes"]))
    report, _ = review(CV, p, stale)
    assert "match_uses_unsupported_skill" in codes(report)
