from types import SimpleNamespace

import pytest

from semcache.decide import KIND_TO_ROUTE
from semcache.jev import CRITERIA, JevClassifier, LowConfidence


class FakeClient:
    def __init__(self, choice, confidence):
        self.answer = SimpleNamespace(choice=choice, confidence=confidence)
        self.sent = None

    def system_one(self, *, state, questions, model):
        self.sent = SimpleNamespace(state=state, questions=questions, model=model)
        return SimpleNamespace(
            answers={"kind": self.answer},
            usage=SimpleNamespace(input_tokens=120, output_tokens=None),
        )


def classifier(choice, confidence):
    client = FakeClient(choice, confidence)
    return JevClassifier(model="jev-x", min_confidence=0.6, client=client), client


def test_one_option_per_kind_the_router_understands():
    assert set(CRITERIA) == set(KIND_TO_ROUTE)


def test_a_confident_answer_becomes_a_classification_and_counts_tokens():
    jev, client = classifier("search", 0.9)
    usage = {"in": 0, "out": 0}
    history = [{"role": "user", "content": "hi " * 200}, {"role": "assistant", "content": "yo"}]
    out = jev.classify(history, "diary apps", usage)
    assert out == {"kind": "search", "query": "", "repo": ""}
    assert usage == {"in": 120, "out": 0}
    assert client.sent.model == "jev-x" and "Latest message: diary apps" in client.sent.state
    assert "hi " * 200 not in client.sent.state  # history is cut to 300 characters a turn


def test_a_shaky_answer_is_treated_as_unavailable():
    jev, _ = classifier("analysis", 0.4)
    with pytest.raises(LowConfidence):
        jev.classify([], "x", {"in": 0, "out": 0})


def test_an_unknown_option_becomes_other():
    jev, _ = classifier("surprise", 0.99)
    assert jev.classify([], "x", {"in": 0, "out": 0})["kind"] == "other"
