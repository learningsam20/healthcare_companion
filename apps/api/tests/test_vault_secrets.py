"""G-18: secrets backend loads file/vault maps without clobbering existing env."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core import vault


@pytest.fixture(autouse=True)
def _reset_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    vault._APPLIED = False  # noqa: SLF001
    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    monkeypatch.delenv("SECRETS_FILE", raising=False)
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.delenv("VAULT_SECRET_PATH", raising=False)


def test_env_backend_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRETS_BACKEND", "env")
    result = vault.apply_secrets(force=True)
    assert result["backend"] == "env"
    assert result["keys"] == 0


def test_file_backend_loads_env_and_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "secrets.env"
    env_file.write_text("PROBE_SECRET_A=alpha\nPROBE_SECRET_B=beta\n", encoding="utf-8")
    monkeypatch.setenv("SECRETS_BACKEND", "file")
    monkeypatch.setenv("SECRETS_FILE", str(env_file))
    monkeypatch.delenv("PROBE_SECRET_A", raising=False)
    monkeypatch.setenv("PROBE_SECRET_B", "keep-me")

    result = vault.apply_secrets(force=True)
    assert result["backend"] == "file"
    assert os.environ["PROBE_SECRET_A"] == "alpha"
    assert os.environ["PROBE_SECRET_B"] == "keep-me"  # existing env wins

    json_file = tmp_path / "secrets.json"
    json_file.write_text(json.dumps({"PROBE_SECRET_C": "gamma"}), encoding="utf-8")
    monkeypatch.setenv("SECRETS_FILE", str(json_file))
    monkeypatch.delenv("PROBE_SECRET_C", raising=False)
    vault._APPLIED = False  # noqa: SLF001
    vault.apply_secrets(force=True)
    assert os.environ["PROBE_SECRET_C"] == "gamma"
