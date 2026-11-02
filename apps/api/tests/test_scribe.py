from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.agents.llm_gateway import LlmResult
from app.agents.scribe_graph import ScribeDraftGraph
from app.core.config import Settings
from app.modules.scribe.grounding import (
    DraftRejected,
    content_hash,
    ground_draft,
    load_schema,
    parse_model_output,
    validate_structure,
)
from sahyog_common.context import ExecutionContext, Role

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = load_schema(ROOT / "config")

TURNS = [
    {
        "turn_index": 0,
        "speaker": "patient",
        "start_ms": 0,
        "end_ms": 4000,
        "text": "I have had fever for three days and a headache.",
    },
    {
        "turn_index": 1,
        "speaker": "doctor",
        "start_ms": 4000,
        "end_ms": 8000,
        "text": "I will prescribe paracetamol 500 mg twice daily for three days.",
    },
]

DRAFT = {
    "subjective": [{"text": "Fever for three days.", "source_turn_ids": [0], "unsourced": False}],
    "objective": [],
    "assessment": [{"text": "Viral fever.", "source_turn_ids": [], "unsourced": True}],
    "plan": [
        {
            "text": "Paracetamol 500 mg twice daily.",
            "source_turn_ids": [1],
            "unsourced": False,
        }
    ],
    "follow_up": None,
    "medicines": [
        {
            "name": "paracetamol",
            "dose": "500 mg",
            "frequency": "twice daily",
            "duration": "three days",
            "instructions": None,
            "source_turn_ids": [1],
            "unsourced": False,
        }
    ],
}


def _context() -> ExecutionContext:
    now = int(time.time())
    return ExecutionContext(
        actor_subject="doctor-1",
        actor_role=Role.DOCTOR,
        patient_id=uuid.uuid4(),
        clinic_ids=("CLINIC-A",),
        trace_id="trace-scribe",
        locale="en-IN",
        issued_at=now,
        expires_at=now + 60,
    )


class FakeTools:
    async def call(self, **_: Any) -> dict[str, Any]:
        return {
            "status": "in_stock",
            "drug_name": "paracetamol",
            "clinic_code": "CLINIC-A",
            "source": "test stock",
            "as_of": "2026-10-25T00:00:00+00:00",
            "stale": False,
        }


def _graph(monkeypatch: pytest.MonkeyPatch, content: str) -> ScribeDraftGraph:
    graph = ScribeDraftGraph(
        settings=Settings(),
        models_config=yaml.safe_load((ROOT / "config" / "models.yaml").read_text()),
        red_flags_config=yaml.safe_load((ROOT / "config" / "red_flags.yaml").read_text()),
        prompt=yaml.safe_load((ROOT / "config" / "prompts" / "scribe.yaml").read_text()),
        config_dir=ROOT / "config",
        tool_client=FakeTools(),  # type: ignore[arg-type]
        stock_source="test stock",
    )

    async def fake_complete(**_: Any) -> LlmResult:
        return LlmResult(
            content=content,
            model_alias="local_main",
            prompt_tokens=100,
            completion_tokens=50,
        )

    monkeypatch.setattr(graph._gateway, "complete", fake_complete)
    return graph


def test_ground_draft_resolves_citations_and_labels_unsourced_lines() -> None:
    draft, sources = ground_draft(DRAFT, turns=TURNS, schema=SCHEMA)
    assert draft["subjective"][0]["text"] == "Fever for three days."
    assert draft["assessment"][0]["text"].endswith("[doctor to specify]")
    subjective = next(source for source in sources if source["field"] == "subjective")
    assert subjective["status"] == "resolved"
    assert subjective["source_ref"]["turn_ids"] == [0]
    assessment = next(source for source in sources if source["field"] == "assessment")
    assert assessment["status"] == "unsourced"
    assert assessment["source_ref"]["turn_ids"] == []


def test_ground_draft_rejects_unknown_citation() -> None:
    bad = {**DRAFT, "subjective": [{"text": "Fever.", "source_turn_ids": [99], "unsourced": False}]}
    with pytest.raises(DraftRejected, match="does not exist") as exc:
        ground_draft(bad, turns=TURNS, schema=SCHEMA)
    assert exc.value.code == "draft_citation_unknown"


def test_ground_draft_rejects_medicine_without_transcript_basis() -> None:
    bad: dict[str, Any] = {
        **DRAFT,
        "medicines": [
            {
                "name": "ibuprofen",
                "dose": None,
                "frequency": None,
                "duration": None,
                "instructions": None,
                "source_turn_ids": [],
                "unsourced": True,
            }
        ],
    }
    with pytest.raises(DraftRejected, match="no transcript basis") as exc:
        ground_draft(bad, turns=TURNS, schema=SCHEMA)
    assert exc.value.code == "medicine_unsourced"


def test_ground_draft_rejects_medicine_name_not_in_cited_turn() -> None:
    bad = {
        **DRAFT,
        "medicines": [
            {
                "name": "amoxicillin",
                "dose": None,
                "frequency": None,
                "duration": None,
                "instructions": None,
                "source_turn_ids": [1],
                "unsourced": False,
            }
        ],
    }
    with pytest.raises(DraftRejected, match="not supported") as exc:
        ground_draft(bad, turns=TURNS, schema=SCHEMA)
    assert exc.value.code == "medicine_ungrounded"


def test_schema_validation_rejects_extra_fields() -> None:
    bad = {**DRAFT, "private_notes": "should not exist"}
    with pytest.raises(DraftRejected) as exc:
        validate_structure(bad, SCHEMA)
    assert exc.value.code == "draft_schema_invalid"


def test_parse_model_output_strips_json_fence() -> None:
    payload = parse_model_output(f"```json\n{json.dumps(DRAFT)}\n```")
    assert payload["subjective"][0]["text"] == "Fever for three days."


def test_coerce_repairs_bare_plan_strings_and_follow_up_list() -> None:
    messy = {
        "subjective": [{"text": "Fever for three days.", "source_turn_ids": [0], "unsourced": False}],
        "objective": [],
        "assessment": [],
        "plan": ["Hydration and rest."],
        "follow_up": [{"text": "Return if worse.", "source_turn_ids": [1], "unsourced": False}],
        "medicines": [
            {
                "name": "paracetamol",
                "dose": "500 mg",
                "frequency": "twice daily",
                "duration": "three days",
                "instructions": None,
                "source_turn_ids": [1],
                "unsourced": False,
            }
        ],
    }
    draft, _sources = ground_draft(messy, turns=TURNS, schema=SCHEMA)
    assert draft["plan"][0]["text"].startswith("Hydration and rest.")
    assert draft["plan"][0]["unsourced"] is True
    assert "[doctor to specify]" in draft["plan"][0]["text"]
    assert draft["follow_up"]["text"] == "Return if worse."
    assert draft["medicines"][0]["name"] == "paracetamol"


def test_content_hash_is_stable_across_key_order() -> None:
    reordered = dict(reversed(list(DRAFT.items())))
    assert content_hash(DRAFT) == content_hash(reordered)


async def test_graph_blocks_emergency_until_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph(monkeypatch, json.dumps(DRAFT))
    turns = [
        *TURNS,
        {
            "turn_index": 2,
            "speaker": "patient",
            "start_ms": 8000,
            "end_ms": 9000,
            "text": "I also have severe breathlessness.",
        },
    ]
    blocked = await graph.run(
        turns=turns,
        locale="en-IN",
        acknowledged=False,
        feedback=None,
        tool_context=_context(),
        clinic_code="CLINIC-A",
    )
    assert blocked.error == "red_flag_ack_required"
    assert blocked.draft is None
    assert any(flag["severity"] == "emergency" for flag in blocked.red_flags)

    acknowledged = await graph.run(
        turns=turns,
        locale="en-IN",
        acknowledged=True,
        feedback=None,
        tool_context=_context(),
        clinic_code="CLINIC-A",
    )
    assert acknowledged.error is None
    assert acknowledged.draft is not None
    assert acknowledged.draft["medicines"][0]["stock"]["status"] == "in_stock"
    assert any(source["source_type"] == "tool" for source in acknowledged.sources)


async def test_graph_grounding_failure_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = {
        **DRAFT,
        "subjective": [{"text": "Fever.", "source_turn_ids": [42], "unsourced": False}],
    }
    graph = _graph(monkeypatch, json.dumps(bad))
    outcome = await graph.run(
        turns=TURNS,
        locale="en-IN",
        acknowledged=False,
        feedback=None,
        tool_context=_context(),
        clinic_code="CLINIC-A",
    )
    assert outcome.error == "draft_citation_unknown"
    assert outcome.draft is None
    assert outcome.sources == []


async def test_graph_rejects_oversized_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph(monkeypatch, json.dumps(DRAFT))
    turns = [
        {
            "turn_index": 0,
            "speaker": "patient",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "x" * 7000,
        }
    ]
    outcome = await graph.run(
        turns=turns,
        locale="en-IN",
        acknowledged=False,
        feedback=None,
        tool_context=_context(),
        clinic_code="CLINIC-A",
    )
    assert outcome.error == "transcript_too_long"
