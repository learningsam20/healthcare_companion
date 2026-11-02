#!/usr/bin/env python3
"""Fail-closed configuration validation used by scripts/start.sh.

Runs inside the API image so the application settings, feature registry, model routes
and price/finops registries are the same objects the API will use. It opens no sockets
and prints no secret values.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py-common"))

from app.composition import build_app_services  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def _config_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix in {".yaml", ".yml"}:
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def main() -> int:
    settings = get_settings()
    settings.validate_startup()
    services = build_app_services(settings)

    aliases = services.models_config.get("aliases", {})
    purposes = services.models_config.get("purposes", {})
    errors: list[str] = []

    if not aliases or not purposes:
        errors.append("models.yaml must define aliases and purposes")
    for name, purpose in purposes.items():
        for slot in ("primary", "fallback"):
            alias = purpose.get(slot)
            if alias is None and slot == "fallback":
                continue
            if alias not in aliases:
                errors.append(f"purpose {name} references unknown alias {alias!r} in {slot}")
        if purpose.get("egress") not in {"local", "external_deidentified"}:
            errors.append(f"purpose {name} has an unknown egress policy")
        if purposes.get(name, {}).get("egress") == "local":
            primary = aliases.get(purpose.get("primary"), {})
            if primary.get("provider") == "openrouter":
                errors.append(f"local purpose {name} resolves to an external provider")

    embedding = aliases.get(purposes.get("embedding", {}).get("primary"), {})
    if embedding.get("dimensions") != settings.embedding_dim:
        errors.append(
            "EMBEDDING_DIM does not match the configured embedding alias "
            f"({settings.embedding_dim} != {embedding.get('dimensions')})"
        )

    metric_ids = [item.get("id") for item in services.metrics.get("metrics", [])]
    if len(metric_ids) != len(set(metric_ids)):
        errors.append("metrics.yaml contains duplicate metric ids")
    for metric in services.metrics.get("metrics", []):
        for field in ("id", "version", "label", "source", "formula", "freshness_hours"):
            if field not in metric:
                errors.append(f"metric {metric.get('id', '<unknown>')} is missing {field}")

    if services.finops_model.get("model_version") is None:
        errors.append("finops_model.yaml has no model_version")
    if not services.prices.get("fx_usd_inr"):
        errors.append("prices.yaml has no FX rate")

    if errors:
        for message in errors:
            print(f"config error: {message}", file=sys.stderr)
        return 2

    summary = {
        "status": "valid",
        "profile": settings.app_profile,
        "environment": settings.app_env,
        "config_hash": _config_hash(settings.config_dir),
        "feature_registry_version": services.feature_registry.version,
        "feature_count": len(services.feature_registry.flags),
        "model_purposes": len(purposes),
        "metrics": len(metric_ids),
        "embedding_dim": settings.embedding_dim,
        "storage_configured": settings.s3_configured,
        "email_configured": services.notifications is not None
        and services.notifications.configured("email"),
        "sms_configured": services.notifications is not None
        and services.notifications.configured("sms"),
        "slack_staff_configured": settings.slack_staff_configured,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
