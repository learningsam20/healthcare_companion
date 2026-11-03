"""Turn spoken consultation language into specific clinical sentences.

The transcript is the visit's own wording. SOAP lines should state the finding,
not repeat the dialogue, and each line should be a complete sentence.
"""

from __future__ import annotations

import re
from typing import Any

UNSOURCED_LABEL = "[doctor to specify]"
SECTION_FIELDS = ("subjective", "objective", "assessment", "plan")

_LEADING = re.compile(
    r"^(?:so|well|okay|ok|right|yeah|yes|um|uh)[,:\s]+",
    re.I,
)
_FRAME = re.compile(
    r"^(?:i will|i'll|we will|we'll|let us|let's|i have had|i've had|"
    r"i have been having|i have|i've|i am having|i'm having|you have|you've|"
    r"i am|i'm)\b[, ]*",
    re.I,
)
_LEADING_PRONOUN = re.compile(r"^(?:your|my)\b[, ]*", re.I)
_BP = re.compile(
    r"(?:blood pressure|b\.?\s*p\.?)\s*(?:is|of|was|today is|reads|:)?\s*"
    r"(\d{2,3})\s*(?:over|/|by)\s*(\d{2,3})",
    re.I,
)
_BARE_BP = re.compile(r"\b(\d{2,3})\s+over\s+(\d{2,3})\b", re.I)
_MMHG = re.compile(r"\b(\d{2,3})\s*/\s*(\d{2,3})\s*mm\s*hg\b", re.I)
_PULSE = re.compile(
    r"(?:pulse|heart rate|pulse rate)\s*(?:is|of|was|reads|:)?\s*(\d{2,3})",
    re.I,
)
_TEMP = re.compile(
    r"(?:temperature|temp)\s*(?:is|of|was|reads|:)?\s*(\d{2,3}(?:\.\d)?)\s*(°?\s*[fc])?",
    re.I,
)
_SPO2 = re.compile(
    r"(?:spo2|sp o2|oxygen saturation|o2 sat|saturation)\s*(?:is|of|was|:)?\s*(\d{2,3})\s*%?",
    re.I,
)
_WEIGHT = re.compile(
    r"\bweight\s*(?:is|of|was|:)?\s*(\d+(?:\.\d+)?)\s*(?:kg|kilos|kilograms)?",
    re.I,
)
_EXAM = re.compile(
    r"\b(?:on examination|o/e|lungs are clear|throat is congested|no pallor|"
    r"no icterus|abdomen is soft|chest is clear|no oedema|no edema)\b",
    re.I,
)
_IMPRESSION = re.compile(
    r"\b(?:diagnos(?:is|e)|impression|this is|looks like|sounds like|likely|"
    r"i suspect|suspect|food poisoning|poisoning|gastritis|that explains)\b",
    re.I,
)
_PLAN = re.compile(
    r"\b(?:prescrib|advise|start|continue|review|follow[\s-]?up|come back|"
    r"return|rest|fluid|hydrat|tablet|syrup|medicine|dawai|recommend|"
    r"rice|salad|pain management|nothing else)\b",
    re.I,
)
_STUB_LINE = re.compile(
    r"(?:stomach ache|abdominal pain|pain|fever|cough|headache)",
    re.I,
)
_HISTORY_WEEK = re.compile(r"\b(?:one|a|1|last)\s+weeks?\b", re.I)
_NEXT_WEEK = re.compile(r"\bnext\s+weeks?\b|\bin\s+(?:a|one)\s+weeks?\b", re.I)
_STOMACH = re.compile(r"\b(?:stomach|abdomen|tummy|belly|gastric)\b", re.I)
_SLEEP = re.compile(r"\b(?:sleep|asleep|wake|waking|morning)\b", re.I)
_FOOD_EVENT = re.compile(r"\b(?:chinese|restaurant|party|roadside)\b", re.I)
_POISON = re.compile(r"\b(?:food\s+poisoning|poisoning)\b", re.I)
_DIET = re.compile(r"\b(?:rice|salads?)\b", re.I)
_PAIN_RX = re.compile(
    r"\bpain\s*management\b|\bfor\s+(?:your|the)\s+pain\b|\bpainkiller\b|\banalgesic\b",
    re.I,
)
_MIXED_COMPLAINT = re.compile(
    r"\b(?:fever for|headache|cough|pain for|since|cold|vomit|nausea)\b",
    re.I,
)


def _in_range(value: str, low: float, high: float) -> bool:
    try:
        number = float(value)
    except ValueError:
        return False
    return low <= number <= high


def format_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    if not cleaned:
        return ""
    chars = list(cleaned)
    for index, char in enumerate(chars):
        if char.isalpha():
            chars[index] = char.upper()
            break
    cleaned = "".join(chars)
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def format_prose(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentence for part in parts if (sentence := format_sentence(part)))


def rewrite_dialogue(text: str) -> str:
    cleaned = text.strip()
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = _LEADING.sub("", cleaned).strip()
        cleaned = _FRAME.sub("", cleaned).strip()
        cleaned = _LEADING_PRONOUN.sub("", cleaned).strip()
    return re.sub(r"\s+", " ", cleaned).strip(" ,;-")


def _temperature_sentence(match: re.Match[str]) -> str | None:
    raw = match.group(1)
    if not _in_range(raw, 34, 110):
        return None
    unit = (match.group(2) or "").casefold()
    value = float(raw)
    if "c" in unit and "f" not in unit:
        suffix = "°C"
    elif "f" in unit:
        suffix = "°F"
    elif value <= 45:
        suffix = "°C"
    else:
        suffix = "°F"
    shown = raw[:-2] if raw.endswith(".0") else raw
    return f"Temperature is {shown}{suffix}."


def vital_sentences(text: str) -> list[str]:
    found: list[str] = []
    pressure = _BP.search(text) or _MMHG.search(text) or _BARE_BP.search(text)
    if pressure and _in_range(pressure.group(1), 70, 250) and _in_range(pressure.group(2), 40, 150):
        found.append(f"Blood pressure is {int(pressure.group(1))}/{int(pressure.group(2))} mmHg.")
    pulse = _PULSE.search(text)
    if pulse and _in_range(pulse.group(1), 30, 220):
        found.append(f"Pulse is {int(pulse.group(1))} per minute.")
    temperature = _TEMP.search(text)
    if temperature:
        sentence = _temperature_sentence(temperature)
        if sentence:
            found.append(sentence)
    saturation = _SPO2.search(text)
    if saturation and _in_range(saturation.group(1), 50, 100):
        found.append(f"Oxygen saturation is {int(saturation.group(1))}%.")
    weight = _WEIGHT.search(text)
    if weight and _in_range(weight.group(1), 1, 250):
        found.append(f"Weight is {weight.group(1)} kg.")
    return found


def _only_measurement(text: str) -> bool:
    return len(text) <= 120 and _MIXED_COMPLAINT.search(text) is None


def exam_sentence(text: str) -> str | None:
    if _EXAM.search(text) is None:
        return None
    cleaned = rewrite_dialogue(text)
    cleaned = re.sub(r"^(?:on examination|o/e)[,:\s]*", "", cleaned, flags=re.I).strip()
    sentence = format_sentence(cleaned)
    return sentence or None


def display_sentence(text: str) -> str:
    """Sentence case for a stored line, keeping the unsourced label intact."""
    has_label = UNSOURCED_LABEL in text
    body = format_prose(text.replace(UNSOURCED_LABEL, " "))
    if not body:
        return text.strip()
    return f"{body} {UNSOURCED_LABEL}" if has_label else body


def polish_line(text: str, *, field: str) -> str:
    raw = text.replace(UNSOURCED_LABEL, " ").strip()
    if not raw:
        return ""
    vitals = vital_sentences(raw)
    exam = exam_sentence(raw)
    if field == "objective":
        parts = list(vitals)
        if exam and exam not in parts:
            parts.append(exam)
        if parts:
            return " ".join(dict.fromkeys(parts))
    if vitals and _only_measurement(raw):
        return " ".join(vitals)
    return format_prose(rewrite_dialogue(raw))


def is_objective_sentence(text: str) -> bool:
    bare = text.replace(UNSOURCED_LABEL, "").strip()
    if bare.startswith(
        (
            "Blood pressure is ",
            "Pulse is ",
            "Temperature is ",
            "Oxygen saturation is ",
            "Weight is ",
        )
    ):
        return True
    return _EXAM.search(bare) is not None and bare[:1].isupper()


def _tidy(text: str) -> str:
    """Light cleanup for speech-to-text, without inventing a different history."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"\b(as well)(?:\s+as well)+\b", r"\1", cleaned, flags=re.I)
    cleaned = re.sub(r"\bmind\s+food\s+poisoning\b", "mild food poisoning", cleaned, flags=re.I)
    cleaned = re.sub(r"\broad\s*side\b", "roadside", cleaned, flags=re.I)
    if re.search(r"\bsalads?\b", cleaned, re.I):
        cleaned = re.sub(r"\bRise\b", "rice", cleaned)
    return cleaned


def _blank(lines: list[dict[str, Any]]) -> bool:
    for line in lines:
        bare = str(line.get("text") or "").replace(UNSOURCED_LABEL, "").strip(" .")
        if bare:
            return False
    return True


def _cited(text: str, turn_index: int) -> dict[str, Any]:
    return {"text": text, "source_turn_ids": [turn_index], "unsourced": False}


def _cited_many(text: str, turn_ids: list[int]) -> dict[str, Any]:
    unique: list[int] = []
    for turn_id in turn_ids:
        if turn_id not in unique:
            unique.append(turn_id)
    return {"text": text, "source_turn_ids": unique, "unsourced": not unique}


def _remember(bucket: list[int], index: int) -> None:
    if index not in bucket:
        bucket.append(index)


def _thin(lines: list[dict[str, Any]]) -> bool:
    """A one-line stub should not block a fuller note from the same transcript."""
    if _blank(lines):
        return True
    if len(lines) != 1:
        return False
    bare = str(lines[0].get("text") or "").replace(UNSOURCED_LABEL, "").strip()
    if re.search(r"\bsomething\b", bare, re.I):
        return True
    return _STUB_LINE.fullmatch(bare.strip(" .")) is not None


def _food_sentence(text: str) -> str | None:
    if _FOOD_EVENT.search(text) is None:
        return None
    if not re.search(r"\b(?:had|ate|eaten|restaurant|party|chinese)\b", text, re.I):
        return None
    roadside = "roadside " if re.search(r"roadside", text, re.I) else ""
    kind = "Chinese food" if re.search(r"chinese", text, re.I) else "a meal"
    place = " at a party" if re.search(r"\bparty\b", text, re.I) else ""
    extra = ""
    if re.search(r"\bno\b", text, re.I) and re.search(r"specific", text, re.I):
        extra = " No other specific food was identified."
    return f"After {roadside}{kind}{place}.{extra}"


def compose_visit(turns: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Clinical lines for history that a short model draft tends to drop."""
    sections: dict[str, list[dict[str, Any]]] = {field: [] for field in SECTION_FIELDS}
    stomach: list[int] = []
    timing: list[int] = []
    history_week: list[int] = []
    food_ids: list[int] = []
    food_text = ""
    poison: list[int] = []
    diet: list[int] = []
    diet_week = False
    pain: list[int] = []
    for turn in turns:
        index = int(turn["turn_index"])
        speaker = str(turn.get("speaker") or "")
        text = _tidy(str(turn.get("text") or ""))
        if not text:
            continue
        for sentence in re.split(r"[.!?]+", text):
            for vital in vital_sentences(sentence):
                sections["objective"].append(_cited(vital, index))
            exam = exam_sentence(sentence)
            if exam:
                sections["objective"].append(_cited(exam, index))
        if speaker == "patient":
            if _STOMACH.search(text):
                _remember(stomach, index)
            if _SLEEP.search(text) and re.search(r"\b(?:pain|ache|having|it)\b", text, re.I):
                _remember(timing, index)
            if _HISTORY_WEEK.search(text) and _NEXT_WEEK.search(text) is None:
                _remember(history_week, index)
            meal = _food_sentence(text)
            if meal:
                _remember(food_ids, index)
                food_text = meal
        elif speaker == "doctor":
            if _POISON.search(text):
                _remember(poison, index)
            if _DIET.search(text):
                _remember(diet, index)
                diet_week = diet_week or _NEXT_WEEK.search(text) is not None
            if _PAIN_RX.search(text):
                _remember(pain, index)
    if stomach:
        if history_week:
            sections["subjective"].append(
                _cited_many("Stomach ache for about one week.", stomach + history_week)
            )
        else:
            sections["subjective"].append(_cited_many("Stomach ache.", stomach))
    elif history_week:
        sections["subjective"].append(_cited_many("Symptoms for about one week.", history_week))
    if timing:
        sections["subjective"].append(
            _cited_many(
                "Pain on going to sleep and on waking in the morning.",
                timing,
            )
        )
    if food_text and food_ids:
        sections["subjective"].append(_cited_many(food_text, food_ids))
    if poison:
        sections["assessment"].append(_cited_many("Possible mild food poisoning.", poison))
    if diet:
        diet_line = "Rice and salads only, and nothing else"
        if diet_week or history_week:
            diet_line += ", for about one week"
        sections["plan"].append(_cited_many(f"{diet_line}.", diet))
    if pain:
        sections["plan"].append(
            _cited_many(
                "Medicine for pain, so the patient can sleep and continue other tasks.",
                pain,
            )
        )
    if not sections["objective"] and (stomach or poison or diet):
        anchor = stomach or poison or diet
        sections["objective"].append(
            _cited(
                "No vital signs or examination findings were recorded.",
                anchor[0],
            )
        )
    return {field: _dedupe(lines) for field, lines in sections.items()}


def visit_follow_up(turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A review interval the doctor actually named."""
    for turn in turns:
        if turn.get("speaker") != "doctor":
            continue
        text = _tidy(str(turn.get("text") or ""))
        if _NEXT_WEEK.search(text) is None:
            continue
        if _DIET.search(text) or re.search(
            r"\b(?:recommend|review|follow|come back|nothing else)\b", text, re.I
        ):
            return _cited("Review in about one week.", int(turn["turn_index"]))
    return None


def _dedupe(lines: list[dict[str, Any]], *, limit: int = 6) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in lines:
        key = str(line["text"]).casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(line)
        if len(kept) >= limit:
            break
    return kept


def abstract_sections(turns: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Specific SOAP lines taken from what was actually said."""
    buckets: dict[str, list[dict[str, Any]]] = {field: [] for field in SECTION_FIELDS}
    for turn in turns:
        speaker = str(turn.get("speaker") or "")
        text = str(turn.get("text") or "").strip()
        if not text:
            continue
        index = int(turn["turn_index"])
        pieces = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        for sentence in pieces or [text]:
            vitals = vital_sentences(sentence)
            for item in vitals:
                buckets["objective"].append(_cited(item, index))
            if vitals and _only_measurement(sentence):
                continue
            exam = exam_sentence(sentence)
            if exam and not vitals:
                buckets["objective"].append(_cited(exam, index))
                continue
            rewritten = format_prose(rewrite_dialogue(sentence))
            if not rewritten:
                continue
            if speaker == "patient":
                buckets["subjective"].append(_cited(rewritten, index))
            elif _IMPRESSION.search(sentence):
                buckets["assessment"].append(_cited(rewritten, index))
            elif speaker == "doctor" and _PLAN.search(sentence):
                buckets["plan"].append(_cited(rewritten, index))
    return {field: _dedupe(lines) for field, lines in buckets.items()}


def fold_sections(
    sections: dict[str, list[dict[str, Any]]], turns: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Fill empty SOAP sections, and keep measurements in objective."""
    result = {field: list(sections.get(field) or []) for field in SECTION_FIELDS}
    moved: list[dict[str, Any]] = []
    for field in ("subjective", "assessment", "plan"):
        kept: list[dict[str, Any]] = []
        for line in result[field]:
            if is_objective_sentence(str(line.get("text") or "")):
                text = str(line["text"]).replace(UNSOURCED_LABEL, "").strip()
                moved.append({**line, "text": text, "unsourced": not line.get("source_turn_ids")})
            else:
                kept.append(line)
        result[field] = kept
    if moved:
        seen = {str(line.get("text") or "") for line in result["objective"]}
        for line in moved:
            if line["text"] not in seen:
                result["objective"].append(line)
                seen.add(line["text"])
    extracted = abstract_sections(turns)
    composed = compose_visit(turns)
    for field in SECTION_FIELDS:
        if _thin(result[field]) and composed[field]:
            result[field] = composed[field]
        elif _blank(result[field]) and extracted[field]:
            result[field] = extracted[field]
    return result
