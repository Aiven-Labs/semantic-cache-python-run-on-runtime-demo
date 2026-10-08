import httpx
import pytest

from semcache import durable


@pytest.fixture(autouse=True)
def _reset():
    durable._blocked_until = 0.0
    yield
    durable._blocked_until = 0.0


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), event_hooks=durable.GATE)


def test_rate_limit_blocks_later_api_calls_without_hitting_github():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={"retry-after": "120"})

    with _client(handler) as c:
        c.get("https://api.github.com/search/repositories")  # trips the limit
        with pytest.raises(durable.RateLimited) as e:
            c.get("https://api.github.com/repos/a/b")
    assert len(calls) == 1
    assert 100 < e.value.wait <= 120


def test_raw_host_is_not_gated():
    durable.note_rate_limit(60)
    with _client(lambda r: httpx.Response(200)) as c:
        assert c.get("https://raw.githubusercontent.com/a/b/HEAD/x").status_code == 200


def test_cooldown_ends_and_never_shortens():
    durable.note_rate_limit(100, now=1000.0)
    durable.note_rate_limit(10, now=1000.0)
    assert durable.blocked_for(now=1050.0) == 50.0
    assert durable.blocked_for(now=1101.0) == 0.0
