"""Shared agent turn types."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

IntentLabel = Literal[
    "emergency",
    "book_appointment",
    "records_question",
    "medication_question",
    "nursing_summary",
    "appointment_help",
    "other",
    "clarify",
]


@dataclass(slots=True)
class AgentTurnResult:
    """Normalized result from any chat-facing graph."""

    content: str
    intent: IntentLabel
    graph: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    red_flag: dict[str, Any] | None = None
    model_alias: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    gateway_request_id: str | None = None
    purpose: str = "conversation"
    metadata: dict[str, Any] = field(default_factory=dict)
    patient_id: uuid.UUID | None = None
