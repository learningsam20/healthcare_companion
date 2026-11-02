#!/usr/bin/env python3
"""OpenAPI contract checks for the API surface used by the SPA and scripts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("APP_ENV", "test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py-common"))

from app.main import create_app  # noqa: E402

GRID_PATHS = {
    "/api/v1/chat/sessions": "get",
    "/api/v1/patients": "get",
    "/api/v1/notifications": "get",
    "/api/v1/admin/audit": "get",
    "/api/v1/consents": "get",
}

REQUIRED_PATHS = {
    "/healthz",
    "/readyz",
    "/api/v1/meta",
    "/api/v1/auth/me",
    "/api/v1/chat/sessions",
    "/api/v1/chat/sessions/{session_id}/messages",
    "/api/v1/records/documents",
    "/api/v1/records/search",
    "/api/v1/records/ask",
    "/api/v1/analytics/overview",
    "/api/v1/analytics/finops",
    "/api/v1/analytics/insights",
    "/api/v1/admin/flags",
    "/api/v1/admin/audit",
}


def main() -> int:
    app = create_app()
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    errors: list[str] = []

    for path in sorted(REQUIRED_PATHS):
        if path not in spec.get("paths", {}):
            errors.append(f"missing path {path}")

    for path, method in GRID_PATHS.items():
        operation = spec.get("paths", {}).get(path, {}).get(method)
        if operation is None:
            errors.append(f"missing {method.upper()} {path}")
            continue
        names = {param.get("name") for param in operation.get("parameters", [])}
        for name in ("q", "page", "page_size", "sort", "order"):
            if name not in names:
                errors.append(f"{method.upper()} {path} lacks server-grid parameter {name}")

    if "SourceRef" not in schemas:
        errors.append("SourceRef is not in the OpenAPI schema")
    if "GridMeta" not in schemas:
        errors.append("GridMeta is not in the OpenAPI schema")
    security = spec.get("components", {}).get("securitySchemes", {})
    secured = any(
        value.get("type") in {"http", "oauth2", "openIdConnect"} for value in security.values()
    )
    if not secured:
        errors.append("no HTTP/OIDC security scheme is declared")

    if errors:
        for message in errors:
            print(f"contract error: {message}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "valid",
                "paths": len(spec.get("paths", {})),
                "schemas": len(schemas),
                "security_schemes": sorted(security),
                "grid_paths": sorted(GRID_PATHS),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
