"""session_title graph — short neutral title after first turn / intent refine."""

from __future__ import annotations

import re
from typing import Any

from app.agents.llm_gateway import LlmGateway, LlmGatewayError
from app.agents.pii_gate import PiiGate

PLACEHOLDER_TITLES = frozenset({"", "New conversation", "New chat"})


class SessionTitleGraph:
    VERSION = "session_title.v2"

    def __init__(self, *, settings: Any, models_config: dict[str, Any]) -> None:
        self._gateway = LlmGateway(settings, models_config)
        self._pii = PiiGate(settings)
        self._settings = settings

    async def run(
        self,
        *,
        first_user_text: str,
        locale: str,
        prior_user_texts: list[str] | None = None,
        intent_hint: str | None = None,
    ) -> str:
        pieces = [first_user_text.strip()]
        for item in prior_user_texts or []:
            text = (item or "").strip()
            if text and text not in pieces:
                pieces.append(text)
        joined = " | ".join(pieces)[:900]
        scrubbed = joined
        try:
            gate = await self._pii.redact(joined, trace_id="session-title")
            if gate.healthy and gate.redacted_text:
                scrubbed = gate.redacted_text
        except Exception:  # noqa: BLE001 - title must never fail the turn
            scrubbed = joined

        hint = f"Detected intent (routing only): {intent_hint}." if intent_hint else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "Write a short chat session title (3-6 words, max 60 characters). "
                    "Neutral, sentence case, no quotes, no PII, no diagnosis, no clinic inventing. "
                    "Reply with the title only."
                ),
            },
            {
                "role": "user",
                "content": f"Locale: {locale}\n{hint}\nMessages: {scrubbed[:500]}",
            },
        ]
        try:
            self._gateway.resolve("title")
            purpose = "title"
        except LlmGatewayError:
            purpose = "conversation"
        try:
            result = await self._gateway.complete(
                purpose=purpose,
                messages=messages,
                max_tokens=24,
                temperature=0.2,
            )
            title = _clean_title(result.content)
            if title and title not in PLACEHOLDER_TITLES:
                return title
        except LlmGatewayError:
            pass
        return _fallback_title(joined)


def _clean_title(raw: str) -> str:
    text = (raw or "").strip().strip("\"'`")
    text = re.sub(r"[\n\r]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    if len(text) > 60:
        text = text[:57].rstrip() + "…"
    return text


def _fallback_title(text: str) -> str:
    words = re.findall(r"[\w\u0900-\u097F]+", text)
    if not words:
        return "New conversation"
    joined = " ".join(words[:5])
    return joined[:60] if joined else "New conversation"


def is_placeholder_title(title: str | None) -> bool:
    return (title or "").strip() in PLACEHOLDER_TITLES
