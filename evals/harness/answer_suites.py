"""Schema validation and loading for answer-bearing framework suites.

The deterministic W1/W2 suites contain rule/provenance checks and deliberately do not
carry model answers.  The answer-bearing suites in this module hold synthetic
question/answer/context fixtures for RAGAS (W3) and DeepEval (X-01).  They never hold
judge scores: scores may only be produced by a framework run against a configured
model alias.  Every fixture must say that it is synthetic and PHI-free, and answers
that were produced by a model must name the producing alias and date.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from evals.harness.errors import EvalSchemaError

ROOT: Final = Path(__file__).resolve().parents[2]
SETS_DIR: Final = ROOT / "evals" / "sets"
MIN_CASES_PER_SUITE: Final = 20
LANGUAGES: Final[tuple[str, ...]] = ("en-IN", "hi-IN", "mr-IN", "mixed-script")
ANSWER_ORIGINS: Final[tuple[str, ...]] = ("authored_fixture", "model_generated")
SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"document", "tool", "memory", "conversation", "rule", "general"}
)
FORBIDDEN_SCORE_KEYS: Final[frozenset[str]] = frozenset(
    {"score", "scores", "metric", "metrics", "judge_score", "judge_scores"}
)
_ID_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_DEVANAGARI: Final = re.compile(r"[\u0900-\u097f]")
_LATIN: Final = re.compile(r"[A-Za-z]")

FrameworkName = Literal["ragas", "deepeval"]
SuiteKind = Literal["rag", "qa"]


@dataclass(frozen=True)
class AnswerSuiteSpec:
    name: str
    framework: FrameworkName
    kind: SuiteKind
    filename: str
    fields: tuple[str, ...]
    description: str


RAG_SPEC: Final = AnswerSuiteSpec(
    name="rag_w3",
    framework="ragas",
    kind="rag",
    filename="rag_w3.jsonl",
    fields=("question", "answer", "contexts", "ground_truth"),
    description="Answer-bearing RAG cases for the optional RAGAS adapter (W3).",
)
QA_SPEC: Final = AnswerSuiteSpec(
    name="qa_x01",
    framework="deepeval",
    kind="qa",
    filename="qa_x01.jsonl",
    fields=("input", "actual_output", "expected_output", "retrieval_context"),
    description="Answer-bearing non-RAG QA cases for the optional DeepEval adapter (X-01).",
)
SUITE_SPECS: Final[dict[str, AnswerSuiteSpec]] = {
    RAG_SPEC.name: RAG_SPEC,
    QA_SPEC.name: QA_SPEC,
}


@dataclass(frozen=True)
class AnswerCase:
    """One validated fixture. ``case`` is the JSON object handed to an adapter."""

    id: str
    suite: str
    framework: FrameworkName
    language: str
    script: str
    case: dict[str, Any]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class AnswerSuite:
    spec: AnswerSuiteSpec
    cases: tuple[AnswerCase, ...]
    path: Path
    dataset_hash: str

    def adapter_cases(self) -> list[dict[str, Any]]:
        """Return detached adapter rows so framework code cannot mutate fixtures."""
        return [deepcopy(case.case) for case in self.cases]

    def language_counts(self) -> dict[str, int]:
        counts: dict[str, int] = dict.fromkeys(LANGUAGES, 0)
        for case in self.cases:
            counts[case.language] += 1
        return counts


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def reject_invented_scores(record: dict[str, Any], location: str) -> None:
    """Reject fixture-level score fields; only a real framework run may score."""
    present = sorted(FORBIDDEN_SCORE_KEYS.intersection(record))
    if present:
        raise EvalSchemaError(
            f"{location} contains score-like field(s) {present}; fixtures must not "
            "record invented judge scores"
        )


def _required_str(record: dict[str, Any], key: str, location: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvalSchemaError(f"{location} needs a non-empty string field {key!r}")
    return value


def _required_object(record: dict[str, Any], key: str, location: str) -> dict[str, Any]:
    value = record.get(key)
    if not isinstance(value, dict):
        raise EvalSchemaError(f"{location} needs an object field {key!r}")
    return {str(name): item for name, item in value.items()}


def _string_list(record: dict[str, Any], key: str, location: str) -> list[str]:
    value = record.get(key)
    if not isinstance(value, list) or not value:
        raise EvalSchemaError(f"{location} needs a non-empty list field {key!r}")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EvalSchemaError(f"{location}.{key}[{index}] must be a non-empty string")
        result.append(item)
    return result


def _parse_date(value: str, location: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise EvalSchemaError(f"{location} must be an ISO date (YYYY-MM-DD): {value!r}") from exc


def _parse_datetime(value: str, location: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvalSchemaError(f"{location} must be an ISO-8601 timestamp: {value!r}") from exc


def _validate_source_refs(provenance: dict[str, Any], location: str) -> None:
    refs = provenance.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise EvalSchemaError(f"{location}.provenance.source_refs must be a non-empty list")
    for index, raw_ref in enumerate(refs):
        ref_location = f"{location}.provenance.source_refs[{index}]"
        if not isinstance(raw_ref, dict):
            raise EvalSchemaError(f"{ref_location} must be an object")
        ref = {str(name): item for name, item in raw_ref.items()}
        reject_invented_scores(ref, ref_location)
        _required_str(ref, "id", ref_location)
        source_type = _required_str(ref, "type", ref_location)
        if source_type not in SOURCE_TYPES:
            raise EvalSchemaError(
                f"{ref_location}.type must be one of {sorted(SOURCE_TYPES)}, got {source_type!r}"
            )
        _required_str(ref, "title", ref_location)
        if source_type in {"document", "tool"}:
            _required_str(ref, "locator", ref_location)
        if "observed_at" in ref:
            _parse_datetime(_required_str(ref, "observed_at", ref_location), ref_location)


def _validate_provenance(provenance: dict[str, Any], location: str) -> None:
    reject_invented_scores(provenance, f"{location}.provenance")
    if provenance.get("synthetic") is not True:
        raise EvalSchemaError(f"{location}.provenance.synthetic must be true")
    if provenance.get("contains_phi") is not False:
        raise EvalSchemaError(f"{location}.provenance.contains_phi must be false")
    origin = _required_str(provenance, "answer_origin", f"{location}.provenance")
    if origin not in ANSWER_ORIGINS:
        raise EvalSchemaError(
            f"{location}.provenance.answer_origin must be one of {ANSWER_ORIGINS}"
        )
    if origin == "model_generated":
        _required_str(provenance, "producing_model_alias", f"{location}.provenance")
        _parse_date(
            _required_str(provenance, "produced_at", f"{location}.provenance"),
            f"{location}.provenance.produced_at",
        )
        if not provenance.get("prompt_version"):
            raise EvalSchemaError(
                f"{location}.provenance.prompt_version is required for model-generated answers"
            )
    else:
        _required_str(provenance, "author", f"{location}.provenance")
        _parse_date(
            _required_str(provenance, "authored_at", f"{location}.provenance"),
            f"{location}.provenance.authored_at",
        )
        if provenance.get("producing_model_alias") is not None:
            raise EvalSchemaError(
                f"{location}.provenance is authored_fixture but names a producing model; "
                "use answer_origin=model_generated and record the alias/date"
            )
    _validate_source_refs(provenance, location)


def _validate_mixed_script(text: str, location: str) -> None:
    if not (_DEVANAGARI.search(text) and _LATIN.search(text)):
        raise EvalSchemaError(
            f"{location} is labelled mixed-script but does not contain both Devanagari "
            "and Latin characters"
        )


def validate_case(raw_case: object, spec: AnswerSuiteSpec) -> AnswerCase:
    """Validate one decoded JSONL fixture against the suite schema."""
    if not isinstance(raw_case, dict):
        raise EvalSchemaError(f"{spec.name}: each case must be a JSON object")
    case = {str(name): value for name, value in raw_case.items()}
    raw_id = case.get("id")
    if not isinstance(raw_id, str) or not _ID_PATTERN.match(raw_id):
        raise EvalSchemaError(
            f"{spec.name}: case id must match {_ID_PATTERN.pattern}, got {raw_id!r}"
        )
    location = f"{spec.name}:{raw_id}"
    reject_invented_scores(case, location)

    if case.get("suite") != spec.name:
        raise EvalSchemaError(f"{location}: suite must be {spec.name!r}")
    if case.get("framework") != spec.framework:
        raise EvalSchemaError(f"{location}: framework must be {spec.framework!r}")
    if case.get("synthetic") is not True:
        raise EvalSchemaError(f"{location}: synthetic must be true")
    if case.get("data_classification") != "synthetic_no_phi":
        raise EvalSchemaError(f"{location}: data_classification must be 'synthetic_no_phi'")
    language = _required_str(case, "language", location)
    if language not in LANGUAGES:
        raise EvalSchemaError(f"{location}: language must be one of {LANGUAGES}")
    script = _required_str(case, "script", location)
    for field in spec.fields:
        if field in {"contexts", "retrieval_context"}:
            _string_list(case, field, location)
        else:
            _required_str(case, field, location)
    if language == "mixed-script":
        _validate_mixed_script(
            _required_str(case, "question" if spec.kind == "rag" else "input", location), location
        )
        _validate_mixed_script(
            _required_str(case, "answer" if spec.kind == "rag" else "actual_output", location),
            location,
        )

    provenance = _required_object(case, "provenance", location)
    _validate_provenance(provenance, location)
    return AnswerCase(
        id=raw_id,
        suite=spec.name,
        framework=spec.framework,
        language=language,
        script=script,
        case=case,
        provenance=provenance,
    )


def load_answer_suite_file(spec: AnswerSuiteSpec, path: Path) -> AnswerSuite:
    """Load and validate one JSONL suite file, rejecting duplicate case ids."""
    if not path.exists():
        raise EvalSchemaError(f"answer-bearing suite {spec.name} has no file at {_display(path)}")
    cases: list[AnswerCase] = []
    seen: set[str] = set()
    text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            decoded: object = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalSchemaError(f"{_display(path)}:{number} is not valid JSON: {exc}") from exc
        case = validate_case(decoded, spec)
        if case.id in seen:
            raise EvalSchemaError(
                f"{_display(path)}:{number} repeats case id {case.id!r}; ids must be unique"
            )
        seen.add(case.id)
        cases.append(case)
    if len(cases) < MIN_CASES_PER_SUITE:
        raise EvalSchemaError(
            f"suite {spec.name} has {len(cases)} cases; at least {MIN_CASES_PER_SUITE} are required"
        )
    return AnswerSuite(
        spec=spec,
        cases=tuple(cases),
        path=path,
        dataset_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def load_answer_suite(name: str) -> AnswerSuite:
    spec = SUITE_SPECS.get(name)
    if spec is None:
        raise EvalSchemaError(
            f"unknown answer-bearing suite {name!r}; available: {sorted(SUITE_SPECS)}"
        )
    return load_answer_suite_file(spec, SETS_DIR / spec.filename)


def load_answer_suites(names: list[str]) -> list[AnswerSuite]:
    """Load suites and enforce globally unique case ids as well as per-file ids."""
    suites = [load_answer_suite(name) for name in names]
    owners: dict[str, str] = {}
    for suite in suites:
        for case in suite.cases:
            previous = owners.get(case.id)
            if previous is not None:
                raise EvalSchemaError(
                    f"case id {case.id!r} appears in both {previous!r} and {suite.spec.name!r}"
                )
            owners[case.id] = suite.spec.name
    return suites
