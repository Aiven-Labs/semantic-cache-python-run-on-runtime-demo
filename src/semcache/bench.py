"""Replay labeled chat messages through a routing strategy and score it.

Three strategies, each starting from an empty history:
  examples      the old router: nearest hand-written exemplar, fixed distance cutoff
  history-fixed nearest earlier question, same fixed cutoff
  history-vote  k nearest earlier questions vote; each route's cutoff is learned

A message the router does not match goes to the classifier, like production. Its answer is what
gets stored as history (not the truth), so classifier mistakes can teach the router, as they would
live. `classify(text)` returns (kind, seconds).
"""

import random
from collections.abc import Callable

from .catalog import Catalog
from .decide import KIND_TO_ROUTE
from .embed import Embedder
from .routes import match_route, record_turn, seed_routes, vote_match

STRATEGIES = ("examples", "history-fixed", "history-vote")
FIXED_CUTOFF, FIXED_LIMITS = 0.25, {"smalltalk": 0.28}  # the constants the old router shipped with
COARSE = {"lookup": "find", "repo_facts": "inspect"}  # the classifier has no kinds for these


def run(
    strategy: str,
    items: list[dict],
    catalog: Catalog,
    embedder: Embedder,
    classify: Callable[[str], tuple[str, float]],
    vote_cfg,
    *,
    seed: int = 0,
) -> list[dict]:
    if strategy == "examples":
        seed_routes(catalog, embedder)
    order = random.Random(seed).sample(items, len(items))
    out = []
    for it in order:
        text = it["text"]
        if strategy == "history-vote":
            route, dist = vote_match(catalog, embedder, text, vote_cfg)
        else:
            kind = "route" if strategy == "examples" else "turn"
            hits = catalog.search(embedder.embed(text), kind, k=1)
            route, dist = match_route(hits, FIXED_CUTOFF, FIXED_LIMITS)
        called, seconds = route is None, 0.0
        if called:
            kind_name, seconds = classify(text)
            route = KIND_TO_ROUTE[kind_name]
            if strategy != "examples":
                record_turn(catalog, embedder, text, route, "", "miss")
        route = COARSE.get(route, route)
        out.append(
            {"text": text, "truth": it["route"], "predicted": route, "called": called,
             "distance": round(dist, 3), "classify_s": seconds}
        )  # fmt: skip
    return out


def _rate(rows: list[dict], pred: Callable[[dict], bool]) -> float:
    return sum(1 for r in rows if pred(r)) / len(rows) if rows else 0.0


def summarize(rows: list[dict]) -> dict:
    """Accuracy, how often the classifier ran, and how often the router was confidently wrong."""
    third = max(1, len(rows) // 3)
    parts = {"first": rows[:third], "middle": rows[third : 2 * third], "last": rows[2 * third :]}
    ok = lambda r: r["predicted"] == r["truth"]  # noqa: E731
    matched = [r for r in rows if not r["called"]]
    return {
        "n": len(rows),
        "accuracy": _rate(rows, ok),
        "classifier_calls": sum(r["called"] for r in rows),
        "classifier_rate": _rate(rows, lambda r: r["called"]),
        "router_matches": len(matched),
        "router_accuracy": _rate(matched, ok),
        "confident_errors": sum(1 for r in matched if not ok(r)),
        "classifier_seconds": sum(r["classify_s"] for r in rows),
        "by_third": {
            k: {"accuracy": _rate(v, ok), "classifier_rate": _rate(v, lambda r: r["called"])}
            for k, v in parts.items()
        },
    }
