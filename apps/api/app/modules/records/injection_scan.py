"""Prompt-injection / instruction-override scan for untrusted document text.

Matches are tagged and excluded from retrieval (`retrieval_allowed=false`).
Never treats document text as executable instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_instructions",
        re.compile(
            r"(?i)\b(ignore|disregard|override)\b.{0,40}\b(previous|prior|system|above)\b.{0,20}"
            r"\b(instructions?|rules?|prompt)\b",
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"(?i)\b(you are now|act as|pretend to be|jailbreak)\b.{0,40}"
            r"\b(system|admin|developer|unrestricted)\b",
        ),
    ),
    (
        "exfiltrate",
        re.compile(
            r"(?i)\b(reveal|exfiltrate|dump|print)\b.{0,40}"
            r"\b(system prompt|api key|other patient|all records|secret)\b",
        ),
    ),
    (
        "tool_coerce",
        re.compile(
            r"(?i)\b(call|invoke|use)\b.{0,20}\b(tool|function|mcp)\b.{0,40}"
            r"\b(without|bypass|ignore)\b.{0,20}\b(consent|scope|auth)\b",
        ),
    ),
    (
        "delimiter_break",
        re.compile(r"(?i)(```system|<<\s*SYS\s*>>|\[INST\]|</?(system|assistant)>)"),
    ),
)


@dataclass(frozen=True, slots=True)
class InjectionHit:
    tag: str
    pattern_id: str
    excerpt: str


def scan_text(text: str, *, max_hits: int = 8) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    if not text or not text.strip():
        return hits
    for pattern_id, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 20)
            excerpt = text[start:end].replace("\n", " ").strip()[:160]
            hits.append(
                InjectionHit(
                    tag="prompt_injection",
                    pattern_id=pattern_id,
                    excerpt=excerpt,
                )
            )
            if len(hits) >= max_hits:
                return hits
    return hits


def quarantine_decision(hits: list[InjectionHit]) -> tuple[bool, str | None]:
    """Return (retrieval_allowed, quarantine_tag)."""
    if not hits:
        return True, None
    return False, "prompt_injection"
