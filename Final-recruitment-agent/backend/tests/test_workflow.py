"""Day-2 end-to-end tests of the orchestrator (run_recruitment_workflow)."""
import asyncio

import pytest

from app.llm import LLMError
from app.models import ExtractedProfile
from app.orchestrator import store, workflow
from app.orchestrator.pipeline import run_retrieval
from app.orchestrator.workflow import run_recruitment_workflow

STAGES = ["retrieval", "extraction", "matching", "qa", "ranking"]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def retrieval():
    return run(run_retrieval())


@pytest.fixture(autouse=True)
def tmp_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "runs_dir", lambda: tmp_path)   # never write into backend/outputs
    return tmp_path


def wf(job_id="J1", retrieval=None, **kw):
    return run(run_recruitment_workflow(job_id, mode=kw.pop("mode", "mock"), retrieval=retrieval, **kw))


# ---------------------------------------------------------------- happy path

def test_end_to_end_ranks_all_eight_candidates(retrieval):
    res = wf("J1", retrieval)
    assert len(res.results) == 8
    assert all(r.status == "ranked" for r in res.results)
    assert [r.rank for r in res.results] == list(range(1, 9))
    scores = [r.match.score for r in res.results]
    assert scores == sorted(scores, reverse=True)
    assert res.results[0].candidate_id == "C01"           # the backend/FastAPI/Docker profile
    assert res.errors == []
    assert all(r.match.explanation and r.qa.status.startswith("approved") for r in res.results)


def test_every_stage_is_recorded_with_status_and_time(retrieval):
    res = wf("J2", retrieval)
    assert list(res.stage_status) == STAGES
    assert set(res.stage_status.values()) == {"done"}
    assert set(res.stage_timings) == set(STAGES) and res.total_seconds >= 0


def test_full_run_from_real_retrieval_works_for_all_jobs():
    for job_id in ("J1", "J2", "J3"):
        res = wf(job_id)
        assert res.job.job_id == job_id and len(res.results) == 8 and res.errors == []


def test_results_are_saved_and_can_be_loaded(retrieval, tmp_runs):
    res = wf("J3", retrieval)
    assert (tmp_runs / f"{res.run_id}.json").exists()
    loaded = store.load_run(res.run_id)
    assert loaded == res
    assert res.run_id in store.list_runs()


def test_load_run_rejects_path_tricks_and_unknown_ids():
    with pytest.raises(ValueError):
        store.load_run("../secrets")
    with pytest.raises(FileNotFoundError):
        store.load_run("J9-20260101-000000")


def test_progress_events_are_emitted_in_order(retrieval):
    events = []

    async def emit(e):
        events.append((e["stage"], e["status"]))

    wf("J1", retrieval, emit=emit)
    started = [s for s, st in events if st == "started"]
    assert started == ["extraction", "matching", "qa", "ranking"]      # retrieval was supplied
    assert events[-1] == ("workflow", "done")


def test_unknown_job_gives_helpful_error(retrieval):
    with pytest.raises(ValueError, match="Available jobs: J1, J2, J3"):
        wf("J42", retrieval)


def test_unknown_mode_is_rejected(retrieval):
    with pytest.raises(ValueError, match="Unknown LLM mode"):
        wf("J1", retrieval, mode="gpt")


# ---------------------------------------------------------------- failure isolation / QA loop

def test_one_failing_candidate_does_not_stop_the_others(retrieval, monkeypatch):
    real = workflow.extract_profile

    async def flaky(cv_text, *, mode, feedback=None):
        if "Omar Hassan" in cv_text:
            raise LLMError("model crashed")
        return await real(cv_text, mode=mode, feedback=feedback)

    monkeypatch.setattr(workflow, "extract_profile", flaky)
    res = wf("J2", retrieval)
    by_id = {r.candidate_id: r for r in res.results}
    assert by_id["C02"].status == "failed" and "model crashed" in by_id["C02"].error
    assert by_id["C02"].rank is None
    ranked = [r for r in res.results if r.status == "ranked"]
    assert len(ranked) == 7 and [r.rank for r in ranked] == list(range(1, 8))
    assert any("C02" in e for e in res.errors)
    assert res.stage_status["ranking"] == "done"


def test_qa_rejection_triggers_retry_with_feedback_and_recovers(retrieval, monkeypatch):
    real = workflow.extract_profile
    feedbacks = []

    async def sloppy_first_time(cv_text, *, mode, feedback=None):
        feedbacks.append(feedback)
        p = await real(cv_text, mode=mode)
        if "Sara Ahmed" in cv_text and feedback is None:
            return p.model_copy(update={"experience_years": 15})    # contradicts "4 years total"
        return p

    monkeypatch.setattr(workflow, "extract_profile", sloppy_first_time)
    res = wf("J1", retrieval)
    sara = next(r for r in res.results if r.candidate_id == "C01")
    assert sara.status == "ranked" and sara.attempts == 2
    assert sara.profile.experience_years == 4
    assert any(f and "CV states 4" in f for f in feedbacks)        # QA's reason was passed back


def test_persistent_qa_rejection_marks_needs_review_and_excludes_from_ranking(retrieval, monkeypatch):
    real = workflow.extract_profile

    async def always_wrong(cv_text, *, mode, feedback=None):
        p = await real(cv_text, mode=mode)
        return p.model_copy(update={"experience_years": 15}) if "Sara Ahmed" in cv_text else p

    monkeypatch.setattr(workflow, "extract_profile", always_wrong)
    res = wf("J1", retrieval, max_attempts=2)
    sara = next(r for r in res.results if r.candidate_id == "C01")
    assert sara.status == "needs_review" and sara.rank is None and sara.attempts == 2
    assert [r.rank for r in res.results if r.status == "ranked"] == list(range(1, 8))
    assert any("C01" in w and "manual review" in w for w in res.warnings)


def test_hallucinated_skill_is_removed_and_score_recomputed(retrieval, monkeypatch):
    real = workflow.extract_profile

    async def hallucinates(cv_text, *, mode, feedback=None):
        p = await real(cv_text, mode=mode)
        if "Omar Hassan" in cv_text:          # a frontend dev "gains" backend skills that are not in the CV
            p = p.model_copy(update={"skills": p.skills + ["Python", "FastAPI", "SQL", "Docker"]})
        return p

    monkeypatch.setattr(workflow, "extract_profile", hallucinates)
    res = wf("J1", retrieval)
    omar = next(r for r in res.results if r.candidate_id == "C02")
    assert omar.match.score == 0 and omar.match.matched_required == []     # fake skills earned nothing
    assert set(omar.qa.removed_skills) == {"Python", "FastAPI", "SQL", "Docker"}
    assert omar.qa.status == "approved_with_warnings"
    assert "Python" not in omar.profile.skills


def test_no_candidates_still_returns_a_result(retrieval):
    empty = retrieval.model_copy(update={"candidates": []})
    res = wf("J1", empty)
    assert res.results == []


# ---------------------------------------------------------------- Ollama mode plumbing

def test_ollama_down_fails_fast_with_clear_message(monkeypatch):
    async def down():
        return {"reachable": False, "model_installed": False, "models": []}

    monkeypatch.setattr(workflow, "check_ollama", down)
    with pytest.raises(LLMError, match="ollama serve"):
        wf("J1", mode="ollama")


def test_missing_model_fails_fast_with_pull_command(monkeypatch):
    async def no_model():
        return {"reachable": True, "model_installed": False, "models": []}

    monkeypatch.setattr(workflow, "check_ollama", no_model)
    with pytest.raises(LLMError, match="ollama pull"):
        wf("J1", mode="ollama")


def test_ollama_mode_runs_end_to_end_through_the_llm_layer(retrieval, monkeypatch):
    """Same pipeline in 'ollama' mode, with the model replaced by a stub returning schema-valid JSON."""
    from app.agents import extractor

    async def ready():
        return {"reachable": True, "model_installed": True, "models": ["stub"]}

    async def stub_chat_json(system, user, schema, **kw):
        cv = user.split('"""')[1]
        return extractor._extract_mock(cv)

    monkeypatch.setattr(workflow, "check_ollama", ready)
    monkeypatch.setattr(extractor, "chat_json", stub_chat_json)
    res = wf("J1", retrieval, mode="ollama")
    assert res.mode == "ollama" and res.model
    assert res.results[0].candidate_id == "C01" and len(res.results) == 8


def test_llm_failure_for_every_candidate_is_reported_not_raised(retrieval, monkeypatch):
    from app.agents import extractor

    async def ready():
        return {"reachable": True, "model_installed": True, "models": ["stub"]}

    async def broken(*a, **k):
        raise LLMError("Model returned invalid JSON after 3 attempts")

    monkeypatch.setattr(workflow, "check_ollama", ready)
    monkeypatch.setattr(extractor, "chat_json", broken)
    res = wf("J1", retrieval, mode="ollama")
    assert all(r.status == "failed" for r in res.results) and len(res.errors) == 8
    assert all(r.rank is None for r in res.results)
