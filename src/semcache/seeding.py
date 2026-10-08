"""Seed a GitHub org's or user's repos into the catalog as a Temporal workflow.

Temporal owns the waiting and retrying: a rate-limited activity fails with the delay GitHub
asked for and Temporal re-runs it then; a crash or restart resumes the workflow where it was.
One workflow per owner, with a fixed id, so starting it twice joins the run already going.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from .durable import RateLimited, Unavailable
from .github import list_owner_repos, repo_from_item, slim
from .seed_workflow import CONCURRENCY, TASK_QUEUE, SeedOwnerWorkflow


def workflow_id(owner: str) -> str:
    return f"seed-{owner}"


def _retryable(e: Exception) -> ApplicationError:
    """Map a GitHub failure to what Temporal should do about it."""
    if isinstance(e, RateLimited):  # wait exactly as long as GitHub said
        return ApplicationError(
            str(e), type="RateLimited", next_retry_delay=timedelta(seconds=e.wait)
        )
    return ApplicationError(str(e), type=type(e).__name__)


class SeedActivities:
    """Activities close over the app's catalog and embedder, so they run in the app process."""

    def __init__(self, catalog, embedder, token: str | None, ingest: Callable, repo_vec: Callable):
        self.catalog, self.embedder, self.token = catalog, embedder, token
        self.ingest, self.repo_vec = ingest, repo_vec

    @activity.defn(name="list_missing")
    def list_missing(self, owner: str) -> list[dict]:
        """The owner's repos that are not in the catalog yet (one listing, no per-repo calls)."""
        try:
            items = list_owner_repos(owner, token=self.token)
        except ValueError as e:  # no such org or user: retrying cannot fix it
            raise ApplicationError(str(e), type="UnknownOwner", non_retryable=True) from e
        except (RateLimited, Unavailable) as e:
            raise _retryable(e) from e
        return [slim(i) for i in items if not self.catalog.exists("candidate", i["full_name"])]

    @activity.defn(name="seed_repo")
    def seed_repo(self, owner: str, item: dict) -> str:
        """Check one repo completely, then store it. Stored only when the check finished, so a
        failed check is retried rather than saved as "no Compose file"."""
        try:
            repo = repo_from_item(item)
        except (RateLimited, Unavailable) as e:
            raise _retryable(e) from e
        self.ingest(repo, self.repo_vec(self.embedder, repo), source=owner)
        return repo.full_name


async def run_seeding(
    client: Client, owners: list[str], activities: SeedActivities, done: asyncio.Event
) -> None:
    """Run a worker for the seed workflow, start one run per owner, and serve until `done`."""
    worker = Worker(
        client, task_queue=TASK_QUEUE, workflows=[SeedOwnerWorkflow],
        activities=[activities.list_missing, activities.seed_repo],
        activity_executor=ThreadPoolExecutor(max_workers=CONCURRENCY + 2),
    )  # fmt: skip
    async with worker:
        for owner in owners:
            await client.start_workflow(
                SeedOwnerWorkflow.run, owner, id=workflow_id(owner), task_queue=TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )  # fmt: skip
        await done.wait()
