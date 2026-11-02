#!/usr/bin/env python3
"""Print effective feature flags for the current environment and profile.

Runs inside the API image so validation, environment precedence and locked-flag rules
are identical to the API. Prints no secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py-common"))

from app.composition import build_app_services  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    settings.validate_startup()
    services = build_app_services(settings)
    flags = services.features.public()
    overrides = {
        key: value
        for key, value in flags.items()
        if value["source"] not in {"config", "not_applicable"}
    }
    payload = {
        "status": "valid",
        "registry_version": services.feature_registry.version,
        "profile": settings.app_profile,
        "environment": settings.app_env,
        "flag_count": len(flags),
        "overrides": overrides,
        "items": flags,
    }
    if args.diff:
        payload["items"] = overrides
    if args.json or args.diff or args.validate:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(
        f"registry v{payload['registry_version']} · profile {settings.app_profile} · "
        f"environment {settings.app_env} · {len(flags)} flags"
    )
    print(f"{'FLAG':<34} {'VALUE':<6} {'CLASS':<9} {'SOURCE':<14} OWNER")
    print("-" * 88)
    for key, flag in flags.items():
        print(
            f"{key:<34} {str(flag['value']).lower():<6} {flag['class']:<9} "
            f"{flag['source']:<14} {flag['owner']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
