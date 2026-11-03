"""Non-clinical memory write policy (shared by API and durable backends)."""

from __future__ import annotations

import re

from sahyog_common.errors import ProblemError

ALLOWED_KEYS = frozenset(
    {
        "preferred_locale",
        "preferred_clinic",
        "preferred_channel",
        "appointment_reminder",
        "ui_density",
        "opt_out",
    }
)

_PII_OR_CLINICAL = re.compile(
    r"("
    r"[\w.+-]+@[\w-]+\.[\w.-]+|"  # email
    r"\b\d{10,12}\b|"  # phone / aadhaar-ish
    r"\b[A-Z]{5}\d{4}[A-Z]\b|"  # PAN
    r"\b(diagnos|prescri|insulin|hiv|cancer|dose|mg\b|tablet|symptom)\b"
    r")",
    re.IGNORECASE,
)


def reject_if_sensitive(value: str) -> None:
    if _PII_OR_CLINICAL.search(value):
        raise ProblemError(
            422,
            "memory_value_rejected",
            "Value rejected",
            "Preference values cannot contain identifiers or clinical detail.",
        )


def is_sensitive(value: str) -> bool:
    return bool(_PII_OR_CLINICAL.search(value or ""))
