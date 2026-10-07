"""The classifier comparison's scoring and report, run on canned answers (no network)."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from semcache.report import to_md

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmarks"))  # for coded_rules
SPEC = importlib.util.spec_from_file_location(
    "compare_classifiers", Path(__file__).parent.parent / "benchmarks" / "compare_classifiers.py"
)
cc = importlib.util.module_from_spec(SPEC)
sys.modules["compare_classifiers"] = cc
SPEC.loader.exec_module(cc)

ITEMS = [
    {"text": "diary apps", "route": "find"},
    {"text": "thanks", "route": "smalltalk"},
    {"text": "tell me a joke", "route": "agent"},
    {"text": "rank these", "route": "analysis"},
]


def rows(*kinds):
    return [{"kind": k, "seconds": 0.5, "in": 100, "out": 10} for k in kinds]


PRICES = {"m": SimpleNamespace(input_per_mtok=1.0, output_per_mtok=5.0)}


def test_scoring_separates_in_scope_accuracy_from_off_topic_handling():
    perfect = cc.summarize("m", rows("search", "chat", "out_of_scope", "analysis"), ITEMS, PRICES)
    assert (perfect["accuracy"], perfect["in_scope_accuracy"]) == (1.0, 1.0)
    assert perfect["out_of_scope_caught"] == 1 and perfect["wrongly_refused"] == 0

    # answered the joke, but refused a real question: costly direction
    flawed = cc.summarize("m", rows("search", "chat", "other", "out_of_scope"), ITEMS, PRICES)
    assert flawed["out_of_scope_caught"] == 0 and flawed["wrongly_refused"] == 1
    assert flawed["in_scope_wrong"] == 1 and flawed["in_scope_accuracy"] == 0.667


def test_cost_comes_from_settings_prices_and_is_none_without_one():
    s = cc.summarize("m", rows("search", "chat", "out_of_scope", "analysis"), ITEMS, PRICES)
    assert s["usd_per_1000"] == round((100 * 1.0 + 10 * 5.0) / 1e6 * 1000, 4)
    assert (
        cc.summarize("unknown", rows("search", "chat", "other", "analysis"), ITEMS, {})[
            "usd_per_1000"
        ]
        is None
    )


def sample_result():
    good = rows("search", "chat", "out_of_scope", "analysis")
    bad = rows("search", "chat", "out_of_scope", "chat")
    return {
        "date": "2026-01-01",
        "summary": {
            "good": cc.summarize("good", good, ITEMS, {}),
            "bad": cc.summarize("bad", bad, ITEMS, {}),
        },
        "rows": {"good": good, "bad": bad},
    }


def test_the_markdown_report_lists_mistakes_and_disagreements():
    md = to_md(cc.build_report(sample_result(), ITEMS))
    assert "| good |" in md and "| bad |" in md and "no price" in md
    assert '"rank these": expected analysis, got chat' in md  # a mistake, by model
    assert "good: analysis, bad: chat" in md  # and where they disagree


def test_a_models_reply_is_parsed_into_one_of_the_six_kinds():
    assert cc.parse_kind('{"kind": "out_of_scope", "query": "", "repo": ""}') == "out_of_scope"
    assert cc.parse_kind('<think>hm</think>{"kind": "SEARCH"}') == "search"
    assert cc.parse_kind("no json here") == "other"
    assert cc.parse_kind('{"kind": "made_up"}') == "other"
