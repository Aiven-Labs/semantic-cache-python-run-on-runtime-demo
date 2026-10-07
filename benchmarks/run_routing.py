"""Live routing benchmark. Needs Valkey (with search), the embeddings server and TYPESAFE_API_KEY.

    fnox exec -- env PYTHONPATH=src uv run python benchmarks/run_routing.py [--seeds 3]

Jev's answers are cached in benchmarks/jev_cache.json, so a rerun only calls Jev for new messages
and the three strategies see identical classifier answers. Uses its own index and key prefix and
never touches the app's data.
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import valkey

from semcache.bench import STRATEGIES, run, summarize
from semcache.catalog import Catalog
from semcache.config import settings, tunables
from semcache.embed import LangChainEmbedder
from semcache.jev import JevClassifier

HERE = Path(__file__).parent
INDEX, PREFIX = "idx:bench", "bench:"


def fresh_catalog(client: valkey.Valkey) -> Catalog:
    try:
        client.execute_command("FT.DROPINDEX", INDEX)
    except valkey.ResponseError:
        pass
    for pattern in (f"{PREFIX}*", f"stats:{PREFIX}*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
    cat = Catalog(client, index=INDEX, prefix=PREFIX, dim=settings.embed_dim)
    cat.ensure_index()
    return cat


def sweep(items, client, embedder, classify, seeds: int) -> None:
    """How sensitive is the vote router to its two knobs? Same messages, same Jev answers."""
    out = []
    for spread in (0.5, 1.0, 2.0):
        for min_share in (0.6, 0.8, 1.0):
            cfg = tunables.routing.vote.model_copy(
                update={"spread": spread, "min_share": min_share}
            )
            sums = []
            for seed in range(seeds):
                catalog = fresh_catalog(client)
                rows = run("history-vote", items, catalog, embedder, classify, cfg, seed=seed)
                sums.append(summarize(rows))
            row = {"spread": spread, "min_share": min_share} | {
                k: round(statistics.mean(x[k] for x in sums), 3)
                for k in ("accuracy", "classifier_rate", "confident_errors")
            }
            out.append(row)
            print(row)
    (HERE / "sweep.json").write_text(json.dumps(out, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default=str(HERE / "results.json"))
    ap.add_argument("--sweep", action="store_true", help="vary the vote knobs; writes sweep.json")
    args = ap.parse_args()

    items = [json.loads(line) for line in (HERE / "routing.jsonl").read_text().splitlines() if line]
    cache_path = HERE / "jev_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    jev = JevClassifier(
        model=tunables.routing.jev.model, min_confidence=0.0
    )  # benchmark wants Jev's raw answer, not a fallback

    def classify(text: str) -> tuple[str, float]:
        if text not in cache:
            t0 = time.monotonic()
            kind = jev.classify([], text, {"in": 0, "out": 0})["kind"]
            cache[text] = {"kind": kind, "seconds": time.monotonic() - t0}
            cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
        return cache[text]["kind"], cache[text]["seconds"]

    client = valkey.from_url(settings.valkey_url)
    embedder = LangChainEmbedder(
        settings.embed_model, settings.embed_base_url, settings.embed_api_key
    )
    if args.sweep:
        sweep(items, client, embedder, classify, args.seeds)
        return
    result: dict = {"messages": len(items), "seeds": args.seeds, "strategies": {}}
    for strategy in STRATEGIES:
        runs = []
        for seed in range(args.seeds):
            rows = run(
                strategy, items, fresh_catalog(client), embedder, classify,
                tunables.routing.vote, seed=seed,
            )  # fmt: skip
            runs.append({"summary": summarize(rows), "rows": rows})
        keys = ["accuracy", "classifier_rate", "router_accuracy", "confident_errors"]
        result["strategies"][strategy] = {
            k: round(statistics.mean(r["summary"][k] for r in runs), 3) for k in keys
        } | {"runs": runs}
        print(strategy, {k: result["strategies"][strategy][k] for k in keys})
    Path(args.out).write_text(json.dumps(result, indent=1))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
