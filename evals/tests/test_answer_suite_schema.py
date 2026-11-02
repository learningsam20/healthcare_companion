"""Schema tests for the answer-bearing RAG and non-RAG QA fixtures."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from evals.harness.answer_suites import (
    LANGUAGES,
    QA_SPEC,
    RAG_SPEC,
    SETS_DIR,
    AnswerSuiteSpec,
    load_answer_suite,
    load_answer_suites,
    validate_case,
)
from evals.harness.errors import EvalSchemaError

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
AADHAAR = re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")


def _raw_cases(spec: AnswerSuiteSpec) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    path = SETS_DIR / spec.filename
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload: object = json.loads(line)
        assert isinstance(payload, dict)
        cases.append({str(key): value for key, value in payload.items()})
    return cases


def _first_raw(spec: AnswerSuiteSpec) -> dict[str, Any]:
    return deepcopy(_raw_cases(spec)[0])


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        found: list[str] = []
        for item in value.values():
            found.extend(_strings(item))
        return found
    if isinstance(value, list):
        found = []
        for item in value:
            found.extend(_strings(item))
        return found
    return []


@pytest.mark.parametrize("name", ["rag_w3", "qa_x01"])
def test_shipped_answer_suites_validate(name: str) -> None:
    suite = load_answer_suite(name)
    assert len(suite.cases) >= 20
    counts = suite.language_counts()
    assert set(counts) == set(LANGUAGES)
    assert all(count >= 5 for count in counts.values()), counts
    for case in suite.cases:
        assert case.case["synthetic"] is True
        assert case.case["data_classification"] == "synthetic_no_phi"
        assert case.provenance["synthetic"] is True
        assert case.provenance["contains_phi"] is False
        assert case.provenance["answer_origin"] == "authored_fixture"
        assert case.provenance["source_refs"]
        for field in suite.spec.fields:
            assert field in case.case


def test_adapter_required_fields_match_framework_contracts() -> None:
    rag = load_answer_suite("rag_w3")
    assert rag.spec.framework == "ragas"
    assert all(
        {"question", "answer", "contexts", "ground_truth"}.issubset(case.case) for case in rag.cases
    )
    qa = load_answer_suite("qa_x01")
    assert qa.spec.framework == "deepeval"
    assert all(
        {"input", "actual_output", "expected_output", "retrieval_context"}.issubset(case.case)
        for case in qa.cases
    )


def test_case_ids_are_unique_across_suites() -> None:
    suites = load_answer_suites(["rag_w3", "qa_x01"])
    ids = [case.id for suite in suites for case in suite.cases]
    assert len(ids) == 48
    assert len(set(ids)) == len(ids)


def test_fixtures_contain_no_phi_patterns() -> None:
    suites = load_answer_suites(["rag_w3", "qa_x01"])
    for suite in suites:
        for case in suite.cases:
            text = " ".join(_strings(case.case))
            for pattern in (EMAIL, PHONE, AADHAAR, PAN):
                assert pattern.search(text) is None, (case.id, pattern.pattern)


def test_fixtures_do_not_record_scores() -> None:
    for spec in (RAG_SPEC, QA_SPEC):
        for raw in _raw_cases(spec):
            assert not {"score", "scores", "metric", "metrics"} & set(raw)
            provenance = raw.get("provenance")
            assert isinstance(provenance, dict)
            assert not {"score", "scores", "metric", "metrics"} & set(provenance)


def test_missing_required_field_is_rejected() -> None:
    raw = _first_raw(RAG_SPEC)
    del raw["contexts"]
    with pytest.raises(EvalSchemaError, match="contexts"):
        validate_case(raw, RAG_SPEC)


def test_model_generated_answer_requires_alias_and_date() -> None:
    raw = _first_raw(QA_SPEC)
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["answer_origin"] = "model_generated"
    with pytest.raises(EvalSchemaError, match="producing_model_alias"):
        validate_case(raw, QA_SPEC)

    provenance["producing_model_alias"] = "local_main"
    provenance["produced_at"] = "2026-10-25"
    with pytest.raises(EvalSchemaError, match="prompt_version"):
        validate_case(raw, QA_SPEC)

    provenance["prompt_version"] = "prompt-2026-10-25"
    validated = validate_case(raw, QA_SPEC)
    assert validated.provenance["producing_model_alias"] == "local_main"


def test_authored_fixture_cannot_claim_a_producing_model() -> None:
    raw = _first_raw(QA_SPEC)
    provenance = raw["provenance"]
    assert isinstance(provenance, dict)
    provenance["producing_model_alias"] = "local_main"
    with pytest.raises(EvalSchemaError, match="authored_fixture"):
        validate_case(raw, QA_SPEC)


def test_score_like_field_is_rejected() -> None:
    raw = _first_raw(RAG_SPEC)
    raw["scores"] = {"faithfulness": 1.0}
    with pytest.raises(EvalSchemaError, match="score"):
        validate_case(raw, RAG_SPEC)


def test_mixed_script_cases_need_both_scripts() -> None:
    raw = next(case for case in _raw_cases(RAG_SPEC) if case["language"] == "mixed-script")
    raw["question"] = "This is Latin only."
    with pytest.raises(EvalSchemaError, match="mixed-script"):
        validate_case(raw, RAG_SPEC)


def test_unknown_suite_is_rejected() -> None:
    with pytest.raises(EvalSchemaError, match="unknown answer-bearing suite"):
        load_answer_suite("w1")


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rag_w3.jsonl"
    with pytest.raises(EvalSchemaError, match="has no file"):
        from evals.harness.answer_suites import load_answer_suite_file

        load_answer_suite_file(RAG_SPEC, path)
