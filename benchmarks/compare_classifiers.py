"""Jev vs a general model (the gateway classifier) on the same 93 labeled messages.

    fnox exec -- env PYTHONPATH=src uv run python benchmarks/compare_classifiers.py

Both get the message with no history, the way the routing benchmark sends it. Writes
benchmarks/classifier_compare.json with every answer, latency and token count.
"""

import json
import statistics
import time
from pathlib import Path

from langchain_openai import ChatOpenAI

from semcache.config import settings, tunables
from semcache.decide import CLASSIFY_PROMPT, KIND_TO_ROUTE, parse_classification
from semcache.jev import JevClassifier

HERE = Path(__file__).parent


def via_model(llm, text: str) -> dict:
    prompt = f"{CLASSIFY_PROMPT}\n\nRecent conversation:\n(none)\n\nLatest message: {text}"
    t0 = time.monotonic()
    out = llm.invoke([("human", prompt)])
    seconds = time.monotonic() - t0
    um = out.usage_metadata or {}
    parsed = parse_classification(out.content if isinstance(out.content, str) else "")
    return {
        "kind": parsed["kind"], "query": parsed["query"], "seconds": seconds,
        "in": um.get("input_tokens", 0), "out": um.get("output_tokens", 0),
    }  # fmt: skip


def via_jev(jev: JevClassifier, text: str) -> dict:
    usage = {"in": 0, "out": 0}
    t0 = time.monotonic()
    state = f"Recent conversation:\n(none)\n\nLatest message: {text}"
    from typesafe_sdk import Choice

    from semcache.jev import CRITERIA, INSTRUCTIONS

    resp = jev.client.system_one(
        state=state,
        questions={"kind": Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)},
        model=jev.model,
    )
    seconds = time.monotonic() - t0
    a = resp.answers["kind"]
    usage["in"], usage["out"] = resp.usage.input_tokens or 0, resp.usage.output_tokens or 0
    kind = a.choice if a.choice in KIND_TO_ROUTE else "other"
    return {"kind": kind, "confidence": a.confidence, "seconds": seconds, **usage}


def summarize(rows: list[dict], items: list[dict], model: str) -> dict:
    price = tunables.cost.models[model]
    right = sum(KIND_TO_ROUTE[r["kind"]] == i["route"] for r, i in zip(rows, items, strict=True))
    secs = sorted(r["seconds"] for r in rows)
    usd = sum(r["in"] * price.input_per_mtok + r["out"] * price.output_per_mtok for r in rows) / 1e6
    return {
        "model": model,
        "accuracy": round(right / len(rows), 3),
        "mean_s": round(statistics.mean(secs), 3),
        "p95_s": round(secs[int(len(secs) * 0.95) - 1], 3),
        "mean_in_tokens": round(statistics.mean(r["in"] for r in rows)),
        "mean_out_tokens": round(statistics.mean(r["out"] for r in rows), 1),
        "usd_per_1000": round(usd / len(rows) * 1000, 4),
    }


def add_model(name: str) -> None:
    """Run one more gateway model through the same prompt and add it to classifier_compare.json,
    leaving the Jev and mid-tier rows from the earlier run untouched."""
    path = HERE / "classifier_compare.json"
    result = json.loads(path.read_text())
    items = [json.loads(line) for line in (HERE / "routing.jsonl").read_text().splitlines() if line]
    llm = ChatOpenAI(
        model=name, base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=120
    ).bind(max_tokens=120)
    rows = [via_model(llm, i["text"]) for i in items]
    result[name] = summarize(rows, items, name)
    result[name]["unparsed"] = sum(r["kind"] == "other" and r["out"] >= 119 for r in rows)
    result["rows"][name] = rows
    path.write_text(json.dumps(result, indent=1))
    print(json.dumps(result[name], indent=1))


def main() -> None:
    import sys

    if len(sys.argv) > 2 and sys.argv[1] == "--add":
        return add_model(sys.argv[2])
    items = [json.loads(line) for line in (HERE / "routing.jsonl").read_text().splitlines() if line]
    jev = JevClassifier(model=tunables.routing.jev.model, min_confidence=0.0)
    model_name = tunables.routing.models.classifier
    llm = ChatOpenAI(
        model=model_name, base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=120
    ).bind(max_tokens=120)
    jev_rows = [via_jev(jev, i["text"]) for i in items]
    llm_rows = [via_model(llm, i["text"]) for i in items]
    result = {
        "jev": summarize(jev_rows, items, jev.model),
        "model": summarize(llm_rows, items, model_name),
        "disagreements": [
            {"text": i["text"], "truth": i["route"], "jev": j["kind"], "model": m["kind"]}
            for i, j, m in zip(items, jev_rows, llm_rows, strict=True)
            if j["kind"] != m["kind"]
        ],
        "rows": {"jev": jev_rows, "model": llm_rows},
    }
    (HERE / "classifier_compare.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({k: result[k] for k in ("jev", "model")}, indent=1))
    print("disagreements:", len(result["disagreements"]))


if __name__ == "__main__":
    main()
