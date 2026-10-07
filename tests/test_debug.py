import json

from semcache.debug import build_report, model_history, settings_snapshot
from semcache.tunables import load_tunables

HIST = [
    {"role": "user", "content": "what language is Dify written in?"},
    {
        "role": "assistant", "content": "TypeScript.", "route": "repo_facts", "distance": 0.013,
        "tier": "pinned", "model": "claude-haiku-4-5", "cached": False, "latency_s": 17.2,
        "usd": 0.012, "priced": True, "in": 5000, "out": 400, "saved_usd": 0.0,
        "notes": ["searched GitHub for Dify"], "suggestions": ["Look at the files in langgenius/dify"],
        "tools": [
            {"name": "repo", "args": {"repo": "difyorg/dify"}, "ok": False,
             "preview": "Tool error: ValueError: not found: difyorg/dify"},
            {"name": "repo", "args": {"repo": "langgenius/dify"}, "ok": True, "preview": "{}"},
        ],
    },
    {"role": "user", "content": "so Dify uses vite?"},
    {"role": "error", "content": "ReadTimeout: slow", "route": "agent", "model": "claude-haiku-4-5",
     "tools": [{"name": "repo", "args": {"repo": "langgenius/dify"}, "ok": None}]},
]  # fmt: skip


def test_report_contains_the_debugging_facts():
    snap = {"routing": {"followup_max_words": 8}}
    r = build_report("conv-12345678", HIST, {"requests": 3}, snap)
    assert "conv-12345678" in r and "failed turns: 1" in r and "turns: 2" in r
    assert "repo(repo='difyorg/dify')` → FAILED" in r
    assert "not found: difyorg/dify" in r  # the failure reason is visible
    assert "repo(repo='langgenius/dify')` → ok" in r
    assert "route=repo_facts" in r and "tier=pinned" in r and "latency=17.2s" in r
    assert "tokens=5000 in / 400 out" in r and "cost=$0.012" in r
    assert "**Error**" in r and "ReadTimeout: slow" in r and "no result recorded" in r
    assert "searched GitHub for Dify" in r and "routing.followup_max_words = 8" in r


def test_report_fences_survive_backticks_in_answers():
    h = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "```py\nprint(1)\n```"}]
    r = build_report("c", h, {}, {})
    assert "````\n```py" in r  # outer fence is longer than any fence inside the text


def test_failed_turns_are_hidden_from_the_model():
    kept = model_history(HIST)
    assert [m["content"] for m in kept] == ["what language is Dify written in?", "TypeScript."]
    assert model_history([{"role": "error", "content": "e"}]) == []


def test_snapshot_has_no_secrets_or_urls():
    t = load_tunables("settings.toml")
    snap = json.dumps(settings_snapshot(t, "embed-model", 1024))
    for bad in ("http", "key", "token", "password", "secret"):
        assert bad not in snap.lower(), bad
    assert "claude-haiku-4-5" in snap and "classifier" in snap


def test_settings_are_compact_one_line_each():
    t = load_tunables("settings.toml")
    r = build_report("c", HIST, {}, settings_snapshot(t, "m", 1024))
    sect = r.split("## Settings")[1].split("## Running")[0]
    assert (
        "routing.models.hit = " in sect
        and "prices_usd_per_mtok.claude-haiku-4-5 = [1.155, 5.775]" in sect
    )
    assert sect.count("\n") < 40  # was ~60 lines of indented JSON
