from __future__ import annotations

import datetime as dt
from typing import Any

from app.repositories.analytics import AnalyticsRepository
from sqlalchemy.dialects import postgresql


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return 0

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)

        class _Result:
            def one(self) -> tuple[float, int]:
                return (0.0, 0)

        return _Result()


async def test_load_guard_counts_only_human_actors() -> None:
    session = _RecordingSession()
    repository = AnalyticsRepository(session)  # type: ignore[arg-type]
    end = dt.datetime.now(dt.UTC)
    await repository.load_guard(
        start=end - dt.timedelta(minutes=15),
        end=end,
        exclude_subjects={"loadtest.patient01"},
    )

    activity, actors, _usage = session.statements
    for statement in (activity, actors):
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = str(compiled)
        assert "NOT LIKE" in sql
        assert "system:%" in compiled.params.values()
