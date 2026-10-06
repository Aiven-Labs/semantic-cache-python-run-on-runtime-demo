"""A ready-to-paste entry for the templates.aiven.io directory (data/manifest.json).

Mirrors the schema in the runs-on-runtime repo (schema.py): `extra="forbid"`, so a typo'd key
fails there at build time. Keep this in sync with that file; a test checks it when the repo is
checked out next to this one.
"""

import json
import re
from datetime import date

from pydantic import BaseModel, ConfigDict

from .compose import IMAGE_ONLY, NONE, normalize_compose

DIRECTORY_REPO = "Aiven-Labs/runs-on-runtime"
# GitHub's web editor on this file forks the repo and opens the pull request form (CONTRIBUTING.md).
EDIT_MANIFEST_URL = f"https://github.com/{DIRECTORY_REPO}/edit/main/data/manifest.json"
MAX_TOPICS = 6
_USER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")  # GitHub username rules
_NOT_TOPICS = {"", "none", "unknown"}


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    owner: str
    repo: str
    added: date
    branch: str | None = None
    description: str | None = None
    logo: str | None = None
    topics: list[str] = []
    website: str | None = None


def display_name(repo: str) -> str:
    """'flow-ctl' -> 'Flow Ctl'. A starting point: names like 'n8n' or 'LiteLLM' are hand-edited."""
    words = [w for w in re.split(r"[-_.]+", repo) if w]
    if any(c.isupper() for c in repo):
        return " ".join(words)
    return " ".join(w.capitalize() for w in words)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")


def topics_for(repo: str, services: str, github_topics: str) -> list[str]:
    """App name first, then Aiven services, then GitHub tags (the order existing entries use)."""
    out: list[str] = []
    for raw in [repo, *(services or "").split(","), *(github_topics or "").split(",")]:
        t = _slug(raw.strip())
        if t not in _NOT_TOPICS and t not in out:
            out.append(t)
    return out[:MAX_TOPICS]


def fork_url(full_name: str) -> str:
    return f"https://github.com/{full_name}/fork"


def build_entry(candidate: dict, today: date, owner: str | None = None) -> tuple[dict, list[str]]:
    """Entry dict (validated) plus warnings about things to check before submitting.

    `owner` is your GitHub username: after you fork, the entry should point at your fork.
    """
    if owner is not None and not _USER.match(owner):
        raise ValueError(f"{owner!r} is not a valid GitHub username")
    full = candidate.get("name", "")
    if full.count("/") != 1:
        raise ValueError(f"expected owner/name, got {full!r}")
    upstream_owner, repo = full.split("/")
    owner = owner or upstream_owner
    desc = " ".join((candidate.get("description") or "").split())
    entry = ManifestEntry(
        name=display_name(repo),
        owner=owner,
        repo=repo,
        added=today,
        description=desc[:200] or None,
        topics=topics_for(repo, candidate.get("services", ""), candidate.get("topics", "")),
    ).model_dump(mode="json", exclude_none=True)
    if not entry["topics"]:
        entry.pop("topics")

    warnings: list[str] = []
    status = normalize_compose(candidate.get("buildable"))
    if status == IMAGE_ONLY:
        warnings.append(
            "Its Compose app uses image: only, so it needs a Dockerfile to run on Runtime."
        )
    elif status == NONE:
        warnings.append(
            "No Compose file was found; the repo may not be deployable on Runtime as is."
        )
    if owner != upstream_owner:
        warnings.append(
            f"Points at your fork {owner}/{repo}: fork {full} first, then make your changes."
        )
    else:
        warnings.append(f"Points at {full}. Fork it to change it, then set your username above.")
    return entry, warnings


def format_entry(entry: dict) -> str:
    """Text to paste into the array: 2-space indent and one-line topics, like the file itself."""
    lines = []
    for key, value in entry.items():
        rendered = json.dumps(value, ensure_ascii=False)  # lists stay on one line
        lines.append(f'    "{key}": {rendered}')
    return "  {\n" + ",\n".join(lines) + "\n  }"
