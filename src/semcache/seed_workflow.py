"""The seeding workflow. Kept free of app imports (httpx and the like): Temporal re-imports this
module inside its workflow sandbox, and anything heavy here fails that check."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

TASK_QUEUE = "semcache-seed"
CONCURRENCY = 8  # repos checked at once

RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=12,
    non_retryable_error_types=["UnknownOwner"],
)


@workflow.defn
class SeedOwnerWorkflow:
    @workflow.run
    async def run(self, owner: str) -> dict:
        items = await workflow.execute_activity(
            "list_missing", owner, start_to_close_timeout=timedelta(minutes=5), retry_policy=RETRY
        )
        gate, failed = asyncio.Semaphore(CONCURRENCY), []

        async def one(item: dict) -> None:
            async with gate:
                try:
                    await workflow.execute_activity(
                        "seed_repo", args=[owner, item],
                        start_to_close_timeout=timedelta(minutes=10), retry_policy=RETRY,
                    )  # fmt: skip
                except ActivityError:  # out of retries: note it, keep seeding the others
                    failed.append(item["full_name"])

        await asyncio.gather(*(one(i) for i in items))
        return {"owner": owner, "added": len(items) - len(failed), "failed": sorted(failed)}
