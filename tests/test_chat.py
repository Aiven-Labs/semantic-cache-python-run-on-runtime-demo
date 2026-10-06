import json

import pytest

from semcache.chat import ConversationStore, ThinkFilter, valid_cid
from semcache.routes import FALLBACK, choose

LIMITS = {"smalltalk": 0.28}


def run(chunks):
    f = ThinkFilter()
    return "".join(f.feed(c) for c in chunks) + f.flush()


def test_think_filter_plain():
    assert run(["hello ", "world"]) == "hello world"


def test_think_filter_removes_block_split_across_chunks():
    assert run(["a<th", "ink>secret</thi", "nk>b"]) == "ab"


def test_think_filter_keeps_lone_angle():
    assert run(["x < y and <b"]) == "x < y and <b"


def test_choose_routes():
    assert choose([{"name": "find", "distance": 0.2}], 0.55) == ("find", 0.2)
    assert choose([{"name": "find", "distance": 0.9}], 0.55)[0] == FALLBACK
    assert choose([], 0.55)[0] == FALLBACK
    assert choose([{"name": "bogus", "distance": 0.1}], 0.55)[0] == FALLBACK


def test_bare_topic_is_not_smalltalk():
    from semcache.routes import looks_like_topic

    weak = [{"name": "smalltalk", "distance": 0.41}]
    assert choose(weak, 0.55, "Durable functions", LIMITS)[0] == "find"
    assert choose(weak, 0.55, "why is the sky blue today for everyone", LIMITS)[0] == FALLBACK
    assert (
        choose([{"name": "smalltalk", "distance": 0.2}], 0.55, "thanks", LIMITS)[0] == "smalltalk"
    )
    assert looks_like_topic("feature flags") and not looks_like_topic("what is Valkey")


class FakeR:
    def __init__(self):
        self.lists, self.ttl = {}, {}

    def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)

    def expire(self, k, t):
        self.ttl[k] = t

    def lrange(self, k, a, b):
        return self.lists.get(k, [])[a:] if a < 0 else self.lists.get(k, [])


def test_store_roundtrip_and_limit():
    s = ConversationStore(FakeR(), ttl=60)
    s.append("conv-12345678", "user", "hi")
    s.append("conv-12345678", "assistant", "yo", route="smalltalk")
    h = s.history("conv-12345678")
    assert [m["role"] for m in h] == ["user", "assistant"] and h[1]["route"] == "smalltalk"
    assert len(s.history("conv-12345678", limit=1)) == 1
    assert s.r.ttl["conv:conv-12345678"] == 60
    json.loads(s.r.lists["conv:conv-12345678"][0])


def test_cid_validation():
    assert valid_cid("abcdefgh-1234")
    assert not valid_cid("../etc")
    with pytest.raises(ValueError):
        ConversationStore(FakeR(), 1).append("bad id", "user", "x")


def test_extract_query():
    from semcache.chat import extract_query

    assert (
        extract_query("find me self-hosted job queue dashboards")
        == "self-hosted job queue dashboards"
    )
    assert (
        extract_query("Can you search GitHub for popular open source headless CMS projects?")
        == "headless CMS"
    )
    assert extract_query("discover new apps that use Kafka") == "use Kafka"
    assert extract_query("feature flags") == "feature flags"
