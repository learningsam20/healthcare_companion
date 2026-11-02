#!/usr/bin/env python3
"""Small authenticated client shared by operator scripts.

Reads .env as data (never sourced), performs real Keycloak password grants and never
prints credentials. Intended for CLI use on the operator host.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.environ.get("ENV_FILE", ROOT / ".env"))


def env_value(key: str, default: str = "") -> str:
    values: dict[str, str] = {}
    try:
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name, value = name.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            else:
                for index, char in enumerate(value):
                    if char == "#" and (index == 0 or value[index - 1] in " \t"):
                        value = value[:index].rstrip()
                        break
            values[name] = value
    except FileNotFoundError:
        pass
    return os.environ.get(key, values.get(key, default))


class OpsError(RuntimeError):
    pass


class OpsClient:
    def __init__(self) -> None:
        self.api = env_value("API_BASE_URL", "http://localhost:5706").rstrip("/")
        self.keycloak = env_value("KEYCLOAK_PUBLIC_URL", "http://localhost:5707").rstrip("/")
        self.realm = env_value("KEYCLOAK_REALM", "sahyog")
        self.client_id = env_value("KEYCLOAK_CLI_CLIENT_ID", "sahyog-cli")
        self.client_secret = env_value("KEYCLOAK_CLI_CLIENT_SECRET")
        self.password = env_value("SEED_DEMO_PASSWORD")
        self._tokens: dict[str, str] = {}

    def _http(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        body: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        headers = {"Accept": "application/json"}
        data: bytes | None = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(form).encode()
        if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
            raise OpsError(f"refusing non-HTTP URL: {url}")
        request = urllib.request.Request(  # noqa: S310
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                detail = raw.decode(errors="replace")[:300]
            raise OpsError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpsError(f"cannot reach {url}: {exc.reason}") from exc

    def token(self, username: str) -> str:
        if username in self._tokens:
            return self._tokens[username]
        if not self.client_secret or not self.password:
            raise OpsError("KEYCLOAK_CLI_CLIENT_SECRET and SEED_DEMO_PASSWORD are required")
        payload = self._http(
            "POST",
            f"{self.keycloak}/realms/{self.realm}/protocol/openid-connect/token",
            form={
                "grant_type": "password",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "username": username,
                "password": self.password,
                "scope": "openid profile email",
            },
        )
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise OpsError(f"Keycloak returned no access token for {username}")
        self._tokens[username] = str(payload["access_token"])
        return self._tokens[username]

    def get(self, path: str, *, username: str) -> Any:
        return self._http("GET", f"{self.api}{path}", token=self.token(username))

    def post(self, path: str, body: dict[str, Any], *, username: str) -> Any:
        return self._http("POST", f"{self.api}{path}", token=self.token(username), body=body)

    def delete(self, path: str, *, username: str) -> Any:
        return self._http("DELETE", f"{self.api}{path}", token=self.token(username))

    def paged(self, path: str, *, username: str, page_size: int = 100) -> list[dict[str, Any]]:
        separator = "&" if "?" in path else "?"
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.get(
                f"{path}{separator}page={page}&page_size={page_size}", username=username
            )
            chunk = payload.get("items", []) if isinstance(payload, dict) else []
            items.extend(chunk)
            meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
            pages = int(meta.get("pages") or 0)
            if page >= pages or not chunk:
                break
            page += 1
        return items
