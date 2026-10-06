"""Terminal UI for Template Scout (Textual). Run: mise run tui

A client of the running web app (it calls the same JSON API), so it needs no secrets or model
access of its own and can point at a deployed copy: SCOUT_URL=https://... mise run tui
"""

import argparse
import os
import shutil
import subprocess
import time
import uuid
import webbrowser

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Markdown,
    Static,
    TabbedContent,
    TabPane,
)

from .tui_client import (
    DEFAULT_URL,
    SORTS,
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

CHAT_HELP = (
    "Commands: [b]/1[/b]-[b]/4[/b] send a suggestion · [b]/new[/b] new chat · "
    "[b]/debug[/b] copy the debug report · [b]/help[/b]"
)


def copy_to_system_clipboard(text: str) -> bool:
    """Use the OS clipboard tool when there is one; the caller falls back to OSC 52 otherwise."""
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
                return True
            except (subprocess.SubprocessError, OSError):
                continue
    return False


class ScoutApp(App):
    TITLE = "Template Scout"
    CSS = """
    .left { width: 3fr; }
    .detail { width: 2fr; border-left: solid $primary; padding: 0 1; }
    DataTable { height: 1fr; }
    .status { height: 1; color: $text-muted; padding: 0 1; }
    #chat-log { height: 1fr; padding: 0 1; }
    #chat-input { dock: bottom; }
    .you { margin-top: 1; text-style: bold; }
    .meta { color: $text-muted; }
    .err { color: $error; }
    """
    BINDINGS = [
        Binding("f1", "tab('search')", "Search"),
        Binding("f2", "tab('repos')", "Repos"),
        Binding("f3", "tab('chat')", "Chat"),
        Binding("slash", "focus_input", "Filter/search", show=True),
        Binding("m", "copy_manifest", "Copy manifest"),
        Binding("f", "open_fork", "Fork"),
        Binding("g", "open_github", "GitHub"),
        Binding("e", "open_editor", "Edit manifest"),
        Binding("r", "retry", "Retry/reload"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, client: ScoutClient | None = None):
        super().__init__()
        self.client = client or ScoutClient(os.environ.get("SCOUT_URL", DEFAULT_URL))
        self.repos: list[dict] = []
        self.results: list[dict] = []
        self.sort = "relevance"
        self.current: dict | None = None  # the detail object last opened
        self.cid = str(uuid.uuid4())
        self.suggestions: list[str] = []

    # ---- layout ---------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="search"):
            with TabPane("Search (F1)", id="search"):
                yield Input(placeholder="Search popular GitHub projects, then Enter", id="q")
                with Horizontal():
                    with Vertical(classes="left"):
                        yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
                        yield Static(
                            "Type a search and press Enter.", id="search-status", classes="status"
                        )
                    with VerticalScroll(classes="detail"):
                        yield Markdown("Select a result and press Enter.", id="search-detail")
            with TabPane("Repos (F2)", id="repos"):
                yield Input(placeholder="Filter by name, language or service", id="filter")
                with Horizontal():
                    with Vertical(classes="left"):
                        yield DataTable(id="repo-table", cursor_type="row", zebra_stripes=True)
                        yield Static("Loading…", id="repos-status", classes="status")
                    with VerticalScroll(classes="detail"):
                        yield Markdown("Select a repo and press Enter.", id="repos-detail")
            with TabPane("Chat (F3)", id="chat"):
                yield VerticalScroll(id="chat-log")
                yield Input(
                    placeholder="Ask about templates or find projects (/help)", id="chat-input"
                )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#results", DataTable).add_columns(
            "Repo", "★", "Match", "Novel", "Services", "Compose"
        )
        self.query_one("#repo-table", DataTable).add_columns(
            "Repo", "★", "Language", "Services", "Compose", "Cached"
        )
        self.load_repos()
        self.chat_intro()
        self.query_one("#q", Input).focus()

    # ---- helpers --------------------------------------------------------------------------
    def say(self, widget_id: str, text: str) -> None:
        self.query_one(widget_id, Static).update(text)

    def copy_text(self, text: str) -> str:
        """Copy to the OS clipboard if possible, else OSC 52. Returns which one was used."""
        if copy_to_system_clipboard(text):
            return "clipboard"
        self.copy_to_clipboard(text)
        return "terminal clipboard (OSC 52)"

    def open_url(self, url: str) -> None:
        webbrowser.open(url)

    def active_tab(self) -> str:
        return self.query_one(TabbedContent).active

    # ---- actions --------------------------------------------------------------------------
    def action_tab(self, name: str) -> None:
        self.query_one(TabbedContent).active = name
        self.action_focus_input()

    def action_focus_input(self) -> None:
        target = {"search": "#q", "repos": "#filter", "chat": "#chat-input"}[self.active_tab()]
        self.query_one(target, Input).focus()

    def action_cycle_sort(self) -> None:
        self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
        if self.results:
            self.show_results()
        self.notify(f"Sorted by {self.sort}")

    async def action_copy_manifest(self) -> None:
        if not self.current:
            self.notify("Open a repo first (Enter).", severity="warning")
            return
        try:
            out = await self.client.manifest(self.current["name"])
        except ScoutError as e:
            self.notify(str(e), severity="error")
            return
        how = self.copy_text(out["text"])
        warn = " ".join(out["warnings"])
        self.notify(
            f"Copied the manifest entry ({how}). Append it as the last item. {warn}", timeout=10
        )

    def _need_current(self) -> dict | None:
        if not self.current:
            self.notify("Open a repo first (Enter).", severity="warning")
        return self.current

    def action_open_fork(self) -> None:
        if d := self._need_current():
            self.open_url(d["fork_url"])

    def action_open_github(self) -> None:
        if d := self._need_current():
            self.open_url(d["url"])

    def action_open_editor(self) -> None:
        if d := self._need_current():
            self.open_url(d["edit_manifest_url"])

    def action_retry(self) -> None:
        if self.active_tab() == "repos" and not self.current:
            self.load_repos()
        elif self.current:
            self.open_detail(self.current["name"], retry=True)
        else:
            self.load_repos()

    # ---- repos tab ------------------------------------------------------------------------
    @work(exclusive=True, group="repos")
    async def load_repos(self) -> None:
        try:
            data = await self.client.repos()
        except ScoutError as e:
            self.say("#repos-status", f"[red]{escape(str(e))}[/red]")
            return
        self.repos = data["repos"]
        self.show_repos()
        if self.active_tab() == "repos":  # focusing a widget in another tab would switch to it
            self.query_one("#repo-table", DataTable).focus()

    def show_repos(self) -> None:
        rows = filter_repos(self.repos, self.query_one("#filter", Input).value)
        table = self.query_one("#repo-table", DataTable)
        table.clear()
        for r in rows:
            table.add_row(*repo_row(r), key=r["name"])
        total = len(self.repos)
        complete = sum(1 for r in self.repos if r["has_info"] and r["has_root"])
        self.say(
            "#repos-status",
            f"{len(rows)} of {total} repos · {complete} with basics cached · ✓✓ = info + root",
        )

    @on(Input.Changed, "#filter")
    def on_filter(self) -> None:
        if self.repos:
            self.show_repos()

    @on(DataTable.RowSelected, "#repo-table")
    def on_repo_selected(self, event: DataTable.RowSelected) -> None:
        self.open_detail(str(event.row_key.value), pane="#repos-detail")

    # ---- search tab -----------------------------------------------------------------------
    @on(Input.Submitted, "#q")
    def on_search(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.run_search(event.value.strip())

    @work(exclusive=True, group="search")
    async def run_search(self, q: str, refresh: bool = False) -> None:
        self.say("#search-status", f"Searching “{escape(q)}”… (a new topic crawls GitHub, ~20 s)")
        try:
            out = await self.client.search(q, refresh=refresh)
        except ScoutError as e:
            self.say("#search-status", f"[red]{escape(str(e))}[/red]")
            return
        self.results = out["results"]
        self.show_results()
        self.say("#search-status", escape(search_status(out)))
        self.query_one("#results", DataTable).focus()

    def show_results(self) -> None:
        table = self.query_one("#results", DataTable)
        table.clear()
        for r in sort_results(self.results, self.sort):
            table.add_row(*result_row(r), key=r["name"])

    @on(DataTable.RowSelected, "#results")
    def on_result_selected(self, event: DataTable.RowSelected) -> None:
        self.open_detail(str(event.row_key.value), pane="#search-detail")

    # ---- details (shared) -----------------------------------------------------------------
    @work(exclusive=True, group="detail")
    async def open_detail(self, name: str, pane: str | None = None, retry: bool = False) -> None:
        pane = pane or ("#search-detail" if self.active_tab() == "search" else "#repos-detail")
        md = self.query_one(pane, Markdown)
        await md.update(f"Loading **{name}**…\n\nThe first open of a repo may call GitHub once.")
        try:
            out = await (self.client.retry(name) if retry else self.client.repo(name))
        except ScoutError as e:
            await md.update(f"**{name}**\n\n> {e}")
            return
        self.current = out["detail"]
        await md.update(detail_markdown(out["detail"], out["errors"]))
        if self.repos:  # the cache state may have changed
            self.load_repos_quietly()

    @work(exclusive=True, group="refresh")
    async def load_repos_quietly(self) -> None:
        try:
            self.repos = (await self.client.repos())["repos"]
        except ScoutError:
            return
        if self.active_tab() == "repos":
            return  # leave the table (and the cursor) alone while the user is on it

    # ---- chat tab -------------------------------------------------------------------------
    def chat_intro(self) -> None:
        log = self.query_one("#chat-log", VerticalScroll)
        log.mount(Static(CHAT_HELP, classes="meta"))

    @on(Input.Submitted, "#chat-input")
    async def on_chat(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            await self.chat_command(text)
        else:
            self.send_chat(text)

    async def chat_command(self, text: str) -> None:
        log = self.query_one("#chat-log", VerticalScroll)
        cmd = text.split()[0].lower()
        if cmd == "/new":
            self.cid = str(uuid.uuid4())
            self.suggestions = []
            await log.remove_children()
            self.chat_intro()
        elif cmd == "/help":
            await log.mount(Static(CHAT_HELP, classes="meta"))
        elif cmd == "/debug":
            try:
                report = await self.client.debug_report(self.cid)
            except ScoutError as e:
                self.notify(str(e), severity="warning")
                return
            self.notify(f"Debug report copied ({self.copy_text(report)}).")
        elif cmd[1:].isdigit() and 1 <= int(cmd[1:]) <= len(self.suggestions):
            self.send_chat(self.suggestions[int(cmd[1:]) - 1])
        else:
            await log.mount(
                Static(f"Unknown command {escape(cmd)}. /help lists them.", classes="err")
            )

    @work(exclusive=True, group="chat")
    async def send_chat(self, message: str) -> None:
        log = self.query_one("#chat-log", VerticalScroll)
        self.suggestions = []
        await log.mount(Static(f"You: {escape(message)}", classes="you"))
        answer = Markdown("")
        footer = Static("", classes="meta")
        await log.mount(answer, footer)
        log.scroll_end(animate=False)
        raw, notes, started, last_paint = "", [], time.monotonic(), 0.0
        try:
            async for ev in self.client.chat(self.cid, message):
                kind = ev["type"]
                if kind == "meta":
                    notes.append(meta_line(ev))
                elif kind == "note":
                    notes.append(ev["t"])
                elif kind == "tool":
                    args = ", ".join(str(v) for v in ev["args"].values())
                    notes.append(f"tool: {ev['name']}({args})")
                elif kind == "tool_result" and not ev["ok"]:
                    notes.append(f"✗ {ev['preview']}")
                elif kind == "cost":
                    notes.append(cost_line(ev))
                elif kind == "reset":
                    raw = ""
                elif kind == "thinking" and not raw:
                    await answer.update(f"*thinking… {int(time.monotonic() - started)}s*")
                elif kind == "token":
                    raw += ev["t"]
                    if time.monotonic() - last_paint > 0.1:  # repaint at most ~10 times a second
                        await answer.update(raw)
                        last_paint = time.monotonic()
                elif kind == "suggestions":
                    self.suggestions = ev["items"]
                elif kind == "error":
                    raw = f"**Error:** {ev['message']}"
                footer.update(escape(" · ".join(notes)))
                log.scroll_end(animate=False)
            await answer.update(raw)
        except ScoutError as e:
            await answer.update(f"**Error:** {e}")
        if self.suggestions:
            lines = "\n".join(f"/{i} {escape(s)}" for i, s in enumerate(self.suggestions, 1))
            await log.mount(Static(lines, classes="meta"))
        log.scroll_end(animate=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Template Scout terminal UI")
    ap.add_argument("--url", default=os.environ.get("SCOUT_URL", DEFAULT_URL), help="web app URL")
    ap.add_argument(
        "--user",
        default=os.environ.get("SCOUT_GH_USER", ""),
        help="your GitHub username, so copied manifest entries point at your fork",
    )
    args = ap.parse_args()
    ScoutApp(ScoutClient(args.url, user=args.user)).run()


if __name__ == "__main__":
    main()
