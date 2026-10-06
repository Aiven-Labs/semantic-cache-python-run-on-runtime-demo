from datetime import date
from pathlib import Path

import numpy as np
import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from semcache.details import build_detail, load_into_cache, valid_repo_parts
from semcache.repocache import RepoCache

TEMPLATES = Path(__file__).parent.parent / "src" / "semcache" / "templates"
TODAY = date(2026, 10, 5)

CANDIDATE = {
    "name": "automatisch/automatisch", "description": "Open source Zapier alternative.",
    "stars": "13987", "language": "TypeScript", "license": "NOASSERTION", "pushed": "2026-09-30",
    "topics": "automation,zapier", "services": "postgresql,valkey", "buildable": "ready",
    "compose_path": "docker-compose.yml", "app_services": "main,worker", "image_apps": "",
    "novelty": "0.228", "closest": "n8n", "url": "https://github.com/automatisch/automatisch",
}  # fmt: skip


class FakeR:
    def __init__(self):
        self.d, self.ttl = {}, {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, ttl, v):
        self.d[k], self.ttl[k] = v, ttl


class FakeCatalog:
    """Stands in for Catalog: one stored vector and canned KNN results."""

    def __init__(self, has_vector=True):
        self.has_vector, self.calls = has_vector, []

    def vector(self, kind, ident):
        return np.zeros(2, dtype=np.float32) if self.has_vector else None

    def search(self, vec, kind, services=None, k=10):
        self.calls.append((kind, k))
        if kind == "template":
            return [{"name": "n8n", "distance": 0.2, "description": "workflow"}]
        return [
            {"name": "automatisch/automatisch", "stars": "1", "distance": 0.0},  # itself: dropped
            {"name": "o/other", "stars": "50", "distance": 0.3},
        ]


def detail(cache=None, catalog=None, cand=None):
    return build_detail(
        cand or CANDIDATE, cache=cache or RepoCache(FakeR(), 60), catalog=catalog or FakeCatalog(),
        today=TODAY,
    )  # fmt: skip


def render(**ctx):
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return env.get_template("repo_detail.html").render(all_services=["postgresql", "valkey"], **ctx)


def test_detail_comes_from_stored_fields():
    d = detail()
    assert d["stars"] == 13987 and d["language"] == "TypeScript" and d["pushed"] == "2026-09-30"
    assert d["services"] == ["postgresql", "valkey"] and d["topics"] == ["automation", "zapier"]
    assert d["compose_status"] == "ready" and d["app_services"] == ["main", "worker"]
    assert d["similar_templates"][0]["name"] == "n8n"
    assert [r["name"] for r in d["similar"]] == ["o/other"]  # never lists itself
    assert '"owner": "automatisch"' in d["manifest_text"]
    assert d["fork_url"].endswith("/automatisch/automatisch/fork")


def test_building_a_detail_never_writes_or_fetches():
    r = FakeR()
    detail(cache=RepoCache(r, 60))
    assert r.d == {} and r.ttl == {}  # reading the cache must not fill it


def test_reports_what_is_and_is_not_cached():
    cold = detail()
    assert (
        not cold["complete"] and not cold["cache"]["has_info"] and cold["cache"]["compose_expected"]
    )
    cache = RepoCache(FakeR(), 60)
    cache.put("info", "automatisch/automatisch", "", {"language": "TypeScript", "archived": False})
    cache.put("ls", "automatisch/automatisch", "", [{"name": "docker", "type": "dir", "size": 0}])
    partial = detail(cache=cache)
    assert partial["cache"]["has_info"] and partial["cache"]["has_root"] and not partial["complete"]
    cache.put("file", "automatisch/automatisch", "docker-compose.yml", "services: {}")
    full = detail(cache=cache)
    assert full["complete"] and full["cache"]["compose_text"] == "services: {}"


def test_no_compose_path_means_nothing_to_wait_for():
    cache = RepoCache(FakeR(), 60)
    cache.put("info", "o/r", "", {})
    cache.put("ls", "o/r", "", [])
    d = detail(
        cache=cache, cand={**CANDIDATE, "name": "o/r", "compose_path": "", "buildable": "none"}
    )
    assert d["complete"] and not d["cache"]["compose_expected"]


def test_old_entries_without_new_fields_still_render():
    sparse = {"name": "o/old", "stars": "9", "services": "unknown", "buildable": "no compose"}
    d = detail(cand=sparse, catalog=FakeCatalog(has_vector=False))
    assert d["compose_status"] == "none" and d["services"] == [] and d["services_unknown"]
    assert d["similar"] == [] and d["similar_templates"] == [] and d["topics"] == []
    assert "o/old" in render(d=d, errors=[])


def test_load_fills_the_cache_with_the_detail_ttl_and_reports_errors():
    cache = RepoCache(FakeR(), 3600)
    calls = []
    errors = load_into_cache(
        CANDIDATE, cache,
        list_dir=lambda repo, path, token=None: calls.append("ls") or [{"name": "a", "type": "file", "size": 1}],
        read_file=lambda repo, path: calls.append("file") or "services: {}",
        repo_info=lambda repo, token=None: calls.append("info") or {"language": "TypeScript"},
        token=None, detail_ttl=604800,
    )  # fmt: skip
    assert errors == [] and calls == ["info", "ls", "file"]
    compose_key = next(k for k in cache.r.ttl if ":file:" in k)
    assert cache.r.ttl[compose_key] == 604800  # the Compose file is kept for the long window
    assert detail(cache=cache)["complete"]

    def boom(*a, **k):
        raise RuntimeError("GitHub rate limit reached")

    bad = load_into_cache(
        CANDIDATE, RepoCache(FakeR(), 60), list_dir=boom, read_file=boom, repo_info=boom,
        token=None, detail_ttl=1,
    )  # fmt: skip
    assert len(bad) == 3 and all("rate limit" in e for e in bad)  # every step reported, none raised


def test_repo_cache_ttl_override_and_peek():
    c = RepoCache(FakeR(), 60)
    assert c.peek("ls", "a/b", "") is None
    assert c.get("ls", "a/b", "", lambda: [1], ttl=999) == [1]
    assert max(c.r.ttl.values()) == 999 and c.peek("ls", "a/b", "") == [1]
    with pytest.raises(ValueError):
        c.peek("ls", "a/b", "../x")


def test_repo_path_parts_are_validated():
    assert valid_repo_parts("automatisch", "automatisch") and valid_repo_parts("a.b", "c_d-e")
    for o, n in (("..", "x"), ("a b", "c"), ("a", "b/c"), ("", "x"), ("a;", "b"), ("x" * 101, "y")):
        assert not valid_repo_parts(o, n)


def test_panel_renders_the_facts_and_the_actions():
    d = detail()
    html = render(d=d, errors=[])
    for needle in (
        "automatisch/automatisch", "13,987", "TypeScript", "last push 2026-09-30",
        "Builds from source: main, worker", "docker-compose.yml", "n8n",
        'data-repo="automatisch/automatisch"', "Retry loading from GitHub",
        'hx-post="/repo/automatisch/automatisch/load"', "/chat?q=", "Edit manifest.json",
    ):  # fmt: skip
        assert needle in html, needle
    assert 'hx-get="/repo/o/other"' in html  # similar projects open in the same panel


def test_panel_escapes_hostile_content_from_repos():
    evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    cache = RepoCache(FakeR(), 60)
    cache.put("file", "automatisch/automatisch", "docker-compose.yml", f"services: {evil}")
    d = detail(cache=cache, cand={**CANDIDATE, "description": evil, "topics": evil})
    html = render(d=d, errors=[f"Boom: {evil}"])
    assert "<script>alert" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html


def test_panel_hides_the_load_button_once_everything_is_cached():
    cache = RepoCache(FakeR(), 60)
    cache.put("info", "automatisch/automatisch", "", {"language": "TS", "archived": False})
    cache.put("ls", "automatisch/automatisch", "", [])
    cache.put("file", "automatisch/automatisch", "docker-compose.yml", "x")
    assert "Retry loading" not in render(d=detail(cache=cache), errors=[])


def test_missing_repo_message():
    assert "is not in the index" in render(missing="nobody/nothing")
