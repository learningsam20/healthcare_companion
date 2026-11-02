"""Small filesystem helpers shared by the API and MCP services."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "config").is_dir() and (candidate / "docs").is_dir():
            return candidate
    return Path.cwd()


def config_dir() -> Path:
    configured = os.environ.get("CONFIG_DIR")
    if configured:
        return Path(configured)
    return find_repo_root() / "config"


def load_yaml(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data
