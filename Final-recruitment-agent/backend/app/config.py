"""Central configuration, read from environment variables (.env supported)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _path(value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else BACKEND_DIR / p


@dataclass(frozen=True)
class Settings:
    cv_dir: Path = _path(os.getenv("CV_DIR", "data/cvs"))
    jobs_source: str = os.getenv("JOBS_SOURCE", "data/jobs.csv")
    github_mode: str = os.getenv("GITHUB_MODE", "mock")  # "mock" | "live"
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_mock_file: Path = _path("data/github_mock.json")
    # LLM: free local models served by Ollama (no API key needed)
    llm_mode: str = os.getenv("LLM_MODE", "ollama")  # "ollama" | "mock" (no model needed, for tests/demo)
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "180"))      # seconds per request (CPU can be slow)
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2500"))   # hard cap on one model answer (stops runaway output)
    llm_concurrency: int = int(os.getenv("LLM_CONCURRENCY", "2"))    # parallel requests to the local model
    single_cv_timeout: float = float(os.getenv("SINGLE_CV_TIMEOUT", "300"))  # whole single-CV analysis, seconds
    max_upload_mb: float = float(os.getenv("MAX_UPLOAD_MB", "5"))
    outputs_dir: Path = _path("outputs")


settings = Settings()
