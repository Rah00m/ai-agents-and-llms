"""Retriever #2: job requirements from a CSV file or a published Google Sheet."""
import asyncio
import csv
import io
from pathlib import Path

import httpx

from app.config import BACKEND_DIR
from app.models import JobRequirement


def _split(value: str) -> list[str]:
    return [s.strip() for s in (value or "").split(";") if s.strip()]


def _rows_to_jobs(text: str) -> list[JobRequirement]:
    reader = csv.DictReader(io.StringIO(text))
    jobs = []
    for row in reader:
        jobs.append(
            JobRequirement(
                job_id=row["job_id"].strip(),
                title=row["title"].strip(),
                required_skills=_split(row["required_skills"]),
                preferred_skills=_split(row.get("preferred_skills", "")),
                min_years_experience=int(row.get("min_years_experience") or 0),
                description=(row.get("description") or "").strip(),
            )
        )
    return jobs


async def retrieve_jobs(source: str) -> tuple[list[JobRequirement], list[str]]:
    """`source` is either a local CSV path or an http(s) Google Sheets CSV-export URL."""
    try:
        if source.startswith("http"):
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                resp = await client.get(source)
                resp.raise_for_status()
                text = resp.text
        else:
            p = Path(source)
            p = p if p.is_absolute() else BACKEND_DIR / p
            text = await asyncio.to_thread(p.read_text, encoding="utf-8")
        return _rows_to_jobs(text), []
    except Exception as exc:  # network, missing file, bad columns...
        return [], [f"Jobs source '{source}': {exc}"]
