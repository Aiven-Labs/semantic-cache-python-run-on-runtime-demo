import json

import pytest

from semcache.chat import inherit_route, repos_block
from semcache.compose import (
    COMPOSE_PATHS,
    IMAGE_ONLY,
    NONE,
    READY,
    analyze,
    compose_status,
    normalize_compose,
)
from semcache.repocache import RepoCache
from semcache.routes import ROUTES, choose


# ---- 1. clear Compose labels -------------------------------------------------------------
def test_status_values():
    assert compose_status(None) == NONE
    assert compose_status(analyze("services:\n  a:\n    image: x/y\n")) == IMAGE_ONLY
    assert compose_status(analyze("services:\n  a:\n    build: .\n")) == READY


def test_legacy_values_are_mapped():
    # "no" used to mean "Compose present, no build:", which the model misread as "no file"
    assert normalize_compose("yes") == READY
    assert normalize_compose("no") == IMAGE_ONLY
    assert normalize_compose("no compose") == NONE
    assert normalize_compose(None) == NONE and normalize_compose("junk") == NONE


def test_prompt_never_says_image_only_means_no_file():
    block = repos_block([{"name": "k/k", "buildable": "no", "novelty": "0.2", "stars": 1}])
    assert "Compose file found, but its app uses image: only" in block
    assert "no Compose file found" not in block


# ---- 2. wider discovery ------------------------------------------------------------------
def test_dify_style_path_is_covered():
    assert "docker/docker-compose.yaml" in COMPOSE_PATHS  # the file we missed for langgenius/dify
    assert COMPOSE_PATHS[0] == "docker-compose.yml"  # root still tried first
    assert len(COMPOSE_PATHS) == len(set(COMPOSE_PATHS))


# ---- 3. repo facts -----------------------------------------------------------------------
def test_repo_facts_in_prompt_and_route():
    r = {"name": "o/r", "language": "Python", "license": "MIT", "pushed": "2026-09-01",
         "buildable": "yes", "stars": 5, "novelty": "0.2"}  # fmt: skip
    block = repos_block([r])
    assert (
        "language: Python" in block and "license: MIT" in block and "last push: 2026-09-01" in block
    )
    assert "language: unknown" in repos_block([{"name": "o/old", "stars": 1}])
    assert "repo_facts" in ROUTES and ROUTES["repo_facts"].exemplars


# ---- 4. follow-ups -----------------------------------------------------------------------
HIST = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a", "route": "agent"}]


def test_short_unmatched_followup_inherits_tool_route():
    assert inherit_route(HIST, "so Dify uses vite?", "agent", 8) == "agent"
    inspect = [{"role": "assistant", "content": "a", "route": "inspect"}]
    assert inherit_route(inspect, "and the web folder?", "agent", 8) == "inspect"


def test_followup_not_inherited_when_it_should_not():
    assert inherit_route([], "so Dify uses vite?", "agent", 8) is None  # no history
    assert inherit_route(HIST, "so Dify uses vite?", "find", 8) is None  # router matched something
    long = "please compare popular project management tools in detail and tell me everything about each"
    assert inherit_route(HIST, long, "agent", 8) is None  # long: a real new question
    small = [{"role": "assistant", "content": "a", "route": "smalltalk"}]
    assert inherit_route(small, "ok and?", "agent", 8) is None
    cheap = [{"role": "assistant", "content": "a", "route": "lookup"}]
    assert inherit_route(cheap, "and kafka?", "agent", 8) == "agent"  # context-only -> tools


def test_bare_followup_without_limit_disabled():
    assert inherit_route(HIST, "ok", "agent", 0) is None
    assert choose([], 0.25, "x")[0] == "find"  # unchanged: bare topics still search


# ---- 5. repo cache -----------------------------------------------------------------------
class FakeR:
    def __init__(self):
        self.d, self.ttl = {}, {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, ttl, v):
        self.d[k], self.ttl[k] = v, ttl


def test_repo_cache_hits_and_validates():
    c, calls = RepoCache(FakeR(), 3600), []

    def fetch():
        calls.append(1)
        return [{"name": "Dockerfile"}]

    assert c.get("ls", "a/b", "docker/", fetch) == [{"name": "Dockerfile"}]
    assert c.get("ls", "a/b", "docker", fetch) == [{"name": "Dockerfile"}]  # same path, cached
    assert c.get("ls", "A/B", "docker", fetch)  # repo case-insensitive
    assert len(calls) == 1
    assert c.get("file", "a/b", "docker", fetch)  # kind is part of the key
    assert len(calls) == 2
    assert set(c.r.ttl.values()) == {3600}
    with pytest.raises(ValueError):
        c.get("ls", "a/b", "../x", fetch)  # validated before touching the cache or network


def test_repo_cache_does_not_cache_errors():
    c = RepoCache(FakeR(), 60)

    def boom():
        raise RuntimeError("rate limit")

    with pytest.raises(RuntimeError):
        c.get("ls", "a/b", "", boom)
    assert c.r.d == {}
    assert json.loads(json.dumps(c.get("ls", "a/b", "", lambda: ["ok"]))) == ["ok"]


# ---- 6. novelty noise --------------------------------------------------------------------
def test_close_novelty_scores_are_flagged_as_noise():
    mk = lambda n, v: {"name": n, "novelty": str(v), "stars": 1}  # noqa: E731
    noisy = repos_block([mk("a/a", 0.228), mk("b/b", 0.214), mk("c/c", 0.207)])
    assert "noise" in noisy
    spread = repos_block([mk("a/a", 0.50), mk("b/b", 0.20)])
    assert "noise" not in spread


def test_timeout_on_one_path_does_not_fail_discovery():
    import httpx

    from semcache.github import _fetch_compose

    def handler(request):
        if request.url.path.endswith("/docker-compose.yml"):
            raise httpx.ReadTimeout("slow", request=request)
        if request.url.path.endswith("/docker/docker-compose.yaml"):
            return httpx.Response(200, text="services:\n  app:\n    build: .\n")
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    info = _fetch_compose(client, "langgenius/dify", "HEAD")
    assert info is not None and info.buildable


def test_repo_info_parses_and_handles_errors():
    import httpx

    from semcache.github import repo_info

    body = {"full_name": "langgenius/dify", "language": "TypeScript",
            "license": {"spdx_id": "NOASSERTION"}, "stargazers_count": 157000,
            "pushed_at": "2026-10-01T10:00:00Z", "topics": ["llm"]}  # fmt: skip
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    info = repo_info("langgenius/dify", client=ok)
    assert info["language"] == "TypeScript" and info["license"] == "unknown"
    assert info["last_push"] == "2026-10-01" and info["stars"] == 157000
    for code, exc in ((404, ValueError), (403, RuntimeError)):
        c = httpx.Client(transport=httpx.MockTransport(lambda r, code=code: httpx.Response(code)))
        with pytest.raises(exc):
            repo_info("a/b", client=c)
    with pytest.raises(ValueError):
        repo_info("not a repo")


# ---- review of a real report: chips and follow-ups --------------------------------------------
def test_chips_follow_the_answer_not_the_search_order():
    from semcache.followups import build_suggestions, follow_the_answer

    seen = [{"name": "oomol-lab/open-flow"}, {"name": "ritik-prog/n8n-templates"},
            {"name": "automatisch/automatisch"}, {"name": "cvhariharan/flowctl"}]  # fmt: skip
    answer = (
        "Best: [automatisch/automatisch](https://github.com/automatisch/automatisch). "
        "Also [cvhariharan/flowctl](https://github.com/cvhariharan/flowctl). Skip the n8n JSON collections."
    )
    ordered = follow_the_answer(seen, answer)
    assert [r["name"] for r in ordered] == ["automatisch/automatisch", "cvhariharan/flowctl"]
    chips = build_suggestions(ordered)
    assert chips[0] == "Look at the files in automatisch/automatisch"
    assert not any("n8n-templates" in c or "open-flow" in c for c in chips)
    assert follow_the_answer(seen, "no links here") == seen  # nothing named: keep search order


def test_chips_keep_inspected_repos():
    from semcache.followups import follow_the_answer

    seen = [{"name": "a/a"}, {"name": "b/b", "inspected": True}]
    got = follow_the_answer(seen, "see https://github.com/a/a.")
    assert [r["name"] for r in got] == ["a/a", "b/b"]


def test_longer_follow_up_with_a_pronoun_is_still_a_follow_up():
    msg = "what specifically in that webUI (react or vite or flask/fastapi)"  # 10 words, from a real chat
    assert len(msg.split()) > 8
    assert inherit_route(HIST, msg, "agent", 8) == "agent"
    new_q = "what are the best open source project management tools with a compose file today"
    assert inherit_route(HIST, new_q, "agent", 8) is None  # long and no reference: a new question
    assert inherit_route(HIST, msg, "agent", 0) is None  # feature off


def test_tool_rules_require_citing_files():
    from semcache.chat import TOOL_RULES

    assert "name the file" in TOOL_RULES and "did not read" in TOOL_RULES


def test_error_hints_distinguish_wrong_path_from_wrong_repo():
    from semcache.chat import HINT_PATH, HINT_REPO, tool_error_hint

    assert tool_error_hint("Tool error: ValueError: file not found: a/b/package.json") == HINT_PATH
    assert tool_error_hint("Tool error: ValueError: not found: a/b") == HINT_REPO
    assert tool_error_hint("Tool error: RuntimeError: GitHub rate limit reached") == ""
    assert "repo" in HINT_PATH and "search(" in HINT_REPO


def test_rules_say_list_root_first():
    from semcache.chat import TOOL_RULES

    assert "call repo with no path first" in TOOL_RULES and "packages/" in TOOL_RULES


# ---- planner / answerer split and visible cache status -----------------------------------------
def _pricing():
    from semcache.cost import Pricing
    from semcache.tunables import ModelPrice

    return Pricing({
        "cheap": ModelPrice(input_per_mtok=1, output_per_mtok=5),
        "strong": ModelPrice(input_per_mtok=3, output_per_mtok=15),
        "free": ModelPrice(input_per_mtok=0, output_per_mtok=0),
    })  # fmt: skip


def test_pricier_only_when_known_and_higher():
    p = _pricing()
    assert p.pricier("strong", "cheap") and not p.pricier("cheap", "strong")
    assert not p.pricier("free", "cheap") and not p.pricier("strong", "unknown")
    assert not p.pricier("cheap", "cheap")


def test_split_savings_count_both_models():
    from semcache.cost import routing_saving, routing_saving_total

    p = _pricing()
    # planner does 6000 in / 100 out, strong answers with 1500 in / 800 out
    parts = [("cheap", 6000, 100), ("strong", 1500, 800)]
    spent = p.cost("cheap", 6000, 100) + p.cost("strong", 1500, 800)
    would = p.cost("strong", 7500, 900)
    assert routing_saving_total(p, "strong", parts) == pytest.approx(would - spent)
    assert routing_saving_total(p, "strong", parts) > 0  # even though strong answered
    assert routing_saving_total(p, "strong", [("unknown", 1, 1)]) == 0.0
    assert routing_saving(p, "strong", "strong", 100, 100) == 0.0


def test_cost_event_adds_planner_cost_but_savings_only_for_the_executor():
    from semcache.chat import ChatService

    svc = ChatService.__new__(ChatService)
    svc.pricing, svc.baseline_model = _pricing(), "strong"
    # a PAID planner: its cost is added; the strong executor equals the baseline, so no savings
    ev = svc._cost_event(
        "strong", "<= 2", {"in": 1500, "out": 800},
        planner="cheap", planner_usage={"in": 6000, "out": 100},
    )  # fmt: skip
    expect = svc.pricing.cost("strong", 1500, 800) + svc.pricing.cost("cheap", 6000, 100)
    assert ev["usd"] == pytest.approx(expect, abs=1e-6)
    assert ev["in"] == 7500 and ev["out"] == 900 and ev["planner"] == "cheap"
    assert ev["saved_by"] is None and ev["saved_usd"] == 0
    # a FREE planner adds nothing to the bill, and the mid-tier executor still saves vs baseline
    free = svc._cost_event(
        "cheap", "<= 0.25", {"in": 1500, "out": 800},
        planner="free", planner_usage={"in": 3000, "out": 300},
    )  # fmt: skip
    assert free["usd"] == pytest.approx(svc.pricing.cost("cheap", 1500, 800), abs=1e-6)
    assert free["saved_by"] == "routing"
    assert free["saved_usd"] == pytest.approx(
        svc.pricing.cost("strong", 1500, 800) - svc.pricing.cost("cheap", 1500, 800), abs=1e-6
    )  # planner tokens are not counted as work the baseline would have done
    solo = svc._cost_event("strong", "<= 2", {"in": 1500, "out": 800})
    assert "planner" not in solo


class _Hit:
    original_prompt, distance = "workflow automation", 0.031


def test_search_status_says_whether_github_was_queried():
    from semcache.chat import ChatService

    svc = ChatService.__new__(ChatService)
    svc.search = lambda q: {"results": [{"name": "a/b"}] * 12, "cache_hit": _Hit(), "crawled": None}
    repos, status = svc._search("workflow")
    assert len(repos) == 8 and status.startswith("GitHub skipped") and "0.031" in status
    svc.search = lambda q: {"results": [], "cache_hit": None, "crawled": 30, "notice": None}
    assert "GitHub searched: 30 repos" in svc._search("x")[1]
    svc.search = lambda q: {"results": [], "cache_hit": None, "crawled": None, "notice": "failed"}
    assert svc._search("x")[1] == "failed"


def test_agent_gets_local_data_first():
    from semcache.chat import LOCAL_FIRST

    assert "Do not search the index for the same thing" in LOCAL_FIRST


def test_followups_skip_the_prefetch_but_fresh_questions_get_it():
    import numpy as np

    from semcache.chat import LOCAL_FIRST, ChatService

    class Cat:
        def search(self, vec, kind, k=0):
            return [{"name": "a/b", "stars": 1, "novelty": "0.2"}]

    class Emb:
        def embed(self, text):
            return np.zeros(2, dtype=np.float32)

    svc = ChatService.__new__(ChatService)
    svc.catalog, svc.embedder = Cat(), Emb()
    seen: list[dict] = []
    ctx, _ = svc._context("agent", "workflow apps", seen, fresh=True)
    assert LOCAL_FIRST in ctx and "Existing templates:" in ctx and seen
    seen2: list[dict] = []
    assert svc._context("agent", "and the web ui?", seen2, fresh=False) == ("", None) and not seen2


def test_answers_are_told_to_stay_short():
    from semcache.chat import SYSTEM

    assert (
        "under about 200 words" in SYSTEM
        and "README" in __import__("semcache.chat").chat.TOOL_RULES
    )


# ---- plan with a free model, execute with a larger one ------------------------------------------
def test_should_plan_matrix():
    from semcache.planning import should_plan

    p = _pricing()
    on = {"agent", "analysis", "inspect"}

    def plan(route="agent", inh=False, model="strong", planner="free", steps=4, routes=on):
        return should_plan(route, inh, p, model, planner, steps, routes)

    assert plan()  # fresh question, paid executor, free planner
    assert plan(route="analysis") and plan(route="inspect")
    assert not plan(route="smalltalk") and not plan(route="lookup") and not plan(route="find")
    assert not plan(inh=True)  # short follow-ups skip planning
    assert not plan(model="free")  # a free executor gains nothing from a free planner
    assert not plan(model="cheap", planner="strong")  # planner must be cheaper than the executor
    assert not plan(
        model="strong", planner="unknown"
    )  # unpriced planner: cannot prove it is cheaper
    assert not plan(planner="")  # not configured
    assert not plan(steps=0)  # no tool steps to plan for
    assert not plan(routes=set()) and not plan(route="inspect", routes={"agent"})  # settings decide


def test_clean_plan():
    from semcache.planning import MAX_PLAN_CHARS, clean_plan

    assert clean_plan('<think>hmm</think>\n1. search("x")\n2. Answer') == (
        '1. search("x")\n2. Answer'
    )
    assert clean_plan("</think>1. Answer") == "1. Answer"  # stray close tag
    assert clean_plan("<think>only thinking</think>") == "" and clean_plan(None) == ""
    long = "\n".join(f"{i}. step number {i} with some words" for i in range(200))
    out = clean_plan(long)
    assert len(out) <= MAX_PLAN_CHARS + 4 and out.endswith("...")


def test_plan_prompt_and_block():
    from semcache.planning import PLAN_PROMPT, plan_block

    for tool in ("search(", "repo(", "templates("):
        assert tool in PLAN_PROMPT  # the planner is told every tool the executor has
    assert "Never invent an owner" in PLAN_PROMPT and "{max_steps}" in PLAN_PROMPT
    assert PLAN_PROMPT.format(max_steps=4)  # formats cleanly
    block = plan_block("1. Answer", "Ornith")
    assert "Ornith" in block and "1. Answer" in block and "Follow it unless" in block


def test_report_shows_the_plan_and_planner_cost():
    from semcache.debug import build_report

    h = [{"role": "user", "content": "q"},
         {"role": "assistant", "content": "a", "route": "agent", "model": "m", "plan": "1. Answer",
          "planner": "Ornith", "planner_in": 900, "planner_out": 80}]  # fmt: skip
    r = build_report("c", h, {}, {})
    assert "Plan (by Ornith" in r and "1. Answer" in r and "planner=Ornith (900 in / 80 out)" in r


def test_parse_plan_accepts_real_plans_and_rejects_reasoning():
    from semcache.planning import parse_plan

    good = (
        '1. repo("langgenius/dify", "")\n'
        '2. repo("langgenius/dify", "docker/docker-compose.yaml")\n'
        "3. Answer\nAnswer should: list the Aiven services it needs."
    )
    assert parse_plan(good, 4) == good
    assert parse_plan("<think>x</think>\n1. Answer", 4) == "1. Answer"
    assert parse_plan('1. `search`("x")\n2. Answer', 4).startswith("1. `search`")
    # what Ornith actually produced: thinking out loud, then maybe numbered thoughts
    rambling = (
        "The user is asking about Dify. Let me think.\n1. First, what is Dify?\n2. Then check."
    )
    assert parse_plan(rambling, 4) == ""
    assert parse_plan("1. Fetch the compose file\n2. Answer", 4) == ""  # not a real tool
    assert parse_plan("", 4) == "" and parse_plan("no numbered steps", 4) == ""
    too_many = "\n".join(f'{i}. search("x")' for i in range(1, 9))
    assert parse_plan(too_many, 4) == ""  # more steps than the executor is allowed
    assert parse_plan("1. Answer\nAlso, remember to be nice.", 4) == ""  # prose after the plan


# ---- three tools instead of six ------------------------------------------------------------------
def _svc_with_repo_stubs(monkeypatch, files=None, dirs=None, info=None):
    """A ChatService whose GitHub access is replaced by dicts, so the repo tool can be exercised."""
    import semcache.chat as chat

    files, dirs = files or {}, dirs or {}

    def fake_read(repo, path, **kw):
        if path in files:
            return files[path]
        raise ValueError(f"file not found: {repo}/{path}")

    def fake_list(repo, path="", **kw):
        if path in dirs:
            return dirs[path]
        raise ValueError(f"not found: {repo}/{path}")

    monkeypatch.setattr(chat, "read_file", fake_read)  # undone automatically after each test
    monkeypatch.setattr(chat, "list_dir", fake_list)
    monkeypatch.setattr(
        chat, "repo_info", lambda repo, **kw: info or {"repo": repo, "language": "Go"}
    )
    svc = chat.ChatService.__new__(chat.ChatService)
    svc.repo_cache, svc.github_token = None, None
    return svc


def test_there_are_three_tools_and_templates_is_optional(monkeypatch):
    from semcache.chat import ChatService

    svc = _svc_with_repo_stubs(monkeypatch)
    assert set(ChatService._tools(svc, [], with_templates=True)) == {"search", "repo", "templates"}
    assert set(ChatService._tools(svc, [], with_templates=False)) == {"search", "repo"}


def test_repo_tool_does_info_folder_and_file(monkeypatch):
    from semcache.chat import ChatService

    root = [
        {"name": "docker", "type": "dir", "size": 0},
        {"name": "README.md", "type": "file", "size": 9},
    ]
    svc = _svc_with_repo_stubs(
        monkeypatch,
        files={"docker/docker-compose.yaml": "services: {}"},
        dirs={"": root, "docker": [{"name": "docker-compose.yaml", "type": "file", "size": 12}]},
    )
    seen: list[dict] = []
    repo = ChatService._tools(svc, seen)["repo"]
    out = repo.invoke({"repo": "o/r"})
    assert out.startswith("INFO ") and '"language": "Go"' in out and "dir  docker/" in out
    assert "DIR o/r/docker" in repo.invoke({"repo": "o/r", "path": "docker"})  # folder -> listing
    assert "FILE o/r/docker/docker-compose.yaml" in repo.invoke(
        {"repo": "o/r", "path": "/docker/docker-compose.yaml/"}
    )
    assert "untrusted data" in repo.invoke({"repo": "o/r", "path": "docker/docker-compose.yaml"})
    with pytest.raises(ValueError, match="not found"):  # neither a file nor a folder
        repo.invoke({"repo": "o/r", "path": "nope"})
    assert all(s["inspected"] and s["name"] == "o/r" for s in seen)


def test_search_tool_index_vs_github(monkeypatch):
    import numpy as np

    from semcache.chat import ChatService

    class Cat:
        def search(self, vec, kind, k=0):
            return [{"name": "x/y", "stars": 1, "novelty": "0.2"}]

    class Emb:
        def embed(self, text):
            return np.zeros(2, dtype=np.float32)

    svc = _svc_with_repo_stubs(monkeypatch)
    svc.catalog, svc.embedder = Cat(), Emb()
    svc.search = lambda q: {"results": [{"name": "g/h"}], "cache_hit": None, "crawled": 3}
    seen: list[dict] = []
    search = ChatService._tools(svc, seen)["search"]
    assert "Local index (no GitHub call)" in search.invoke({"query": "x", "where": "index"})
    assert "GitHub searched: 3 repos" in search.invoke({"query": "x"})  # github is the default
    assert [s["name"] for s in seen] == ["x/y", "g/h"]


def test_big_root_listing_is_capped():
    from semcache.chat import ROOT_LISTING_CAP, fmt_listing

    rows = [{"name": f"f{i}", "type": "file", "size": 1} for i in range(200)]
    out = fmt_listing(rows, ROOT_LISTING_CAP)
    assert out.count("\n") == ROOT_LISTING_CAP and "and 160 more" in out
    assert fmt_listing(rows[:5], ROOT_LISTING_CAP).count("\n") == 4  # small roots untouched
    assert "more" not in fmt_listing(rows)  # folder listings are not capped
    assert fmt_listing([]) == "(empty)"


def test_fact_rules_skip_the_pointless_search():
    from semcache.chat import FACT_RULES

    assert "call repo(owner/name) directly" in FACT_RULES and "do not search first" in FACT_RULES


# ---- chit-chat must not become a GitHub search -----------------------------------------------------
def test_conversational_phrases_are_not_topics_to_search():
    from semcache.routes import looks_like_topic

    for chat in ("that's really helpful, thanks", "nice one", "good morning", "hmm interesting",
                 "you're awesome", "never mind", "lol", "sorry, I misread that", "cool", "ok thanks"):  # fmt: skip
        assert not looks_like_topic(chat), chat
    for topic in ("observability tools", "diary apps?", "feature flags", "Durable functions",
                  "headless CMS", "something like dayone"):  # fmt: skip
        assert looks_like_topic(topic), topic
    for question in ("what do you think?", "why?", "are you sure?", "how does it work"):
        assert not looks_like_topic(question), question  # questions are not topic searches


def test_smalltalk_has_examples_for_reactions_and_clarifications():
    from semcache.routes import ROUTES

    ex = " | ".join(ROUTES["smalltalk"].exemplars).lower()
    for needle in ("thanks", "lol", "good morning", "what do you mean by that", "explain that",
                   "tell me more", "why did you pick that one", "never mind"):  # fmt: skip
        assert needle in ex, needle
    assert len(ROUTES["smalltalk"].exemplars) >= 30
    # nothing in a route's examples may be shared with another route (it would make routing a coin flip)
    seen: dict[str, str] = {}
    for name, route in ROUTES.items():
        for e in route.exemplars:
            assert seen.setdefault(e.lower(), name) == name, (
                f"{e!r} in {seen[e.lower()]} and {name}"
            )
