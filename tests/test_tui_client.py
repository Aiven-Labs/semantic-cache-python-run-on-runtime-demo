import asyncio
import json

import httpx
import pytest
from test_details import CANDIDATE, FakeCatalog, detail

from semcache.tui_client import (
    ScoutClient,
    ScoutError,
    cost_line,
    detail_markdown,
    filter_repos,
    meta_line,
    repo_row,
    result_row,
    search_status,
    sort_results,
)


def client(handler):
    http = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    return ScoutClient("http://t", client=http)


def run(coro):
    return asyncio.run(coro)


# ---- HTTP client ------------------------------------------------------------------------------
def test_search_sends_the_query_and_parses_json():
    seen = {}

    def handler(req):
        seen.update(path=req.url.path, params=dict(req.url.params))
        return httpx.Response(200, json={"results": [], "cache_hit": None, "crawled": 3})

    out = run(client(handler).search("feature flags", sort="stars", refresh=True))
    assert out["crawled"] == 3
    assert seen == {
        "path": "/api/search",
        "params": {"q": "feature flags", "sort": "stars", "refresh": "true"},
    }


def test_http_errors_become_readable_messages():
    c = client(lambda r: httpx.Response(404, json={"detail": "x/y is not in the index"}))
    with pytest.raises(ScoutError, match="not in the index"):
        run(c.repo("x/y"))
    c = client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(ScoutError, match="HTTP 500"):
        run(c.repos())


def test_unreachable_server_says_how_to_start_it():
    def refuse(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(ScoutError, match="Is the app running"):
        run(client(refuse).repos())


def test_manifest_uses_your_username_for_a_fork():
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json={"text": "{}", "warnings": []})

    c = client(handler)
    run(c.manifest("o/r"))
    c.user = "kjaymiller"
    run(c.manifest("o/r"))
    assert seen == [{"repo": "o/r"}, {"repo": "o/r", "owner": "kjaymiller"}]


def test_chat_streams_events_in_order():
    events = [{"type": "meta", "route": "x"}, {"type": "token", "t": "hi"}, {"type": "done"}]
    body = "".join(json.dumps(e) + "\n" for e in events)

    async def collect(c):
        return [e async for e in c.chat("cid-12345678", "hello")]

    got = run(collect(client(lambda r: httpx.Response(200, content=body))))
    assert [e["type"] for e in got] == ["meta", "token", "done"]


def test_chat_error_status_is_reported():
    async def collect(c):
        return [e async for e in c.chat("cid-12345678", "hello")]

    with pytest.raises(ScoutError, match="HTTP 400"):
        run(collect(client(lambda r: httpx.Response(400, json={"detail": "bad"}))))


def test_debug_report_404_is_a_friendly_message():
    with pytest.raises(ScoutError, match="Nothing to report yet"):
        run(client(lambda r: httpx.Response(404)).debug_report("cid-12345678"))
    assert (
        run(client(lambda r: httpx.Response(200, text="# report")).debug_report("c")) == "# report"
    )


# ---- formatting -------------------------------------------------------------------------------
REPO = {"name": "a/b", "stars": 13987, "language": "Go", "services": ["postgresql", "valkey"],
        "compose": "image-only", "has_info": True, "has_root": False}  # fmt: skip


def test_rows():
    assert repo_row(REPO) == ("a/b", "13,987", "Go", "postgresql,valkey", "image only", "✓-")
    assert repo_row({**REPO, "services": [], "language": None})[2:4] == ("", "-")
    res = {
        "name": "a/b",
        "stars": 5,
        "match": 0.789,
        "novelty": 0.228,
        "services": [],
        "compose": "ready",
    }
    assert result_row(res) == ("a/b", "5", "0.79", "0.23", "-", "Compose+build")


def test_filter_matches_name_language_and_service():
    repos = [REPO, {**REPO, "name": "c/d", "language": "Rust", "services": ["kafka"]}]
    assert [r["name"] for r in filter_repos(repos, "RUST")] == ["c/d"]
    assert [r["name"] for r in filter_repos(repos, "valkey")] == ["a/b"]
    assert filter_repos(repos, "  ") == repos and filter_repos(repos, "nope") == []


def test_sorting_does_not_mutate_and_handles_unknown_sort():
    rs = [{"name": "a", "stars": 1, "match": 0.9, "novelty": 0.1},
          {"name": "b", "stars": 9, "match": 0.5, "novelty": 0.3}]  # fmt: skip
    assert [r["name"] for r in sort_results(rs, "stars")] == ["b", "a"]
    assert [r["name"] for r in sort_results(rs, "novelty")] == ["b", "a"]
    assert [r["name"] for r in sort_results(rs, "relevance")] == ["a", "b"]
    assert [r["name"] for r in sort_results(rs, "bogus")] == ["a", "b"]
    assert [r["name"] for r in rs] == ["a", "b"]


def test_search_status_tells_where_results_came_from():
    base = {"results": [1, 2], "cache_hit": None, "crawled": None, "notice": None}
    assert "GitHub searched: 30 repos" in search_status({**base, "crawled": 30})
    hit = {"query": "workflow", "distance": 0.031}
    assert "GitHub skipped" in search_status(
        {**base, "cache_hit": hit}
    ) and "0.031" in search_status({**base, "cache_hit": hit})
    assert search_status({**base, "notice": "GitHub search failed"}).endswith(
        "GitHub search failed"
    )


def test_cost_and_meta_lines():
    assert (
        cost_line({"usd": 0.0123, "saved_usd": 0.02, "saved_by": "routing"})
        == "cost $0.0123 · saved $0.0200 by routing"
    )
    assert (
        cost_line({"usd": 0.0}) == "cost $0"
        and cost_line({"usd": 0, "priced": False}) == "no price set"
    )
    ev = {"route": "agent", "distance": 0.3, "tier": "miss", "model": "m", "cached": True,
          "reason": "classifier: open-ended"}  # fmt: skip
    assert meta_line(ev) == "miss · m · route agent (classifier: open-ended) · cached answer"
    assert meta_line({**ev, "reason": "", "cached": False}) == "miss · m · route agent"


def test_detail_markdown_has_what_the_web_panel_has():
    d = detail()
    d["cache"]["compose_text"] = "\n".join(f"line {i}" for i in range(60))
    d["cache"]["has_compose"] = True
    md = detail_markdown(d, ["repo info: RuntimeError: GitHub rate limit reached"])
    for needle in ("# automatisch/automatisch", "13,987", "TypeScript", "**postgresql**", "Runtime-ready",
                   "builds from source: main, worker", "## Manifest entry", '"owner": "automatisch"',
                   "Press `m` to copy it.", "n8n (match", "o/other", "Could not load everything",
                   "Press `r` to retry", "… 20 more lines"):  # fmt: skip
        assert needle in md, needle


def test_detail_markdown_survives_hostile_and_sparse_data():
    d = detail(cand={"name": "o/old", "stars": "9", "services": "unknown", "buildable": "no compose"},
               catalog=FakeCatalog(has_vector=False))  # fmt: skip
    md = detail_markdown(d)
    assert "Services unknown" in md and "no Compose file found" in md
    d2 = detail(cand={**CANDIDATE, "description": "```` evil ```"})
    assert "evil" in detail_markdown(d2)  # backtick runs in data must not break the document
    fenced = detail_markdown({**d2, "manifest_text": "x ``` y"})
    assert "````" in fenced
