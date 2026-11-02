from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import RedisSettings


async def enqueue(
    redis_url: str, function: str, *args: Any, queue_name: str | None = None
) -> str | None:
    pool = await create_pool(RedisSettings.from_dsn(redis_url))
    try:
        job = await pool.enqueue_job(function, *args, _queue_name=queue_name)
    finally:
        await pool.aclose()
    return job.job_id if job is not None else None
