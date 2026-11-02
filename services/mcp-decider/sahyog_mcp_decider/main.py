"""Intent classification via OpenDecider (Ollama/LiteLLM), optional Strands Decider, or keywords.

Red-flag rules stay deterministic and authoritative. The model is advisory only.
Spec names OpenDecider (ADR-09). Strands Decider is an optional local fallback when
OpenDecider weights/backends are slow to obtain; responses label the engine honestly.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict
from typing import Any

import httpx
from sahyog_common.context import ExecutionContext
from sahyog_common.files import config_dir, load_yaml
from sahyog_common.mcp_service import create_mcp_app
from sahyog_common.red_flags import detect_red_flags

RED_FLAGS = load_yaml(config_dir() / "red_flags.yaml")

INTENTS: dict[str, list[str]] = {
    "book_appointment": [
        "book",
        "appointment",
        "slot",
        "reschedule",
        "cancel",
        "doctor",
        "बुक",
        "अपॉइंटमेंट",
        "डॉक्टर",
        "तारीख",
        "वेळ",
    ],
    "records_question": [
        "report",
        "prescription",
        "document",
        "lab",
        "test result",
        "discharge",
        "रिपोर्ट",
        "दस्तावेज",
        "दस्तऐवज",
        "चाचणी",
    ],
    "medication_question": [
        "medicine",
        "medication",
        "tablet",
        "dose",
        "pharmacy",
        "refill",
        "दवा",
        "औषध",
        "गोळी",
    ],
    "emergency": [
        "chest pain",
        "bleeding",
        "breathless",
        "unconscious",
        "stroke",
        "सीने में दर्द",
        "छातीत दुखणे",
        "रक्त",
    ],
    "nursing_summary": [
        "nursing",
        "shift handover",
        "handover",
        "nurse",
        "नर्सिंग",
        "हैंडओवर",
    ],
}

VALID_INTENTS = set(INTENTS) | {"other", "clarify", "appointment_help"}
INTENT_CRITERIA = {
    "book_appointment": "User wants to book, reschedule or cancel a clinic appointment",
    "records_question": "User asks about documents, labs, reports or medical records",
    "medication_question": "User asks about medicines, doses, pharmacy or refills",
    "emergency": "Possible emergency symptoms needing urgent handoff",
    "nursing_summary": "Nursing shift handover or X-01 summary request",
    "clarify": "Message is ambiguous and needs clarification",
    "appointment_help": "General appointment navigation without a clear book/cancel act",
    "other": "None of the other intents",
}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _keyword_intent(text: str) -> dict[str, Any]:
    normalized = _normalize(text)
    scores = {
        intent: sum(1 for keyword in keywords if _normalize(keyword) in normalized)
        for intent, keywords in INTENTS.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    intent, score = ranked[0]
    if score == 0:
        return {
            "engine": "deterministic_v1",
            "model": None,
            "intent": "other",
            "category": "conversation",
            "confidence": 0.3,
            "scores": scores,
        }
    return {
        "engine": "deterministic_v1",
        "model": None,
        "intent": intent,
        "category": "clinical" if intent == "emergency" else "workflow",
        "confidence": min(0.55 + 0.1 * score, 0.95),
        "scores": scores,
    }


def _backend() -> str:
    return os.environ.get("DECIDER_BACKEND", "auto").strip().lower() or "auto"


def _openai_compatible_base() -> str | None:
    backend = _backend()
    # Explicit ollama backend must not be shadowed by Compose DECIDER_LLAMA_URL→LiteLLM.
    if backend == "ollama":
        for key in ("OLLAMA_BASE_URL", "OLLAMA_HOST", "OPENAI_BASE_URL"):
            raw = os.environ.get(key, "").strip()
            if raw:
                return raw.rstrip("/")
        return "http://host.docker.internal:11434"
    for key in ("DECIDER_LLAMA_URL", "LITELLM_BASE_URL", "OPENAI_BASE_URL", "OLLAMA_BASE_URL"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw.rstrip("/")
    return None


def _decider_chat_model() -> str:
    return (
        os.environ.get("DECIDER_MODEL", "").strip()
        or os.environ.get(
            "OPENDECIDER_OLLAMA_MODEL",
            "hf.co/manjunathshiva/opendecider-small-GGUF:Q8_0",
        )
    )


def _is_jev_decision_model(model: str | None = None) -> bool:
    """Ollama Jev-style decision models (blog 2026-09-29): nimble / tev1 / tev1:0.8b."""
    name = (model or _decider_chat_model()).strip().lower()
    return name in {"nimble", "tev1", "tev1:0.8b"} or name.startswith("tev1:")


def _strands_url() -> str | None:
    raw = os.environ.get("STRANDS_DECIDER_URL", "").strip()
    return raw.rstrip("/") if raw else None


def _systemone_base() -> str | None:
    """Prefer explicit Strands URL; otherwise host Ollama when using a Jev decision model."""
    strands = _strands_url()
    if strands:
        return strands
    if _is_jev_decision_model() and _backend() in {"auto", "ollama", "strands"}:
        return _openai_compatible_base() or "http://host.docker.internal:11434"
    return None


def _parse_intent_payload(raw: str, *, model: str) -> dict[str, Any] | None:
    """Parse intent JSON from model text (content, reasoning, or thinking)."""
    match = re.search(r"\{.*\}", str(raw or ""), flags=re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    intent = str(data.get("intent", "")).strip()
    if intent not in VALID_INTENTS:
        return None
    confidence = float(data.get("confidence") or 0.7)
    return {
        "engine": "opendecider_openai_compatible",
        "model": model,
        "intent": intent,
        "category": "clinical" if intent == "emergency" else "workflow",
        "confidence": max(0.0, min(confidence, 0.99)),
        "scores": {},
    }


def _message_text_blobs(payload: dict[str, Any]) -> str:
    """OpenDecider-on-Ollama often leaves content empty and puts JSON in reasoning/thinking."""
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") if isinstance(choice, dict) else {}
    if not isinstance(message, dict):
        message = {}
    parts = [
        message.get("content"),
        message.get("reasoning"),
        message.get("thinking"),
        choice.get("text") if isinstance(choice, dict) else None,
        payload.get("response"),
        payload.get("thinking"),
    ]
    return "\n".join(str(p) for p in parts if p)


async def _model_intent_chat(text: str) -> dict[str, Any] | None:
    base = _openai_compatible_base()
    if not base:
        return None
    api_key = (
        os.environ.get("LITELLM_MASTER_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or "sk-local"
    ).strip()
    model = _decider_chat_model()
    ollama_like = "11434" in base or base.rstrip("/").endswith("ollama") or _backend() == "ollama"
    if base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"
    if "/v1/v1/" in url:
        url = url.replace("/v1/v1/", "/v1/")
    prompt = (
        "Classify the user message into exactly one intent. "
        f"Allowed: {sorted(VALID_INTENTS)}. "
        'Reply JSON only: {"intent":"...","confidence":0-1}'
    )
    # Host OpenDecider via Docker can take >2 min on cold load (measured ~180s).
    timeout = float(os.environ.get("DECIDER_HTTP_TIMEOUT_SECONDS", "240" if ollama_like else "20"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0,
                    "max_tokens": 80,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": text[:2000]},
                    ],
                },
            )
            if response.status_code >= 400:
                payload: dict[str, Any] = {}
            else:
                payload = response.json()
            parsed = _parse_intent_payload(_message_text_blobs(payload), model=model)
            if parsed is not None:
                return parsed
            # Ollama OpenDecider: /api/generate puts the JSON in `thinking` with empty `response`.
            if ollama_like:
                gen_base = base[:-3] if base.endswith("/v1") else base
                gen = await client.post(
                    f"{gen_base.rstrip('/')}/api/generate",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": model,
                        "stream": False,
                        "prompt": f"{prompt}\nUser: {text[:2000]}\nJSON:",
                        "options": {"num_predict": 64, "temperature": 0},
                    },
                )
                if gen.status_code < 400:
                    return _parse_intent_payload(_message_text_blobs(gen.json()), model=model)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None
    return None


async def _strands_intent(text: str) -> dict[str, Any] | None:
    """Typed choice via Ollama/Strands /v1/systemone (Jev-style decision models)."""
    base = _systemone_base()
    if not base:
        return None
    model = (
        os.environ.get("STRANDS_DECIDER_MODEL", "").strip()
        or _decider_chat_model()
        or "nimble"
    )
    options = {name: INTENT_CRITERIA[name] for name in sorted(VALID_INTENTS) if name in INTENT_CRITERIA}
    # Ensure all VALID_INTENTS appear
    for name in sorted(VALID_INTENTS):
        options.setdefault(name, name.replace("_", " "))
    payload: dict[str, Any] = {
        "model": model,
        "state": {"message": text[:4000]},
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "Which workflow intent best matches the user message?",
                "criteria": options,
            }
        },
    }
    timeout = float(os.environ.get("DECIDER_HTTP_TIMEOUT_SECONDS", "60"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base.rstrip('/')}/v1/systemone",
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code >= 400:
                return None
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    answers = data.get("answers") or data.get("questions") or data
    block = answers.get("intent") if isinstance(answers, dict) else None
    if not isinstance(block, dict):
        return None
    intent = str(block.get("answer") or block.get("choice") or "").strip()
    if intent not in VALID_INTENTS:
        # Some servers return {"intent": {"billing": 0.7, ...}} style
        probs = block.get("probabilities") or block.get("scores") or block
        if isinstance(probs, dict):
            ranked = sorted(
                ((k, float(v)) for k, v in probs.items() if k in VALID_INTENTS),
                key=lambda item: item[1],
                reverse=True,
            )
            if ranked:
                intent, confidence = ranked[0]
            else:
                return None
        else:
            return None
    else:
        confidence = float(block.get("confidence") or block.get("probability") or 0.7)
    engine = "ollama_jev_decider" if _is_jev_decision_model(model) else "strands_decider"
    return {
        "engine": engine,
        "model": model,
        "intent": intent,
        "category": "clinical" if intent == "emergency" else "workflow",
        "confidence": max(0.0, min(float(confidence), 0.99)),
        "scores": {},
        "note": (
            "Ollama Jev-style decision model via /v1/systemone"
            if engine == "ollama_jev_decider"
            else "Optional Strands fallback; prefer Jev decision models (nimble/tev1) locally."
        ),
    }


def _opendecider_weights_path() -> str:
    return (
        os.environ.get("OPENDECIDER_GGUF", "").strip()
        or os.environ.get("DECIDER_GGUF", "").strip()
        or "/models/opendecider/model.gguf"
    )


def _opendecider_required() -> bool:
    return os.environ.get("OPENDECIDER_REQUIRED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _weights_present() -> bool:
    from pathlib import Path

    return Path(_opendecider_weights_path()).exists()


async def classify_intent(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    backend = _backend()
    if _opendecider_required() and not _openai_compatible_base() and not _weights_present() and not _strands_url():
        raise ValueError(
            "opendecider_weights_missing: set OPENDECIDER_GGUF, DECIDER_LLAMA_URL, "
            "STRANDS_DECIDER_URL, or unset OPENDECIDER_REQUIRED to allow keyword fallback"
        )
    modeled: dict[str, Any] | None = None
    # Prefer Jev-style /v1/systemone (nimble/tev1) when configured — far smaller than
    # multi-GB OpenDecider/chat residents that starve qwen2.5:3b chat latency.
    if backend in {"auto", "ollama", "strands"} and (
        _is_jev_decision_model() or _strands_url()
    ):
        modeled = await _strands_intent(text.strip())
    # OpenDecider/Ollama chat-completions path (ADR-09) when not using a Jev model.
    if modeled is None and backend in {"auto", "opendecider", "ollama", "openai_compatible"}:
        if not _is_jev_decision_model():
            modeled = await _model_intent_chat(text.strip())
    if modeled is not None:
        return modeled
    fallback = _keyword_intent(text)
    if _opendecider_required():
        fallback["opendecider_unavailable"] = True
        fallback["weights_present"] = _weights_present()
        fallback["backend"] = _openai_compatible_base() or _strands_url() or None
    return fallback


def classify_red_flag(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is required")
    locale = args.get("locale", context.locale)
    matches = detect_red_flags(text, RED_FLAGS, str(locale))
    return {
        "engine": "deterministic_rules",
        "model": None,
        "count": len(matches),
        "matches": [asdict(match) for match in matches],
        "escalate": any(match.severity in {"emergency", "urgent"} for match in matches),
    }


def explain_decision(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    weights = _weights_present()
    backend = _openai_compatible_base()
    return {
        "method": (
            "OpenDecider via Ollama/LiteLLM/llama-server when available; "
            "optional Strands Decider at STRANDS_DECIDER_URL; else keyword scoring"
        ),
        "limits": [
            "Not a clinical model and not clinically validated.",
            "Deterministic red-flag rules run independently and take precedence.",
            "Keyword fallback is never labelled as OpenDecider.",
            "Strands Decider is an optional local fallback, not a rename of OpenDecider.",
        ],
        "version": "opendecider_or_strands_or_deterministic_v1",
        "decider_backend": _backend(),
        "chat_model": _decider_chat_model(),
        "strands_url": _strands_url(),
        "backend": backend or ("keyword_only" if not weights else "gguf_present_backend_unconfigured"),
        "weights_present": weights,
        "weights_path": _opendecider_weights_path(),
        "opendecider_required": _opendecider_required(),
    }


app = create_mcp_app(
    "decider",
    {
        "classify_intent": (
            classify_intent,
            "Map multilingual text to an intent used for tool and model routing.",
        ),
        "classify_red_flag": (
            classify_red_flag,
            "Run the deterministic red-flag rule set as a second signal.",
        ),
        "explain_decision": (
            explain_decision,
            "Explain the decision method and its limits.",
        ),
    },
)
