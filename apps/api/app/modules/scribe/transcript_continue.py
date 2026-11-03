"""Decide how a new dictation save relates to turns already stored."""

from __future__ import annotations


def continued_turns(
    prior: list[tuple[str, str]], incoming: list[tuple[str, str]]
) -> list[tuple[str, str]] | None:
    """Append new transcript turns. None means the incoming tail is already saved."""
    if incoming and prior and len(prior) >= len(incoming) and prior[-len(incoming) :] == incoming:
        return None
    return [*prior, *incoming]
