#!/usr/bin/env python3
"""Regenerate the as-built API catalogue from FastAPI OpenAPI (G-38).

Writes:
  docs/evidence/openapi-catalogue.json
  docs/evidence/openapi-catalogue.md

Does not rewrite architecture.md automatically — paste or diff §7.5 from the markdown.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps" / "api"), str(ROOT / "packages" / "py-common")]


def main() -> int:
    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(_env_file=None, app_env="test")
    app = create_app(settings)
    spec = app.openapi()
    paths = sorted(spec.get("paths") or {})
    methods: dict[str, list[str]] = {}
    for path, ops in (spec.get("paths") or {}).items():
        methods[path] = sorted(k.upper() for k in ops if k in {"get", "post", "put", "patch", "delete"})

    stamp = datetime.now(UTC).isoformat()
    catalogue = {
        "generated_at": stamp,
        "title": spec.get("info", {}).get("title"),
        "version": spec.get("info", {}).get("version"),
        "path_count": len(paths),
        "paths": methods,
        "note": "As-built OpenAPI catalogue for G-38; not a WCAG/ABDM certification claim.",
    }
    out_json = ROOT / "docs" / "evidence" / "openapi-catalogue.json"
    out_md = ROOT / "docs" / "evidence" / "openapi-catalogue.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(catalogue, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        f"# As-built OpenAPI catalogue",
        "",
        f"Generated: `{stamp}` · paths: **{len(paths)}**",
        "",
        "| Method | Path |",
        "| --- | --- |",
    ]
    for path in paths:
        for method in methods[path]:
            lines.append(f"| `{method}` | `{path}` |")
    lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"path_count": len(paths), "json": str(out_json), "md": str(out_md)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
