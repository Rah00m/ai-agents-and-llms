"""Retriever #3: public GitHub activity per candidate (live API or offline mock)."""
from __future__ import annotations
import asyncio
import json
from collections import Counter
import httpx

from app.config import settings
from app.models import GitHubProfile

API = "https://api.github.com"


def _load_mock() -> dict:
    try:
        return json.loads(settings.github_mock_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _from_repos(username: str, repos: list[dict], source: str) -> GitHubProfile:
    langs = Counter(r["language"] for r in repos if r.get("language"))
    notable = sorted(repos, key=lambda r: r.get("stars", 0), reverse=True)[:3]
    return GitHubProfile(
        username=username,
        public_repos=len(repos),
        top_languages=[l for l, _ in langs.most_common(3)],
        notable_repos=[
            {"name": r["name"], "language": r.get("language"), "stars": r.get("stars", 0),
             "description": r.get("description", "")}
            for r in notable
        ],
        source=source,
    )


async def _fetch_live(client: httpx.AsyncClient, username: str) -> GitHubProfile:
    resp = await client.get(f"{API}/users/{username}/repos", params={"per_page": 30, "sort": "pushed"})
    resp.raise_for_status()
    repos = [
        {"name": r["name"], "language": r["language"], "stars": r["stargazers_count"],
         "description": r["description"] or ""}
        for r in resp.json() if not r["fork"]
    ]
    return _from_repos(username, repos, "live")


async def retrieve_github(
    usernames: list[str],
    *,
    mode: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, GitHubProfile], list[str]]:
    """One concurrent lookup per username.

    mode "live": real GitHub API. A failed lookup is reported and the profile is marked
                 'unavailable'. It is NEVER replaced by sample data.
    mode "mock": offline sample data from data/github_mock.json (profiles are marked source='mock').
    """
    mode = mode or settings.github_mode
    mock = _load_mock() if mode != "live" else {}
    errors: list[str] = []
    profiles: dict[str, GitHubProfile] = {}

    async def one(client: httpx.AsyncClient | None, username: str) -> None:
        if client is not None:
            try:
                profiles[username] = await _fetch_live(client, username)
            except Exception as exc:
                errors.append(f"GitHub live lookup failed for '{username}': {exc}")
                profiles[username] = GitHubProfile(username=username, source="unavailable")
        elif username in mock:
            profiles[username] = _from_repos(username, mock[username]["repos"], "mock")
        else:
            profiles[username] = GitHubProfile(username=username, source="unavailable")

    if mode == "live":
        headers = {"Accept": "application/vnd.github+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        client_kwargs = {"headers": headers, "timeout": 15}
        if transport is not None:
            client_kwargs["transport"] = transport

        async with httpx.AsyncClient(**client_kwargs) as client:
            await asyncio.gather(*(one(client, u) for u in usernames))
    else:
        await asyncio.gather(*(one(None, u) for u in usernames))

    return profiles, errors