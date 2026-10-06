import json
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import httpx
import valkey
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .cache import SemanticCache
from .catalog import Catalog, embed_text
from .chat import ChatService, ConversationStore, valid_cid
from .compose import compose_status, normalize_compose
from .config import settings, tunables
from .cost import CostStats, Pricing
from .debug import build_report, settings_snapshot
from .details import (
    build_detail,
    ensure_basics,
    group_alphabetical,
    load_into_cache,
    valid_repo_parts,
)
from .embed import LangChainEmbedder
from .followups import STARTERS
from .github import discover, list_dir, read_file, repo_info
from .manifest import EDIT_MANIFEST_URL, build_entry, fork_url, format_entry
from .modelcheck import check as check_models
from .repocache import RepoCache
from .routes import seed_routes
from .seed import TEMPLATES

log = logging.getLogger("uvicorn.error")
HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
SERVICES = ["postgresql", "valkey", "kafka", "opensearch"]  # have a logo in static/icons


def _llm(model: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=300,
        stream_usage=True,  # ask for token counts on streamed replies, for the cost estimate
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = valkey.from_url(settings.valkey_url)
    embedder = LangChainEmbedder(
        settings.embed_model, settings.embed_base_url, settings.embed_api_key
    )
    catalog = Catalog(
        client, index=settings.catalog_index, prefix=settings.catalog_prefix,
        dim=settings.embed_dim,
    )  # fmt: skip
    catalog.ensure_index()
    for t in TEMPLATES:
        if not catalog.exists("template", t["name"]):
            vec = embedder.embed(embed_text(t["name"], t["description"], t["tags"], t["services"]))
            catalog.upsert("template", t["name"], vec, t)
    seed_routes(catalog, embedder)

    def semantic_cache(index: str, prefix: str, max_distance: float, ttl: int) -> SemanticCache:
        c = SemanticCache(
            client, embedder, index_name=index, prefix=prefix, dim=settings.embed_dim,
            max_distance=max_distance, ttl_seconds=ttl,
        )  # fmt: skip
        c.ensure_index()
        return c

    crawl_cache = semantic_cache(
        settings.cache_index, settings.cache_prefix,
        tunables.cache.crawl_max_distance, tunables.cache.crawl_ttl_seconds,
    )  # fmt: skip
    answer_cache = semantic_cache(
        settings.chat_cache_index, settings.chat_cache_prefix,
        tunables.cache.answer_max_distance, tunables.cache.answer_ttl_seconds,
    )  # fmt: skip

    app.state.r = client
    app.state.model_check = check_models(tunables, settings.llm_base_url, settings.llm_api_key)
    if not app.state.model_check["checked"]:
        log.warning("could not list models on the gateway; configured model names are unchecked")
    elif app.state.model_check["missing"]:
        log.warning(
            "settings.toml names models the gateway does not serve: %s",
            ", ".join(app.state.model_check["missing"]),
        )
    app.state.embedder, app.state.catalog, app.state.crawl_cache = embedder, catalog, crawl_cache
    llms: dict[str, ChatOpenAI] = {}

    def llm_for(model: str) -> ChatOpenAI:
        if model not in llms:
            llms[model] = _llm(model)
        return llms[model]

    repo_cache = RepoCache(client, tunables.github.repo_cache_ttl_seconds)
    app.state.repo_cache = repo_cache
    pricing = Pricing(tunables.cost.models)
    stats = CostStats(client)
    app.state.stats, app.state.pricing = stats, pricing
    app.state.store = ConversationStore(client, tunables.chat.conversation_ttl_seconds)
    app.state.chat = ChatService(
        store=app.state.store, catalog=catalog, embedder=embedder,
        llm_for=llm_for,
        models=tunables.routing.models, coverage=tunables.routing.coverage,
        always_expensive=tunables.routing.always_expensive, route_pins=tunables.routing.pin,
        search_cached=lambda q: crawl_cache.lookup("search", q) is not None,
        answer_cache=answer_cache,
        search=run_search,
        route_max_distance=tunables.routing.max_distance,
        route_limits={"smalltalk": tunables.routing.smalltalk_max_distance},
        history_turns=tunables.chat.history_turns,
        max_tool_steps=tunables.chat.max_tool_steps,
        pricing=pricing, stats=stats, github_token=settings.github_token,
        repo_cache=repo_cache,
        followup_max_words=tunables.routing.followup_max_words,
        followup_model=tunables.routing.followup_model,
        planner_model=tunables.routing.planner_model,
        plan_max_tokens=tunables.routing.plan_max_tokens,
        plan_routes=tunables.routing.plan_routes,
    )  # fmt: skip
    yield


app = FastAPI(title="Template Scout", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/healthz")
def healthz() -> dict:
    """Liveness, plus any configured chat models the gateway does not serve."""
    mc = getattr(app.state, "model_check", {"checked": False, "missing": []})
    return {"ok": True, "models_checked": mc["checked"], "missing_models": mc["missing"]}


def _crawl(query: str) -> int:
    """Fetch popular repos from GitHub and add them to the catalog. Returns count ingested."""
    embedder, catalog = app.state.embedder, app.state.catalog
    repos = discover(query, token=settings.github_token, limit=tunables.search.results_per_query)
    for repo in repos:
        services = repo.compose.services if repo.compose else ["unknown"]
        vec = embedder.embed(embed_text(repo.full_name, repo.description, repo.topics, services))
        closest = catalog.nearest_template(vec)
        catalog.upsert(
            "candidate", repo.full_name, vec,
            {
                "name": repo.full_name,
                "description": repo.description,
                "url": repo.url,
                "stars": repo.stars,
                "services": services or ["none"],
                "buildable": compose_status(repo.compose),
                "language": repo.language,
                "license": repo.license,
                "pushed": repo.pushed_at,
                "topics": ",".join(repo.topics),
                "compose_path": repo.compose.path if repo.compose else "",
                "app_services": ",".join(repo.compose.app_services) if repo.compose else "",
                "image_apps": ",".join(repo.compose.image_only_apps) if repo.compose else "",
                "closest": closest[0] if closest else "",
                "novelty": f"{closest[1]:.3f}" if closest else "1.000",
            },
        )  # fmt: skip
        if repo.info:  # basic info came with the search result, so caching it costs no API call
            app.state.repo_cache.put(
                "info", repo.full_name, "", repo.info, ttl=tunables.github.detail_ttl_seconds
            )
        if repo.compose and repo.compose.raw:  # keep the file so its details page can show it
            app.state.repo_cache.put(
                "file", repo.full_name, repo.compose.path, repo.compose.raw,
                ttl=tunables.github.detail_ttl_seconds,
            )  # fmt: skip
    return len(repos)


def run_search(q: str, services: list[str] | None = None, refresh: bool = False) -> dict:
    """GitHub search via the semantic cache, then rank the index. Used by the page and chat."""
    out = {"results": [], "notice": None, "cache_hit": None, "crawled": None}
    cache: SemanticCache = app.state.crawl_cache
    hit = None if refresh else cache.lookup("search", q)
    if hit:
        out["cache_hit"] = hit
    else:
        try:
            out["crawled"] = _crawl(q)
            if out[
                "crawled"
            ]:  # never cache an empty crawl, or similar searches skip GitHub for a day
                cache.store("search", q, str(out["crawled"]))
        except httpx.HTTPError as e:
            out["notice"] = f"GitHub search failed ({type(e).__name__}); showing what is indexed."

    results = app.state.catalog.search(
        app.state.embedder.embed(q), "candidate", services or None, k=30
    )
    for r in results:
        r["novelty"] = float(r["novelty"])
        r["stars"] = int(r["stars"])
        r["compose"] = normalize_compose(r.get("buildable"))  # also maps pre-rename values
    out["results"] = results
    return out


def _search_view(q: str, services: list[str], sort: str, refresh: bool) -> dict:
    """GitHub search via the semantic cache, ranked and sorted. Shared by the page and the API."""
    out = run_search(q, [x for x in services if x in SERVICES], refresh)
    results = out.pop("results")
    if sort == "stars":
        results.sort(key=lambda r: -r["stars"])
    elif sort == "novelty":
        results.sort(key=lambda r: -r["novelty"])
    return {**out, "results": results}


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    q: str = "",
    sort: str = "relevance",
    refresh: bool = False,
    services: list[str] = Query(default=[]),
):
    services = [x for x in services if x in SERVICES]
    q = q.strip()
    ctx = {
        "q": q,
        "sort": sort,
        "services": services,
        "all_services": SERVICES,
        "results": None,
        "notice": None,
        "cache_hit": None,
        "crawled": None,
        "edit_manifest_url": EDIT_MANIFEST_URL,
    }
    if q:
        ctx.update(_search_view(q, services, sort, refresh))
    return templates.TemplateResponse(request, "index.html", ctx)


class ChatIn(BaseModel):
    conversation_id: str
    message: str


def _safe_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _open_repo(owner: str, name: str, errors: list[str] | None = None):
    """(detail, errors) for an indexed repo, or None if it is not indexed. The first open fetches
    whatever is missing from GitHub once; after that it reads the cache."""
    if not valid_repo_parts(owner, name):
        raise HTTPException(404, "invalid repo")
    candidate = app.state.catalog.get("candidate", f"{owner}/{name}")
    if candidate is None:
        return None
    if errors is None:
        errors = ensure_basics(
            candidate, app.state.repo_cache, list_dir=list_dir, read_file=read_file,
            repo_info=repo_info, token=settings.github_token,
            detail_ttl=tunables.github.detail_ttl_seconds,
        )  # fmt: skip
    detail = build_detail(
        candidate, cache=app.state.repo_cache, catalog=app.state.catalog, today=date.today()
    )
    return detail, errors


def _detail_response(request: Request, owner: str, name: str, errors: list[str] | None = None):
    """Details for one indexed project. A fragment for htmx, a full page otherwise."""
    htmx = request.headers.get("hx-request") == "true"
    opened = _open_repo(owner, name, errors)
    tpl = "repo_detail.html" if htmx else "repo_page.html"
    if opened is None:
        status = 200 if htmx else 404
        return templates.TemplateResponse(
            request, tpl, {"missing": f"{owner}/{name}"}, status_code=status
        )
    detail, errors = opened
    return templates.TemplateResponse(
        request, tpl, {"d": detail, "errors": errors, "all_services": SERVICES}
    )


def _repo_rows() -> list[dict]:
    """Every indexed repo with what is cached for it. Reads Valkey only."""
    rows = app.state.catalog.list_all("candidate")
    cache = app.state.repo_cache
    for r in rows:
        r["stars"] = _safe_int(r.get("stars"))
        r["compose"] = normalize_compose(r.get("buildable"))
        r["has_info"] = cache.peek("info", r["name"], "") is not None
        r["has_root"] = cache.peek("ls", r["name"], "") is not None
    return rows


@app.get("/repos", response_class=HTMLResponse)
def repos_list(request: Request):
    """Every repo in the index, A to Z, with what is cached for each. Reads Valkey only."""
    rows = _repo_rows()
    ctx = {
        "groups": group_alphabetical(rows), "total": len(rows), "all_services": SERVICES,
        "with_basics": sum(1 for r in rows if r["has_info"] and r["has_root"]),
        "edit_manifest_url": EDIT_MANIFEST_URL,
    }  # fmt: skip
    return templates.TemplateResponse(request, "repos.html", ctx)


@app.get("/repo/{owner}/{name}", response_class=HTMLResponse)
def repo_detail(request: Request, owner: str, name: str):
    return _detail_response(request, owner, name)


@app.post("/repo/{owner}/{name}/load", response_class=HTMLResponse)
def repo_load(request: Request, owner: str, name: str):
    """Fill the cache for this project from GitHub (the only place the details panel calls it)."""
    if not valid_repo_parts(owner, name):
        raise HTTPException(404, "invalid repo")
    candidate = app.state.catalog.get("candidate", f"{owner}/{name}")
    errors: list[str] = []
    if candidate:
        app.state.repo_cache.forget("fail", f"{owner}/{name}")  # an explicit retry always tries
        errors = load_into_cache(
            candidate, app.state.repo_cache, list_dir=list_dir, read_file=read_file,
            repo_info=repo_info, token=settings.github_token,
            detail_ttl=tunables.github.detail_ttl_seconds,
        )  # fmt: skip
    return _detail_response(request, owner, name, errors)


def _api_result(r: dict) -> dict:
    return {
        "name": r["name"], "url": r.get("url", ""), "description": r.get("description", ""),
        "stars": r["stars"], "language": r.get("language", ""),
        "services": [x for x in r.get("services", "").split(",") if x and x != "none"],
        "compose": normalize_compose(r.get("buildable")), "novelty": r["novelty"],
        "closest": r.get("closest", ""), "match": round(1 - r["distance"], 3),
    }  # fmt: skip


@app.get("/api/search")
def api_search(
    q: str, sort: str = "relevance", refresh: bool = False, services: list[str] = Query(default=[])
):
    """JSON twin of the search page, for the terminal UI and scripts."""
    q = q.strip()
    if not q:
        raise HTTPException(422, "q is empty")
    out = _search_view(q, services, sort, refresh)
    hit = out["cache_hit"]
    return {
        "q": q,
        "results": [_api_result(r) for r in out["results"]],
        "cache_hit": {"query": hit.original_prompt, "distance": round(hit.distance, 3)}
        if hit else None,
        "crawled": out["crawled"],
        "notice": out["notice"],
    }  # fmt: skip


@app.get("/api/repos")
def api_repos():
    """Every indexed repo, A to Z, with what is cached for each."""
    rows = sorted(_repo_rows(), key=lambda r: r["name"].lower())
    return {
        "total": len(rows),
        "with_basics": sum(1 for r in rows if r["has_info"] and r["has_root"]),
        "repos": [
            {
                "name": r["name"], "stars": r["stars"], "language": r.get("language", ""),
                "services": [x for x in r.get("services", "").split(",") if x not in ("", "none")],
                "compose": r["compose"], "has_info": r["has_info"], "has_root": r["has_root"],
            }
            for r in rows
        ],
    }  # fmt: skip


@app.get("/api/repo/{owner}/{name}")
def api_repo(owner: str, name: str):
    """Details for one indexed repo (fetches missing basics from GitHub on the first open)."""
    opened = _open_repo(owner, name)
    if opened is None:
        raise HTTPException(404, f"{owner}/{name} is not in the index")
    detail, errors = opened
    return {"detail": detail, "errors": errors}


@app.post("/api/repo/{owner}/{name}/load")
def api_repo_load(owner: str, name: str):
    """Retry loading a repo's basics now, ignoring any remembered failure."""
    candidate = (
        app.state.catalog.get("candidate", f"{owner}/{name}")
        if valid_repo_parts(owner, name)
        else None
    )
    if candidate is None:
        raise HTTPException(404, f"{owner}/{name} is not in the index")
    app.state.repo_cache.forget("fail", f"{owner}/{name}")
    errors = load_into_cache(
        candidate, app.state.repo_cache, list_dir=list_dir, read_file=read_file,
        repo_info=repo_info, token=settings.github_token,
        detail_ttl=tunables.github.detail_ttl_seconds,
    )  # fmt: skip
    detail, _ = _open_repo(owner, name, errors)
    return {"detail": detail, "errors": errors}


@app.get("/manifest-entry")
def manifest_entry(repo: str, owner: str | None = None):
    """The JSON object to paste into runs-on-runtime data/manifest.json for an indexed project.

    No model is involved: it is built from the stored project data and checked against the
    directory's schema. `owner` is your GitHub username, for an entry that points at your fork.
    """
    candidate = app.state.catalog.get("candidate", repo)
    if candidate is None:
        raise HTTPException(404, f"{repo} is not in the index; search for it first")
    try:
        entry, warnings = build_entry(candidate, date.today(), owner or None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {
        "entry": entry,
        "text": format_entry(entry),
        "warnings": warnings,
        "fork_url": fork_url(repo),
        "edit_manifest_url": EDIT_MANIFEST_URL,
    }


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html", {})


@app.get("/stats")
def stats():
    """Running spend and savings, estimated from the prices in settings.toml."""
    return {
        **app.state.stats.totals(),
        "models": {
            name: {"input_per_mtok": p.input_per_mtok, "output_per_mtok": p.output_per_mtok}
            for name, p in tunables.cost.models.items()
        },
    }


@app.get("/chat/starters")
def chat_starters():
    return STARTERS


@app.get("/chat/debug/{cid}", response_class=PlainTextResponse)
def chat_debug(cid: str):
    """Markdown report for one conversation, for pasting into a bug report. No secrets."""
    if not valid_cid(cid):
        raise HTTPException(400, "invalid conversation id")
    history = app.state.store.history(cid)
    if not history:
        raise HTTPException(404, "no such conversation")
    snap = settings_snapshot(tunables, settings.embed_model, settings.embed_dim)
    return build_report(cid, history, app.state.stats.totals(), snap)


@app.get("/chat/history/{cid}")
def chat_history(cid: str):
    if not valid_cid(cid):
        raise HTTPException(400, "invalid conversation id")
    return app.state.store.history(cid)


@app.post("/chat/send")
def chat_send(body: ChatIn):
    """Stream the reply as newline-delimited JSON events: meta, note, token..., done | error."""
    if not valid_cid(body.conversation_id):
        raise HTTPException(400, "invalid conversation id")
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "message is empty")

    def events():
        for ev in app.state.chat.reply(body.conversation_id, message):
            yield json.dumps(ev) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")
