"""Drives the real Textual app headlessly against a fake server (no network, no terminal)."""

import asyncio
import json

import httpx
import pytest

pytest.importorskip("textual")

from test_details import detail  # noqa: E402
from textual.widgets import DataTable, Input, Markdown, Static  # noqa: E402

from semcache.tui import ScoutApp  # noqa: E402
from semcache.tui_client import ScoutClient  # noqa: E402

DETAIL = detail()
REPOS = [
    {"name": "acme/zeta", "stars": 5, "language": "Go", "services": ["kafka"], "compose": "ready",
     "has_info": True, "has_root": True},
    {"name": "automatisch/automatisch", "stars": 13987, "language": "TypeScript",
     "services": ["postgresql", "valkey"], "compose": "ready", "has_info": True, "has_root": False},
    {"name": "beta/tool", "stars": 90, "language": "Rust", "services": [], "compose": "none",
     "has_info": False, "has_root": False},
]  # fmt: skip
RESULTS = [
    {"name": "low/relevance-high-stars", "url": "u", "description": "", "stars": 9000,
     "language": "Go", "services": ["postgresql"], "compose": "ready", "novelty": 0.10,
     "closest": "n8n", "match": 0.50},
    {"name": "top/relevance", "url": "u", "description": "", "stars": 10, "language": "Go",
     "services": [], "compose": "image-only", "novelty": 0.40, "closest": "n8n", "match": 0.95},
]  # fmt: skip


def ndjson(*events):
    return "".join(json.dumps(e) + "\n" for e in events)


class Server:
    """A fake of the web app's API that records every request."""

    def __init__(self):
        self.calls, self.down, self.chat_bodies = [], False, []
        self.chat_events = [
            {"type": "meta", "route": "agent", "distance": 0.3, "tier": "miss", "model": "m",
             "cached": False, "reason": "classifier: open-ended"},
            {"type": "tool", "name": "search", "args": {"query": "dashboards", "where": "github"}},
            {"type": "tool_result", "name": "search", "ok": True, "preview": "ok"},
            {"type": "reset"},
            {"type": "token", "t": "Hello "},
            {"type": "token", "t": "**world**"},
            {"type": "cost", "usd": 0.0123, "saved_usd": 0.01, "saved_by": "routing", "priced": True},
            {"type": "suggestions", "items": ["Look at the files in a/b", "Compare a/b and c/d"]},
            {"type": "done"},
        ]  # fmt: skip

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path, dict(req.url.params)))
        if self.down:
            raise httpx.ConnectError("refused", request=req)
        p = req.url.path
        if p == "/api/repos":
            done = sum(1 for r in REPOS if r["has_info"] and r["has_root"])
            return httpx.Response(
                200, json={"total": len(REPOS), "with_basics": done, "repos": REPOS}
            )
        if p == "/api/search":
            return httpx.Response(200, json={"q": "x", "results": RESULTS, "crawled": 30,
                                             "cache_hit": None, "notice": None})  # fmt: skip
        if p.startswith("/api/repo/"):
            return httpx.Response(200, json={"detail": DETAIL, "errors": []})
        if p == "/manifest-entry":
            return httpx.Response(200, json={"text": "  {MANIFEST}", "warnings": ["w1"]})
        if p == "/chat/send":
            self.chat_bodies.append(json.loads(req.content))
            return httpx.Response(200, content=ndjson(*self.chat_events))
        if p.startswith("/chat/debug/"):
            return httpx.Response(200, text="# debug report")
        if p == "/chat/starters":
            return httpx.Response(200, json=["s"])
        return httpx.Response(404, json={"detail": "nope"})

    def paths(self, prefix=""):
        return [c for c in self.calls if c[1].startswith(prefix)]


def make(server, user=""):
    http = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(server.handler))
    app = ScoutApp(ScoutClient("http://t", user=user, client=http))
    app.copied, app.opened = [], []
    app.copy_text = lambda text: (app.copied.append(text), "test clipboard")[1]
    app.open_url = app.opened.append
    return app


async def settle(app, pilot):
    for _ in range(3):
        await pilot.pause()
        await app.workers.wait_for_complete()
    await pilot.pause()


def text_of(widget) -> str:
    return str(getattr(widget, "renderable", None) or getattr(widget, "content", ""))


def names(app, table_id):
    t = app.query_one(table_id, DataTable)
    return [str(k.value) for k in t.rows]


def scenario(coro_fn, server=None, **kw):
    server = server or Server()

    async def go():
        app = make(server, **kw)
        async with app.run_test(size=(160, 45)) as pilot:
            await settle(app, pilot)
            await coro_fn(app, pilot, server)

    asyncio.run(go())


# ---- startup and repos tab ----------------------------------------------------------------------
def test_starts_on_search_with_the_repo_list_loaded_a_to_z():
    async def t(app, pilot, server):
        assert app.active_tab() == "search"  # loading the repos must not steal focus to its tab
        assert names(app, "#repo-table") == ["acme/zeta", "automatisch/automatisch", "beta/tool"]
        assert "3 of 3 repos" in text_of(app.query_one("#repos-status"))
        assert "1 with basics" in text_of(app.query_one("#repos-status"))

    scenario(t)


def test_filter_narrows_the_list_and_clearing_restores_it():
    async def t(app, pilot, server):
        await pilot.press("f2")
        await settle(app, pilot)
        box = app.query_one("#filter", Input)
        box.value = "valkey"
        await settle(app, pilot)
        assert names(app, "#repo-table") == ["automatisch/automatisch"]
        box.value = ""
        await settle(app, pilot)
        assert len(names(app, "#repo-table")) == 3

    scenario(t)


def test_moving_the_cursor_never_calls_the_detail_endpoint_but_enter_does():
    async def t(app, pilot, server):
        await pilot.press("f2")
        app.query_one("#repo-table").focus()
        await settle(app, pilot)
        await pilot.press("down", "down", "up")
        await settle(app, pilot)
        assert server.paths("/api/repo/") == []  # a first open can call GitHub: never on hover
        await pilot.press("enter")
        await settle(app, pilot)
        assert [c[1] for c in server.paths("/api/repo/")] == ["/api/repo/automatisch/automatisch"]
        assert app.current["name"] == "automatisch/automatisch"
        md = app.query_one("#repos-detail", Markdown).source
        assert "# automatisch/automatisch" in md and "## Manifest entry" in md

    scenario(t)


# ---- actions on the opened repo -----------------------------------------------------------------
async def open_first(app, pilot):
    await pilot.press("f2")
    app.query_one("#repo-table").focus()
    await settle(app, pilot)
    await pilot.press("down", "enter")
    await settle(app, pilot)


def test_m_copies_the_manifest_entry_from_the_server():
    async def t(app, pilot, server):
        await open_first(app, pilot)
        await pilot.press("m")
        await settle(app, pilot)
        assert app.copied == ["  {MANIFEST}"]
        assert server.paths("/manifest-entry")[-1][2] == {"repo": "automatisch/automatisch"}

    scenario(t)


def test_m_points_the_entry_at_your_fork_when_a_user_is_set():
    async def t(app, pilot, server):
        await open_first(app, pilot)
        await pilot.press("m")
        await settle(app, pilot)
        assert server.paths("/manifest-entry")[-1][2] == {
            "repo": "automatisch/automatisch", "owner": "kjaymiller",
        }  # fmt: skip

    scenario(t, user="kjaymiller")


def test_fork_github_and_editor_keys_open_the_right_links():
    async def t(app, pilot, server):
        await open_first(app, pilot)
        await pilot.press("f", "g", "e")
        assert app.opened == [DETAIL["fork_url"], DETAIL["url"], DETAIL["edit_manifest_url"]]

    scenario(t)


def test_action_keys_without_an_open_repo_warn_and_do_nothing():
    async def t(app, pilot, server):
        app.query_one("#repo-table").focus()
        await pilot.press("m", "f", "g", "e")
        await settle(app, pilot)
        assert app.copied == [] and app.opened == []
        assert server.paths("/manifest-entry") == []

    scenario(t)


def test_r_retries_the_open_repo_through_the_load_endpoint():
    async def t(app, pilot, server):
        await open_first(app, pilot)
        await pilot.press("r")
        await settle(app, pilot)
        assert ("POST", "/api/repo/automatisch/automatisch/load", {}) in server.calls

    scenario(t)


# ---- search tab -----------------------------------------------------------------------------------
def test_search_shows_results_status_and_sorts_on_s():
    async def t(app, pilot, server):
        q = app.query_one("#q", Input)
        q.focus()
        q.value = "dashboards"
        await pilot.press("enter")
        await settle(app, pilot)
        assert names(app, "#results") == ["top/relevance", "low/relevance-high-stars"]
        assert "2 results" in text_of(app.query_one("#search-status"))
        assert "GitHub searched: 30 repos" in text_of(app.query_one("#search-status"))
        await pilot.press("s")  # relevance -> stars, client side: no new search
        await settle(app, pilot)
        assert names(app, "#results") == ["low/relevance-high-stars", "top/relevance"]
        assert len(server.paths("/api/search")) == 1
        await pilot.press("s")  # stars -> novelty
        await settle(app, pilot)
        assert names(app, "#results") == ["top/relevance", "low/relevance-high-stars"]

    scenario(t)


def test_search_result_opens_in_the_search_pane():
    async def t(app, pilot, server):
        q = app.query_one("#q", Input)
        q.value = "x"
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        assert "# automatisch/automatisch" in app.query_one("#search-detail", Markdown).source

    scenario(t)


def test_an_empty_search_does_nothing():
    async def t(app, pilot, server):
        app.query_one("#q", Input).focus()
        await pilot.press("enter")
        await settle(app, pilot)
        assert server.paths("/api/search") == []

    scenario(t)


def test_server_down_shows_a_message_not_a_traceback():
    async def t(app, pilot, server):
        assert "Is the app running" in text_of(app.query_one("#repos-status"))
        q = app.query_one("#q", Input)
        q.value = "x"
        await pilot.press("enter")
        await settle(app, pilot)
        assert "Is the app running" in text_of(app.query_one("#search-status"))

    srv = Server()
    srv.down = True
    scenario(t, server=srv)


# ---- chat tab -------------------------------------------------------------------------------------
async def chat(app, pilot, message):
    await pilot.press("f3")
    box = app.query_one("#chat-input", Input)
    box.focus()
    box.value = message
    await pilot.press("enter")
    await settle(app, pilot)


def answers(app):
    return [m.source for m in app.query("#chat-log Markdown").results(Markdown)]


def test_chat_streams_the_answer_and_shows_route_tools_and_cost():
    async def t(app, pilot, server):
        await chat(app, pilot, "find dashboards")
        assert answers(app) == ["Hello **world**"]  # the pre-tool text was dropped by `reset`
        statics = " | ".join(text_of(s) for s in app.query("#chat-log Static").results(Static))
        assert "You: find dashboards" in statics
        assert (
            "miss · m · route agent (classifier: open-ended)" in statics
            and "tool: search(dashboards, github)" in statics
        )
        assert "cost $0.0123 · saved $0.0100 by routing" in statics
        assert "/1 Look at the files in a/b" in statics and "/2 Compare a/b and c/d" in statics
        assert server.chat_bodies == [{"conversation_id": app.cid, "message": "find dashboards"}]

    scenario(t)


def test_slash_number_sends_that_suggestion():
    async def t(app, pilot, server):
        sent = []
        orig = app.client.chat

        async def spy(cid, message):
            sent.append(message)
            async for ev in orig(cid, message):
                yield ev

        app.client.chat = spy
        await chat(app, pilot, "find dashboards")
        await chat(app, pilot, "/2")
        assert sent == ["find dashboards", "Compare a/b and c/d"]

    scenario(t)


def test_slash_new_starts_a_fresh_conversation():
    async def t(app, pilot, server):
        await chat(app, pilot, "hello")
        first = app.cid
        assert answers(app)
        await chat(app, pilot, "/new")
        assert app.cid != first and answers(app) == [] and app.suggestions == []

    scenario(t)


def test_slash_debug_copies_the_report_and_bad_commands_are_explained():
    async def t(app, pilot, server):
        await chat(app, pilot, "hello")
        await chat(app, pilot, "/debug")
        assert app.copied == ["# debug report"]
        assert server.paths("/chat/debug/")[0][1] == f"/chat/debug/{app.cid}"
        await chat(app, pilot, "/nonsense")
        statics = " | ".join(text_of(s) for s in app.query("#chat-log Static").results(Static))
        assert "Unknown command /nonsense" in statics
        await chat(app, pilot, "/9")  # no suggestion 9
        assert "Unknown command /9" in " | ".join(
            text_of(s) for s in app.query("#chat-log Static").results(Static)
        )

    scenario(t)


def test_chat_error_event_and_dropped_server_are_shown():
    async def t(app, pilot, server):
        await chat(app, pilot, "hello")
        assert answers(app)[-1] == "**Error:** model unavailable"
        server.down = True
        await chat(app, pilot, "again")
        assert "Is the app running" in answers(app)[-1]

    srv = Server()
    srv.chat_events = [{"type": "error", "message": "model unavailable"}, {"type": "done"}]
    scenario(t, server=srv)


def test_chat_text_with_markup_characters_is_not_interpreted():
    async def t(app, pilot, server):
        await chat(app, pilot, "[bold red]boom[/] and [/]")  # would crash Rich if parsed as markup
        statics = " | ".join(text_of(s) for s in app.query("#chat-log Static").results(Static))
        assert "[bold red]boom" in statics

    scenario(t)
