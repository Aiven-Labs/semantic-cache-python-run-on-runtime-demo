from pathlib import Path

import httpx
import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from semcache.catalog import Catalog
from semcache.details import ensure_basics, group_alphabetical
from semcache.github import info_from_item, repo_info
from semcache.repocache import RepoCache

TEMPLATES = Path(__file__).parent.parent / "src" / "semcache" / "templates"


# ---- alphabetical list ------------------------------------------------------------------------
def names(groups):
    return [(g, [r["name"] for r in rows]) for g, rows in groups]


def test_sorted_case_insensitively_and_grouped_by_letter():
    rows = [{"name": n} for n in ("zed/Zulu", "acme/b", "Acme/a", "beta/x", "alpha/y")]
    # sorted by the whole 'owner/name', ignoring case: Acme/a < acme/b < alpha/y < beta/x < zed/Zulu
    assert names(group_alphabetical(rows)) == [
        ("A", ["Acme/a", "acme/b", "alpha/y"]),
        ("B", ["beta/x"]),
        ("Z", ["zed/Zulu"]),
    ]


def test_digits_and_symbols_group_first_under_hash():
    rows = [
        {"name": "zeta/z"},
        {"name": "3d-tools/viewer"},
        {"name": "_under/score"},
        {"name": "a/a"},
    ]
    got = names(group_alphabetical(rows))
    assert [g for g, _ in got] == ["#", "A", "Z"]
    assert got[0][1] == ["3d-tools/viewer", "_under/score"]


def test_empty_list():
    assert group_alphabetical([]) == []


class PagedR:
    """Fake Valkey that serves FT.SEARCH pages from a fixed list of documents."""

    def __init__(self, total):
        self.total, self.calls = total, []

    def execute_command(self, *args):
        offset, num = int(args[args.index("LIMIT") + 1]), int(args[args.index("LIMIT") + 2])
        self.calls.append((offset, num))
        out: list = [self.total]
        for i in range(offset, min(offset + num, self.total)):
            out += [f"k{i}".encode(), [b"name", f"o/r{i:04d}".encode()]]
        return out


@pytest.mark.parametrize("total", [0, 1, 199, 200, 201, 450])
def test_list_all_pages_through_everything(total):
    cat = Catalog(PagedR(total), index="i", prefix="p:", dim=2)
    rows = cat.list_all("candidate", page=200)
    assert len(rows) == total and len({r["name"] for r in rows}) == total  # nothing lost or doubled


def test_list_all_stops_at_the_safety_cap():
    cat = Catalog(PagedR(10_000), index="i", prefix="p:", dim=2)
    assert len(cat.list_all("candidate", page=200, max_rows=600)) == 600


# ---- basic info cached for free ---------------------------------------------------------------
ITEM = {
    "full_name": "gethomepage/homepage", "description": "A start page.", "language": "JavaScript",
    "license": {"spdx_id": "GPL-3.0"}, "stargazers_count": 32985, "pushed_at": "2026-10-05T12:00:00Z",
    "archived": False, "topics": ["docker", "nextjs"],
}  # fmt: skip


def test_search_result_carries_all_the_basic_info():
    info = info_from_item(ITEM)
    assert info == {
        "repo": "gethomepage/homepage", "description": "A start page.", "language": "JavaScript",
        "license": "GPL-3.0", "stars": 32985, "last_push": "2026-10-05", "archived": False,
        "topics": ["docker", "nextjs"],
    }  # fmt: skip
    sparse = info_from_item({"full_name": "o/r", "license": {"spdx_id": "NOASSERTION"}})
    assert (
        sparse["language"] == "unknown" and sparse["license"] == "unknown" and sparse["stars"] == 0
    )


def test_the_free_info_has_the_same_shape_as_the_api_call():
    api = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=ITEM)))
    assert repo_info("gethomepage/homepage", client=api) == info_from_item(ITEM)


# ---- first open caches, later opens read ------------------------------------------------------
class FakeR:
    def __init__(self):
        self.d, self.ttl = {}, {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, ttl, v):
        self.d[k], self.ttl[k] = v, ttl

    def delete(self, k):
        self.d.pop(k, None)


CAND = {"name": "o/r", "compose_path": ""}


def fetchers(counter, fail=False):
    def boom():
        raise RuntimeError("GitHub rate limit reached")

    def mk(label, value):
        def f(*a, **k):
            counter.append(label)
            if fail:
                boom()
            return value

        return f

    return dict(
        list_dir=mk("ls", [{"name": "Dockerfile", "type": "file", "size": 1}]),
        read_file=mk("file", "x"),
        repo_info=mk("info", {"language": "Go"}),
        token=None,
        detail_ttl=604800,
    )


def test_first_open_fetches_once_then_it_is_all_cache():
    cache, calls = RepoCache(FakeR(), 3600), []
    assert ensure_basics(CAND, cache, **fetchers(calls)) == []
    assert sorted(calls) == ["info", "ls"]
    assert set(cache.r.ttl.values()) == {604800}  # kept for the long window, not the 1 h one
    assert ensure_basics(CAND, cache, **fetchers(calls)) == []
    assert sorted(calls) == ["info", "ls"]  # second open: zero new GitHub calls


def test_info_cached_at_search_time_is_not_fetched_again():
    cache, calls = RepoCache(FakeR(), 3600), []
    cache.put("info", "o/r", "", info_from_item(ITEM), ttl=604800)  # what the crawl stores
    ensure_basics(CAND, cache, **fetchers(calls))
    assert calls == ["ls"]  # only the root folder, which needs the API


def test_a_failure_is_remembered_so_reopening_does_not_hammer_github():
    cache, calls = RepoCache(FakeR(), 3600), []
    first = ensure_basics(CAND, cache, **fetchers(calls, fail=True), fail_ttl=120)
    assert len(first) == 2 and all("rate limit" in e for e in first)
    n = len(calls)
    again = ensure_basics(CAND, cache, **fetchers(calls, fail=True))
    assert again == first and len(calls) == n  # served from the failure note: no new calls
    fail_key = next(k for k in cache.r.ttl if ":fail:" in k)
    assert cache.r.ttl[fail_key] == 120
    cache.forget("fail", "o/r")  # what the Retry button does
    before = len(calls)
    assert ensure_basics(CAND, cache, **fetchers(calls)) == []  # succeeds now
    assert sorted(calls[before:]) == ["info", "ls"]  # exactly the two missing pieces were fetched


# ---- the page -----------------------------------------------------------------------------------
def render_repos(**ctx):
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return env.get_template("repos.html").render(all_services=["postgresql", "valkey"], **ctx)


def row(name, **kw):
    base = {"name": name, "stars": 5, "language": "Go", "services": "postgresql", "compose": "ready",
            "has_info": True, "has_root": False}  # fmt: skip
    return {**base, **kw}


def test_repos_page_lists_a_to_z_with_cache_state():
    groups = group_alphabetical([row("zed/z"), row("acme/a", has_root=True), row("acme/b")])
    html = render_repos(groups=groups, total=3, with_basics=1)
    assert html.index("acme/a") < html.index("acme/b") < html.index("zed/z")
    assert (
        '<strong id="count">3</strong> repos cached' in html and "1 with their basic info" in html
    )
    assert 'href="#L-A"' in html and 'href="#L-Z"' in html
    assert 'hx-get="/repo/acme/a"' in html  # rows open the same drawer
    assert 'id="drawer"' in html  # the shared drawer is on this page too


def test_repos_page_escapes_hostile_names_and_handles_empty():
    evil = '"><script>alert(1)</script>'
    html = render_repos(groups=group_alphabetical([row(f"o/{evil}")]), total=1, with_basics=0)
    assert "<script>alert(1)" not in html
    assert "Nothing is cached yet" in render_repos(groups=[], total=0, with_basics=0)
