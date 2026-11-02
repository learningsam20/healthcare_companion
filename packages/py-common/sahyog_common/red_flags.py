"""Deterministic red-flag detection shared by the API and MCP clinical services.

Matching is case-insensitive and Unicode-safe. A rule with qualifiers fires only when
a base pattern and at least one qualifier are present. The demo rule set is not
clinically validated.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sahyog_common.provenance import SourceRef, SourceType


@dataclass(frozen=True, slots=True)
class RedFlagMatch:
    rule_id: str
    name: str
    severity: str
    action: str
    guidance: str


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(_normalize(phrase))}(?!\w)", text) is not None


def detect_red_flags(
    text: str, config: dict[str, Any], locale: str = "en-IN"
) -> list[RedFlagMatch]:
    normalized = _normalize(text)
    copy = config.get("safety_copy", {})
    matches: list[RedFlagMatch] = []
    for rule in config.get("rules", []):
        patterns = [_normalize(item) for item in rule.get("patterns", [])]
        if not any(_contains(normalized, pattern) for pattern in patterns):
            continue
        qualifiers = rule.get("qualifiers") or []
        if qualifiers and not any(_contains(normalized, item) for item in qualifiers):
            continue
        severity = str(rule.get("severity", "urgent"))
        guidance = copy.get(f"{severity}_{locale.split('-')[0]}") or copy.get(f"{severity}_en", "")
        matches.append(
            RedFlagMatch(
                rule_id=str(rule["id"]),
                name=str(rule["name"]),
                severity=severity,
                action=str(rule.get("action", "same_day_clinician")),
                guidance=str(guidance),
            )
        )
    return matches


def red_flag_sources(matches: list[RedFlagMatch]) -> list[SourceRef]:
    return [
        SourceRef(
            id=match.rule_id,
            type=SourceType.RULE,
            title=f"Red-flag rule: {match.name}",
            locator=match.rule_id,
        )
        for match in matches
    ]
