"""Problem+JSON errors shared by the API and MCP services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProblemError(Exception):
    status: int
    code: str
    title: str
    detail: str
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.detail)

    def to_problem(self, instance: str | None = None) -> dict[str, Any]:
        problem: dict[str, Any] = {
            "type": f"https://errors.sahyog.invalid/{self.code}",
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
        }
        if instance:
            problem["instance"] = instance
        problem.update(self.extra)
        return problem
