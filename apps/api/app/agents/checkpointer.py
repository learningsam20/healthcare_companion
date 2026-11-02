"""LangGraph Postgres checkpointer for durable interrupts across replicas."""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def invoke_config(*, thread_id: str | None = None, checkpoint_ns: str = "") -> dict[str, Any]:
    """Config required when a Postgres checkpointer is compiled into the graph."""
    return {
        "configurable": {
            "thread_id": thread_id or str(uuid.uuid4()),
            "checkpoint_ns": checkpoint_ns,
        }
    }


async def open_checkpointer(database_url: str | None) -> Any | None:
    """Open a long-lived AsyncPostgresSaver, or None if unavailable."""
    if not database_url:
        return None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        logger.warning(
            "langgraph postgres checkpointer unavailable",
            extra={
                "event": "graph.checkpointer_import_failed",
                "extra_fields": {"reason": str(exc)},
            },
        )
        return None
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        # from_conn_string returns an async context manager in recent versions
        cm = AsyncPostgresSaver.from_conn_string(dsn)
        if hasattr(cm, "__aenter__"):
            saver = await cm.__aenter__()
            await saver.setup()
            # stash closer on the saver for lifespan shutdown
            saver._sahyog_cm = cm  # type: ignore[attr-defined]
            return saver
        await cm.setup()  # type: ignore[attr-defined]
        return cm
    except Exception as exc:  # noqa: BLE001
        hint = ""
        reason = str(exc)
        if "libpq" in reason or "pq wrapper" in reason:
            hint = " (install psycopg[binary] via uv sync --all-packages for host/--local)"
        logger.warning(
            "checkpointer setup failed%s",
            hint,
            extra={"event": "graph.checkpointer_failed", "extra_fields": {"reason": reason}},
        )
        return None


async def close_checkpointer(saver: Any | None) -> None:
    if saver is None:
        return
    cm = getattr(saver, "_sahyog_cm", None)
    if cm is not None and hasattr(cm, "__aexit__"):
        try:
            await cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            logger.debug("checkpointer close failed", exc_info=True)


def compile_graph(builder: Any, checkpointer: Any | None = None) -> Any:
    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
