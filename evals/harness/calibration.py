"""Judge-calibration fixtures and agreement math.

The shipped calibration set is authored, paired good/bad answer data.  Its labels are
*provisional fixture labels*, not human review.  A calibration artefact therefore says
``calibrated_by: "unreviewed"`` and ``status: "pending"`` until a reviewer file with an
explicit human-review attestation is supplied.  Agreement is only meaningful when it is
computed between two complete label sets; the functions below never invent a score.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from evals.harness.answer_suites import LANGUAGES, ROOT, reject_invented_scores
from evals.harness.errors import CalibrationError, EvalSchemaError

CALIBRATION_PATH: Final = ROOT / "evals" / "calibration" / "judge_calibration.json"
KAPPA_TARGET: Final = 0.6
LABELS: Final[tuple[str, ...]] = ("good", "bad")
MIN_PAIRS: Final = 10
RESERVED_REVIEWERS: Final[frozenset[str]] = frozenset(
    {"unreviewed", "pending", "system", "model", "judge", "n/a", "none"}
)
RESERVED_JUDGE_ALIASES: Final[frozenset[str]] = frozenset(
    {"unreviewed", "pending", "system", "human", "reviewer", "n/a", "none"}
)
Label = Literal["good", "bad"]


@dataclass(frozen=True)
class CalibrationItem:
    id: str
    pair_id: str
    label: Label
    answer: str
    language: str


@dataclass(frozen=True)
class CalibrationPair:
    pair_id: str
    language: str
    topic: str
    question: str
    contexts: tuple[str, ...]
    ground_truth: str
    good: CalibrationItem
    bad: CalibrationItem


@dataclass(frozen=True)
class CalibrationSet:
    dataset: str
    schema_version: int
    created_at: dt.date
    path: Path
    dataset_hash: str
    pairs: tuple[CalibrationPair, ...]
    review_instructions: tuple[str, ...]
    rubric: tuple[str, ...]

    @property
    def items(self) -> tuple[CalibrationItem, ...]:
        return tuple(item for pair in self.pairs for item in (pair.good, pair.bad))

    def fixture_labels(self) -> dict[str, str]:
        return {item.id: item.label for item in self.items}


@dataclass(frozen=True)
class ReviewerLabels:
    reviewer_id: str
    reviewed_at: dt.date
    labels: dict[str, str]
    note: str | None = None


@dataclass(frozen=True)
class JudgeLabels:
    judge_alias: str
    produced_at: dt.date
    labels: dict[str, str]
    note: str | None = None


@dataclass(frozen=True)
class Agreement:
    n: int
    observed_agreement: float
    cohen_kappa: float | None
    confusion: dict[str, dict[str, int]]
    disagreements: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "observed_agreement": self.observed_agreement,
            "cohen_kappa": self.cohen_kappa,
            "confusion": self.confusion,
            "disagreements": list(self.disagreements),
        }


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvalSchemaError(f"cannot read {_display(path)}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EvalSchemaError(f"{_display(path)} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvalSchemaError(f"{_display(path)} must contain a JSON object")
    return {str(key): value for key, value in payload.items()}


def _text(record: dict[str, Any], key: str, location: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvalSchemaError(f"{location} needs a non-empty string field {key!r}")
    return value


def _date(record: dict[str, Any], key: str, location: str) -> dt.date:
    value = _text(record, key, location)
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise EvalSchemaError(f"{location}.{key} must be YYYY-MM-DD, got {value!r}") from exc


def _string_tuple(record: dict[str, Any], key: str, location: str) -> tuple[str, ...]:
    value = record.get(key)
    if not isinstance(value, list) or not value:
        raise EvalSchemaError(f"{location}.{key} must be a non-empty list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EvalSchemaError(f"{location}.{key}[{index}] must be a non-empty string")
        result.append(item)
    return tuple(result)


def _label(value: object, location: str) -> Label:
    if value not in LABELS:
        raise EvalSchemaError(f"{location} must be one of {LABELS}, got {value!r}")
    return "good" if value == "good" else "bad"


def _validate_item(
    raw_item: object, pair_id: str, expected_label: Label, language: str, location: str
) -> CalibrationItem:
    if not isinstance(raw_item, dict):
        raise EvalSchemaError(f"{location} must be an object")
    item = {str(key): value for key, value in raw_item.items()}
    reject_invented_scores(item, location)
    item_id = _text(item, "id", location)
    label = _label(item.get("label"), f"{location}.label")
    if label != expected_label:
        raise EvalSchemaError(
            f"{location}.label must be {expected_label!r} for the {expected_label} answer"
        )
    return CalibrationItem(
        id=item_id,
        pair_id=pair_id,
        label=label,
        answer=_text(item, "answer", location),
        language=language,
    )


def load_calibration(path: Path = CALIBRATION_PATH) -> CalibrationSet:
    """Load and validate the paired good/bad calibration set (no scores allowed)."""
    payload = _read_json_object(path)
    reject_invented_scores(payload, _display(path))
    if payload.get("schema_version") != 1:
        raise EvalSchemaError(f"{_display(path)}.schema_version must be 1")
    if payload.get("synthetic") is not True:
        raise EvalSchemaError(f"{_display(path)}.synthetic must be true")
    if payload.get("contains_phi") is not False:
        raise EvalSchemaError(f"{_display(path)}.contains_phi must be false")
    if payload.get("human_review_performed") is not False:
        raise EvalSchemaError(
            f"{_display(path)} ships unreviewed; do not set human_review_performed=true"
        )
    if payload.get("calibrated_by") != "unreviewed" or payload.get("status") != "pending":
        raise EvalSchemaError(
            f"{_display(path)} must ship as calibrated_by='unreviewed' and status='pending'"
        )
    pairs_raw = payload.get("pairs")
    if not isinstance(pairs_raw, list) or len(pairs_raw) < MIN_PAIRS:
        raise EvalSchemaError(
            f"{_display(path)}.pairs must contain at least {MIN_PAIRS} good/bad pairs"
        )
    pairs: list[CalibrationPair] = []
    item_ids: set[str] = set()
    pair_ids: set[str] = set()
    for index, raw_pair in enumerate(pairs_raw):
        location = f"{_display(path)}.pairs[{index}]"
        if not isinstance(raw_pair, dict):
            raise EvalSchemaError(f"{location} must be an object")
        pair = {str(key): value for key, value in raw_pair.items()}
        reject_invented_scores(pair, location)
        pair_id = _text(pair, "pair_id", location)
        if pair_id in pair_ids:
            raise EvalSchemaError(f"{location} repeats pair_id {pair_id!r}")
        pair_ids.add(pair_id)
        language = _text(pair, "language", location)
        if language not in LANGUAGES:
            raise EvalSchemaError(f"{location}.language must be one of {LANGUAGES}")
        good = _validate_item(pair.get("good"), pair_id, "good", language, f"{location}.good")
        bad = _validate_item(pair.get("bad"), pair_id, "bad", language, f"{location}.bad")
        for item in (good, bad):
            if item.id in item_ids:
                raise EvalSchemaError(f"{location} repeats calibration item id {item.id!r}")
            item_ids.add(item.id)
        if good.answer == bad.answer:
            raise EvalSchemaError(f"{location} good and bad answers must differ")
        pairs.append(
            CalibrationPair(
                pair_id=pair_id,
                language=language,
                topic=_text(pair, "topic", location),
                question=_text(pair, "question", location),
                contexts=_string_tuple(pair, "contexts", location),
                ground_truth=_text(pair, "ground_truth", location),
                good=good,
                bad=bad,
            )
        )
    return CalibrationSet(
        dataset=_text(payload, "dataset", _display(path)),
        schema_version=1,
        created_at=_date(payload, "created_at", _display(path)),
        path=path,
        dataset_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        pairs=tuple(pairs),
        review_instructions=_string_tuple(payload, "review_instructions", _display(path)),
        rubric=_string_tuple(payload, "rubric", _display(path)),
    )


def _validate_label_map(raw_labels: object, known_ids: set[str], location: str) -> dict[str, str]:
    if not isinstance(raw_labels, dict) or not raw_labels:
        raise EvalSchemaError(f"{location} must be a non-empty object of item id -> label")
    labels: dict[str, str] = {}
    for raw_id, raw_label in raw_labels.items():
        item_id = str(raw_id)
        if item_id not in known_ids:
            raise EvalSchemaError(f"{location} names unknown calibration item {item_id!r}")
        labels[item_id] = _label(raw_label, f"{location}.{item_id}")
    return labels


def load_reviewer_labels(path: Path, calibration: CalibrationSet) -> ReviewerLabels:
    """Load a named human review.  Files without an explicit attestation are rejected."""
    payload = _read_json_object(path)
    if payload.get("attested_human_review") is not True:
        raise EvalSchemaError(
            f"{_display(path)} must set attested_human_review=true; a file cannot claim "
            "human review implicitly"
        )
    reviewer_id = _text(payload, "reviewer_id", _display(path)).strip()
    if reviewer_id.lower() in RESERVED_REVIEWERS:
        raise EvalSchemaError(
            f"{_display(path)}.reviewer_id {reviewer_id!r} is reserved and cannot attest review"
        )
    note_value = payload.get("note")
    note = note_value if isinstance(note_value, str) and note_value.strip() else None
    return ReviewerLabels(
        reviewer_id=reviewer_id,
        reviewed_at=_date(payload, "reviewed_at", _display(path)),
        labels=_validate_label_map(
            payload.get("labels"), set(calibration.fixture_labels()), f"{_display(path)}.labels"
        ),
        note=note,
    )


def load_judge_labels(path: Path, calibration: CalibrationSet) -> JudgeLabels:
    """Load externally produced judge verdicts (good/bad per calibration item)."""
    payload = _read_json_object(path)
    judge_alias = _text(payload, "judge_alias", _display(path)).strip()
    if judge_alias.lower() in RESERVED_JUDGE_ALIASES:
        raise EvalSchemaError(f"{_display(path)}.judge_alias must name a configured judge alias")
    note_value = payload.get("note")
    note = note_value if isinstance(note_value, str) and note_value.strip() else None
    return JudgeLabels(
        judge_alias=judge_alias,
        produced_at=_date(payload, "produced_at", _display(path)),
        labels=_validate_label_map(
            payload.get("labels"), set(calibration.fixture_labels()), f"{_display(path)}.labels"
        ),
        note=note,
    )


def compute_agreement(truth: Mapping[str, str], predicted: Mapping[str, str]) -> Agreement:
    """Compute observed agreement and Cohen's kappa for two complete label maps.

    Kappa is ``None`` when both raters used a single class for every item because the
    chance-agreement denominator is zero; observed agreement is still reported.
    """
    if not truth or not predicted:
        raise CalibrationError("agreement needs two non-empty label maps")
    if set(truth) != set(predicted):
        missing = sorted(set(truth) - set(predicted))
        extra = sorted(set(predicted) - set(truth))
        raise CalibrationError(
            f"label maps must cover the same items; missing={missing}, extra={extra}"
        )
    counts: dict[str, dict[str, int]] = {label: dict.fromkeys(LABELS, 0) for label in LABELS}
    disagreements: list[str] = []
    for item_id in sorted(truth):
        truth_label = _label(truth[item_id], f"truth.{item_id}")
        predicted_label = _label(predicted[item_id], f"predicted.{item_id}")
        counts[truth_label][predicted_label] += 1
        if truth_label != predicted_label:
            disagreements.append(item_id)
    total = len(truth)
    matches = sum(counts[label][label] for label in LABELS)
    observed = matches / total
    truth_totals = [sum(counts[label].values()) / total for label in LABELS]
    predicted_totals = [sum(counts[other][label] for other in LABELS) / total for label in LABELS]
    chance = sum(
        truth_share * predicted_share
        for truth_share, predicted_share in zip(truth_totals, predicted_totals, strict=True)
    )
    kappa = None if chance == 1.0 else (observed - chance) / (1.0 - chance)
    return Agreement(
        n=total,
        observed_agreement=round(observed, 6),
        cohen_kappa=round(kappa, 6) if kappa is not None else None,
        confusion=counts,
        disagreements=tuple(disagreements),
    )


def _unavailable_agreement(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "observed_agreement": None,
        "cohen_kappa": None,
        "n": 0,
        "confusion": None,
        "disagreements": [],
    }


def build_calibration_artifact(
    calibration: CalibrationSet,
    *,
    reviewer: ReviewerLabels | None = None,
    judge: JudgeLabels | None = None,
) -> dict[str, Any]:
    """Build the honest judge-calibration artefact.

    ``status`` stays ``pending`` and ``calibrated_by`` stays ``unreviewed`` unless a
    reviewer file covers every item.  Judge-versus-human agreement is only computed
    when both a complete review and complete judge verdicts are supplied.
    """
    item_ids = set(calibration.fixture_labels())
    reviewer_labels = reviewer.labels if reviewer is not None else {}
    missing_review = sorted(item_ids - set(reviewer_labels))
    complete_review = reviewer is not None and not missing_review
    judge_labels = judge.labels if judge is not None else {}
    missing_judge = sorted(item_ids - set(judge_labels))
    complete_judge = judge is not None and not missing_judge

    fixture_vs_reviewer = _unavailable_agreement(
        "a complete reviewer file is required before any label agreement is reported"
    )
    if complete_review:
        fixture_vs_reviewer = {
            "available": True,
            "basis": "reviewer_vs_fixture_provisional_labels",
            **compute_agreement(calibration.fixture_labels(), reviewer_labels).to_dict(),
        }

    judge_vs_reviewer = _unavailable_agreement(
        "judge-versus-human agreement requires complete reviewer labels and judge verdicts"
    )
    meets_target: bool | None = None
    if complete_review and complete_judge:
        agreement = compute_agreement(reviewer_labels, judge_labels)
        meets_target = agreement.cohen_kappa is not None and agreement.cohen_kappa >= KAPPA_TARGET
        judge_vs_reviewer = {
            "available": True,
            "basis": "judge_vs_reviewer_labels",
            "target_kappa": KAPPA_TARGET,
            "meets_target": meets_target,
            **agreement.to_dict(),
        }

    human_review_performed = reviewer is not None and bool(reviewer_labels)
    if not complete_review:
        status = "pending"
        judge_calibration_status = "pending_human_review"
    elif not complete_judge:
        status = "reviewed"
        judge_calibration_status = "pending_judge_verdicts"
    elif meets_target is True:
        # Threshold gate: human attestation + κ≥target required before "calibrated".
        status = "calibrated"
        judge_calibration_status = "calibrated"
    else:
        status = "reviewed"
        judge_calibration_status = "below_threshold"
    limitations = [
        "Fixture labels are provisional and were authored with the synthetic answers.",
        "Judge scores are not part of this fixture and are never invented.",
        "Agreement is not a clinical-validation claim.",
        f"status=calibrated requires attested human review and Cohen κ ≥ {KAPPA_TARGET}.",
    ]
    if not complete_review:
        limitations.insert(0, "No complete human review has been supplied.")
    if complete_review and not complete_judge:
        limitations.insert(0, "Human review is complete, but judge verdicts are still missing.")
    if complete_review and complete_judge and meets_target is False:
        limitations.insert(
            0,
            f"Judge-vs-human κ is below the {KAPPA_TARGET} gate; keep judge untrusted.",
        )

    return {
        "dataset": calibration.dataset,
        "schema_version": calibration.schema_version,
        "dataset_hash": calibration.dataset_hash,
        "dataset_path": _display(calibration.path),
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "synthetic": True,
        "contains_phi": False,
        "pair_count": len(calibration.pairs),
        "item_count": len(calibration.items),
        "label_counts": {
            label: sum(1 for item in calibration.items if item.label == label) for label in LABELS
        },
        "calibrated_by": "unreviewed" if reviewer is None else reviewer.reviewer_id,
        "status": status,
        "judge_calibration_status": judge_calibration_status,
        "kappa_target": KAPPA_TARGET,
        "meets_kappa_target": meets_target,
        "human_review_performed": human_review_performed,
        "review": {
            "reviewer_id": None if reviewer is None else reviewer.reviewer_id,
            "reviewed_at": None if reviewer is None else reviewer.reviewed_at.isoformat(),
            "coverage": round(len(reviewer_labels) / len(item_ids), 6) if item_ids else 0.0,
            "missing_item_ids": missing_review,
            "note": None if reviewer is None else reviewer.note,
        },
        "judge": {
            "labels_supplied": judge is not None,
            "judge_alias": None if judge is None else judge.judge_alias,
            "produced_at": None if judge is None else judge.produced_at.isoformat(),
            "coverage": round(len(judge_labels) / len(item_ids), 6) if item_ids else 0.0,
            "missing_item_ids": missing_judge,
            "note": None if judge is None else judge.note,
        },
        "agreement": {
            "reviewer_vs_fixture": fixture_vs_reviewer,
            "judge_vs_reviewer": judge_vs_reviewer,
        },
        "rubric": list(calibration.rubric),
        "review_instructions": list(calibration.review_instructions),
        "items": [
            {
                "id": item.id,
                "pair_id": item.pair_id,
                "language": item.language,
                "fixture_label": item.label,
            }
            for item in calibration.items
        ],
        "limitations": limitations,
    }


def write_calibration_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
