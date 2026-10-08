"""Markdown debug report for one conversation: settings, routing, cost, tools and errors.

Built only from stored conversation records and non-secret settings. Endpoints, URLs and API
keys are never included.
"""

import json
from datetime import UTC, datetime

from .tunables import Tunables


def settings_snapshot(t: Tunables, embed_model: str, embed_dim: int) -> dict:
    return {
        "embedding": {"model": embed_model, "dim": embed_dim},
        "cache": t.cache.model_dump(),
        "routing": {
            "vote": t.routing.vote.model_dump(),
            "models": t.routing.models.model_dump(),
            "coverage": t.routing.coverage.model_dump(),
            "always_expensive": t.routing.always_expensive,
            "pin": t.routing.pin,
            "followup_max_words": t.routing.followup_max_words,
            "followup_model": t.routing.followup_model,
        },
        "chat": t.chat.model_dump(),
        "search": t.search.model_dump(),
        "github": t.github.model_dump(),
        "prices_usd_per_mtok": {
            k: [v.input_per_mtok, v.output_per_mtok] for k, v in t.cost.models.items()
        },
    }


def _flat(d: dict, prefix: str = "") -> list[str]:
    """One `key = value` line per setting; nested tables become dotted keys, lists stay inline."""
    lines: list[str] = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            lines += _flat(v, key + ".")
        else:
            lines.append(f"{key} = {json.dumps(v)}")
    return lines


def model_history(history: list[dict]) -> list[dict]:
    """What the model should see: user/assistant turns, minus failed turns (an error record
    and the user message that caused it)."""
    out: list[dict] = []
    for m in history:
        if m.get("role") == "error":
            if out and out[-1].get("role") == "user":
                out.pop()
            continue
        out.append(m)
    return out


def _fence(text: str, lang: str = "") -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}{lang}\n{text}\n{fence}"


def build_report(cid: str, history: list[dict], totals: dict, snapshot: dict) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    turns = sum(1 for m in history if m.get("role") == "user")
    errors = sum(1 for m in history if m.get("role") == "error")
    out = [
        "# Template Scout debug report",
        f"- generated: {now}",
        f"- conversation: `{cid}`",
        f"- turns: {turns}, failed turns: {errors}",
        "",
        "## Settings (non-secret)",
        _fence("\n".join(_flat(snapshot)), "toml"),
        "",
        "## Running totals (all conversations)",
        "- " + ", ".join(f"{k}: {v}" for k, v in totals.items()),
        "",
        "## Conversation",
    ]
    n = 0
    for m in history:
        role = m.get("role")
        if role == "user":
            n += 1
            out += ["", f"### Turn {n}", "**User:**", _fence(m.get("content", ""))]
            continue
        label = "Error" if role == "error" else "Assistant"
        bits = [
            f"route={m.get('route')}",
            f"distance={m.get('distance')}",
            f"tier={m.get('tier')}",
            f"model={m.get('model')}",
            f"cached={m.get('cached')}",
        ]
        if m.get("reason"):
            bits.append(f"why={m['reason']!r}")
        if "latency_s" in m:
            bits.append(f"latency={m['latency_s']}s")
        if m.get("in") or m.get("out"):
            bits.append(f"tokens={m.get('in')} in / {m.get('out')} out")
        if "usd" in m:
            bits.append(f"cost=${m['usd']}" if m.get("priced") else "cost=no price set")
        cls = m.get("classifier") or m.get("planner")  # older records called it "planner"
        if cls:
            tin = m.get("classifier_in", m.get("planner_in"))
            tout = m.get("classifier_out", m.get("planner_out"))
            bits.append(f"classifier={cls} ({tin} in / {tout} out)")
        if m.get("saved_usd"):
            bits.append(f"saved=${m['saved_usd']} by {m.get('saved_by')}")
        if m.get("estimated"):
            bits.append("(tokens estimated)")
        out.append(f"**{label}** — " + ", ".join(bits))
        for note in m.get("notes") or []:
            out.append(f"- note: {note}")
        tools = m.get("tools") or []
        if tools:
            out.append("Tool calls:")
            for i, t in enumerate(tools, 1):
                status = {True: "ok", False: "FAILED", None: "no result recorded"}[t.get("ok")]
                args = ", ".join(f"{k}={v!r}" for k, v in (t.get("args") or {}).items())
                out.append(f"{i}. `{t.get('name')}({args})` → {status}")
                if t.get("preview"):
                    out.append(f"   - result: {t['preview']}")
        out.append(_fence(m.get("content", "") or "(empty)"))
        if m.get("suggestions"):
            out.append("Suggestions shown: " + " | ".join(m["suggestions"]))
    return "\n".join(out) + "\n"
