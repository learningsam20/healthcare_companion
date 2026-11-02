"""PII detection, redaction, and token vault.

When Presidio + GLiNER-PII weights are available, reports engine=composite so the API
PII gate can allow gated egress. Otherwise falls back to regex and stays fail-closed
for egress (not_clinical_grade=true).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any

from sahyog_common.context import ExecutionContext
from sahyog_common.mcp_service import create_mcp_app

PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone_in": re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)"),
    "aadhaar": re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
    "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "mrn": re.compile(r"\bMRN[\s:-]*\d{4,12}\b", re.IGNORECASE),
}

_TOKEN_VAULT: dict[str, str] = {}
_COMPOSITE: dict[str, Any] | None = None
_COMPOSITE_TRIED = False


def _token_secret() -> bytes:
    raw = os.environ.get("PII_TOKEN_SECRET", "").strip() or "dev-only-insecure-pii-token"
    return raw.encode("utf-8")


def _regex_spans(text: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for entity_type, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            found.append(
                {
                    "type": entity_type,
                    "start": match.start(),
                    "end": match.end(),
                    "text": match.group(0),
                    "engine": "regex",
                }
            )
    found.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    deduped: list[dict[str, Any]] = []
    for span in found:
        if deduped and span["start"] < deduped[-1]["end"]:
            continue
        deduped.append(span)
    return deduped


def _load_composite() -> dict[str, Any] | None:
    global _COMPOSITE, _COMPOSITE_TRIED
    if _COMPOSITE_TRIED:
        return _COMPOSITE
    _COMPOSITE_TRIED = True
    if os.environ.get("PII_ENGINE", "composite").strip().lower() not in {
        "composite",
        "presidio",
        "gliner",
    }:
        return None
    if os.environ.get("PRESIDIO_ENABLED", "true").strip().lower() in {"0", "false", "no"}:
        return None

    analyzers: list[Any] = []
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        # Default Presidio config wants en_core_web_lg; local stack ships en_core_web_sm.
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        ).create_engine()
        analyzers.append(("presidio", AnalyzerEngine(nlp_engine=nlp_engine)))
    except BaseException:
        # Includes SystemExit from spacy.cli.download on missing models —
        # fall through to GLiNER / regex_fallback rather than killing the request.
        pass

    gliner_path = os.environ.get("GLINER_MODEL", "").strip() or "/models/gliner-pii/gliner-pii-large-v1.0"
    if os.environ.get("GLINER_ENABLED", "true").strip().lower() not in {"0", "false", "no"}:
        try:
            from gliner import GLiNER

            if _path_exists(gliner_path):
                analyzers.append(("gliner", GLiNER.from_pretrained(gliner_path)))
        except BaseException:
            pass

    if not analyzers:
        _COMPOSITE = None
        return None
    _COMPOSITE = {"analyzers": analyzers}
    return _COMPOSITE


def _path_exists(path: str) -> bool:
    from pathlib import Path

    return Path(path).exists()


def _composite_spans(text: str) -> list[dict[str, Any]] | None:
    bundle = _load_composite()
    if bundle is None:
        return None
    spans: list[dict[str, Any]] = []
    for name, engine in bundle["analyzers"]:
        if name == "presidio":
            try:
                results = engine.analyze(text=text, language="en")
                for item in results:
                    spans.append(
                        {
                            "type": str(item.entity_type).lower(),
                            "start": int(item.start),
                            "end": int(item.end),
                            "text": text[int(item.start) : int(item.end)],
                            "engine": "presidio",
                        }
                    )
            except Exception:
                continue
        elif name == "gliner":
            try:
                labels = [
                    "person",
                    "email",
                    "phone number",
                    "address",
                    "date of birth",
                    "medical record number",
                    "aadhaar",
                    "pan",
                ]
                threshold = float(os.environ.get("PII_SCORE_THRESHOLD", "0.65"))
                for hit in engine.predict_entities(text, labels, threshold=threshold):
                    start = int(hit.get("start", 0))
                    end = int(hit.get("end", 0))
                    spans.append(
                        {
                            "type": str(hit.get("label", "pii")).lower().replace(" ", "_"),
                            "start": start,
                            "end": end,
                            "text": text[start:end],
                            "engine": "gliner",
                        }
                    )
            except Exception:
                continue
    # Always union regex for India-specific IDs
    spans.extend(_regex_spans(text))
    spans.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    deduped: list[dict[str, Any]] = []
    for span in spans:
        if deduped and span["start"] < deduped[-1]["end"]:
            continue
        deduped.append(span)
    return deduped


def _spans(text: str) -> tuple[list[dict[str, Any]], str, bool]:
    composite = _composite_spans(text)
    if composite is not None and _COMPOSITE is not None:
        return composite, "composite", False
    return _regex_spans(text), "regex_fallback", True


def detect(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text is required")
    spans, engine, not_clinical = _spans(text)
    return {
        "engine": engine,
        "not_clinical_grade": not_clinical,
        "count": len(spans),
        "entities": [
            {"type": span["type"], "start": span["start"], "end": span["end"]} for span in spans
        ],
    }


def redact(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text is required")
    spans, engine, not_clinical = _spans(text)
    redacted = text
    for span in reversed(spans):
        placeholder = f"[{span['type'].upper()}]"
        redacted = redacted[: span["start"]] + placeholder + redacted[span["end"] :]
    return {
        "engine": engine,
        "not_clinical_grade": not_clinical,
        "count": len(spans),
        "types": sorted({span["type"] for span in spans}),
        "redacted_text": redacted,
    }


def tokenize(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text is required")
    spans, engine, not_clinical = _spans(text)
    out = text
    tokens: list[dict[str, str]] = []
    for span in reversed(spans):
        value = span["text"]
        digest = hmac.new(_token_secret(), value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        token = f"tok_{span['type']}_{digest}"
        _TOKEN_VAULT[token] = value
        tokens.append({"token": token, "type": span["type"]})
        out = out[: span["start"]] + token + out[span["end"] :]
    return {
        "engine": engine,
        "not_clinical_grade": not_clinical,
        "tokenized_text": out,
        "tokens": list(reversed(tokens)),
        "count": len(tokens),
    }


def restore_in_private_boundary(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    """Restore tokens only inside the private boundary (MCP with signed context)."""
    text = args.get("text")
    if not isinstance(text, str):
        raise ValueError("text is required")
    restored = text
    used = 0
    for token, value in list(_TOKEN_VAULT.items()):
        if token in restored:
            restored = restored.replace(token, value)
            used += 1
    return {"restored_text": restored, "restored_count": used}


app = create_mcp_app(
    "pii",
    {
        "detect": (detect, "Detect PII spans (composite when models loaded)"),
        "redact": (redact, "Redact detected PII"),
        "tokenize": (tokenize, "Replace PII with reversible tokens in the private boundary"),
        "restore_in_private_boundary": (
            restore_in_private_boundary,
            "Restore tokens only inside the private MCP boundary",
        ),
    },
)
