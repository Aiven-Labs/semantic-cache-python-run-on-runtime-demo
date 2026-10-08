"""Routing learns from answered questions: they are stored as kind=turn and matched by KNN."""

from types import SimpleNamespace

import numpy as np

from semcache.chat import ChatService
from semcache.decide import Decision
from semcache.routes import RESPONSE_CLIP, match_route, record_turn, vote_route


class Cat:
    def __init__(self):
        self.rows, self.samples = [], []

    def search(self, vec, kind, services=None, k=10):
        return [
            {"name": f["name"], "description": f["description"], "distance": 0.1}
            for _, _, f in self.rows
        ]

    def exists(self, kind, ident):
        return any(i == ident for _, i, _ in self.rows)

    def add_route_sample(self, route, distance):
        self.samples.append((route, distance))

    def upsert(self, kind, ident, vec, fields):
        self.rows.append((kind, ident, fields))


class Emb:
    def embed(self, text):
        return np.zeros(2, dtype=np.float32)


def test_an_answered_question_is_stored_with_its_route_and_a_clipped_response():
    cat = Cat()
    record_turn(cat, Emb(), "  Good   OTel options? ", "find", "x" * 5000, "miss")
    kind, ident, fields = cat.rows[0]
    assert (kind, ident) == ("turn", "good otel options?")  # normalized, so a repeat refreshes it
    assert fields["name"] == "find" and fields["tier"] == "miss"
    assert (
        fields["description"] == "Good OTel options?" and len(fields["response"]) == RESPONSE_CLIP
    )


def test_unknown_routes_and_blank_questions_are_not_stored():
    cat = Cat()
    record_turn(cat, Emb(), "hello", "nonsense", "hi", "hit")
    record_turn(cat, Emb(), "   ", "smalltalk", "hi", "hit")
    assert cat.rows == []


def test_a_stored_question_routes_a_close_repeat_and_ignores_a_far_one():
    hit = [{"name": "find", "distance": 0.05}]
    assert match_route(hit, 0.25) == ("find", 0.05)
    assert match_route([{"name": "find", "distance": 0.4}], 0.25) == (None, 0.4)


def remembering_service():
    svc = ChatService.__new__(ChatService)
    svc.catalog, svc.embedder = Cat(), Emb()
    return svc


def d(route, tier, classifier_used=False):
    return Decision(route, "m", tier, "r", 0.3, classifier_used=classifier_used)


def test_classifier_answers_become_history_but_guesses_and_follow_ups_do_not():
    svc = remembering_service()
    svc._remember("good otel options", d("find", "miss", classifier_used=True), "a")
    svc._remember("tell me more", d("find", "follow-up"), "a")  # inherited route
    svc._remember("anything", d("agent", "miss"), "a")  # classifier was down: a guess
    assert [r[2]["description"] for r in svc.catalog.rows] == ["good otel options"]


def test_a_storage_error_never_fails_the_reply():
    svc = remembering_service()
    svc.catalog = SimpleNamespace(upsert=lambda *a, **k: 1 / 0)
    svc._remember("q", d("find", "miss", classifier_used=True), "a")  # must not raise


def test_a_second_question_on_the_same_route_teaches_the_route_its_spacing():
    cat = Cat()
    record_turn(cat, Emb(), "good otel options", "find", "a", "miss")
    assert cat.samples == []  # nothing to measure against yet
    record_turn(cat, Emb(), "best observability tools", "find", "a", "miss")
    record_turn(cat, Emb(), "good otel options", "find", "a", "miss")  # a repeat is not a sample
    assert cat.samples == [("find", 0.1)]


def test_vote_needs_agreement_samples_and_closeness():
    stats = lambda r: (30, 0.2, 0.05)  # noqa: E731  limit = 0.2 + 2*0.05 = 0.3
    kw = {"spread": 2.0, "min_samples": 5, "min_share": 0.6}
    near = [{"name": "find", "distance": d} for d in (0.1, 0.12, 0.15)]
    assert vote_route(near, stats, **kw) == ("find", 0.1)
    far = [{"name": "find", "distance": d} for d in (0.4, 0.42, 0.45)]
    assert vote_route(far, stats, **kw)[0] is None  # farther than this route's own spacing
    split = [{"name": "find", "distance": 0.1}, {"name": "lookup", "distance": 0.11}]
    assert vote_route(split, stats, **kw)[0] is None  # the vote disagrees
    assert vote_route(near, lambda r: (2, 0.2, 0.05), **kw)[0] is None  # too few samples
    assert vote_route([], stats, **kw) == (None, 1.0)
