"""Classifier shootout: Jev and general models on the same labeled messages, with a report.

    mise run bench-classifiers                       # default model list
    mise run bench-classifiers -- claude-opus-5 qwen3-32b    # your own list

Needs TYPESAFE_API_KEY (for Jev) and SEMCACHE_LLM_BASE_URL / SEMCACHE_LLM_API_KEY (the gateway
every other model goes through). Prices come from settings.toml. Writes, next to this file:

    classifier_compare.json   every answer, latency and token count
    report.md                 the summary, per-model mistakes and where models disagree

Every classifier gets the same six choices: the five Template Scout kinds plus `out_of_scope`
for messages the app is not meant to answer (general knowledge, coding help, jokes, weather).
Messages are sent one at a time with no conversation history.
"""

import json
import os
import re
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from langchain_openai import ChatOpenAI
from typesafe_sdk import Choice

from semcache.decide import CLASSIFY_PROMPT
from semcache.jev import CRITERIA, INSTRUCTIONS, JevClassifier
from semcache.tunables import load_tunables

HERE = Path(__file__).parent
DEFAULT_MODELS = [
    "jev-latest",
    "qwen3-32b",
    "claude-haiku-4-5",
    "claude-sonnet-5",
    "claude-opus-5-5",
]
JEV_PREFIX = "jev"

OUT_OF_SCOPE = (
    "Not about open-source projects, templates, or this conversation: general knowledge, "
    "coding help, jokes, weather, math, translation."
)
KINDS = [*CRITERIA, "out_of_scope"]
TRUTH = {  # dataset route -> the kind a classifier should answer
    "find": "search", "inspect": "repo", "analysis": "analysis", "smalltalk": "chat",
    "agent": "out_of_scope",
}  # fmt: skip

PROMPT = CLASSIFY_PROMPT.replace(
    '- "other": anything else.',
    f'- "other": anything about Template Scout that fits none of the above.\n'
    f'- "out_of_scope": {OUT_OF_SCOPE}',
)
assert "out_of_scope" in PROMPT
_JSON = re.compile(r"\{.*\}", re.S)


def parse_kind(text: str) -> str:
    """The kind from a model's JSON reply; anything unusable counts as 'other'."""
    m = _JSON.search(re.sub(r"<think>.*?</think>", "", text or "", flags=re.S))
    try:
        kind = str(json.loads(m.group(0)).get("kind", "")).strip().lower() if m else ""
    except (json.JSONDecodeError, AttributeError):
        kind = ""
    return kind if kind in KINDS else "other"


def via_model(llm, text: str) -> dict:
    prompt = f"{PROMPT}\n\nRecent conversation:\n(none)\n\nLatest message: {text}"
    t0 = time.monotonic()
    out = llm.invoke([("human", prompt)])
    seconds = time.monotonic() - t0
    um = out.usage_metadata or {}
    return {
        "kind": parse_kind(out.content if isinstance(out.content, str) else ""),
        "seconds": seconds, "in": um.get("input_tokens", 0), "out": um.get("output_tokens", 0),
    }  # fmt: skip


def via_jev(jev: JevClassifier, text: str) -> dict:
    criteria = {**CRITERIA, "out_of_scope": OUT_OF_SCOPE}
    state = f"Recent conversation:\n(none)\n\nLatest message: {text}"
    t0 = time.monotonic()
    resp = jev.client.system_one(
        state=state,
        questions={"kind": Choice(instructions=INSTRUCTIONS, criteria=criteria)},
        model=jev.model,
    )
    seconds = time.monotonic() - t0
    a = resp.answers["kind"]
    return {
        "kind": a.choice if a.choice in KINDS else "other", "confidence": a.confidence,
        "seconds": seconds, "in": resp.usage.input_tokens or 0,
        "out": resp.usage.output_tokens or 0,
    }  # fmt: skip


def summarize(name: str, rows: list[dict], items: list[dict], prices) -> dict:
    """Accuracy over everything, over the in-scope messages, and how out-of-scope was handled."""
    pairs = list(zip(rows, items, strict=True))
    right = [r["kind"] == TRUTH[i["route"]] for r, i in pairs]
    scoped = [ok for ok, (_, i) in zip(right, pairs, strict=True) if i["route"] != "agent"]
    off = [r["kind"] for r, i in pairs if i["route"] == "agent"]
    refused = [r["kind"] == "out_of_scope" for r, i in pairs if i["route"] != "agent"]
    secs = sorted(r["seconds"] for r in rows)
    price = prices.get(name)
    usd = (
        sum(r["in"] * price.input_per_mtok + r["out"] * price.output_per_mtok for r in rows) / 1e6
        if price
        else None
    )
    return {
        "model": name,
        "accuracy": round(sum(right) / len(right), 3),
        "in_scope_accuracy": round(sum(scoped) / len(scoped), 3),
        "in_scope_wrong": len(scoped) - sum(scoped),
        "out_of_scope_caught": sum(k == "out_of_scope" for k in off),
        "out_of_scope_total": len(off),
        "wrongly_refused": sum(refused),  # in-scope messages it called out_of_scope
        "mean_s": round(statistics.mean(secs), 3),
        "p95_s": round(secs[max(0, int(len(secs) * 0.95) - 1)], 3),
        "mean_in_tokens": round(statistics.mean(r["in"] for r in rows)),
        "mean_out_tokens": round(statistics.mean(r["out"] for r in rows), 1),
        "usd_per_1000": None if usd is None else round(usd / len(rows) * 1000, 4),
    }


def money(v) -> str:
    return "no price" if v is None else f"${v:.3f}"


def report(result: dict, items: list[dict]) -> str:
    models = list(result["summary"])
    s = result["summary"]
    lines = [
        "# Classifier comparison",
        "",
        f"Run on {result['date']}: {len(items)} labeled messages, one at a time with no "
        "conversation history. Every model chooses between the same six kinds: chat, search, "
        "repo, analysis, other and out_of_scope. Prices are the list prices in `settings.toml`.",
        "",
        "## Summary",
        "",
        "| Model | In-scope accuracy | All-message accuracy | Off-topic caught | Wrongly refused | "
        "Mean latency | p95 | Tokens in / out | $ per 1,000 calls |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for m in models:
        x = s[m]
        lines.append(
            f"| {m} | {x['in_scope_accuracy']:.1%} ({x['in_scope_wrong']} wrong) "
            f"| {x['accuracy']:.1%} | {x['out_of_scope_caught']}/{x['out_of_scope_total']} "
            f"| {x['wrongly_refused']} | {x['mean_s']:.2f} s | {x['p95_s']:.2f} s "
            f"| {x['mean_in_tokens']} / {x['mean_out_tokens']} | {money(x['usd_per_1000'])} |"
        )
    lines += [
        "",
        "In-scope accuracy covers the messages Template Scout is meant to handle. Off-topic caught "
        "is how many of the off-topic messages were labeled out_of_scope. Wrongly refused is how "
        "many in-scope messages a model called out_of_scope, which is the costly direction.",
        "",
        "## Mistakes by model",
    ]
    for m in models:
        rows = result["rows"][m]
        bad = [
            (i["text"], TRUTH[i["route"]], r["kind"], r.get("confidence"))
            for r, i in zip(rows, items, strict=True)
            if r["kind"] != TRUTH[i["route"]]
        ]
        lines += ["", f"### {m} ({len(bad)} wrong)", ""]
        if not bad:
            lines.append("None.")
        for text, truth, got, conf in bad:
            c = f", confidence {conf:.2f}" if conf is not None else ""
            lines.append(f'- "{text}": expected {truth}, got {got}{c}')
    lines += ["", "## Where the models disagree", ""]
    n = 0
    for k, item in enumerate(items):
        answers = {m: result["rows"][m][k]["kind"] for m in models}
        if len(set(answers.values())) > 1:
            n += 1
            detail = ", ".join(f"{m}: {a}" for m, a in answers.items())
            lines.append(f'- "{item["text"]}" (expected {TRUTH[item["route"]]}): {detail}')
    if not n:
        lines.append("They agree on every message.")
    lines += [
        "",
        "## Caveats",
        "",
        f"- {len(items)} messages written and labeled by one person; some labels are judgment "
        "calls.",
        "- One message per call with no history, which undersells models that use conversation.",
        "- Single run per model: Jev and the LLMs can answer differently on a rerun.",
        "- Measures classification only, not answer quality. Cost is estimated from list prices.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    names = sys.argv[1:] or DEFAULT_MODELS
    tunables = load_tunables(os.environ.get("SEMCACHE_SETTINGS_FILE", "settings.toml"))
    items = [json.loads(line) for line in (HERE / "routing.jsonl").read_text().splitlines() if line]
    rows_by_model: dict[str, list[dict]] = {}
    for name in names:
        print(f"{name} ...", flush=True)
        if name.startswith(JEV_PREFIX):
            jev = JevClassifier(model=name, min_confidence=0.0)  # raw answer, no fallback gate
            rows_by_model[name] = [via_jev(jev, i["text"]) for i in items]
        else:
            llm = ChatOpenAI(
                model=name, base_url=os.environ["SEMCACHE_LLM_BASE_URL"],
                api_key=os.environ["SEMCACHE_LLM_API_KEY"], timeout=120,
            ).bind(max_tokens=120)  # fmt: skip
            rows_by_model[name] = [via_model(llm, i["text"]) for i in items]
    result = {
        "date": date.today().isoformat(),
        "summary": {
            n: summarize(n, r, items, tunables.cost.models) for n, r in rows_by_model.items()
        },
        "rows": rows_by_model,
    }
    (HERE / "classifier_compare.json").write_text(json.dumps(result, indent=1))
    (HERE / "report.md").write_text(report(result, items))
    for s in result["summary"].values():
        print(
            f"{s['model']:20} in-scope {s['in_scope_accuracy']:.1%}  off-topic "
            f"{s['out_of_scope_caught']}/{s['out_of_scope_total']}  "
            f"refused {s['wrongly_refused']}  {s['mean_s']:.2f}s  {money(s['usd_per_1000'])}/1k"
        )
    print("wrote benchmarks/report.md")


if __name__ == "__main__":
    main()
