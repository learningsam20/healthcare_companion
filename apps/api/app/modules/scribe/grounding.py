"""SOAP draft schema validation and line-level grounding.

A schema or citation failure on a SOAP line is a hard failure: nothing is persisted
and the doctor sees a retryable error. Unsourced section lines are explicitly
labelled. A medicine the transcript does not support is omitted so the rest of the
draft can still be reviewed; invented drugs are never persisted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.scribe.clinical_prose import fold_sections, polish_line, visit_follow_up
from app.modules.scribe.medicine_match import supporting_turns
from jsonschema import Draft202012Validator

SCHEMA_VERSION = "scribe_v1"
UNSOURCED_LABEL = "[doctor to specify]"
SECTION_FIELDS = ("subjective", "objective", "assessment", "plan")
_PLACEHOLDER_TEXT = {
    "",
    "undefined",
    "null",
    "none",
    "n/a",
    "na",
    "unknown",
    "nil",
    "medicine",
    "something",
    "[doctor to specify]",
    "doctor to specify",
}


class DraftRejected(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def load_schema(config_dir: Path) -> dict[str, Any]:
    path = config_dir / "schemas" / f"{SCHEMA_VERSION}.json"
    schema: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return schema


def parse_model_output(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DraftRejected("draft_invalid_json", "The model did not return valid JSON.") from exc
    if not isinstance(payload, dict):
        raise DraftRejected("draft_invalid_json", "The model did not return a JSON object.")
    return coerce_model_draft(payload)


def _optional_text(value: Any, *, limit: int) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(value).strip()
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    if text.casefold() in _PLACEHOLDER_TEXT:
        return None
    return text[:limit]


def _placeholder_name(name: str) -> bool:
    return name.casefold() in _PLACEHOLDER_TEXT


def _as_line(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        text = item.strip()
        return {
            "text": text or UNSOURCED_LABEL,
            "source_turn_ids": [],
            "unsourced": True,
        }
    if not isinstance(item, dict):
        return {"text": UNSOURCED_LABEL, "source_turn_ids": [], "unsourced": True}
    text = str(item.get("text") or "").strip() or UNSOURCED_LABEL
    turn_ids_raw = item.get("source_turn_ids") or []
    turn_ids = [int(value) for value in turn_ids_raw if str(value).lstrip("-").isdigit()]
    unsourced = bool(item.get("unsourced")) or not turn_ids
    return {"text": text, "source_turn_ids": turn_ids, "unsourced": unsourced}


def coerce_model_draft(payload: dict[str, Any]) -> dict[str, Any]:
    """Repair common local-model shape mistakes before hard schema validation.

    Small instruct models often emit bare strings in SOAP arrays or wrap follow_up
    as a list. Placeholder medicine names and blank dose fields are dropped here;
    transcript grounding still removes any drug the visit did not mention.
    """
    coerced: dict[str, Any] = {}
    for field in SECTION_FIELDS:
        raw = payload.get(field, [])
        if raw is None:
            raw = []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raw = [raw]
        coerced[field] = [_as_line(item) for item in raw]

    follow_up = payload.get("follow_up")
    if isinstance(follow_up, list):
        follow_up = follow_up[0] if follow_up else None
    coerced["follow_up"] = None if follow_up is None else _as_line(follow_up)

    medicines_raw = payload.get("medicines", [])
    if medicines_raw is None:
        medicines_raw = []
    if isinstance(medicines_raw, dict):
        medicines_raw = [medicines_raw]
    medicines: list[dict[str, Any]] = []
    for item in medicines_raw if isinstance(medicines_raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or _placeholder_name(name):
            continue
        turn_ids_raw = item.get("source_turn_ids") or []
        turn_ids = [int(value) for value in turn_ids_raw if str(value).lstrip("-").isdigit()]
        unsourced = bool(item.get("unsourced")) or not turn_ids
        medicines.append(
            {
                "name": name[:200],
                "dose": _optional_text(item.get("dose"), limit=100),
                "frequency": _optional_text(item.get("frequency"), limit=100),
                "duration": _optional_text(item.get("duration"), limit=100),
                "instructions": _optional_text(item.get("instructions"), limit=300),
                "source_turn_ids": turn_ids,
                "unsourced": unsourced,
            }
        )
    coerced["medicines"] = medicines
    return coerced


def validate_structure(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload), key=lambda item: list(item.path)
    )
    if errors:
        first = errors[0]
        path = ".".join(str(item) for item in first.path) or "draft"
        raise DraftRejected(
            "draft_schema_invalid",
            f"The draft failed schema validation at {path}: {first.message}",
        )


def _turns_by_index(turns: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(turn["turn_index"]): turn for turn in turns}


def _line_sources(
    *,
    field: str,
    line_index: int,
    turn_ids: list[int],
    turns: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    unknown = [turn_id for turn_id in turn_ids if turn_id not in turns]
    if unknown:
        raise DraftRejected(
            "draft_citation_unknown",
            f"{field} line {line_index + 1} cites a transcript turn that does not exist.",
        )
    return {
        "field": field,
        "line_index": line_index,
        "source_type": "transcript" if turn_ids else "none",
        "source_ref": {
            "turn_ids": turn_ids,
            "turns": [
                {
                    "turn_index": turn_id,
                    "speaker": turns[turn_id]["speaker"],
                    "start_ms": int(turns[turn_id]["start_ms"]),
                    "end_ms": int(turns[turn_id]["end_ms"]),
                }
                for turn_id in turn_ids
            ],
            "label": None if turn_ids else UNSOURCED_LABEL,
        },
        "status": "resolved" if turn_ids else "unsourced",
        "as_of": None,
    }


def _normalize_line(
    line: dict[str, Any], *, field: str, line_index: int, turns: dict[int, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    text = polish_line(str(line["text"]).strip(), field=field) or str(line["text"]).strip()
    turn_ids = [int(item) for item in line["source_turn_ids"]]
    unsourced = bool(line["unsourced"]) or not turn_ids
    if unsourced and UNSOURCED_LABEL not in text:
        text = f"{text} {UNSOURCED_LABEL}".strip()
    if turn_ids and UNSOURCED_LABEL in text:
        text = text.replace(UNSOURCED_LABEL, "").strip()
        unsourced = False
    normalized = {"text": text, "source_turn_ids": turn_ids, "unsourced": unsourced}
    source = _line_sources(field=field, line_index=line_index, turn_ids=turn_ids, turns=turns)
    return normalized, source


def ground_draft(
    payload: dict[str, Any],
    *,
    turns: list[dict[str, Any]],
    schema: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = coerce_model_draft(payload)
    validate_structure(payload, schema)
    by_index = _turns_by_index(turns)
    normalized: dict[str, Any] = {}
    sources: list[dict[str, Any]] = []
    pending: dict[str, list[dict[str, Any]]] = {}
    for field in SECTION_FIELDS:
        lines: list[dict[str, Any]] = []
        for index, line in enumerate(payload[field]):
            clean, _source = _normalize_line(line, field=field, line_index=index, turns=by_index)
            lines.append(clean)
        pending[field] = lines
    pending = fold_sections(pending, turns)
    for field in SECTION_FIELDS:
        normalized[field] = pending[field]
        for index, line in enumerate(pending[field]):
            sources.append(
                _line_sources(
                    field=field,
                    line_index=index,
                    turn_ids=[int(item) for item in line["source_turn_ids"]],
                    turns=by_index,
                )
            )
    follow_up = payload.get("follow_up") or visit_follow_up(turns)
    if follow_up is not None:
        clean, source = _normalize_line(follow_up, field="follow_up", line_index=0, turns=by_index)
        normalized["follow_up"] = clean
        sources.append(source)
    else:
        normalized["follow_up"] = None

    medicines: list[dict[str, Any]] = []
    for medicine in payload["medicines"]:
        name = str(medicine["name"]).strip()
        if _placeholder_name(name):
            continue
        spoken = supporting_turns(name, turns)
        turn_ids = [int(item) for item in medicine["source_turn_ids"] if int(item) in spoken]
        if not turn_ids:
            turn_ids = spoken
        if not turn_ids:
            # Keep the SOAP draft. An invented or unspoken drug is not a clinical order.
            continue
        medicines.append(
            {**medicine, "name": name, "source_turn_ids": turn_ids, "unsourced": False}
        )
        sources.append(
            _line_sources(
                field="medicine",
                line_index=len(medicines) - 1,
                turn_ids=turn_ids,
                turns=by_index,
            )
        )
    normalized["medicines"] = medicines
    return normalized, sources


def content_hash(content: dict[str, Any]) -> str:
    import hashlib

    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
