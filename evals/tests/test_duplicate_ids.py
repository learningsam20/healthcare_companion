"""Duplicate-id rejection for answer-bearing suites."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import evals.harness.answer_suites as answer_suites
from evals.harness.answer_suites import (
    QA_SPEC,
    RAG_SPEC,
    SETS_DIR,
    AnswerSuiteSpec,
    load_answer_suite_file,
    load_answer_suites,
)
from evals.harness.errors import EvalSchemaError


def _raw_first(spec: AnswerSuiteSpec) -> dict[str, Any]:
    path = SETS_DIR / spec.filename
    line = path.read_text(encoding="utf-8").splitlines()[0]
    payload: object = json.loads(line)
    assert isinstance(payload, dict)
    return {str(key): value for key, value in payload.items()}


def test_duplicate_id_in_one_file_is_rejected(tmp_path: Path) -> None:
    raw = _raw_first(RAG_SPEC)
    path = tmp_path / "duplicate.jsonl"
    path.write_text(
        json.dumps(raw, ensure_ascii=False) + "\n" + json.dumps(raw, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(EvalSchemaError, match="repeats case id"):
        load_answer_suite_file(RAG_SPEC, path)


def test_duplicate_ids_across_suites_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rag_raw = _raw_first(RAG_SPEC)
    qa_raw = _raw_first(QA_SPEC)
    rag_lines: list[str] = []
    qa_lines: list[str] = []
    for index in range(20):
        case_id = f"shared-{index:03d}"
        rag_case = deepcopy(rag_raw)
        qa_case = deepcopy(qa_raw)
        rag_case["id"] = case_id
        qa_case["id"] = case_id
        rag_lines.append(json.dumps(rag_case, ensure_ascii=False))
        qa_lines.append(json.dumps(qa_case, ensure_ascii=False))
    (tmp_path / RAG_SPEC.filename).write_text("\n".join(rag_lines) + "\n", encoding="utf-8")
    (tmp_path / QA_SPEC.filename).write_text("\n".join(qa_lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(answer_suites, "SETS_DIR", tmp_path)
    with pytest.raises(EvalSchemaError, match="appears in both"):
        load_answer_suites(["rag_w3", "qa_x01"])
