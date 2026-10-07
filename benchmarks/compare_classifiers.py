"""Classifier shootout: Jev and general models on the same labeled messages, with a report.

    mise run bench-classifiers                              # default models, md + json
    mise run bench-classifiers -- claude-opus-5 qwen3-32b   # your own list
    mise run bench-classifiers -- --formats all             # json, csv, html, pdf, md
    mise run bench-classifiers -- --from-saved --formats html,pdf   # re-render, no model calls

Needs TYPESAFE_API_KEY (for Jev) and SEMCACHE_LLM_BASE_URL / SEMCACHE_LLM_API_KEY (the gateway
every other model goes through). Prices come from settings.toml. Writes to --out-dir (default:
next to this file):

    classifier_compare.json   the raw answers, latency and token counts, one row per message
    report.<ext>              the report, in each format asked for; every case has a test id

Every classifier gets the same six choices: the five Template Scout kinds plus `out_of_scope`
for messages the app is not meant to answer (general knowledge, coding help, jokes, weather).
Messages are sent one at a time with no conversation history. PDF needs `uv sync --extra report`.
"""

import argparse
import json
import os
import re
import statistics
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from coded_rules import classify as coded_classify
from langchain_openai import ChatOpenAI
from typesafe_sdk import Choice

from semcache.decide import CLASSIFY_PROMPT
from semcache.jev import CRITERIA, INSTRUCTIONS, JevClassifier
from semcache.report import Case, Report, item_id, parse_formats, test_id, write
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
CODED = "coded-rules"  # no model: regexes and keywords (benchmarks/coded_rules.py)

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


def coded_row(text: str) -> dict:
    t0 = time.monotonic()
    kind = coded_classify(text)
    return {"kind": kind, "seconds": time.monotonic() - t0, "in": 0, "out": 0}


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


SUITE = "classifier-compare"


def build_report(result: dict, items: list[dict]) -> Report:
    """One case per message per model, with a test id: classifier-compare::<model>::<item id>."""
    cases = []
    for model, rows in result["rows"].items():
        for item, row in zip(items, rows, strict=True):
            expected = TRUTH[item["route"]]
            cases.append(
                Case(
                    test_id=test_id(SUITE, model, item["text"]),
                    suite=SUITE,
                    subject=model,
                    item_id=item_id(item["text"]),
                    text=item["text"],
                    expected=expected,
                    actual=row["kind"],
                    passed=row["kind"] == expected,
                    in_scope=item["route"] != "agent",
                    confidence=row.get("confidence"),
                    seconds=round(row["seconds"], 3),
                    tokens_in=row["in"],
                    tokens_out=row["out"],
                )  # fmt: skip
            )
    headers = [
        "Model", "In-scope accuracy", "All-message accuracy", "Off-topic caught",
        "Wrongly refused", "Mean latency", "p95", "Tokens in / out", "$ per 1,000 calls",
    ]  # fmt: skip
    table = []
    for m, x in result["summary"].items():
        table.append([
            m, f"{x['in_scope_accuracy']:.1%} ({x['in_scope_wrong']} wrong)",
            f"{x['accuracy']:.1%}", f"{x['out_of_scope_caught']}/{x['out_of_scope_total']}",
            str(x["wrongly_refused"]), f"{x['mean_s']:.2f} s", f"{x['p95_s']:.2f} s",
            f"{x['mean_in_tokens']} / {x['mean_out_tokens']}", money(x["usd_per_1000"]),
        ])  # fmt: skip
    return Report(
        title="Classifier comparison", suite=SUITE,
        meta={"date": result["date"], "messages": len(items), "models": len(result["rows"])},
        summary_headers=headers, summary_rows=table, cases=cases,
        notes=[
            "In-scope accuracy covers the messages Template Scout is meant to handle. Wrongly "
            "refused counts in-scope messages a model called out_of_scope, the costly direction.",
            "One message per call, no conversation history; one run per model, so answers can "
            "differ on a rerun. Prices are the list prices in settings.toml.",
            f"{len(items)} messages written and labeled by one person; some labels are judgment "
            "calls.",
        ],
    )  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("models", nargs="*", help=f"gateway model names (default: {DEFAULT_MODELS})")
    ap.add_argument("--formats", default="md,json", help="json,csv,html,pdf,md or 'all'")
    ap.add_argument("--out-dir", default=str(HERE), help="where the report files go")
    ap.add_argument("--from-saved", action="store_true", help="re-render classifier_compare.json")
    args = ap.parse_args()
    formats = parse_formats(args.formats)
    items = [json.loads(line) for line in (HERE / "routing.jsonl").read_text().splitlines() if line]
    saved = HERE / "classifier_compare.json"

    tunables = load_tunables(os.environ.get("SEMCACHE_SETTINGS_FILE", "settings.toml"))
    prices = {**tunables.cost.models, CODED: SimpleNamespace(input_per_mtok=0, output_per_mtok=0)}

    def run_model(name: str) -> list[dict]:
        print(f"{name} ...", flush=True)
        if name == CODED:
            return [coded_row(i["text"]) for i in items]
        if name.startswith(JEV_PREFIX):
            jev = JevClassifier(model=name, min_confidence=0.0)  # raw answer, no fallback gate
            return [via_jev(jev, i["text"]) for i in items]
        llm = ChatOpenAI(
            model=name, base_url=os.environ["SEMCACHE_LLM_BASE_URL"],
            api_key=os.environ["SEMCACHE_LLM_API_KEY"], timeout=120,
        ).bind(max_tokens=120)  # fmt: skip
        return [via_model(llm, i["text"]) for i in items]

    if args.from_saved:  # re-render what is saved; any models named are run and added to it
        result = json.loads(saved.read_text())
        for name in args.models:
            result["rows"][name] = run_model(name)
            result["summary"][name] = summarize(name, result["rows"][name], items, prices)
        if args.models:
            saved.write_text(json.dumps(result, indent=1))
    else:
        rows_by_model = {n: run_model(n) for n in args.models or DEFAULT_MODELS}
        result = {
            "date": date.today().isoformat(),
            "summary": {n: summarize(n, r, items, prices) for n, r in rows_by_model.items()},
            "rows": rows_by_model,
        }
        saved.write_text(json.dumps(result, indent=1))

    for s in result["summary"].values():
        print(
            f"{s['model']:20} in-scope {s['in_scope_accuracy']:.1%}  off-topic "
            f"{s['out_of_scope_caught']}/{s['out_of_scope_total']}  "
            f"refused {s['wrongly_refused']}  {s['mean_s']:.2f}s  {money(s['usd_per_1000'])}/1k"
        )
    for path in write(build_report(result, items), formats, Path(args.out_dir)):
        print("wrote", path)


if __name__ == "__main__":
    main()
