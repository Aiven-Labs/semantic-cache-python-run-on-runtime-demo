import pytest

from semcache.cost import CostStats, Pricing, routing_saving
from semcache.tunables import ModelPrice, load_tunables

GOOD = """
[cache]
crawl_max_distance = 0.1
crawl_ttl_seconds = 60
answer_max_distance = 0.08
answer_ttl_seconds = 60
[routing]
followup_max_words = 8
followup_model = "mid"
always_expensive = ["analysis"]
[routing.vote]
k = 5
min_share = 0.6
min_samples = 5
spread = 2.0
[routing.models]
hit = "near"
classifier = "mid"
miss = "far"
[routing.jev]
model = "jev-test"
min_confidence = 0.6
[routing.coverage]
index_hit_distance = 0.3
index_hit_min = 3
[routing.pin]
analysis = "pinned-model"
[chat]
history_turns = 8
conversation_ttl_seconds = 60
max_tool_steps = 4
[search]
results_per_query = 30
[github]
repo_cache_ttl_seconds = 60
detail_ttl_seconds = 600
[cost.models."m"]
input_per_mtok = 1.0
output_per_mtok = 5.0
"""


def write(tmp_path, text):
    p = tmp_path / "settings.toml"
    p.write_text(text)
    return p


def test_load_good(tmp_path):
    t = load_tunables(write(tmp_path, GOOD))
    assert t.cache.crawl_max_distance == 0.1 and t.cost.models["m"].output_per_mtok == 5.0


def test_repo_settings_file_is_valid():
    t = load_tunables("settings.toml")
    assert t.cost.models and t.routing.vote.k > 0


def test_missing_file(tmp_path):
    with pytest.raises(RuntimeError, match="settings file not found"):
        load_tunables(tmp_path / "nope.toml")


def test_typo_and_range_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_tunables(write(tmp_path, GOOD.replace("crawl_max_distance", "crawl_max_distence")))
    with pytest.raises(ValueError):
        load_tunables(write(tmp_path, GOOD.replace("= 0.08", "= 7")))
    with pytest.raises(ValueError):  # a required key removed
        load_tunables(write(tmp_path, GOOD.replace("max_tool_steps = 4", "")))


def test_cost_math():
    p = Pricing(
        {
            "cheap": ModelPrice(input_per_mtok=1, output_per_mtok=5),
            "strong": ModelPrice(input_per_mtok=3, output_per_mtok=15),
        }
    )
    assert p.cost("cheap", 1_000_000, 1_000_000) == 6.0
    assert p.cost("unknown", 10, 10) == 0.0 and not p.known("unknown")
    # same 1000/500 tokens: strong 0.0105, cheap 0.0035 -> saved 0.007
    assert routing_saving(p, "strong", "cheap", 1000, 500) == pytest.approx(0.007)
    assert routing_saving(p, "strong", "strong", 1000, 500) == 0.0  # baseline: nothing saved
    assert routing_saving(p, "strong", "unknown", 1000, 500) == 0.0


class FakeR:
    def __init__(self):
        self.h, self.ops = {}, []

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


def test_stats_record_and_totals():
    s = CostStats(FakeR())
    s.record(0.01, 0.0, 0.007, cache_hit=False)
    s.record(0.0, 0.02, 0.0, cache_hit=True)
    t = s.totals()
    assert t["requests"] == 2 and t["cache_hits"] == 1
    assert t["spent_usd"] == pytest.approx(0.01) and t["saved_cache_usd"] == pytest.approx(0.02)
