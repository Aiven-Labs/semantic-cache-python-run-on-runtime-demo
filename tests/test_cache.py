import numpy as np

from semcache.cache import SemanticCache, _escape_tag, _to_dict


class FakeEmbedder:
    def embed(self, text: str) -> np.ndarray:
        return np.zeros(4, dtype=np.float32)


class FakeValkey:
    def __init__(self, search_result):
        self.search_result = search_result

    def execute_command(self, *args):
        return self.search_result


def make(result, max_distance=0.12):
    return SemanticCache(
        FakeValkey(result), FakeEmbedder(),
        index_name="i", prefix="p:", dim=4, max_distance=max_distance, ttl_seconds=10,
    )  # fmt: skip


def row(distance):
    return [1, b"p:abc", [b"distance", str(distance).encode(), b"response", b"hi", b"prompt", b"q"]]


def test_hit_under_threshold():
    hit = make(row(0.05)).lookup("t1", "q")
    assert hit and hit.response == "hi"


def test_miss_over_threshold():
    assert make(row(0.5)).lookup("t1", "q") is None


def test_miss_empty():
    assert make([0]).lookup("t1", "q") is None


def test_tag_escape():
    assert _escape_tag("acme-corp.io") == "acme\\-corp\\.io"


def test_to_dict():
    assert _to_dict([b"a", b"1"]) == {"a": "1"}
