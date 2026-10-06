"""Everything a repo's details panel shows, read from Valkey only (never from GitHub)."""

import re
from datetime import date

from .compose import COMPOSE_LABELS, normalize_compose
from .manifest import EDIT_MANIFEST_URL, build_entry, fork_url, format_entry

_NOT_SERVICES = {"", "none", "unknown"}
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def valid_repo_parts(owner: str, name: str) -> bool:
    """GitHub-shaped names only; '.' and '..' are not valid names and could alter a URL path."""
    return all(_REPO.match(x) and set(x) != {"."} for x in (owner, name))


def _split(csv: str | None) -> list[str]:
    return [x for x in (csv or "").split(",") if x.strip()]


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_detail(c: dict, *, cache, catalog, today: date) -> dict:
    """View-model for one indexed project. `cache` is a RepoCache, `catalog` a Catalog."""
    name = c["name"]
    path = c.get("compose_path") or ""
    status = normalize_compose(c.get("buildable"))
    info = cache.peek("info", name, "")
    root = cache.peek("ls", name, "")
    compose_text = cache.peek("file", name, path) if path else None

    vec = catalog.vector("candidate", name)
    templates = catalog.search(vec, "template", k=3) if vec is not None else []
    similar = []
    if vec is not None:
        similar = [r for r in catalog.search(vec, "candidate", k=6) if r["name"] != name][:5]

    entry, warnings = build_entry(c, today)
    services = [s for s in _split(c.get("services")) if s not in _NOT_SERVICES]
    return {
        "name": name,
        "owner": name.split("/")[0],
        "url": c.get("url") or f"https://github.com/{name}",
        "fork_url": fork_url(name),
        "edit_manifest_url": EDIT_MANIFEST_URL,
        "description": c.get("description", ""),
        "stars": _int(c.get("stars")),
        "language": c.get("language", ""),
        "license": c.get("license", ""),
        "pushed": c.get("pushed", ""),
        "topics": _split(c.get("topics")),
        "services": services,
        "services_unknown": "unknown" in _split(c.get("services")),
        "compose_status": status,
        "compose_label": COMPOSE_LABELS[status],
        "compose_path": path,
        "app_services": _split(c.get("app_services")),
        "image_apps": _split(c.get("image_apps")),
        "novelty": _float(c.get("novelty")),
        "closest": c.get("closest", ""),
        "similar_templates": [
            {"name": t["name"], "distance": t["distance"], "description": t.get("description", "")}
            for t in templates
        ],
        "similar": [
            {"name": r["name"], "stars": _int(r.get("stars")), "distance": r["distance"]}
            for r in similar
        ],
        "manifest_text": format_entry(entry),
        "manifest_warnings": warnings,
        "cache": {
            "info": info,
            "root": root,
            "compose_text": compose_text,
            "has_info": info is not None,
            "has_root": root is not None,
            "has_compose": compose_text is not None,
            "compose_expected": bool(path),
        },
        "complete": info is not None
        and root is not None
        and (compose_text is not None or not path),
    }


def load_into_cache(
    c: dict, cache, *, list_dir, read_file, repo_info, token, detail_ttl
) -> list[str]:
    """Fill the cache from GitHub for one project. Returns human-readable errors (never raises)."""
    name, path = c["name"], c.get("compose_path") or ""
    errors: list[str] = []

    def step(label, kind, p, fetch, ttl=None):
        try:
            cache.get(kind, name, p, fetch, ttl=ttl)
        except Exception as e:  # rate limit, network, repo gone
            errors.append(f"{label}: {type(e).__name__}: {str(e)[:160]}")

    step("repo info", "info", "", lambda: repo_info(name, token=token), ttl=detail_ttl)
    step("root folder", "ls", "", lambda: list_dir(name, "", token=token), ttl=detail_ttl)
    if path:
        step("compose file", "file", path, lambda: read_file(name, path), ttl=detail_ttl)
    return errors


def group_alphabetical(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Sort by name (case-insensitive), group by first letter; digits and symbols go under '#'."""
    ordered = sorted(rows, key=lambda r: r.get("name", "").lower())
    groups: dict[str, list[dict]] = {}
    for r in ordered:
        first = r.get("name", "#")[:1].upper()
        groups.setdefault(first if first.isalpha() else "#", []).append(r)
    # '#' first, like a phone book; letters follow in order (dict preserves sorted insertion)
    return sorted(groups.items(), key=lambda kv: (kv[0] != "#", kv[0]))


def ensure_basics(
    c: dict, cache, *, list_dir, read_file, repo_info, token, detail_ttl, fail_ttl: int = 120
) -> list[str]:
    """Cache a project's basics the first time it is opened; later opens only read the cache.

    Missing pieces are fetched once and kept for `detail_ttl`. If GitHub fails (rate limit,
    network), the failure is remembered for `fail_ttl` seconds so reopening does not hammer a
    limited API.
    """
    name = c["name"]
    prior = cache.peek("fail", name, "")
    if prior:
        return list(prior)
    errors = load_into_cache(
        c, cache, list_dir=list_dir, read_file=read_file, repo_info=repo_info, token=token,
        detail_ttl=detail_ttl,
    )  # fmt: skip
    if errors:
        cache.put("fail", name, "", errors, ttl=fail_ttl)
    return errors
