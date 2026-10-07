from types import SimpleNamespace

import numpy as np
import pytest
from test_details import FakeR

from semcache.chat import ChatService
from semcache.decide import (
    CLASSIFY_PROMPT,
    KIND_TO_ROUTE,
    choose_model,
    hit_or_miss,
    index_covers,
    parse_classification,
)
from semcache.repocache import RepoCache

MODELS = SimpleNamespace(hit="free-local", classifier="haiku", miss="sonnet")
COVERAGE = SimpleNamespace(index_hit_distance=0.30, index_hit_min=3)
EXPENSIVE = {"analysis"}


# ---- the classifier's reply ---------------------------------------------------------------------
def test_parse_classification_accepts_clean_and_noisy_replies():
    assert parse_classification('{"kind": "search", "query": "diary apps", "repo": ""}') == {
        "kind": "search", "query": "diary apps", "repo": "",
    }  # fmt: skip
    noisy = '<think>hmm</think> Sure! ```json\n{"kind": "REPO", "query": "", "repo": "a/b"}\n```'
    assert parse_classification(noisy) == {"kind": "repo", "query": "", "repo": "a/b"}


def test_parse_classification_never_trusts_the_model():
    other = {"kind": "other", "query": "", "repo": ""}
    for bad in ("", "no json here", "{broken", "[1, 2]", '{"kind": "delete everything"}', None):
        assert parse_classification(bad) == other
    assert parse_classification('{"kind": "repo", "repo": "../x"}')["repo"] == ""
    assert parse_classification('{"kind": "repo", "repo": "not a repo"}')["repo"] == ""
    assert parse_classification('{"kind": "search", "query": "  a   b  "}')["query"] == "a b"
    long = parse_classification('{"kind": "search", "query": "' + "x" * 500 + '"}')["query"]
    assert len(long) == 80


def test_every_kind_the_prompt_offers_has_a_route():
    for kind in ("chat", "search", "repo", "analysis", "other"):
        assert f'"{kind}"' in CLASSIFY_PROMPT and kind in KIND_TO_ROUTE
    assert set(KIND_TO_ROUTE.values()) == {"smalltalk", "find", "inspect", "analysis", "agent"}


# ---- the rules ----------------------------------------------------------------------------------
def test_index_covers():
    assert index_covers([0.1, 0.2, 0.3], 0.30, 3)  # the boundary counts
    assert not index_covers([0.1, 0.2, 0.31], 0.30, 3)
    assert not index_covers([], 0.30, 3)


def test_choose_model():
    assert choose_model(True, "find", MODELS, {}, EXPENSIVE) == ("free-local", "hit")
    assert choose_model(False, "find", MODELS, {}, EXPENSIVE) == ("sonnet", "miss")
    assert choose_model(True, "analysis", MODELS, {}, EXPENSIVE) == ("sonnet", "miss")  # reasoning
    assert choose_model(True, "repo_facts", MODELS, {"repo_facts": "haiku"}, EXPENSIVE) == (
        "haiku", "pinned",
    )  # fmt: skip
    assert choose_model(False, "analysis", MODELS, {"analysis": "x"}, EXPENSIVE) == ("x", "pinned")


@pytest.mark.parametrize(
    "route, matched, covered, hit",
    [
        ("smalltalk", True, False, True),
        ("lookup", True, False, True),
        ("find", True, False, True),  # router matched: a hit even if GitHub is queried
        ("analysis", True, False, False),  # matched, but it is reasoning
        ("smalltalk", False, False, True),  # classifier: conversation
        ("find", False, True, True),  # classifier: search, cache covers it
        ("find", False, False, False),  # classifier: search, GitHub must be queried
        ("inspect", False, True, True),
        ("inspect", False, False, False),
        ("agent", False, False, False),
        ("analysis", False, True, False),
    ],
)
def test_hit_or_miss_matrix(route, matched, covered, hit):
    got, reason = hit_or_miss(route, matched=matched, covered=covered, always_expensive=EXPENSIVE)
    assert got is hit and reason  # always explains itself


# ---- the whole decision, with fake services -------------------------------------------------------
class Cat:
    def __init__(self, route_hits=None, candidates=None, known=()):
        self.route_hits, self.candidates, self.known = (
            route_hits or [],
            candidates or [],
            set(known),
        )

    def search(self, vec, kind, services=None, k=10):
        return self.route_hits if kind == "turn" else self.candidates

    def route_stats(self, route):  # a route whose questions sit about 0.2 apart, +/- 0.025
        return 30, 0.2, 0.025

    def get(self, kind, name):
        return {"name": name, "compose_path": ""} if name in self.known else None


class Emb:
    def embed(self, text):
        return np.zeros(2, dtype=np.float32)


class LLM:
    """A classifier model that replies with canned text and counts its calls."""

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def bind(self, **kw):
        return self

    def invoke(self, msgs):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(
            content=self.reply, usage_metadata={"input_tokens": 300, "output_tokens": 25}
        )


def service(*, route_hits=None, candidates=None, reply='{"kind": "other"}', cached_search=False,
            known=(), pins=None):  # fmt: skip
    svc = ChatService.__new__(ChatService)
    svc.catalog = Cat(route_hits, candidates, known)
    svc.embedder = Emb()
    svc.llm = LLM(reply)
    svc.llm_for = lambda name: svc.llm
    svc.models, svc.coverage, svc.baseline_model = MODELS, COVERAGE, "sonnet"
    svc.always_expensive, svc.route_pins = EXPENSIVE, pins or {}
    svc.search_cached = lambda q: cached_search
    svc.route_vote = SimpleNamespace(k=5, min_share=0.6, min_samples=5, spread=2.0)
    svc.followup_max_words, svc.followup_model = 8, "haiku"
    svc.repo_cache = RepoCache(FakeR(), 60)
    return svc


def decide(svc, message="x", history=None):
    usage = {"in": 0, "out": 0}
    return svc._decide(history or [], message, usage), usage


def near(name, d=0.05):
    return [{"name": name, "distance": d}]


def test_a_confident_router_match_is_a_hit_and_skips_the_classifier():
    svc = service(route_hits=near("smalltalk"))
    d, usage = decide(svc, "thanks")
    assert (d.route, d.tier, d.model, d.classifier_used) == (
        "smalltalk",
        "hit",
        "free-local",
        False,
    )
    assert svc.llm.calls == 0 and usage == {"in": 0, "out": 0}  # a match costs nothing extra
    assert "router matched smalltalk" in d.reason and "0.05" in d.reason


def test_matched_analysis_is_always_a_miss():
    d, _ = decide(service(route_hits=near("analysis")), "compare these")
    assert (d.route, d.tier, d.model) == ("analysis", "miss", "sonnet")


def test_pins_beat_hit_and_miss():
    d, _ = decide(service(route_hits=near("repo_facts"), pins={"repo_facts": "haiku"}), "language?")
    assert (d.tier, d.model) == ("pinned", "haiku")


def test_unmatched_chit_chat_is_a_hit_and_costs_one_small_classifier_call():
    svc = service(route_hits=near("smalltalk", 0.9), reply='{"kind": "chat"}')
    d, usage = decide(svc, "oh i see")
    assert (d.route, d.tier, d.model, d.classifier_used) == ("smalltalk", "hit", "free-local", True)
    assert svc.llm.calls == 1 and usage == {"in": 300, "out": 25}  # tokens are counted for cost
    assert "classifier: conversation" in d.reason


def test_unmatched_search_is_a_hit_when_a_similar_search_is_cached():
    svc = service(
        route_hits=[], reply='{"kind": "search", "query": "diary apps"}', cached_search=True
    )
    d, _ = decide(svc, "diary apps?")
    assert (d.route, d.tier, d.model, d.query) == ("find", "hit", "free-local", "diary apps")


def test_unmatched_search_is_a_hit_when_the_index_has_enough_close_repos():
    close = [{"name": f"o/r{i}", "distance": 0.2} for i in range(3)]
    svc = service(reply='{"kind": "search", "query": "diary apps"}', candidates=close)
    assert decide(svc)[0].tier == "hit"
    two = close[:2] + [{"name": "o/far", "distance": 0.6}]
    svc = service(reply='{"kind": "search", "query": "diary apps"}', candidates=two)
    d, _ = decide(svc)
    assert (d.tier, d.model) == ("miss", "sonnet") and "GitHub must be queried" in d.reason


def test_unmatched_repo_question_hits_only_when_its_details_are_cached():
    reply = '{"kind": "repo", "repo": "o/r"}'
    svc = service(reply=reply, known={"o/r"})
    assert decide(svc)[0].tier == "miss"  # nothing cached yet
    svc.repo_cache.put("info", "o/r", "", {})
    assert decide(svc)[0].tier == "miss"  # root folder still missing
    svc.repo_cache.put("ls", "o/r", "", [])
    d, _ = decide(svc)
    assert (d.route, d.tier, d.model) == ("inspect", "hit", "free-local")
    unknown = service(reply='{"kind": "repo", "repo": "nobody/nothing"}')
    assert decide(unknown)[0].tier == "miss"  # not even indexed


def test_unmatched_analysis_and_open_ended_are_misses():
    for reply, route in (('{"kind": "analysis"}', "analysis"), ('{"kind": "other"}', "agent")):
        d, _ = decide(service(reply=reply))
        assert (d.route, d.tier, d.model) == (route, "miss", "sonnet")


def test_a_broken_classifier_falls_back_to_the_mid_tier_model_not_a_crash():
    for reply in (RuntimeError("gateway down"), "I think this is a search", ""):
        d, _ = decide(service(reply=reply))
        if isinstance(reply, Exception):
            assert (d.route, d.model, d.tier) == ("agent", "haiku", "miss")
            assert "classifier unavailable" in d.reason
        else:
            assert d.route == "agent" and d.tier == "miss"  # unparsable -> kind "other"


def test_short_follow_ups_reuse_the_previous_route_without_calling_the_classifier():
    hist = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a", "route": "inspect"},
    ]
    svc = service(route_hits=[])
    d, _ = decide(svc, "and the web ui?", hist)
    assert (d.route, d.tier, d.model) == ("inspect", "follow-up", "haiku")
    assert svc.llm.calls == 0
    d, _ = decide(
        svc, "please compare popular project management tools in detail for me today", hist
    )
    assert d.tier != "follow-up"  # a long, new question is classified instead


def test_classifier_search_words_drive_the_search():
    from semcache.chat import extract_query

    svc = service()
    svc._search = lambda q: ([{"name": f"found/{q}"}], "status")
    ctx, note = svc._context("find", "ha, anything like dayone?", [], query="journaling apps")
    assert "found/journaling apps" in ctx and 'search "journaling apps"' in note
    ctx2, _ = svc._context("find", "find me feature flags", [], query="")
    assert f"found/{extract_query('find me feature flags')}" in ctx2  # no classifier: old behavior


# ---- Jev as the classifier ----------------------------------------------------------------------
class FakeJev:
    """Stands in for JevClassifier: canned kind, or an exception."""

    model = "jev-latest"

    def __init__(self, kind="other", error=None):
        self.kind, self.error = kind, error

    def classify(self, history, message, usage):
        if self.error:
            raise self.error
        usage["in"] += 40
        return {"kind": self.kind, "query": "", "repo": ""}


def jev_service(kind="other", error=None, **kw):
    svc = service(**kw)
    svc.jev = FakeJev(kind, error)
    return svc


def test_jev_classifies_without_calling_the_gateway_model():
    svc = jev_service("chat")
    d, usage = decide(svc)
    assert (d.route, d.tier, d.classifier_used) == ("smalltalk", "hit", True)
    assert svc.llm.calls == 0 and usage["in"] == 40
    assert svc.classifier_name == "jev-latest"
    assert "router missed at" in d.reason  # the distance is the router's miss, not Jev's


def test_a_jev_search_gets_its_words_so_the_cache_can_cover_it():
    svc = jev_service("search", cached_search=True)
    d, _ = decide(svc, "find me popular otel collectors")
    assert (d.route, d.tier, d.query) == ("find", "hit", "otel collectors")


def test_a_jev_repo_answer_gets_its_repo_from_the_catalog():
    svc = jev_service(
        "repo", candidates=[{"name": "langgenius/dify", "distance": 0.1}], known={"langgenius/dify"}
    )
    d, _ = decide(svc, "what language is Dify written in?")
    assert (d.route, d.repo) == ("inspect", "langgenius/dify")


def test_a_repo_name_that_is_not_in_the_message_is_not_guessed():
    svc = jev_service("repo", candidates=[{"name": "langgenius/dify", "distance": 0.1}])
    d, _ = decide(svc, "what language is it written in?")
    assert d.route == "inspect" and d.repo == ""


def test_a_jev_failure_falls_back_to_the_mid_tier_model():
    d, _ = decide(jev_service(error=RuntimeError("boom")))
    assert (d.route, d.model, d.classifier_used) == ("agent", "haiku", False)
    assert "classifier unavailable" in d.reason
