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


def test_ground_draft_omits_medicine_without_transcript_basis() -> None:
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
    draft, sources = ground_draft(bad, turns=TURNS, schema=SCHEMA)
    assert draft["medicines"] == []
    assert draft["subjective"][0]["text"] == "Fever for three days."
    assert not any(source["field"] == "medicine" for source in sources)


def test_ground_draft_autogrounds_medicine_mentioned_in_transcript() -> None:
    payload: dict[str, Any] = {
        **DRAFT,
        "medicines": [
            {
                "name": "paracetamol",
                "dose": "500 mg",
                "frequency": "twice daily",
                "duration": "three days",
                "instructions": None,
                "source_turn_ids": [],
                "unsourced": True,
            }
        ],
    }
    draft, sources = ground_draft(payload, turns=TURNS, schema=SCHEMA)
    assert draft["medicines"][0]["source_turn_ids"] == [1]
    assert draft["medicines"][0]["unsourced"] is False
    medicine = next(source for source in sources if source["field"] == "medicine")
    assert medicine["status"] == "resolved"


def test_ground_draft_omits_medicine_name_not_in_cited_turn() -> None:
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
    draft, _sources = ground_draft(bad, turns=TURNS, schema=SCHEMA)
    assert draft["medicines"] == []
    assert draft["plan"][0]["text"].startswith("Paracetamol")


def test_ground_draft_drops_placeholder_medicine_and_blank_dose() -> None:
    payload: dict[str, Any] = {
        **DRAFT,
        "medicines": [
            {
                "name": "undefined",
                "dose": "undefined",
                "frequency": "null",
                "duration": None,
                "instructions": "none",
                "source_turn_ids": [],
                "unsourced": True,
            },
            {
                "name": "paracetamol",
                "dose": "undefined",
                "frequency": "twice daily",
                "duration": "three days",
                "instructions": None,
                "source_turn_ids": [1],
                "unsourced": False,
            },
        ],
    }
    draft, _sources = ground_draft(payload, turns=TURNS, schema=SCHEMA)
    assert [item["name"] for item in draft["medicines"]] == ["paracetamol"]
    assert draft["medicines"][0]["dose"] is None
    assert draft["medicines"][0]["frequency"] == "twice daily"


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
        "subjective": [
            {"text": "Fever for three days.", "source_turn_ids": [0], "unsourced": False}
        ],
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


def test_ground_draft_writes_specific_objective_and_sentences() -> None:
    turns = [
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
            "text": "Your blood pressure today is 128 over 82. We will review your medicines.",
        },
    ]
    payload = {
        "subjective": [
            {
                "text": "i have had fever for three days and a headache",
                "source_turn_ids": [0],
                "unsourced": False,
            }
        ],
        "objective": [],
        "assessment": [],
        "plan": [],
        "follow_up": None,
        "medicines": [],
    }
    draft, _sources = ground_draft(payload, turns=turns, schema=SCHEMA)
    assert draft["subjective"][0]["text"] == "Fever for three days and a headache."
    assert draft["objective"][0]["text"] == "Blood pressure is 128/82 mmHg."
    assert draft["objective"][0]["source_turn_ids"] == [1]
    assert draft["plan"][0]["text"] == "Review your medicines."


def test_catalog_matches_class_and_symptom_to_loaded_medicines() -> None:
    from app.modules.scribe.medicine_match import apply_catalog

    catalog = [
        {"name": "Augmentin 625 Duo Tablet", "form": "tablet", "strength": "625 mg"},
        {"name": "Azithral 500 Tablet", "form": "tablet", "strength": "500 mg"},
        {"name": "Ascoril LS Syrup", "form": "syrup", "strength": "30 mg"},
        {"name": "Acepain SP Tablet", "form": "tablet", "strength": "500 mg"},
        {"name": "Allegra 120mg Tablet", "form": "tablet", "strength": "120 mg"},
    ]
    turns = [
        {
            "turn_index": 0,
            "speaker": "patient",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "I have fever and a cough.",
        },
        {
            "turn_index": 1,
            "speaker": "doctor",
            "start_ms": 1000,
            "end_ms": 2000,
            "text": "Start an antibiotic for five days, and a cough syrup.",
        },
    ]
    draft, _sources = apply_catalog(
        {**DRAFT, "medicines": []},
        turns,
        catalog,
    )
    names = [item["name"] for item in draft["medicines"]]
    assert names[0] == "Augmentin 625 Duo Tablet"
    assert "Ascoril LS Syrup" in names
    antibiotic = draft["medicines"][0]
    assert antibiotic["duration"] == "for five days"
    assert antibiotic["source_turn_ids"] == [1]


def test_catalog_keeps_named_drug_and_aligns_brand() -> None:
    from app.modules.scribe.medicine_match import apply_catalog

    catalog = [
        {"name": "Azithral 500 Tablet", "form": "tablet", "strength": "500 mg"},
        {"name": "Acepain SP Tablet", "form": "tablet", "strength": ""},
    ]
    turns = [
        {
            "turn_index": 1,
            "speaker": "doctor",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "Give Azithral 500 once daily for three days.",
        }
    ]
    draft, _sources = apply_catalog({**DRAFT, "medicines": []}, turns, catalog)
    assert [item["name"] for item in draft["medicines"]] == ["Azithral 500 Tablet"]
    assert draft["medicines"][0]["frequency"].casefold() == "once daily"
    fever_only = [
        {
            "turn_index": 1,
            "speaker": "doctor",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "Give something for the fever.",
        }
    ]
    fever_draft, _sources = apply_catalog({**DRAFT, "medicines": []}, fever_only, catalog)
    assert fever_draft["medicines"][0]["name"] == "Acepain SP Tablet"
    named = [
        {
            "turn_index": 1,
            "speaker": "doctor",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "I will prescribe paracetamol 500 mg twice daily.",
        }
    ]
    kept, _sources = apply_catalog({**DRAFT, "medicines": []}, named, catalog)
    assert [item["name"] for item in kept["medicines"]] == ["paracetamol"]


def test_stomach_visit_fills_note_and_pain_medicine() -> None:
    from app.modules.scribe.medicine_match import apply_catalog, search_terms_for

    spoken = [
        (0, "doctor", "yeah who are you"),
        (1, "patient", "I am fine doctor I am having stomach ache"),
        (2, "doctor", "oh that's awful what exactly when are you having it"),
        (
            3,
            "patient",
            "I am generally having it when I go to sleep as well as well I get up in the morning",
        ),
        (4, "doctor", "okay is it happening very recently or it is daily routine"),
        (5, "patient", "no gently it's be time since last one week or so"),
        (6, "doctor", "did you do anything cost this any type of food"),
        (
            7,
            "patient",
            "no I didn't don't you collect having a specific type of food yeah but we have "
            "been to a party and we had a road side Chinese restaurant best food",
        ),
        (
            8,
            "doctor",
            "that explains maybe some mind food poisoning my recommendation is to follow "
            "you only Rise and salads and nothing else for the next week or so",
        ),
        (9, "patient", "would that work"),
        (10, "doctor", "I will also give you as well as something for your pain management"),
        (
            11,
            "doctor",
            "so that you are able to sleep and you are able to keep calm and focus "
            "on your other task",
        ),
    ]
    turns = [
        {
            "turn_index": index,
            "speaker": speaker,
            "start_ms": index * 1000,
            "end_ms": index * 1000 + 900,
            "text": text,
        }
        for index, speaker, text in spoken
    ]
    thin = {
        "subjective": [{"text": "Stomach ache.", "source_turn_ids": [1, 7], "unsourced": False}],
        "objective": [],
        "assessment": [],
        "plan": [
            {
                "text": "Prescribe something for pain management.",
                "source_turn_ids": [10, 11],
                "unsourced": False,
            }
        ],
        "follow_up": None,
        "medicines": [],
    }
    draft, _sources = ground_draft(thin, turns=turns, schema=SCHEMA)
    subjective = " ".join(line["text"] for line in draft["subjective"]).casefold()
    assert "one week" in subjective
    assert "sleep" in subjective
    assert "chinese" in subjective
    assert draft["objective"][0]["text"].startswith("No vital signs")
    assert "food poisoning" in draft["assessment"][0]["text"].casefold()
    plan = " ".join(line["text"] for line in draft["plan"]).casefold()
    assert "rice" in plan and "salad" in plan
    assert "pain" in plan
    assert "week" in draft["follow_up"]["text"].casefold()
    assert "acepain" in search_terms_for(turns, [])
    catalog = [
        {"name": "Acepain SP Tablet", "form": "tablet", "strength": "500 mg"},
        {"name": "Analgin Tablet", "form": "tablet", "strength": "500 mg"},
    ]
    filled, _sources = apply_catalog(draft, turns, catalog)
    assert filled["medicines"][0]["name"] == "Acepain SP Tablet"
    assert 10 in filled["medicines"][0]["source_turn_ids"]


def test_every_prescribed_medicine_is_recommended() -> None:
    from app.modules.scribe.medicine_match import apply_catalog

    catalog = [
        {"name": "Augmentin 625 Duo Tablet", "form": "tablet", "strength": "625 mg"},
        {"name": "Azithral 500 Tablet", "form": "tablet", "strength": "500 mg"},
        {"name": "Acepain SP Tablet", "form": "tablet", "strength": "500 mg"},
    ]
    turns = [
        {
            "turn_index": 1,
            "speaker": "doctor",
            "start_ms": 0,
            "end_ms": 2000,
            "text": "Start Augmentin for five days and also Azithral, plus something for pain.",
        }
    ]
    draft, _sources = apply_catalog({**DRAFT, "medicines": [], "plan": []}, turns, catalog)
    names = [item["name"] for item in draft["medicines"]]
    assert "Augmentin 625 Duo Tablet" in names
    assert "Azithral 500 Tablet" in names
    assert "Acepain SP Tablet" in names
    plan = " ".join(line["text"] for line in draft["plan"])
    for name in names:
        assert name in plan


def test_patient_symptom_alone_does_not_add_a_medicine() -> None:
    from app.modules.scribe.medicine_match import apply_catalog

    catalog = [{"name": "Acepain SP Tablet", "form": "tablet", "strength": ""}]
    turns = [
        {
            "turn_index": 0,
            "speaker": "patient",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "I have fever and a headache.",
        }
    ]
    draft, _sources = apply_catalog({**DRAFT, "medicines": []}, turns, catalog)
    assert draft["medicines"] == []


def test_continued_turns_keep_the_previous_transcript() -> None:
    from app.modules.scribe.transcript_continue import continued_turns

    prior = [("doctor", "Hello"), ("patient", "I have fever")]
    added = continued_turns(prior, [("doctor", "Blood pressure is 128 over 82")])
    assert added == [*prior, ("doctor", "Blood pressure is 128 over 82")]
    assert continued_turns(prior, [("patient", "I have fever")]) is None


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
