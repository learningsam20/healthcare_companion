"""Load secrets into the process environment before Settings are constructed.

Backends (SECRETS_BACKEND):
  - ``env`` (default): no-op; use process env / ``.env`` as today.
  - ``file``: load ``SECRETS_FILE`` (``.env`` KEY=VALUE lines or JSON object).
  - ``vault``: HashiCorp Vault KV v2 at ``VAULT_ADDR`` + ``VAULT_SECRET_PATH``
    (default ``secret/data/sahyog``) using ``VAULT_TOKEN`` or
    ``VAULT_TOKEN_FILE``.

Existing process-environment keys win over vault/file values so operators can
override a single secret without rewriting the store. Never logs secret values.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_APPLIED = False


def _parse_env_file(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        out[key] = value
    return out


def _load_file(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("SECRETS_FILE JSON must be an object of string values")
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    return _parse_env_file(text)


def _load_vault() -> dict[str, str]:
    addr = (os.environ.get("VAULT_ADDR") or "").rstrip("/")
    path = (os.environ.get("VAULT_SECRET_PATH") or "secret/data/sahyog").lstrip("/")
    token = (os.environ.get("VAULT_TOKEN") or "").strip()
    token_file = (os.environ.get("VAULT_TOKEN_FILE") or "").strip()
    if not token and token_file:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    if not addr or not token:
        raise RuntimeError("vault backend needs VAULT_ADDR and VAULT_TOKEN (or VAULT_TOKEN_FILE)")
    url = f"{addr}/v1/{path}"
    req = Request(url, headers={"X-Vault-Token": token}, method="GET")
    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310 — operator-configured Vault URL
            payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"vault HTTP {exc.code} for {path}") from exc
    except URLError as exc:
        raise RuntimeError(f"vault unreachable at {addr}") from exc
    data = payload.get("data") or {}
    # KV v2 nests under data.data; KV v1 uses data directly.
    nested = data.get("data") if isinstance(data.get("data"), dict) else None
    source = nested if nested is not None else data
    if not isinstance(source, dict):
        raise RuntimeError("vault secret payload is not a map")
    return {str(k): str(v) for k, v in source.items() if v is not None}


def apply_secrets(*, force: bool = False) -> dict[str, Any]:
    """Merge secrets into ``os.environ``. Safe to call multiple times."""
    global _APPLIED
    if _APPLIED and not force:
        return {"backend": os.environ.get("SECRETS_BACKEND", "env"), "applied": False, "keys": 0}

    backend = (os.environ.get("SECRETS_BACKEND") or "env").strip().lower()
    loaded: dict[str, str] = {}
    if backend in {"", "env", "none", "dotenv"}:
        _APPLIED = True
        return {"backend": "env", "applied": True, "keys": 0}
    if backend == "file":
        path_raw = (os.environ.get("SECRETS_FILE") or "").strip()
        if not path_raw:
            raise RuntimeError("SECRETS_BACKEND=file requires SECRETS_FILE")
        loaded = _load_file(Path(path_raw).expanduser())
    elif backend == "vault":
        loaded = _load_vault()
    else:
        raise RuntimeError(f"Unknown SECRETS_BACKEND={backend!r} (use env|file|vault)")

    applied = 0
    for key, value in loaded.items():
        if key in os.environ and os.environ[key] != "":
            continue
        os.environ[key] = value
        applied += 1

    _APPLIED = True
    logger.info(
        "secrets backend applied",
        extra={
            "event": "secrets.applied",
            "extra_fields": {"backend": backend, "keys_loaded": len(loaded), "keys_set": applied},
        },
    )
    return {"backend": backend, "applied": True, "keys": applied, "available": len(loaded)}
