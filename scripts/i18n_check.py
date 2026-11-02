#!/usr/bin/env python3
"""Compare the three web locale dictionaries for missing keys and placeholders."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps" / "web" / "src" / "i18n" / "locales.ts"
BLOCK = re.compile(r"const (en|hi|mr)(?:: Dictionary)? = \{(.*?)\n\}(?: as const)?;", re.S)
ENTRY = re.compile(r'^\s*"([^"]+)":\s*"(.*)",?\s*$', re.M)
PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    blocks = {match.group(1): match.group(2) for match in BLOCK.finditer(text)}
    if set(blocks) != {"en", "hi", "mr"}:
        print(f"error: expected en/hi/mr dictionaries in {SOURCE}", file=sys.stderr)
        return 2

    parsed = {locale: dict(ENTRY.findall(body)) for locale, body in blocks.items()}
    english = set(parsed["en"])
    errors: list[str] = []
    for locale in ("hi", "mr"):
        missing = sorted(english - set(parsed[locale]))
        extra = sorted(set(parsed[locale]) - english)
        if missing:
            errors.append(f"{locale}: {len(missing)} missing keys, e.g. {missing[:5]}")
        if extra:
            errors.append(f"{locale}: {len(extra)} keys not in English, e.g. {extra[:5]}")
        for key in sorted(english & set(parsed[locale])):
            expected = set(PLACEHOLDER.findall(parsed["en"][key]))
            actual = set(PLACEHOLDER.findall(parsed[locale][key]))
            if expected != actual:
                errors.append(
                    f"{locale}:{key} placeholders differ ({sorted(expected)} != {sorted(actual)})"
                )

    if errors:
        for message in errors:
            print(f"i18n error: {message}", file=sys.stderr)
        return 2
    print(f"i18n ok: {len(english)} keys across en-IN, hi-IN and mr-IN; placeholders match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
