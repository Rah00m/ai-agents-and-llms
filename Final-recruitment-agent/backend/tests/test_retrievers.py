"""Day-1 tests: retrievers, error handling and the unified Candidate/Job shape."""
import asyncio
import shutil
from dataclasses import replace

import httpx
import pytest
from reportlab.pdfgen import canvas

from app.config import settings
from app.models import Candidate, CandidateCV, GitHubProfile, JobRequirement
from app.orchestrator.candidates import build_candidates
from app.orchestrator.pipeline import run_retrieval
from app.retrievers import github_retriever
from app.retrievers.cv_retriever import retrieve_cvs
from app.retrievers.github_retriever import retrieve_github
from app.retrievers.jobs_retriever import retrieve_jobs


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def result():
    return run(run_retrieval())


# ---------- happy path ----------

def test_reads_all_8_cvs():
    cvs, errors = run(retrieve_cvs(settings.cv_dir))
    assert len(cvs) == 8
    assert errors == []
    assert all(cv.name and cv.email and cv.github_username for cv in cvs)


def test_reads_3_jobs_with_expected_fields():
    jobs, errors = run(retrieve_jobs(settings.jobs_source))
    assert errors == []
    assert [j.job_id for j in jobs] == ["J1", "J2", "J3"]
    assert all(isinstance(j, JobRequirement) and j.required_skills for j in jobs)
    assert jobs[0].preferred_skills == ["PostgreSQL", "AWS"]
    assert jobs[0].min_years_experience == 3


def test_github_profiles_for_all_candidates(result):
    assert result.counts["github_profiles"] == 8
    assert all(c.github_profile and c.github_profile.source == "mock" for c in result.candidates)


def test_full_retrieval_has_no_errors_or_warnings(result):
    assert result.errors == []
    assert result.warnings == []
    assert result.counts["candidates"] == 8 and result.counts["jobs"] == 3
    assert "retrieval_total" in result.timings


# ---------- unified data shape / ID matching ----------

def test_candidate_ids_are_unique_and_match_ground_truth(result):
    ids = [c.candidate_id for c in result.candidates]
    assert len(ids) == len(set(ids))
    import json
    gt = json.loads((settings.cv_dir.parent / "ground_truth.json").read_text())
    gt_ids = {cid for job in gt.values() for cid in job["ranking"]}
    assert gt_ids <= set(ids)


def test_candidate_has_unified_shape(result):
    c = result.candidates[0]
    assert isinstance(c, Candidate)
    assert c.cv_text and c.github_profile.username
    # filled by the Skill Extractor on Day 2
    assert c.skills == [] and c.experience == [] and c.education == []


# ---------- error handling ----------

def test_missing_cv_directory_reports_error(tmp_path):
    cvs, errors = run(retrieve_cvs(tmp_path / "does_not_exist"))
    assert cvs == []
    assert any("No PDF files found" in e for e in errors)


def test_corrupt_pdf_is_reported_but_not_fatal(tmp_path):
    shutil.copy(next(settings.cv_dir.glob("cv_01_*.pdf")), tmp_path)
    (tmp_path / "cv_99_broken.pdf").write_bytes(b"this is not a pdf")
    cvs, errors = run(retrieve_cvs(tmp_path))
    assert len(cvs) == 1                      # the valid CV still loads
    assert any("cv_99_broken.pdf" in e for e in errors)


def test_pdf_without_text_is_reported(tmp_path):
    c = canvas.Canvas(str(tmp_path / "cv_98_blank.pdf"))
    c.showPage()
    c.save()
    cvs, errors = run(retrieve_cvs(tmp_path))
    assert cvs == []
    assert any("no extractable text" in e for e in errors)


def test_missing_jobs_file_reports_error():
    jobs, errors = run(retrieve_jobs("data/not_there.csv"))
    assert jobs == []
    assert len(errors) == 1 and "not_there.csv" in errors[0]


def test_jobs_csv_with_missing_columns_reports_error(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("job_id,title\nJ1,Dev\n", encoding="utf-8")
    jobs, errors = run(retrieve_jobs(str(bad)))
    assert jobs == [] and errors


def test_unknown_github_user_degrades_to_unavailable():
    profiles, _ = run(retrieve_github(["no-such-user-xyz"]))
    assert profiles["no-such-user-xyz"].source == "unavailable"


def test_live_github_failure_never_falls_back_to_mock(monkeypatch):
    monkeypatch.setattr(
        github_retriever,
        "settings",
        replace(settings, github_mode="live", github_token=""),
    )

    def handler(request):
        return httpx.Response(503, request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        github_retriever.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )

    profiles, errors = run(retrieve_github(["alice"]))

    assert profiles["alice"].source == "unavailable"
    assert any("live lookup failed for 'alice'" in error for error in errors)


def test_live_github_success_uses_live_profile_and_bearer_token(monkeypatch):
    requests = []
    monkeypatch.setattr(
        github_retriever,
        "settings",
        replace(settings, github_mode="live", github_token="secret-token"),
    )

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            request=request,
            json=[{
                "name": "project",
                "language": "Python",
                "stargazers_count": 4,
                "description": "A project",
                "fork": False,
            }],
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        github_retriever.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )

    profiles, errors = run(retrieve_github(["alice"]))

    assert errors == []
    assert profiles["alice"].source == "live"
    assert profiles["alice"].public_repos == 1
    assert requests[0].headers["Authorization"] == "Bearer secret-token"


def test_build_candidates_warns_on_missing_github_and_duplicates():
    def cv(cid, gh):
        return CandidateCV(candidate_id=cid, name="X", email="x@example.com",
                           github_username=gh, raw_text="text", source_file=f"{cid}.pdf")

    cands, errors, warnings = build_candidates(
        [cv("C01", None), cv("C01", "dup"), cv("C02", "ghost")],
        {"ghost": GitHubProfile(username="ghost", source="unavailable")},
    )
    assert [c.candidate_id for c in cands] == ["C01", "C02"]
    assert any("Duplicate candidate_id C01" in e for e in errors)
    assert any("no GitHub username" in w for w in warnings)
    assert any("unavailable" in w for w in warnings)
