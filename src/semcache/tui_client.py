"""HTTP client and text formatting for the terminal UI.

No Textual in here: this is the part that talks to the running web app (so the TUI also works
against a deployed copy) and turns its JSON into rows and Markdown. It is plain Python, so it is
tested without a terminal.
"""

import json
from collections.abc import AsyncIterator

import httpx

DEFAULT_URL = "http://localhost:8000"
SORTS = ("relevance", "stars", "novelty")
COMPOSE_SHORT = {"ready": "Compose+build", "image-only": "image only", "none": "no Compose"}


class ScoutError(Exception):
    """Something the user should see in the status line, not a traceback."""


class ScoutClient:
    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        *,
        user: str = "",
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.user = user.strip()
        # Searches can crawl GitHub (~20 s) and chat answers can take minutes: no read timeout.
        self.http = client or httpx.AsyncClient(
            base_url=self.base_url, timeout=httpx.Timeout(30.0, read=None)
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _json(self, method: str, path: str, **kw) -> dict | list:
        try:
            r = await self.http.request(method, path, **kw)
        except httpx.ConnectError as e:
            raise ScoutError(
                f"Can't reach {self.base_url}. Is the app running? (mise run up)"
            ) from e
        except httpx.HTTPError as e:
            raise ScoutError(f"{type(e).__name__}: {e}") from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = None
            raise ScoutError(str(detail or f"HTTP {r.status_code}"))
        return r.json()

    async def repos(self) -> dict:
        return await self._json("GET", "/api/repos")

    async def search(self, q: str, sort: str = "relevance", refresh: bool = False) -> dict:
        params = {"q": q, "sort": sort, "refresh": str(refresh).lower()}
        return await self._json("GET", "/api/search", params=params)

    async def repo(self, full_name: str) -> dict:
        return await self._json("GET", f"/api/repo/{full_name}")

    async def retry(self, full_name: str) -> dict:
        return await self._json("POST", f"/api/repo/{full_name}/load")

    async def manifest(self, full_name: str) -> dict:
        params = {"repo": full_name, **({"owner": self.user} if self.user else {})}
        return await self._json("GET", "/manifest-entry", params=params)

    async def starters(self) -> list[str]:
        return await self._json("GET", "/chat/starters")  # type: ignore[return-value]

    async def stats(self) -> dict:
        return await self._json("GET", "/stats")  # type: ignore[return-value]

    async def debug_report(self, cid: str) -> str:
        try:
            r = await self.http.get(f"/chat/debug/{cid}")
        except httpx.HTTPError as e:
            raise ScoutError(f"{type(e).__name__}: {e}") from e
        if r.status_code == 404:
            raise ScoutError("Nothing to report yet: send a message first")
        r.raise_for_status()
        return r.text

    async def chat(self, cid: str, message: str) -> AsyncIterator[dict]:
        """Stream the reply's events (meta, note, tool, token, cost, suggestions, done, error)."""
        body = {"conversation_id": cid, "message": message}
        try:
            async with self.http.stream("POST", "/chat/send", json=body) as r:
                if r.status_code >= 400:
                    await r.aread()
                    raise ScoutError(f"chat failed: HTTP {r.status_code}")
                async for line in r.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.ConnectError as e:
            raise ScoutError(f"Can't reach {self.base_url}. Is the app running?") from e
        except httpx.HTTPError as e:
            raise ScoutError(f"{type(e).__name__}: {e}") from e


# ---- formatting ---------------------------------------------------------------------------------
def fmt_services(services: list[str]) -> str:
    return ",".join(services) if services else "-"


def repo_row(r: dict) -> tuple:
    """Cells for the Repos table."""
    cache = ("✓" if r["has_info"] else "-") + ("✓" if r["has_root"] else "-")
    return (
        r["name"], f"{r['stars']:,}", r.get("language") or "", fmt_services(r["services"]),
        COMPOSE_SHORT.get(r["compose"], r["compose"]), cache,
    )  # fmt: skip


def result_row(r: dict) -> tuple:
    """Cells for the Search results table."""
    return (
        r["name"], f"{r['stars']:,}", f"{r['match']:.2f}", f"{r['novelty']:.2f}",
        fmt_services(r["services"]), COMPOSE_SHORT.get(r["compose"], r["compose"]),
    )  # fmt: skip


def filter_repos(repos: list[dict], text: str) -> list[dict]:
    q = text.strip().lower()
    if not q:
        return repos
    return [
        r for r in repos
        if q in f"{r['name']} {r.get('language') or ''} {' '.join(r['services'])}".lower()
    ]  # fmt: skip


def sort_results(results: list[dict], sort: str) -> list[dict]:
    """Client-side re-sort of already fetched results (no new search)."""
    keys = {"relevance": lambda r: -r["match"], "stars": lambda r: -r["stars"],
            "novelty": lambda r: -r["novelty"]}  # fmt: skip
    return sorted(results, key=keys.get(sort, keys["relevance"]))


def search_status(out: dict) -> str:
    bits = [f"{len(out['results'])} results"]
    if out.get("cache_hit"):
        h = out["cache_hit"]
        bits.append(f'GitHub skipped: similar search cached ("{h["query"]}", {h["distance"]})')
    elif out.get("crawled") is not None:
        bits.append(f"GitHub searched: {out['crawled']} repos indexed")
    if out.get("notice"):
        bits.append(out["notice"])
    return " · ".join(bits)


def _fence(text: str, lang: str = "") -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}{lang}\n{text}\n{fence}"


def detail_markdown(d: dict, errors: list[str] | None = None) -> str:
    """The details panel as Markdown, from the /api/repo detail object."""
    out = [f"# {d['name']}", ""]
    if errors:
        out += ["> **Could not load everything from GitHub:**"]
        out += [f"> - {e}" for e in errors] + ["> Press `r` to retry.", ""]
    links = f"[GitHub]({d['url']}) · [Fork]({d['fork_url']})"
    out += [f"{links} · [Edit manifest.json]({d['edit_manifest_url']})", ""]
    facts = [f"★ {d['stars']:,}"]
    facts += [x for x in (d["language"], d["license"]) if x]
    if d["pushed"]:
        facts.append(f"last push {d['pushed']}")
    out += [" · ".join(facts), ""]
    if d["description"]:
        out += [d["description"], ""]
    if d["topics"]:
        out += [" ".join(f"`{t}`" for t in d["topics"]), ""]

    out += ["## Aiven Runtime fit", ""]
    if d["services"]:
        out.append("Services: " + ", ".join(f"**{s}**" for s in d["services"]))
    elif d["services_unknown"]:
        out.append("Services unknown (no Compose file was found)")
    else:
        out.append("No Aiven data service detected")
    status = d["compose_label"] + (f" (`{d['compose_path']}`)" if d["compose_path"] else "")
    out += ["", f"**{status}**"]
    if d["app_services"]:
        out.append(f"- builds from source: {', '.join(d['app_services'])}")
    if d["image_apps"]:
        out.append(f"- pulls an image only (needs a Dockerfile): {', '.join(d['image_apps'])}")
    closest = f", closest existing template: {d['closest']}" if d["closest"] else ""
    out += [
        "",
        f"Novelty {d['novelty']:.2f}{closest}. Scores within ~0.05 of each other are noise.",
        "",
    ]

    if d["similar_templates"]:
        out += ["## Most similar existing templates", ""]
        out += [f"- {t['name']} (match {1 - t['distance']:.2f})" for t in d["similar_templates"]]
        out.append("")

    out += ["## Manifest entry", "", _fence(d["manifest_text"], "json")]
    out += ["", *[f"- {w}" for w in d["manifest_warnings"]], "", "Press `m` to copy it.", ""]

    c = d["cache"]
    marks = [("repo info", c["has_info"]), ("root folder", c["has_root"])]
    if c["compose_expected"]:
        marks.append(("Compose file", c["has_compose"]))
    out += ["## From the cache", "", "  ".join(f"{'✓' if ok else '–'} {n}" for n, ok in marks), ""]
    if c["info"]:
        out += [f"GitHub primary language: {c['info'].get('language')}, "
                f"archived: {'yes' if c['info'].get('archived') else 'no'}", ""]  # fmt: skip
    if c["root"]:
        names = [f"{r['name']}{'/' if r['type'] == 'dir' else ''}" for r in c["root"]]
        shown = ", ".join(names[:40]) + (f", … +{len(names) - 40} more" if len(names) > 40 else "")
        out += [f"**Root folder** ({len(names)}): {shown}", ""]
    if c["compose_text"]:
        lines = c["compose_text"].splitlines()
        text = "\n".join(lines[:40]) + (
            f"\n… {len(lines) - 40} more lines" if len(lines) > 40 else ""
        )
        out += [f"**{d['compose_path']}**", "", _fence(text, "yaml"), ""]

    if d["similar"]:
        out += ["## Similar indexed projects", ""]
        out += [
            f"- {r['name']} (★ {r['stars']:,}, match {1 - r['distance']:.2f})" for r in d["similar"]
        ]
    return "\n".join(out) + "\n"


def cost_line(ev: dict) -> str:
    if not ev.get("priced", True):
        s = "no price set"
    else:
        s = f"cost ${ev['usd']:.4f}" if ev["usd"] else "cost $0"
    if ev.get("saved_usd"):
        s += f" · saved ${ev['saved_usd']:.4f} by {ev['saved_by']}"
    return s


def meta_line(ev: dict) -> str:
    s = f"{ev['tier']} · {ev['model']} · route {ev['route']}"
    if ev.get("reason"):
        s += f" ({ev['reason']})"
    return s + (" · cached answer" if ev.get("cached") else "")
