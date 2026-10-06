import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from .compose import COMPOSE_PATHS, ComposeInfo, analyze


@dataclass
class Repo:
    full_name: str
    description: str
    url: str
    stars: int
    topics: list[str]
    compose: ComposeInfo | None  # None: no parseable Compose file found
    language: str = ""
    license: str = ""
    pushed_at: str = ""  # date of the last push, YYYY-MM-DD
    info: dict = field(default_factory=dict)  # basic info, same shape repo_info() returns


def info_from_item(d: dict) -> dict:
    """Basic repo info from a GitHub repo object: a search result carries all of this for free."""
    return {
        "repo": d["full_name"],
        "description": d.get("description") or "",
        "language": d.get("language") or "unknown",
        "license": ((d.get("license") or {}).get("spdx_id") or "unknown").replace(
            "NOASSERTION", "unknown"
        ),
        "stars": d.get("stargazers_count", 0),
        "last_push": (d.get("pushed_at") or "")[:10],
        "archived": d.get("archived", False),
        "topics": d.get("topics", []),
    }


def truncate_text(text: str, max_bytes: int = 20_000) -> str:
    """Same shape read_file returns: the first max_bytes, plus a marker if it was cut."""
    data = text.encode("utf-8", "replace")
    if len(data) <= max_bytes:
        return text
    return data[:max_bytes].decode("utf-8", "replace") + f"\n...[truncated at {max_bytes} bytes]"


def _headers(token: str | None) -> dict:
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _fetch_compose(client: httpx.Client, full_name: str, branch: str) -> ComposeInfo | None:
    for path in COMPOSE_PATHS:
        try:
            r = client.get(f"https://raw.githubusercontent.com/{full_name}/{branch}/{path}")
        except httpx.HTTPError:  # one slow or failed file must not fail the whole search
            continue
        if r.status_code == 200:
            info = analyze(r.text)
            if info is not None:
                info.path, info.raw = path, truncate_text(r.text)
            return info
    return None


def discover(query: str, *, token: str | None, limit: int = 30) -> list[Repo]:
    """Most-starred GitHub repos matching `query`, each checked for a Compose file."""
    with httpx.Client(timeout=15, headers=_headers(token)) as client:
        r = client.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"{query} stars:>100 archived:false",
                "sort": "stars",
                "order": "desc",
                "per_page": limit,
            },
        )
        r.raise_for_status()
        items = r.json().get("items", [])

        def one(item: dict) -> Repo:
            return Repo(
                full_name=item["full_name"],
                description=item.get("description") or "",
                url=item["html_url"],
                stars=item.get("stargazers_count", 0),
                topics=item.get("topics", []),
                compose=_fetch_compose(client, item["full_name"], item["default_branch"]),
                language=item.get("language") or "",
                license=((item.get("license") or {}).get("spdx_id") or "").replace(
                    "NOASSERTION", ""
                ),
                pushed_at=(item.get("pushed_at") or "")[:10],
                info=info_from_item(item),
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            return list(pool.map(one, items))


_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_PATH = re.compile(r"^[A-Za-z0-9_./@+ -]{0,300}$")
MAX_FILE_BYTES = 20_000
MAX_LISTING = 100


def _check(repo: str, path: str) -> str:
    """Validate model-supplied input before it goes into a URL. Returns the cleaned path."""
    if not _REPO.match(repo or "") or any(set(part) == {"."} for part in repo.split("/")):
        raise ValueError("repo must look like owner/name")
    path = (path or "").strip().strip("/")
    if not _PATH.match(path) or ".." in path.split("/"):
        raise ValueError("invalid path")
    return path


clean = _check  # public name: validate and normalize (repo, path) before building a cache key


def list_dir(repo: str, path: str = "", *, token: str | None = None, client=None) -> list[dict]:
    """Files and folders at `path` in a public repo's default branch (1 GitHub API call)."""
    path = _check(repo, path)
    own = client is None
    client = client or httpx.Client(timeout=15, headers=_headers(token))
    try:
        r = client.get(f"https://api.github.com/repos/{repo}/contents/{quote(path)}")
        if r.status_code == 404:
            raise ValueError(f"not found: {repo}/{path}".rstrip("/"))
        if r.status_code in (403, 429):
            raise RuntimeError("GitHub rate limit reached; set GITHUB_TOKEN for a higher limit")
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            client.close()
    items = data if isinstance(data, list) else [data]
    rows = [
        {
            "name": i["name"],
            "type": "dir" if i["type"] == "dir" else "file",
            "size": i.get("size", 0),
        }
        for i in items
    ]
    rows.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    return rows[:MAX_LISTING]


def read_file(repo: str, path: str, *, client=None, max_bytes: int = MAX_FILE_BYTES) -> str:
    """First `max_bytes` of a text file from a public repo's default branch.

    Uses raw.githubusercontent.com, which does not count against the API rate limit. No
    credentials are sent to it.
    """
    path = _check(repo, path)
    if not path:
        raise ValueError("path is required")
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        with client.stream(
            "GET", f"https://raw.githubusercontent.com/{repo}/HEAD/{quote(path)}"
        ) as r:
            if r.status_code == 404:
                raise ValueError(f"file not found: {repo}/{path}")
            r.raise_for_status()
            data = b""
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > max_bytes:
                    break
    finally:
        if own:
            client.close()
    if b"\0" in data[:2000]:
        return "(binary file, not shown)"
    text = data[:max_bytes].decode("utf-8", "replace")
    if len(data) > max_bytes:
        text += f"\n...[truncated at {max_bytes} bytes]"
    return text


def repo_info(repo: str, *, token: str | None = None, client=None) -> dict:
    """Language, license, stars, last push and topics for one repo (1 GitHub API call)."""
    _check(repo, "")
    own = client is None
    client = client or httpx.Client(timeout=15, headers=_headers(token))
    try:
        r = client.get(f"https://api.github.com/repos/{repo}")
        if r.status_code == 404:
            raise ValueError(f"not found: {repo}")
        if r.status_code in (403, 429):
            raise RuntimeError("GitHub rate limit reached; set GITHUB_TOKEN for a higher limit")
        r.raise_for_status()
        d = r.json()
    finally:
        if own:
            client.close()
    return info_from_item(d)
