"""Everything on the gateway: the startup model check, the repo name given to the model, and the
cost accounting fixes found in the audit."""

from types import SimpleNamespace

import httpx
import pytest
from test_decide import MODELS, service

from semcache.chat import ChatService
from semcache.cost import CostStats, Pricing
from semcache.decide import Decision
from semcache.modelcheck import check, configured_models, gateway_models
from semcache.tunables import ModelPrice, load_tunables


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---- startup model check --------------------------------------------------------------------------
def models_ok(ids):
    return client(lambda r: httpx.Response(200, json={"data": [{"id": i} for i in ids]}))


def test_configured_models_covers_every_selectable_model():
    t = load_tunables("settings.toml")
    names = configured_models(t)
    r = t.routing
    assert {r.models.hit, r.models.classifier, r.models.miss, r.followup_model} <= names
    assert set(r.pin.values()) <= names
    expected = {r.models.hit, r.models.classifier, r.models.miss, r.followup_model, *r.pin.values()}
    assert r.plan_routes == [] and names == expected  # planning is off: its model is not required
    on = t.model_copy(update={"routing": r.model_copy(update={"plan_routes": ["inspect"],
                                                           "planner_model": "some-planner"})})  # fmt: skip
    assert "some-planner" in configured_models(on)  # ...but is required as soon as a route plans


def test_every_model_in_the_real_settings_is_on_the_gateway_list():
    """The gateway as of this change: the models the shipped settings.toml names."""
    t = load_tunables("settings.toml")
    served = {"claude-haiku-4-5", "claude-sonnet-5-5", "qwen3-32b", "gpt-oss-20b"}
    assert check(t, "http://g/v1", "k", models_ok(served)) == {"checked": True, "missing": []}


def test_a_missing_model_is_named():
    t = load_tunables("settings.toml")
    out = check(t, "http://g/v1", "k", models_ok({"claude-haiku-4-5", "claude-sonnet-5-5"}))
    assert out == {"checked": True, "missing": ["qwen3-32b"]}


def test_an_unreachable_or_unauthorized_gateway_is_reported_not_raised():
    t = load_tunables("settings.toml")

    def refuse(req):
        raise httpx.ConnectError("refused", request=req)

    assert check(t, "http://g/v1", "k", client(refuse)) == {"checked": False, "missing": []}
    assert gateway_models("http://g/v1", "k", client(lambda r: httpx.Response(401))) is None
    assert (
        gateway_models("http://g/v1", "k", client(lambda r: httpx.Response(200, json={}))) is None
    )


def test_the_check_sends_the_key_to_the_models_url():
    seen = {}

    def handler(req):
        seen.update(url=str(req.url), auth=req.headers["authorization"])
        return httpx.Response(200, json={"data": []})

    gateway_models("https://gw.example/v1/", "secret", client(handler))
    assert seen == {"url": "https://gw.example/v1/models", "auth": "Bearer secret"}


# ---- the model is told which repo ---------------------------------------------------------------------
def test_the_classifier_resolved_repo_reaches_the_model():
    svc = service(reply='{"kind": "repo", "repo": "langgenius/dify"}', known={"langgenius/dify"})
    d = svc._decide([], "what language is Dify written in?", {"in": 0, "out": 0})
    assert d.repo == "langgenius/dify" and d.route == "inspect"
    ctx, _ = svc._context("inspect", "x", [], repo=d.repo)
    assert "langgenius/dify" in ctx and "do not guess another owner" in ctx
    assert svc._context("inspect", "x", [], repo="")[0] == ""  # nothing resolved: no made-up claim


def test_a_search_or_chat_classification_carries_no_repo():
    d = service(reply='{"kind": "search", "query": "diary apps"}')._decide(
        [], "x", {"in": 0, "out": 0}
    )
    assert d.repo == ""


# ---- cost accounting ----------------------------------------------------------------------------------
def priced_service():
    svc = ChatService.__new__(ChatService)
    svc.pricing = Pricing({"haiku": ModelPrice(input_per_mtok=1, output_per_mtok=5),
                           "sonnet": ModelPrice(input_per_mtok=3, output_per_mtok=15)})  # fmt: skip
    svc.models, svc.baseline_model = SimpleNamespace(classifier="haiku"), "sonnet"
    svc.stats = CostStats(FakeStats())
    return svc


class FakeStats:
    def __init__(self):
        self.h = {}

    def pipeline(self):
        return self

    def hincrbyfloat(self, k, f, v):
        self.h[f] = float(self.h.get(f, 0)) + v

    def hincrby(self, k, f, v):
        self.h[f] = int(self.h.get(f, 0)) + v

    def execute(self):
        pass

    def hgetall(self, k):
        return {f.encode(): str(v).encode() for f, v in self.h.items()}


def test_an_answer_cache_hit_still_pays_for_the_classifier_that_ran_first():
    svc = priced_service()
    classify = {"in": 1_000_000, "out": 100_000}  # 1M in + 0.1M out on haiku = $1.50
    ev = svc._cost_event(
        "sonnet", "miss", {"in": 0, "out": 0}, cache_hit=True, avoided=0.04,
        planner="haiku", planner_usage=classify,
    )  # fmt: skip
    assert ev["usd"] == pytest.approx(1.5) and ev["saved_usd"] == 0.04 and ev["saved_by"] == "cache"
    plain = svc._cost_event("sonnet", "miss", {"in": 0, "out": 0}, cache_hit=True, avoided=0.04)
    assert plain["usd"] == 0.0  # no classifier ran: a hit is free, as before


def test_a_failed_or_empty_turn_still_records_what_it_spent():
    svc = priced_service()
    d = Decision("find", "sonnet", "miss", "x", 0.4, classifier_used=True)
    svc._record_unanswered("sonnet", {"in": 1_000_000, "out": 0}, d, {"in": 1_000_000, "out": 0})
    totals = svc.stats.totals()
    assert totals["spent_usd"] == pytest.approx(3.0 + 1.0)  # sonnet input + classifier input
    assert totals["requests"] == 1 and totals["cache_hits"] == 0
    svc._record_unanswered("sonnet", {"in": 0, "out": 0}, Decision("find", "s", "hit", "x", 0), {})
    assert svc.stats.totals()["requests"] == 1  # nothing spent, nothing recorded


def test_prices_exist_for_every_model_the_settings_can_pick():
    t = load_tunables("settings.toml")
    missing = [m for m in configured_models(t) if m not in t.cost.models]
    assert missing == [], f"no price set for {missing}"
    assert MODELS.miss  # fixture sanity
