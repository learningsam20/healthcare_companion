"""Shared chat session auto-title helpers (Wave F)."""

from __future__ import annotations

import logging

from app.agents.session_title import SessionTitleGraph, is_placeholder_title
from app.core.services import Services
from app.repositories.models import ChatSession

logger = logging.getLogger(__name__)


async def maybe_auto_title(
    *,
    services: Services,
    chat: ChatSession,
    user_texts: list[str],
    intent: str | None = None,
) -> str | None:
    """Generate or refine a system title. Never overwrites user-named titles.

    - Placeholder + ≥1 user turn → first title
    - System title + exactly 3 user turns → one intent refine
    """
    source = getattr(chat, "title_source", None) or "system"
    if source == "user":
        return None

    texts = [t.strip() for t in user_texts if (t or "").strip()]
    user_count = len(texts)
    if user_count < 1:
        return None

    placeholder = is_placeholder_title(chat.title)
    refine = source == "system" and not placeholder and user_count == 3
    first = placeholder and user_count >= 1
    if not first and not refine:
        return None

    graph = SessionTitleGraph(settings=services.settings, models_config=services.models_config)
    try:
        title = await graph.run(
            first_user_text=texts[0],
            locale=chat.locale or "en-IN",
            prior_user_texts=texts[1:],
            intent_hint=intent,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("session title failed", exc_info=exc)
        return None
    if not title or is_placeholder_title(title):
        return None
    if title == chat.title:
        return None
    chat.title = title[:80]
    chat.title_source = "system"
    return chat.title
