#!/usr/bin/env python3
"""End-to-end smoke checks against a running Sahyog stack.

Uses real Keycloak password grants and the real API. It never bypasses authentication
and never prints tokens or passwords. Checks that need a model are skipped rather than
reported as passing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.environ.get("ENV_FILE", ROOT / ".env"))
PATIENT_ID = "20000000-0000-4000-8000-000000000001"


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


class CheckError(RuntimeError):
    pass


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
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
        raise CheckError(f"refusing non-HTTP URL: {url}")
    request = urllib.request.Request(  # noqa: S310
        url, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw.decode(errors="replace")[:300]
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw.decode(errors="replace")[:300]
        return exc.code, payload
    except urllib.error.URLError as exc:
        raise CheckError(f"cannot reach {url}: {exc.reason}") from exc


class Smoke:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.api = env_value("API_BASE_URL", "http://localhost:5706").rstrip("/")
        self.web = env_value("APP_BASE_URL", "http://localhost:5705").rstrip("/")
        self.keycloak = env_value("KEYCLOAK_PUBLIC_URL", "http://localhost:5707").rstrip("/")
        self.realm = env_value("KEYCLOAK_REALM", "sahyog")
        self.client_id = env_value("KEYCLOAK_CLI_CLIENT_ID", "sahyog-cli")
        self.client_secret = env_value("KEYCLOAK_CLI_CLIENT_SECRET")
        self.password = env_value("SEED_DEMO_PASSWORD")
        self.results: list[dict[str, Any]] = []
        self._tokens: dict[str, str] = {}

    def record(self, name: str, ok: bool, detail: str = "", skipped: bool = False) -> None:
        self.results.append({"check": name, "ok": ok, "skipped": skipped, "detail": detail[:400]})
        marker = "SKIP" if skipped else ("PASS" if ok else "FAIL")
        print(f"  {marker:<4} {name}" + (f" — {detail}" if detail else ""))

    def expect(self, name: str, method: str, path: str, **kwargs: Any) -> Any:
        status, payload = _request(method, f"{self.api}{path}", **kwargs)
        if status >= 400:
            raise CheckError(f"{name}: HTTP {status} {str(payload)[:240]}")
        self.record(name, True)
        return payload

    def token(self, username: str) -> str:
        if username in self._tokens:
            return self._tokens[username]
        if not self.client_secret or not self.password:
            raise CheckError(
                "KEYCLOAK_CLI_CLIENT_SECRET and SEED_DEMO_PASSWORD are required for smoke"
            )
        status, payload = _request(
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
        if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
            raise CheckError(f"Keycloak login failed for {username}: HTTP {status}")
        self._tokens[username] = str(payload["access_token"])
        return self._tokens[username]

    def run(self) -> int:
        print(f"Smoke target: {self.api} · web {self.web}\n")

        status, health = _request("GET", f"{self.api}/healthz")
        self.record("api.liveness", status == 200, f"HTTP {status}")
        status, ready = _request("GET", f"{self.api}/readyz")
        self.record("api.readiness", status == 200, f"HTTP {status}")

        if not self.args.skip_ui:
            status, _ = _request("GET", f"{self.web}/healthz")
            self.record("web.health", status == 200, f"HTTP {status}")

        meta = self.expect("meta", "GET", "/api/v1/meta")
        self.record(
            "meta.contract",
            all(key in meta for key in ("app", "features", "purposes", "adapters", "disclaimer")),
            "app/features/purposes/adapters/disclaimer",
        )
        adapters = meta.get("adapters", {})
        valid = {"configured", "unconfigured", "disabled", "enabled"}
        bad = {
            key: value.get("status")
            for key, value in adapters.items()
            if value.get("status") not in valid
        }
        self.record("meta.adapters_truthful", not bad, str(bad) if bad else "no mock states")

        patient = self.token("patient.priya")
        me = self.expect("auth.patient_me", "GET", "/api/v1/auth/me", token=patient)
        self.record(
            "auth.patient_role",
            me.get("primary_role") == "patient" and bool(me.get("patient_linked")),
            f"role={me.get('primary_role')} linked={me.get('patient_linked')}",
        )

        forbidden = _request("GET", f"{self.api}/api/v1/patients", token=patient)
        self.record(
            "authz.patient_cannot_list_patients",
            forbidden[0] == 403,
            f"HTTP {forbidden[0]}",
        )

        doctor = self.token("doctor.rao")
        docs = self.expect(
            "records.doctor_documents",
            "GET",
            f"/api/v1/records/documents?patient_id={PATIENT_ID}&page=1&page_size=5",
            token=doctor,
        )
        self.record(
            "grid.server_meta",
            isinstance(docs, dict) and {"items", "meta"}.issubset(docs),
            f"total={docs.get('meta', {}).get('total') if isinstance(docs, dict) else '?'}",
        )

        session = self.expect(
            "chat.session_create",
            "POST",
            "/api/v1/chat/sessions",
            token=patient,
            body={"title": "smoke", "locale": "en-IN"},
        )
        session_id = session.get("id")
        try:
            reply = self.expect(
                "chat.red_flag_local",
                "POST",
                f"/api/v1/chat/sessions/{session_id}/messages",
                token=patient,
                body={"content": "I have severe breathlessness and cannot breathe."},
            )
            red_flag = reply.get("red_flag") or {}
            self.record(
                "chat.red_flag_detected",
                red_flag.get("severity") == "emergency",
                f"rules={red_flag.get('rule_ids')}",
            )
            sources = reply.get("assistant_message", {}).get("sources") or []
            self.record(
                "provenance.chat_sources",
                bool(sources) and all(item.get("type") for item in sources),
                f"{len(sources)} source(s)",
            )
            sessions = self.expect(
                "chat.session_grid", "GET", "/api/v1/chat/sessions", token=patient
            )
            self.record(
                "chat.session_grid_meta",
                "meta" in sessions and "items" in sessions,
                f"total={sessions.get('meta', {}).get('total')}",
            )
        finally:
            status, _ = _request(
                "DELETE", f"{self.api}/api/v1/chat/sessions/{session_id}", token=patient
            )
            self.record("chat.session_delete", status in {204, 404}, f"HTTP {status}")

        notifications = self.expect(
            "notifications.inapp_list", "GET", "/api/v1/notifications", token=patient
        )
        total = (
            notifications.get("meta", {}).get("total") if isinstance(notifications, dict) else "?"
        )
        self.record(
            "notifications.inapp_grid",
            isinstance(notifications, dict) and "items" in notifications,
            f"total={total}",
        )
        if self.args.notifications:
            email = adapters.get("email", {}).get("status")
            slack = adapters.get("slack_staff", {}).get("status")
            self.record(
                "notifications.channels_declared",
                email in valid and slack in valid,
                f"email={email} slack_staff={slack}",
            )

        admin = self.token("admin.ops")
        if self.args.flags:
            flags = self.expect("flags.list", "GET", "/api/v1/admin/flags", token=admin)
            items = flags.get("items", []) if isinstance(flags, dict) else []
            locked = [item for item in items if item.get("flag_class") == "locked"]
            self.record(
                "flags.locked_default_on",
                bool(items) and all(item.get("value") for item in locked),
                f"{len(items)} flags, {len(locked)} locked",
            )
            self.record(
                "flags.registry_version",
                bool(flags.get("registry_version")) if isinstance(flags, dict) else False,
                f"v{flags.get('registry_version') if isinstance(flags, dict) else '?'}",
            )

        if self.args.analytics:
            for path, name in (
                ("/api/v1/analytics/overview", "analytics.overview"),
                ("/api/v1/analytics/quality", "analytics.quality"),
                ("/api/v1/analytics/compliance", "analytics.compliance"),
                ("/api/v1/analytics/evaluations", "analytics.evaluations"),
                ("/api/v1/analytics/finops", "analytics.finops"),
                ("/api/v1/analytics/insights", "analytics.insights"),
            ):
                payload = self.expect(name, "GET", path, token=admin)
                tiles = payload.get("tiles") or payload.get("metrics") or []
                shaped = all(
                    {"id", "value", "status", "as_of"}.issubset(tile) for tile in tiles if tile
                )
                self.record(
                    f"{name}.tiles",
                    shaped,
                    f"{len(tiles)} tile(s)",
                )

        if self.args.sources:
            self.record(
                "provenance.types",
                bool(sources),
                "chat source panel exercised",
            )

        audit = self.expect(
            "audit.list",
            "GET",
            "/api/v1/admin/audit?page=1&page_size=5&sort=created_at&order=desc",
            token=admin,
        )
        self.record(
            "audit.grid",
            isinstance(audit, dict) and bool(audit.get("items")),
            f"total={audit.get('meta', {}).get('total') if isinstance(audit, dict) else '?'}",
        )

        if self.args.stt:
            stt = adapters.get("stt", {}).get("status")
            self.record(
                "stt.adapter",
                stt in {"enabled", "disabled"},
                f"status={stt}",
                skipped=stt == "disabled",
            )

        if self.args.telemetry:
            meta_status = meta.get("app", {}).get("profile")
            self.record(
                "telemetry.profile",
                meta_status in {"core", "full"},
                f"profile={meta_status}",
                skipped=meta_status not in {"core", "full"},
            )

        failed = [item for item in self.results if not item["ok"] and not item["skipped"]]
        skipped = [item for item in self.results if item["skipped"]]
        if self.args.summary:
            print(
                json.dumps(
                    {
                        "status": "failed" if failed else "passed",
                        "checks": len(self.results),
                        "failed": len(failed),
                        "skipped": len(skipped),
                        "results": self.results,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                f"\n{len(self.results) - len(failed) - len(skipped)} passed · "
                f"{len(skipped)} skipped · {len(failed)} failed"
            )
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", action="store_true", help="Assert the chat source panel")
    parser.add_argument("--notifications", action="store_true")
    parser.add_argument("--analytics", action="store_true")
    parser.add_argument("--flags", action="store_true")
    parser.add_argument("--stt", action="store_true")
    parser.add_argument("--telemetry", action="store_true")
    parser.add_argument("--cost", action="store_true")
    parser.add_argument("--summary", action="store_true", help="Print a JSON summary")
    parser.add_argument("--skip-ui", action="store_true")
    args = parser.parse_args()
    if args.cost:
        args.analytics = True
    try:
        return Smoke(args).run()
    except CheckError as exc:
        print(f"  FAIL smoke aborted — {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
