"""Locale and script helpers. Language metadata travels with requests and traces."""

from __future__ import annotations

import re
from dataclasses import dataclass

SUPPORTED_LOCALES = ("en-IN", "hi-IN", "mr-IN")
DEFAULT_LOCALE = "en-IN"

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_LATIN = re.compile(r"[A-Za-z]")

# Lightweight lexical priors for Hinglish / Marathi-English routing (FR-I18N-04).
_MR_HINTS = re.compile(
    r"(?i)\b(aahe|nahi|mala|tumhi|dok|dokate|tap|khokla|vedana|aaj|udya)\b"
)
_HI_HINTS = re.compile(
    r"(?i)\b(hai|nahi|mujhe|aap|dard|bukhar|khansi|aaj|kal|doctor|davai)\b"
)
_MR_DEV = re.compile(r"(आहे|नाही|मला|तुम्ही|डॉक्टर|ताप|खोकला|वेदना)")
_HI_DEV = re.compile(r"(है|नहीं|मुझे|आप|दर्द|बुखार|खाँसी|डॉक्टर)")


@dataclass(frozen=True, slots=True)
class LocaleDetection:
    locale: str
    confidence: float
    scripts: frozenset[str]
    mixed: bool
    needs_clarify: bool


def normalize_locale(value: str | None) -> str:
    if not value:
        return DEFAULT_LOCALE
    lowered = value.strip().replace("_", "-").lower()
    if lowered.startswith("hi"):
        return "hi-IN"
    if lowered.startswith("mr"):
        return "mr-IN"
    return DEFAULT_LOCALE


def detect_scripts(text: str) -> set[str]:
    scripts: set[str] = set()
    if _DEVANAGARI.search(text):
        scripts.add("devanagari")
    if _LATIN.search(text):
        scripts.add("latin")
    return scripts


def is_mixed_language(text: str) -> bool:
    return len(detect_scripts(text)) > 1


def detect_locale(text: str, *, fallback: str = DEFAULT_LOCALE) -> LocaleDetection:
    """Heuristic BCP-47 locale detection for intake (no cloud dependency)."""
    sample = (text or "").strip()
    scripts = frozenset(detect_scripts(sample))
    mixed = len(scripts) > 1
    if not sample:
        return LocaleDetection(
            locale=normalize_locale(fallback),
            confidence=0.0,
            scripts=scripts,
            mixed=False,
            needs_clarify=True,
        )

    scores = {"en-IN": 0.15, "hi-IN": 0.0, "mr-IN": 0.0}
    if "latin" in scripts:
        scores["en-IN"] += 0.35
    if "devanagari" in scripts:
        scores["hi-IN"] += 0.25
        scores["mr-IN"] += 0.25
    hi_hits = len(_HI_HINTS.findall(sample)) + len(_HI_DEV.findall(sample))
    mr_hits = len(_MR_HINTS.findall(sample)) + len(_MR_DEV.findall(sample))
    scores["hi-IN"] += min(0.55, 0.12 * hi_hits)
    scores["mr-IN"] += min(0.55, 0.12 * mr_hits)
    if mixed and hi_hits + mr_hits == 0:
        # Hinglish without strong Marathi markers → Hindi-leaning mixed.
        scores["hi-IN"] += 0.2

    locale = max(scores, key=scores.get)
    confidence = round(min(0.98, scores[locale]), 3)
    # Prefer explicit session fallback when detection is weak and latin-only.
    if confidence < 0.45 and "devanagari" not in scripts:
        locale = normalize_locale(fallback)
        confidence = max(confidence, 0.4)
    needs_clarify = confidence < 0.55 or (mixed and confidence < 0.7)
    return LocaleDetection(
        locale=locale,
        confidence=confidence,
        scripts=scripts,
        mixed=mixed,
        needs_clarify=needs_clarify,
    )
