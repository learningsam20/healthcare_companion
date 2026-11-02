"""G-38: every design §7.5 row is classified against the committed as-built catalogue."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "diff_api_catalogue", ROOT / "scripts" / "diff_api_catalogue.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normalise_ignores_parameter_names() -> None:
    mod = _load()
    assert mod.normalise("/a/{id}/b/{note_id}") == mod.normalise("/a/{x}/b/{y}")


def test_committed_design_rows_are_all_classified_and_targets_exist() -> None:
    mod = _load()
    design = mod.parse_design((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    built = mod.load_as_built(ROOT / "docs" / "evidence" / "openapi-catalogue.json")
    result = mod.diff(design, built)
    assert design, "no design rows parsed from architecture §7.5"
    assert result["unresolved"] == [], result["unresolved"]
    assert result["invalid_rename_targets"] == [], result["invalid_rename_targets"]


def test_out_of_scope_is_never_asserted_by_the_diff() -> None:
    mod = _load()
    markdown = mod.to_markdown(
        {
            "matched": [],
            "renamed": [],
            "proposed_out_of_scope": [{"method": "GET", "path": "/x", "reason": "r"}],
            "deferred_not_built": [],
            "unresolved": [],
            "invalid_rename_targets": [],
            "as_built_only": [],
        },
        "now",
    )
    assert "awaiting product sign-off" in markdown
    assert "Nothing here is marked out of scope by engineering" in markdown
