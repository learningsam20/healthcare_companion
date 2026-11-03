"""Match a consultation to medicines that are actually loaded in stock.

A brand the doctor says is aligned to the catalogue row. A class or a symptom
("antibiotic", "something for the fever", "cough syrup") is matched only from the
doctor's words, and only to a loaded product. A drug nobody asked for is not added.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

CatalogSearch = Callable[[list[str], str], Awaitable[list[dict[str, Any]]]]

_TOKEN = re.compile(r"[a-z][a-z0-9-]{3,}", re.I)
_DOSE = re.compile(r"\b(\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|iu|%))\b", re.I)
_FREQUENCY = re.compile(
    r"\b(once daily|twice daily|thrice daily|three times(?: a day)?|two times(?: a day)?|"
    r"at night|every night|in the morning|after food|before food|after meals|before meals|"
    r"\bod\b|\bbd\b|\btds\b|\bhs\b|\bsos\b)\b",
    re.I,
)
_DURATION = re.compile(
    r"\b((?:for\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:day|days|week|weeks|month|months))\b",
    re.I,
)
_AFTER_FOOD = re.compile(r"\b(after food|before food|after meals|before meals|with food)\b", re.I)

_STOP = {
    "about",
    "after",
    "again",
    "allergy",
    "antibiotic",
    "antibiotics",
    "before",
    "blood",
    "body",
    "acute",
    "better",
    "check",
    "chest",
    "clinic",
    "cold",
    "comes",
    "continue",
    "cough",
    "daily",
    "days",
    "doctor",
    "follow",
    "dose",
    "every",
    "fever",
    "fluids",
    "having",
    "headache",
    "hello",
    "infection",
    "looks",
    "medicine",
    "month",
    "morning",
    "night",
    "pain",
    "patient",
    "please",
    "prescribe",
    "pressure",
    "return",
    "review",
    "right",
    "severe",
    "since",
    "sounds",
    "something",
    "start",
    "syrup",
    "tablet",
    "tablets",
    "temperature",
    "thank",
    "there",
    "these",
    "this",
    "those",
    "three",
    "throat",
    "today",
    "until",
    "viral",
    "visit",
    "worse",
    "twice",
    "water",
    "week",
    "which",
    "would",
    "your",
}

_GENERIC_NAMES = {
    "analgesic",
    "antacid",
    "antibiotic",
    "antibiotics",
    "antihistamine",
    "antipyretic",
    "cold",
    "cough",
    "cough syrup",
    "drug",
    "fever",
    "headache",
    "inhaler",
    "medicine",
    "pain",
    "pain killer",
    "painkiller",
    "pain management",
    "something",
    "syrup",
    "tablet",
}


@dataclass(frozen=True, slots=True)
class Cue:
    id: str
    generic: re.Pattern[str]
    specific: re.Pattern[str]
    terms: tuple[str, ...]
    form: str | None = None


CUES: tuple[Cue, ...] = (
    Cue(
        "antibiotic",
        re.compile(r"\b(?:antibiotic|antibiotics)\b", re.I),
        re.compile(
            r"\b(?:amox(?:icillin|yclav)?|augmentin|azith(?:romycin|ral)?|azee|ciproflox)\b",
            re.I,
        ),
        ("augmentin", "amoxyclav", "azithral", "azithromycin", "amox"),
    ),
    Cue(
        "fever",
        re.compile(
            r"\b(?:fever|pyrexia|bukhar|bukhaar|painkiller|pain\s*killer|analgesic|"
            r"antipyretic|headache|body\s*ache|bodyache|sir\s*dard|"
            r"pain\s*management|for\s+(?:your\s+|the\s+)?pain)\b",
            re.I,
        ),
        re.compile(r"\b(?:paracetamol|acetaminophen|dolo|crocin|calpol|acepain|analgin)\b", re.I),
        ("paracetamol", "dolo", "crocin", "calpol", "acepain", "analgin"),
    ),
    Cue(
        "cough",
        re.compile(r"\b(?:cough|khansi|expectorant|cold|cough\s+syrup)\b", re.I),
        re.compile(r"\b(?:ascoril|asthalin|alex)\b", re.I),
        ("ascoril", "asthalin", "alex"),
        "syrup",
    ),
    Cue(
        "allergy",
        re.compile(
            r"\b(?:allerg\w*|itching|itchy|antihistamine|cetirizine|cetrizine|"
            r"levocetirizine)\b",
            re.I,
        ),
        re.compile(r"\b(?:allegra|cetirizine|cetrizine|levocet)\b", re.I),
        ("allegra", "cetirizine", "allergin", "levocet"),
    ),
    Cue(
        "acidity",
        re.compile(r"\b(?:acidity|antacid|heartburn|gastritis|gastric)\b", re.I),
        re.compile(r"\b(?:pantoprazole|pantop|pan[\s-]?d)\b", re.I),
        ("pantoprazole", "pantop", "pan-d", "antacid", "aulcer"),
    ),
    Cue(
        "blood_pressure",
        re.compile(r"\b(?:hypertension|high blood pressure|amlodipine|telmisartan)\b", re.I),
        re.compile(r"\b(?:amlodipine|amlodac|telmisartan|atenolol)\b", re.I),
        ("amlodac", "amlodipine", "telmisartan", "atenolol"),
    ),
    Cue(
        "asthma",
        re.compile(r"\b(?:asthma|wheez\w*|inhaler|nebulis\w*)\b", re.I),
        re.compile(r"\b(?:asthalin|budesonide|salbutamol)\b", re.I),
        ("asthalin", "budesonide", "salbutamol"),
        "inhaler",
    ),
    Cue(
        "vomiting",
        re.compile(r"\b(?:vomit\w*|ulti|nausea|ondansetron)\b", re.I),
        re.compile(r"\b(?:ondansetron|domperidone|avomits)\b", re.I),
        ("ondansetron", "avomits", "domperidone"),
    ),
    Cue(
        "diabetes",
        re.compile(r"\b(?:diabetes|diabetic|metformin|glimepiride)\b", re.I),
        re.compile(r"\b(?:metformin|glimepiride)\b", re.I),
        ("metformin", "glimepiride"),
    ),
)


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _contains(phrase: str, text: str) -> bool:
    folded = _fold(phrase)
    if len(folded) < 3:
        return False
    return f" {folded} " in f" {_fold(text)} "


def _words(text: str) -> list[str]:
    return _fold(text).split()


def _first_word(text: str) -> str:
    words = _words(text)
    return words[0] if words else ""


def _generic_name(name: str) -> bool:
    return _fold(name) in _GENERIC_NAMES


def _name_fits(name: str, terms: tuple[str, ...]) -> bool:
    words = _words(name)
    if not words:
        return False
    for term in terms:
        needle = _fold(term)
        if len(needle) < 4:
            continue
        if any(word.startswith(needle) for word in words):
            return True
    return False


def _doctor_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [turn for turn in turns if turn.get("speaker") == "doctor"]


def _doctor_text(turns: list[dict[str, Any]]) -> str:
    return " ".join(str(turn.get("text") or "") for turn in _doctor_turns(turns))


def supporting_turns(name: str, turns: list[dict[str, Any]]) -> list[int]:
    """Turns that justify keeping this medicine name."""
    first = _first_word(name)
    spoken: list[int] = []
    for turn in turns:
        text = str(turn.get("text") or "")
        named = _contains(name, text) or (
            len(first) >= 4 and first not in _STOP and _contains(first, text)
        )
        if named:
            spoken.append(int(turn["turn_index"]))
    if spoken:
        return spoken
    if _generic_name(name) or _name_fits(name, tuple(term for cue in CUES for term in cue.terms)):
        for cue in CUES:
            matched = [
                int(turn["turn_index"])
                for turn in _doctor_turns(turns)
                if cue.generic.search(str(turn.get("text") or ""))
                and (_generic_name(name) or _name_fits(name, cue.terms))
            ]
            if matched:
                return matched
    return []


def _tokens(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN.finditer(text):
        token = _fold(match.group(0))
        if len(token) < 5 or token in _STOP or token in seen:
            continue
        seen.add(token)
        found.append(token)
    return found


def search_terms_for(turns: list[dict[str, Any]], medicines: list[dict[str, Any]]) -> list[str]:
    """Catalogue search terms for brands, classes, and symptoms the doctor used."""
    del medicines
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        needle = _fold(term)
        if len(needle) < 3 or needle in seen:
            return
        seen.add(needle)
        terms.append(needle)

    doctor = _doctor_text(turns)
    for cue in CUES:
        specific = cue.specific.search(doctor)
        if specific:
            add(specific.group(0))
            continue
        if cue.generic.search(doctor):
            for term in cue.terms:
                add(term)
    for token in _tokens(doctor):
        add(token)
    blob = " ".join(str(turn.get("text") or "") for turn in turns)
    for token in _tokens(blob):
        add(token)
    return terms[:32]


def _score(term: str, row: dict[str, Any], form_hint: str | None) -> int:
    needle = _fold(term)
    if len(needle) < 3:
        return -1
    words = _words(str(row.get("name") or ""))
    if not words:
        return -1
    if words[0] == needle or words[0].startswith(needle):
        score = 80
    elif any(word.startswith(needle) for word in words):
        score = 45
    elif any(needle in word for word in words):
        score = 10
    else:
        return -1
    form = str(row.get("form") or "").casefold()
    name = str(row.get("name") or "").casefold()
    if form_hint and (form_hint in form or form_hint in name):
        score += 25
    score -= len(name) // 20
    return score


def best_row(
    terms: tuple[str, ...] | list[str],
    catalog: list[dict[str, Any]],
    form_hint: str | None = None,
) -> dict[str, Any] | None:
    for term in terms:
        ranked = [(_score(term, row, form_hint), row) for row in catalog]
        strong = [item for item in ranked if item[0] >= 45]
        pool = strong or [item for item in ranked if item[0] >= 10]
        if not pool:
            continue
        pool.sort(key=lambda item: item[0], reverse=True)
        return pool[0][1]
    return None


def _same_product(name: str, row: dict[str, Any]) -> bool:
    left = _first_word(name)
    right = _first_word(str(row.get("name") or ""))
    if len(left) < 4 or len(right) < 4:
        return False
    return left == right or left.startswith(right) or right.startswith(left)


def _catalog_name(name: str, catalog: list[dict[str, Any]]) -> str | None:
    ranked = [(_score(name, row, None), row) for row in catalog if _same_product(name, row)]
    ranked = [item for item in ranked if item[0] >= 45]
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return str(ranked[0][1]["name"])[:200]


def _regimen(medicine: dict[str, Any], text: str) -> dict[str, Any]:
    updated = dict(medicine)
    if not updated.get("dose"):
        dose = _DOSE.search(text)
        if dose:
            updated["dose"] = dose.group(1)
    if not updated.get("frequency"):
        frequency = _FREQUENCY.search(text)
        if frequency:
            updated["frequency"] = frequency.group(1)
    if not updated.get("duration"):
        duration = _DURATION.search(text)
        if duration:
            updated["duration"] = duration.group(1)
    if not updated.get("instructions"):
        instructions = _AFTER_FOOD.search(text)
        if instructions:
            updated["instructions"] = instructions.group(1)
    return updated


def _turn_text(turns: list[dict[str, Any]], turn_ids: list[int]) -> str:
    wanted = set(turn_ids)
    return " ".join(
        str(turn.get("text") or "") for turn in turns if int(turn["turn_index"]) in wanted
    )


def _form_hint(cue: Cue, text: str) -> str | None:
    folded = text.casefold()
    if "syrup" in folded:
        return "syrup"
    if "inhaler" in folded:
        return "inhaler"
    if cue.form and cue.form in folded:
        return cue.form
    return cue.form if cue.id == "cough" and "syrup" in folded else None


def _recommend_all(
    draft: dict[str, Any], turns: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Put every prescribed medicine into the plan. The doctor can edit the wording."""
    del turns
    plan = [dict(line) for line in draft.get("plan") or []]
    blob = " ".join(str(line.get("text") or "") for line in plan).casefold()
    sources: list[dict[str, Any]] = []
    for medicine in draft.get("medicines") or []:
        name = str(medicine.get("name") or "").strip()
        if len(name) < 3 or name.casefold() in blob:
            continue
        detail = " ".join(
            part
            for part in (
                name,
                str(medicine.get("dose") or "").strip(),
                str(medicine.get("frequency") or "").strip(),
                str(medicine.get("duration") or "").strip(),
            )
            if part
        )
        text = f"Prescribe {detail}."
        turn_ids = [int(value) for value in medicine.get("source_turn_ids") or []]
        plan.append({"text": text, "source_turn_ids": turn_ids, "unsourced": not turn_ids})
        blob = f"{blob} {text.casefold()}"
        sources.append(_plan_source(len(plan) - 1, turn_ids))
    return {**draft, "plan": plan}, sources


def _plan_source(index: int, turn_ids: list[int]) -> dict[str, Any]:
    return {
        "field": "plan",
        "line_index": index,
        "source_type": "transcript" if turn_ids else "none",
        "source_ref": {"turn_ids": turn_ids, "label": None if turn_ids else "clinician review"},
        "status": "resolved" if turn_ids else "unsourced",
        "as_of": None,
    }


def _source(index: int, turn_ids: list[int], turns: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {int(turn["turn_index"]): turn for turn in turns}
    return {
        "field": "medicine",
        "line_index": index,
        "source_type": "transcript",
        "source_ref": {
            "turn_ids": turn_ids,
            "turns": [
                {
                    "turn_index": turn_id,
                    "speaker": by_id[turn_id].get("speaker"),
                    "start_ms": int(by_id[turn_id].get("start_ms") or 0),
                    "end_ms": int(by_id[turn_id].get("end_ms") or 0),
                }
                for turn_id in turn_ids
                if turn_id in by_id
            ],
            "label": None,
        },
        "status": "resolved",
        "as_of": None,
    }


def _covered(cue: Cue, doctor: str, medicines: list[dict[str, Any]]) -> bool:
    if cue.specific.search(doctor):
        return True
    return any(_name_fits(str(item.get("name") or ""), cue.terms) for item in medicines)


def _already(medicines: list[dict[str, Any]], name: str) -> bool:
    folded = _fold(name)
    first = _first_word(name)
    for item in medicines:
        current = _fold(str(item.get("name") or ""))
        if not current:
            continue
        if folded == current or folded in current or current in folded:
            return True
        if first and len(first) >= 4 and current.split()[0].startswith(first):
            return True
    return False


def _append_medicine(
    medicines: list[dict[str, Any]],
    *,
    name: str,
    turn_ids: list[int],
    turns: list[dict[str, Any]],
    seed: dict[str, Any] | None = None,
) -> None:
    if not name or not turn_ids or _already(medicines, name) or _generic_name(name):
        return
    base = {
        "name": name[:200],
        "dose": None,
        "frequency": None,
        "duration": None,
        "instructions": None,
        "source_turn_ids": turn_ids,
        "unsourced": False,
    }
    if seed:
        base.update(
            {
                "dose": seed.get("dose"),
                "frequency": seed.get("frequency"),
                "duration": seed.get("duration"),
                "instructions": seed.get("instructions"),
            }
        )
    medicines.append(_regimen(base, _turn_text(turns, turn_ids)))


def apply_catalog(
    draft: dict[str, Any],
    turns: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    doctor = _doctor_text(turns)
    medicines: list[dict[str, Any]] = []
    for item in draft.get("medicines") or []:
        original = str(item.get("name") or "").strip()
        if not original:
            continue
        name = _catalog_name(original, catalog) or original
        literal = _contains(original, doctor) or (
            len(_first_word(original)) >= 4 and _contains(_first_word(original), doctor)
        )
        if _generic_name(original) or not literal:
            replacement = None
            for cue in CUES:
                # Match this medicine on its own name. Another drug in the same
                # visit must not be replaced by the first class the doctor mentioned.
                if cue.specific.search(original):
                    continue
                if not cue.generic.search(original) and not _name_fits(original, cue.terms):
                    continue
                hit = best_row(cue.terms, catalog, _form_hint(cue, doctor))
                if hit:
                    replacement = str(hit["name"])
                    break
            if replacement:
                name = replacement
            elif _generic_name(original) or not literal:
                continue
        turn_ids = [int(value) for value in item.get("source_turn_ids") or []]
        if not turn_ids:
            turn_ids = supporting_turns(original, turns)
        _append_medicine(medicines, name=name, turn_ids=turn_ids, turns=turns, seed=item)

    for token in _tokens(doctor):
        hit = best_row((token,), catalog, None)
        if hit is None or _score(token, hit, None) < 80:
            continue
        turn_ids = [
            int(turn["turn_index"])
            for turn in _doctor_turns(turns)
            if _contains(token, str(turn.get("text") or ""))
        ]
        _append_medicine(medicines, name=str(hit["name"]), turn_ids=turn_ids, turns=turns)

    for cue in CUES:
        specifics = list(cue.specific.finditer(doctor))
        if specifics:
            for match in specifics:
                word = match.group(0)
                if _already(medicines, word):
                    continue
                hit = best_row((word, *cue.terms), catalog, _form_hint(cue, doctor))
                name = str(hit["name"]) if hit and _score(word, hit, None) >= 45 else word
                turn_ids = [
                    int(turn["turn_index"])
                    for turn in _doctor_turns(turns)
                    if _contains(word, str(turn.get("text") or ""))
                ]
                _append_medicine(medicines, name=name, turn_ids=turn_ids, turns=turns)
            continue
        if not cue.generic.search(doctor) or _covered(cue, doctor, medicines):
            continue
        hit = best_row(cue.terms, catalog, _form_hint(cue, doctor))
        if not hit:
            continue
        turn_ids = [
            int(turn["turn_index"])
            for turn in _doctor_turns(turns)
            if cue.generic.search(str(turn.get("text") or ""))
        ]
        _append_medicine(medicines, name=str(hit["name"]), turn_ids=turn_ids, turns=turns)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in medicines:
        key = _fold(str(item["name"]))
        if not key or key in seen or _generic_name(str(item["name"])):
            continue
        seen.add(key)
        deduped.append(item)
    deduped = deduped[:30]
    updated = {**draft, "medicines": deduped}
    updated, plan_sources = _recommend_all(updated, turns)
    sources = [
        _source(index, [int(value) for value in item["source_turn_ids"]], turns)
        for index, item in enumerate(deduped)
    ]
    return updated, [*plan_sources, *sources]


async def align_draft_medicines(
    draft: dict[str, Any],
    sources: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    clinic_code: str,
    search: CatalogSearch | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if search is None:
        return draft, sources
    terms = search_terms_for(turns, list(draft.get("medicines") or []))
    if not terms:
        return draft, sources
    try:
        catalog = await search(terms, clinic_code)
    except Exception:
        # A formulary miss must not discard the SOAP note.
        return draft, sources
    updated, medicine_sources = apply_catalog(draft, turns, list(catalog or []))
    kept = [item for item in sources if item.get("field") != "medicine"]
    return updated, [*kept, *medicine_sources]
