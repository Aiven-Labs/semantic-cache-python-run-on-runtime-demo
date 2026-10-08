"""The routing benchmark harness, run against fakes (no Valkey, embeddings or classifier)."""

import json
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from semcache.bench import STRATEGIES, run, summarize

DATA = Path(__file__).parent.parent / "benchmarks" / "routing.jsonl"
VOTE = SimpleNamespace(k=5, min_share=0.6, min_samples=5, spread=2.0)


class Emb:
    """Bag of words hashed into 64 dims: texts sharing words land close together."""

    def embed(self, text):
        v = np.zeros(64, dtype=np.float32)
        for w in text.lower().replace("?", "").split():
            v[zlib.crc32(w.encode()) % 64] += 1
        return v / (np.linalg.norm(v) or 1.0)


class MemCatalog:
    def __init__(self):
        self.docs, self.stats = {}, {}

    def exists(self, kind, ident):
        return (kind, ident) in self.docs

    def upsert(self, kind, ident, vec, fields):
        self.docs[(kind, ident)] = (vec, fields)

    def search(self, vec, kind, services=None, k=10):
        rows = [
            {**f, "distance": float(1 - vec @ v)}
            for (kd, _), (v, f) in self.docs.items()
            if kd == kind
        ]
        return sorted(rows, key=lambda r: r["distance"])[:k]

    def route_stats(self, route):
        xs = self.stats.get(route, [])
        return len(xs), float(np.mean(xs)) if xs else 0.0, float(np.std(xs)) if xs else 0.0

    def add_route_sample(self, route, distance):
        self.stats.setdefault(route, []).append(distance)


TRUTH_TO_KIND = {"find": "search", "inspect": "repo", "smalltalk": "chat",
                 "analysis": "analysis", "agent": "other"}  # fmt: skip


def perfect_classifier(items):
    kinds = {i["text"]: TRUTH_TO_KIND[i["route"]] for i in items}
    return lambda text: (kinds[text], 0.2)


def items():
    return [json.loads(line) for line in DATA.read_text().splitlines() if line]


def test_dataset_is_labeled_with_routes_the_classifier_can_produce():
    rows = items()
    assert len(rows) >= 90 and len({r["text"] for r in rows}) == len(rows)
    assert {r["route"] for r in rows} == set(TRUTH_TO_KIND)


def test_every_strategy_scores_every_message_once():
    rows = items()
    for strategy in STRATEGIES:
        out = run(strategy, rows, MemCatalog(), Emb(), perfect_classifier(rows), VOTE, seed=1)
        assert sorted(r["text"] for r in out) == sorted(r["text"] for r in rows)
        s = summarize(out)
        assert s["n"] == len(rows) and 0 <= s["accuracy"] <= 1


def paraphrases():
    """Two routes, each a family of near-identical phrasings (cosine distance ~0.2 inside a family)."""
    fam = {"find": "find self hosted feature flag", "smalltalk": "thanks that really helps me"}
    return [
        {"text": f"{base} {w}", "route": route}
        for route, base in fam.items()
        for w in "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu".split()
    ]


def test_history_strategies_start_cold_and_call_the_classifier_first():
    rows = paraphrases()
    for strategy in ("history-fixed", "history-vote"):
        out = run(strategy, rows, MemCatalog(), Emb(), perfect_classifier(rows), VOTE, seed=1)
        assert out[0]["called"]  # nothing learned yet


def test_history_routing_learns_and_calls_the_classifier_less_over_time():
    rows = paraphrases()
    for strategy in ("history-fixed", "history-vote"):
        out = run(strategy, rows, MemCatalog(), Emb(), perfect_classifier(rows), VOTE, seed=2)
        s = summarize(out)
        assert s["classifier_calls"] < s["n"]  # remembered questions replaced classifier calls
        assert s["by_third"]["last"]["classifier_rate"] < s["by_third"]["first"]["classifier_rate"]
        assert s["accuracy"] > 0.9  # a perfect classifier teaches the router the right routes


def test_the_old_router_does_not_learn():
    rows = paraphrases()
    out = run("examples", rows, MemCatalog(), Emb(), perfect_classifier(rows), VOTE, seed=2)
    first, last = summarize(out)["by_third"]["first"], summarize(out)["by_third"]["last"]
    assert abs(first["classifier_rate"] - last["classifier_rate"]) < 0.5
