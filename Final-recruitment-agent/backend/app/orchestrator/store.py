"""Save / load finished workflow runs as JSON files (used by the Day-3 API)."""
from pathlib import Path

from app.config import settings
from app.models import WorkflowResult


def runs_dir() -> Path:
    d = settings.outputs_dir / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_run(result: WorkflowResult) -> Path:
    path = runs_dir() / f"{result.run_id}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(run_id: str) -> WorkflowResult:
    if not run_id.replace("-", "").replace("_", "").isalnum():   # no path tricks like ../
        raise ValueError(f"Invalid run id: {run_id!r}")
    path = runs_dir() / f"{run_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No saved run '{run_id}'")
    return WorkflowResult.model_validate_json(path.read_text(encoding="utf-8"))


def list_runs() -> list[str]:
    return sorted((p.stem for p in runs_dir().glob("*.json")), reverse=True)
