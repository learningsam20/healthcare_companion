from __future__ import annotations

from pathlib import Path

from sahyog_common.files import load_yaml
from sahyog_common.red_flags import detect_red_flags, red_flag_sources

CONFIG = load_yaml(Path("config/red_flags.yaml"))


def test_chest_pain_with_qualifier_is_emergency() -> None:
    matches = detect_red_flags("I have chest pain and sweating since morning", CONFIG)
    assert [match.rule_id for match in matches] == ["RF-CHEST-PAIN"]
    assert matches[0].severity == "emergency"
    assert matches[0].action == "emergency_handoff"
    assert matches[0].guidance


def test_chest_pain_without_qualifier_does_not_fire() -> None:
    matches = detect_red_flags("I had chest pain last year, feeling better now", CONFIG)
    assert matches == []


def test_hindi_chest_pain_is_detected() -> None:
    matches = detect_red_flags("मुझे छाती में दर्द और सांस की तकलीफ है", CONFIG, "hi-IN")
    assert any(match.rule_id == "RF-CHEST-PAIN" for match in matches)
    assert matches[0].guidance


def test_word_boundary_prevents_substring_false_positive() -> None:
    matches = detect_red_flags("The chest painting is beautiful", CONFIG)
    assert matches == []


def test_multiple_rules_can_match() -> None:
    matches = detect_red_flags("heavy bleeding and I want to die", CONFIG)
    ids = {match.rule_id for match in matches}
    assert {"RF-BLEEDING", "RF-SUICIDE"} <= ids


def test_matching_is_case_and_width_insensitive() -> None:
    matches = detect_red_flags("SEVERE BREATHLESSNESS", CONFIG)
    assert [match.rule_id for match in matches] == ["RF-BREATHLESS"]


def test_red_flag_sources_are_rule_provenance() -> None:
    matches = detect_red_flags("severe breathlessness", CONFIG)
    refs = red_flag_sources(matches)
    assert refs and refs[0].type.value == "rule"
    assert refs[0].id == "RF-BREATHLESS"
    assert refs[0].locator == "RF-BREATHLESS"


def test_empty_text_matches_nothing() -> None:
    assert detect_red_flags("", CONFIG) == []
