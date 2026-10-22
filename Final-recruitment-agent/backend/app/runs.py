"""Runs the workflow in the background and tracks live progress for the API.

POST /analyze must answer immediately (a local LLM can take minutes), so the workflow runs as an
asyncio task. The UI polls GET /results/{run_id} to see which stage is running, then the result.
Finished runs are also saved to disk (store.py), so they survive a server restart.
"""
import asyncio
import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import LLMError
from app.models import WorkflowResult
from app.orchestrator import store
from app.orchestrator.workflow import new_run_id, run_recruitment_workflow

STAGE_ORDER = ["retrieval", "extraction", "matching", "qa", "ranking", "report"]
MAX_EVENTS = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StageState(BaseModel):
    status: Literal["pending", "running", "done", "failed"] = "pending"
    detail: str = ""
    seconds: float | None = None


class RunState(BaseModel):
    run_id: str
    job_id: str
    mode: str
    status: Literal["running", "done", "failed"] = "running"
    started_at: str = Field(default_factory=_now)
    finished_at: str | None = None
    stages: dict[str, StageState] = Field(default_factory=lambda: {s: StageState() for s in STAGE_ORDER})
    events: list[dict] = Field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    result: WorkflowResult | None = None


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._tasks: set[asyncio.Task] = set()       # keep references so tasks are not garbage collected
        self._stage_started: dict[tuple[str, str], float] = {}

    # ------------------------------------------------------------------ queries
    def active(self) -> RunState | None:
        return next((r for r in self._runs.values() if r.status == "running"), None)

    def get(self, run_id: str) -> RunState | None:
        """Live state from memory, or - for runs from before a restart - rebuilt from the saved file."""
        if run_id in self._runs:
            return self._runs[run_id]
        try:
            res = store.load_run(run_id)
        except FileNotFoundError:
            return None
        return self._from_result(res)

    def summaries(self) -> list[dict]:
        """Newest first: live runs plus saved runs."""
        seen: dict[str, dict] = {}
        for rid in store.list_runs():
            state = self.get(rid)
            if state:
                seen[rid] = self.summary(state)
        for rid, state in self._runs.items():
            seen[rid] = self.summary(state)
        return sorted(seen.values(), key=lambda s: s["started_at"], reverse=True)

    @staticmethod
    def summary(state: RunState) -> dict:
        top = None
        if state.result:
            ranked = [r for r in state.result.results if r.status == "ranked"]
            if ranked:
                top = {"candidate_id": ranked[0].candidate_id, "name": ranked[0].name,
                       "score": ranked[0].match.score}
        job = state.result.job if state.result else None
        return {
            "run_id": state.run_id, "job_id": state.job_id, "job_title": job.title if job else None,
            "mode": state.mode, "status": state.status, "started_at": state.started_at,
            "finished_at": state.finished_at, "top": top,
            "ranked": sum(1 for r in state.result.results if r.status == "ranked") if state.result else None,
            "candidates": len(state.result.results) if state.result else None,
        }

    # ------------------------------------------------------------------ running
    def start(self, job_id: str, mode: str) -> RunState:
        state = RunState(run_id=new_run_id(job_id), job_id=job_id, mode=mode)
        self._runs[state.run_id] = state
        task = asyncio.create_task(self._run(state))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return state

    async def _run(self, state: RunState) -> None:
        async def on_event(event: dict) -> None:
            self._on_event(state, event)

        try:
            state.result = await run_recruitment_workflow(
                state.job_id, mode=state.mode, emit=on_event, run_id=state.run_id)
            state.status = "done"
        except LLMError as exc:
            self._fail(state, "llm_error", str(exc))
        except ValueError as exc:
            self._fail(state, "invalid_request", str(exc))
        except Exception as exc:  # never let a background task die silently
            self._fail(state, "workflow_error", f"{type(exc).__name__}: {exc}")
        finally:
            state.finished_at = _now()

    def _fail(self, state: RunState, code: str, message: str) -> None:
        state.status, state.error_code, state.error = "failed", code, message
        for st in state.stages.values():
            if st.status == "running":
                st.status = "failed"

    def _on_event(self, state: RunState, event: dict) -> None:
        state.events.append({**event, "at": _now()})
        del state.events[:-MAX_EVENTS]
        stage = state.stages.get(event["stage"])
        if stage is None:            # e.g. the final "workflow" event
            return
        key = (state.run_id, event["stage"])
        if event["status"] == "started":
            stage.status, stage.detail = "running", event["detail"]
            self._stage_started[key] = time.perf_counter()
        elif event["status"] == "progress":
            stage.detail = event["detail"]
        elif event["status"] in ("done", "failed"):
            stage.status = event["status"]
            stage.detail = event["detail"]
            t0 = self._stage_started.pop(key, None)
            stage.seconds = round(time.perf_counter() - t0, 3) if t0 else None

    @staticmethod
    def _from_result(res: WorkflowResult) -> RunState:
        stages = {s: StageState(status=res.stage_status.get(s, "pending"), seconds=res.stage_timings.get(s))
                  for s in STAGE_ORDER}
        return RunState(run_id=res.run_id, job_id=res.job.job_id, mode=res.mode, status="done",
                        started_at=_run_started_from_id(res.run_id), finished_at=None,
                        stages=stages, result=res)


def _run_started_from_id(run_id: str) -> str:
    """Saved runs keep their start time inside the id: J1-20261020-194100-a3f9."""
    try:
        parts = run_id.split("-")
        dt = datetime.strptime(parts[1] + parts[2], "%Y%m%d%H%M%S")
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (IndexError, ValueError):
        return "1970-01-01T00:00:00+00:00"
