"""Mixed-script query expansion for hybrid retrieval (G-03).

Expands common drug/specialty/condition terms across Latin, Devanagari and
Hinglish spellings so lexical/trigram search can hit either script. Embeddings
still run on the original query; expansions only feed lexical candidates.
"""

from __future__ import annotations

import re

# Bidirectional aliases: any token in a group expands to the whole group.
_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"diabetes", "sugar", "मधुमेह", "madhumeh", "madhumeha"}),
    frozenset({"hypertension", "bp", "blood pressure", "उच्च रक्तचाप", "bp high"}),
    frozenset({"metformin", "मेटफॉर्मिन", "glycomet", "glucophage"}),
    frozenset({"paracetamol", "acetaminophen", "crocin", "dolo", "पैरासिटामोल", "पॅरासिटामॉल"}),
    frozenset({"amoxicillin", "amox", "ऍमोक्सिसिलिन", "एमोक्सिसिलिन"}),
    frozenset({"insulin", "इन्सुलिन", "इन्शुलिन"}),
    frozenset({"asthma", "दम", "दमा", "shwas"}),
    frozenset({"fever", "bukhar", "बुखार", "ताप"}),
    frozenset({"cough", "khansi", "खांसी", "खोकला"}),
    frozenset({"cardiology", "heart", "हृदय", "कार्डियोलॉजी"}),
    frozenset({"orthopedics", "ortho", "हड्डी", "ऑर्थोपेडिक"}),
    frozenset({"pediatrics", "paediatrics", "child", "बालरोग", "बच्चे"}),
    frozenset({"gynecology", "gynaecology", "gynae", "स्त्रीरोग"}),
    frozenset({"dermatology", "skin", "त्वचा", "डर्मेटोलॉजी"}),
)

_TOKEN_RE = re.compile(r"[\w\u0900-\u097F]+", re.UNICODE)


def expand_query_terms(question: str, *, max_terms: int = 24) -> list[str]:
    """Return unique search strings: original question plus alias expansions."""
    text = (question or "").strip()
    if not text:
        return []
    terms: list[str] = [text]
    seen = {text.casefold()}
    tokens = [m.group(0) for m in _TOKEN_RE.finditer(text)]
    lowered = {t.casefold() for t in tokens}
    for group in _ALIAS_GROUPS:
        group_lower = {item.casefold() for item in group}
        if lowered & group_lower:
            for alias in group:
                key = alias.casefold()
                if key not in seen:
                    seen.add(key)
                    terms.append(alias)
                    if len(terms) >= max_terms:
                        return terms
    return terms
