import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from semcache import durable, github, seed_workflow, seeding
from semcache.seed import SEED_OWNERS


def _item(name: str, **kw) -> dict:
    return {"full_name": f"o/{name}", "html_url": "u", "default_branch": "main", **kw}


def _patch_client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(
        github.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler))
    )


def test_aiven_labs_is_seeded():
    assert "Aiven-Labs" in SEED_OWNERS


# ---- rate limit parsing ------------------------------------------------------------------
def _resp(status, **headers):
    return httpx.Response(status, headers=headers)


def test_rate_limit_wait():
    assert durable.rate_limit_wait(_resp(200)) is None
    assert durable.rate_limit_wait(_resp(404)) is None
    assert durable.rate_limit_wait(_resp(403)) is None  # a plain 403 is not a rate limit
    assert durable.rate_limit_wait(_resp(429, **{"retry-after": "7"})) == 7
    assert durable.rate_limit_wait(_resp(403, **{"retry-after": "3"})) == 3
    spent = _resp(403, **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1100"})
    assert durable.rate_limit_wait(spent, now=1000) == 101
    assert durable.rate_limit_wait(_resp(429)) == 60


# ---- request: one attempt, errors classified for Temporal -----------------------------------
def _client(responses):
    seq = iter(responses)
    return httpx.Client(transport=httpx.MockTransport(lambda r: next(seq)))


def test_request_classifies_failures():
    with pytest.raises(durable.RateLimited) as e:
        durable.request(_client([_resp(429, **{"retry-after": "900"})]), "https://x/")
    assert e.value.wait == 900
    with pytest.raises(durable.Unavailable):
        durable.request(_client([httpx.Response(502)]), "https://x/")
    assert durable.request(_client([httpx.Response(404)]), "https://x/").status_code == 404


# ---- strict compose check -----------------------------------------------------------------
def test_strict_compose_never_stores_a_failed_check_as_no_file():
    c = _client([httpx.Response(404), httpx.Response(503)])
    with pytest.raises(durable.Unavailable):
        github._fetch_compose(c, "o/r", "main", strict=True)


# ---- owner listing ------------------------------------------------------------------------
def test_list_owner_repos_filters_and_falls_back_to_users(monkeypatch):
    items = [_item("a"), _item("old", archived=True), _item("fk", fork=True)]

    def handler(request: httpx.Request) -> httpx.Response:
        if "/users/" in request.url.path:
            return httpx.Response(200, json=items)
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)
    assert [i["full_name"] for i in github.list_owner_repos("o", token=None)] == ["o/a"]


def test_list_owner_repos_unknown_owner_and_bad_name(monkeypatch):
    _patch_client(monkeypatch, lambda r: httpx.Response(404))
    with pytest.raises(ValueError, match="no GitHub org"):
        github.list_owner_repos("ghost", token=None)
    with pytest.raises(ValueError, match="not a valid"):
        github.list_owner_repos("bad/../x", token=None)


# ---- Temporal ---------------------------------------------------------------------------------
class FakeCatalog:
    def __init__(self, have=()):
        self.have = set(have)

    def exists(self, kind, name):
        return name in self.have


def _acts(have=(), stored=None):
    stored = [] if stored is None else stored
    return seeding.SeedActivities(
        FakeCatalog(have), object(), None,
        lambda repo, vec, source="": stored.append((repo.full_name, source)),
        lambda e, repo: [0.0],
    )  # fmt: skip


def test_rate_limit_becomes_a_retry_at_githubs_delay():
    err = seeding._retryable(durable.RateLimited(90))
    assert err.next_retry_delay == timedelta(seconds=90) and err.type == "RateLimited"
    assert seeding._retryable(durable.Unavailable("boom")).next_retry_delay is None


def test_unknown_owner_is_not_retried(monkeypatch):
    def nope(owner, token):
        raise ValueError("no GitHub org or user named 'x'")

    monkeypatch.setattr(seeding, "list_owner_repos", nope)
    with pytest.raises(ApplicationError) as e:
        _acts().list_missing("x")
    assert e.value.non_retryable


def test_seed_repo_stores_nothing_when_the_check_is_cut_short(monkeypatch):
    stored = []

    def limited(item):
        raise durable.RateLimited(5)

    monkeypatch.setattr(seeding, "repo_from_item", limited)
    with pytest.raises(ApplicationError):
        _acts(stored=stored).seed_repo("Aiven-Labs", _item("x"))
    assert stored == []


async def _run_workflow(acts, owner="o"):
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with Worker(
            env.client, task_queue="t", workflows=[seed_workflow.SeedOwnerWorkflow],
            activities=[acts.list_missing, acts.seed_repo],
            activity_executor=ThreadPoolExecutor(4),
        ):  # fmt: skip
            return await env.client.execute_workflow(
                seed_workflow.SeedOwnerWorkflow.run, owner, id="w", task_queue="t"
            )
    finally:
        await env.shutdown()


def test_workflow_waits_out_a_rate_limit_then_seeds_everything(monkeypatch):
    items = [seeding.slim({**_item("a"), "stargazers_count": 1}), seeding.slim(_item("b"))]
    monkeypatch.setattr(seeding, "list_owner_repos", lambda owner, token: items)
    calls = {"n": 0}

    def repo_from_item(item):
        calls["n"] += 1
        if calls["n"] == 1:
            raise durable.RateLimited(3600)  # Temporal waits an hour (time-skipped), then retries
        return github.Repo(item["full_name"], "", "u", 1, [], None)

    monkeypatch.setattr(seeding, "repo_from_item", repo_from_item)
    stored = []
    result = asyncio.run(_run_workflow(_acts(stored=stored)))
    assert result == {"owner": "o", "added": 2, "failed": []}
    assert sorted(n for n, _ in stored) == ["o/a", "o/b"] and calls["n"] == 3
