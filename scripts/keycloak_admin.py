#!/usr/bin/env python3
"""Idempotent Keycloak realm, client, role and demo-user provisioning.

Uses the master admin only for bootstrap/sync. Application automation should use the
`sahyog-admin` service account after the first sync. Passwords are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, cast

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))

from demo_fixtures import (  # noqa: E402
    DEMO_USERS,
    loadtest_users,
)

APP_ROLES = (
    "patient",
    "caregiver",
    "doctor",
    "front_desk",
    "pharmacist",
    "compliance",
    "admin",
    "service",
)
INTERACTIVE_ROLES = APP_ROLES[:-1]

# Seeded fixtures use fixed subjects so seeding is idempotent. Keycloak issues its
# own user IDs, so every seeded row that stores a subject must be re-pointed at the
# real ID after users exist. audit_events is append-only and is deliberately absent.
DEMO_SUBJECT_COLUMNS = (
    ("consents", "grantor_subject"),
    ("consents", "caregiver_subject"),
    ("chat_sessions", "owner_subject"),
    ("contact_channels", "subject"),
    ("documents", "uploaded_by_subject"),
    ("encounters", "doctor_subject"),
    ("notifications", "recipient_subject"),
    ("review_tasks", "created_by_subject"),
    ("review_tasks", "owner_subject"),
    ("clinical_notes", "author_subject"),
    ("scribe_runs", "requested_by_subject"),
    ("stock_reservations", "reserved_by_subject"),
    ("memory_preferences", "subject"),
)
REALM_TEMPLATE = Path(
    os.environ.get("KEYCLOAK_REALM_TEMPLATE", ROOT / "docker" / "keycloak" / "realm-sahyog.json")
)


def _load_realm_template() -> dict[str, Any] | None:
    if not REALM_TEMPLATE.exists():
        return None
    return cast(dict[str, Any], json.loads(REALM_TEMPLATE.read_text(encoding="utf-8")))


class KeycloakError(RuntimeError):
    pass


def _dotenv_value(name: str) -> str:
    """Read a single key from repo .env as data (never sourced as shell)."""
    env_path = Path(os.environ.get("ENV_FILE", ROOT / ".env"))
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() != name:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                return value[1:-1]
            for index, char in enumerate(value):
                if char == "#" and (index == 0 or value[index - 1] in " \t"):
                    return value[:index].rstrip()
            return value
    except FileNotFoundError:
        return ""
    return ""


def _setting(name: str, default: str = "") -> str:
    # Process env wins (export_host_runtime_env rewrites URLs for --local); else .env.
    value = os.environ.get(name)
    if value is None or value == "":
        value = _dotenv_value(name) or default
    return value.strip()


def _external_web_client(representation: dict[str, Any]) -> dict[str, Any]:
    if representation.get("clientId") != _setting("KEYCLOAK_WEB_CLIENT_ID", "sahyog-web"):
        return representation
    root_url = _setting("KEYCLOAK_WEB_ROOT_URL").rstrip("/")
    redirects = _setting("KEYCLOAK_WEB_REDIRECT_URIS")
    origins = _setting("KEYCLOAK_WEB_ORIGINS")
    # Always keep Vite (5729) + Compose web (5705) logout redirects allowlisted so
    # ./scripts/start.sh --local sign-out works even when KEYCLOAK_WEB_* is unset.
    updated = copy.deepcopy(representation)
    default_redirects = [
        "http://localhost:5705/*",
        "http://localhost:5729/*",
        "http://127.0.0.1:5705/*",
        "http://127.0.0.1:5729/*",
    ]
    if root_url:
        updated["rootUrl"] = root_url
    if redirects:
        updated["redirectUris"] = [item.strip() for item in redirects.split(",") if item.strip()]
    else:
        existing = [str(item) for item in (updated.get("redirectUris") or [])]
        updated["redirectUris"] = list(dict.fromkeys([*existing, *default_redirects]))
    if origins:
        updated["webOrigins"] = [item.strip() for item in origins.split(",") if item.strip()]
    else:
        existing_origins = [str(item) for item in (updated.get("webOrigins") or [])]
        default_origins = [
            "http://localhost:5705",
            "http://localhost:5729",
            "http://127.0.0.1:5705",
            "http://127.0.0.1:5729",
        ]
        updated["webOrigins"] = list(dict.fromkeys([*existing_origins, *default_origins]))
    logout_uris = []
    for uri in updated.get("redirectUris") or default_redirects:
        base = str(uri).rstrip("*").rstrip("/")
        if base:
            logout_uris.append(f"{base}/*")
    if root_url:
        logout_uris.insert(0, f"{root_url}/*")
    updated.setdefault("attributes", {})["post.logout.redirect.uris"] = "##".join(
        dict.fromkeys(logout_uris)
    )
    return updated


class Keycloak:
    def __init__(self) -> None:
        self.realm = _setting("KEYCLOAK_REALM", "sahyog")
        base = _setting("KEYCLOAK_ADMIN_URL") or _setting(
            "KEYCLOAK_PUBLIC_URL", "http://localhost:5707"
        )
        self.base_url = base.rstrip("/")
        self.timeout = httpx.Timeout(30.0, connect=10.0)
        self._client: httpx.AsyncClient | None = None
        self._token: str | None = None

    async def __aenter__(self) -> Keycloak:
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        self._token = await self._admin_token()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Keycloak client is not open")
        return self._client

    async def _admin_token(self) -> str:
        user = _setting("KEYCLOAK_ADMIN_USER", "admin")
        password = _setting("KEYCLOAK_ADMIN_PASSWORD")
        if not password:
            raise KeycloakError("KEYCLOAK_ADMIN_PASSWORD is required")
        response = await self.client.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": user,
                "password": password,
            },
        )
        if response.status_code != 200:
            raise KeycloakError(f"admin token failed with HTTP {response.status_code}")
        return str(response.json()["access_token"])

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...] = (200, 201, 204),
        **kwargs: Any,
    ) -> httpx.Response:
        response = await self.client.request(method, path, headers=self._headers(), **kwargs)
        if response.status_code not in expected:
            detail = response.text[:300]
            raise KeycloakError(f"{method} {path} -> HTTP {response.status_code}: {detail}")
        return response

    # ---------------------------------------------------------------- realm
    async def realm_exists(self) -> bool:
        response = await self.request("GET", f"/admin/realms/{self.realm}", expected=(200, 404))
        return response.status_code == 200

    async def ensure_realm(self) -> bool:
        if await self.realm_exists():
            return False
        template = await asyncio.to_thread(_load_realm_template)
        if template is None:
            raise KeycloakError(f"realm template not found: {REALM_TEMPLATE}")
        if template.get("realm") != self.realm:
            template["realm"] = self.realm
        await self.request("POST", "/admin/realms", json=template)
        return True

    async def ensure_roles(self) -> None:
        for role in APP_ROLES:
            path = f"/admin/realms/{self.realm}/roles/{role}"
            existing = await self.request("GET", path, expected=(200, 404))
            if existing.status_code == 404:
                await self.request(
                    "POST",
                    f"/admin/realms/{self.realm}/roles",
                    json={"name": role, "description": f"Sahyog {role} role"},
                )

    async def find_client(self, client_id: str) -> dict[str, Any] | None:
        response = await self.request(
            "GET",
            f"/admin/realms/{self.realm}/clients",
            params={"clientId": client_id},
        )
        items = response.json()
        return items[0] if items else None

    async def ensure_client(self, representation: dict[str, Any]) -> dict[str, Any]:
        client_id = str(representation["clientId"])
        existing = await self.find_client(client_id)
        if existing is None:
            await self.request("POST", f"/admin/realms/{self.realm}/clients", json=representation)
            existing = await self.find_client(client_id)
            if existing is None:
                raise KeycloakError(f"client {client_id} was not created")
            return existing
        merged = {**existing}
        for key in (
            "enabled",
            "publicClient",
            "bearerOnly",
            "standardFlowEnabled",
            "implicitFlowEnabled",
            "directAccessGrantsEnabled",
            "serviceAccountsEnabled",
            "fullScopeAllowed",
            "redirectUris",
            "webOrigins",
            "attributes",
            "rootUrl",
            "baseUrl",
            "secret",
        ):
            if key in representation:
                merged[key] = representation[key]
        await self.request(
            "PUT", f"/admin/realms/{self.realm}/clients/{existing['id']}", json=merged
        )
        updated = await self.find_client(client_id)
        if updated is None:
            raise KeycloakError(f"client {client_id} disappeared during update")
        return updated

    async def ensure_clients(self) -> dict[str, dict[str, Any]]:
        template = await asyncio.to_thread(_load_realm_template)
        if template is None:
            raise KeycloakError(f"realm template not found: {REALM_TEMPLATE}")
        clients: dict[str, dict[str, Any]] = {}
        for representation in template.get("clients", []):
            representation = _external_web_client(representation)
            clients[str(representation["clientId"])] = await self.ensure_client(representation)

        admin_secret = _setting("KEYCLOAK_ADMIN_CLIENT_SECRET")
        if not admin_secret:
            raise KeycloakError("KEYCLOAK_ADMIN_CLIENT_SECRET is required for the admin client")
        admin = await self.ensure_client(
            {
                "clientId": _setting("KEYCLOAK_ADMIN_CLIENT_ID", "sahyog-admin"),
                "name": "Sahyog least-privilege administration",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "bearerOnly": False,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": True,
                "consentRequired": False,
                "fullScopeAllowed": True,
                "secret": admin_secret,
            }
        )
        clients[str(admin["clientId"])] = admin

        mcp_secret = _setting("KEYCLOAK_MCP_CLIENT_SECRET") or _setting("MCP_SERVICE_TOKEN")
        if not mcp_secret:
            raise KeycloakError("MCP_SERVICE_TOKEN is required for the MCP service client")
        mcp = await self.ensure_client(
            {
                "clientId": _setting("KEYCLOAK_MCP_CLIENT_ID", "sahyog-mcp"),
                "name": "Sahyog MCP service identity",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "bearerOnly": False,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": True,
                "consentRequired": False,
                "fullScopeAllowed": True,
                "secret": mcp_secret,
            }
        )
        clients[str(mcp["clientId"])] = mcp

        cli_secret = _setting("KEYCLOAK_CLI_CLIENT_SECRET")
        if not cli_secret:
            raise KeycloakError(
                "KEYCLOAK_CLI_CLIENT_SECRET is required for the operator CLI client"
            )
        cli = await self.ensure_client(
            {
                "clientId": _setting("KEYCLOAK_CLI_CLIENT_ID", "sahyog-cli"),
                "name": ("Sahyog local operator scripts (password grant; disable outside local)"),
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "bearerOnly": False,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": True,
                "serviceAccountsEnabled": False,
                "consentRequired": False,
                "fullScopeAllowed": True,
                "secret": cli_secret,
            }
        )
        clients[str(cli["clientId"])] = cli
        return clients

    async def ensure_user_profile(self) -> None:
        path = f"/admin/realms/{self.realm}/users/profile"
        response = await self.request("GET", path)
        config = cast(dict[str, Any], response.json())
        if config.get("unmanagedAttributePolicy") == "ADMIN_EDIT":
            return
        # Custom claims (patient_id, clinic_ids, traffic_class) are dropped unless
        # admins may manage unmanaged attributes. Users must not self-edit them.
        config["unmanagedAttributePolicy"] = "ADMIN_EDIT"
        await self.request("PUT", path, json=config)

    async def ensure_mappers(self, web_client: dict[str, Any]) -> None:
        template = await asyncio.to_thread(_load_realm_template)
        if template is None:
            return
        web = next(
            (item for item in template.get("clients", []) if item.get("clientId") == "sahyog-web"),
            None,
        )
        if web is None:
            return
        client_uuid = web_client["id"]
        existing = await self.request(
            "GET",
            f"/admin/realms/{self.realm}/clients/{client_uuid}/protocol-mappers/models",
        )
        by_name = {item["name"]: item for item in existing.json()}
        for mapper in web.get("protocolMappers", []):
            current = by_name.get(mapper["name"])
            if current is None:
                await self.request(
                    "POST",
                    f"/admin/realms/{self.realm}/clients/{client_uuid}/protocol-mappers/models",
                    json=mapper,
                )
            else:
                merged = {**current, "config": {**current.get("config", {}), **mapper["config"]}}
                await self.request(
                    "PUT",
                    (
                        f"/admin/realms/{self.realm}/clients/{client_uuid}"
                        f"/protocol-mappers/models/{current['id']}"
                    ),
                    json=merged,
                )

    async def await_service_account(self, client_uuid: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(20):
            response = await self.request(
                "GET",
                f"/admin/realms/{self.realm}/clients/{client_uuid}/service-account-user",
                expected=(200, 404),
            )
            if response.status_code == 200:
                return cast(dict[str, Any], response.json())
            last_error = KeycloakError("service account not ready")
            await asyncio.sleep(0.5)
        raise KeycloakError(str(last_error or "service account not ready"))

    async def _realm_management_client_id(self) -> str:
        client = await self.find_client("realm-management")
        if client is None:
            raise KeycloakError("realm-management client not found")
        return str(client["id"])

    async def _client_roles(self, client_uuid: str, names: tuple[str, ...]) -> list[dict[str, Any]]:
        roles: list[dict[str, Any]] = []
        for name in names:
            response = await self.request(
                "GET",
                f"/admin/realms/{self.realm}/clients/{client_uuid}/roles/{name}",
                expected=(200, 404),
            )
            if response.status_code == 200:
                roles.append(response.json())
        return roles

    async def _realm_role(self, name: str) -> dict[str, Any]:
        response = await self.request(
            "GET", f"/admin/realms/{self.realm}/roles/{name}", expected=(200, 404)
        )
        if response.status_code != 200:
            raise KeycloakError(f"realm role {name} not found")
        return cast(dict[str, Any], response.json())

    async def ensure_service_accounts(self, clients: dict[str, dict[str, Any]]) -> None:
        realm_management = await self._realm_management_client_id()
        admin_client = clients.get(_setting("KEYCLOAK_ADMIN_CLIENT_ID", "sahyog-admin"))
        if admin_client is None:
            raise KeycloakError("admin client missing")
        admin_user = await self.await_service_account(str(admin_client["id"]))
        admin_roles = await self._client_roles(
            realm_management,
            (
                "manage-users",
                "view-users",
                "query-users",
                "view-realm",
                "view-clients",
                "query-clients",
            ),
        )
        current = await self.request(
            "GET",
            (
                f"/admin/realms/{self.realm}/users/{admin_user['id']}"
                f"/role-mappings/clients/{realm_management}"
            ),
        )
        current_ids = {item["id"] for item in current.json()}
        missing = [role for role in admin_roles if role["id"] not in current_ids]
        if missing:
            await self.request(
                "POST",
                (
                    f"/admin/realms/{self.realm}/users/{admin_user['id']}"
                    f"/role-mappings/clients/{realm_management}"
                ),
                json=missing,
            )

        mcp_client = clients.get(_setting("KEYCLOAK_MCP_CLIENT_ID", "sahyog-mcp"))
        if mcp_client is not None:
            mcp_user = await self.await_service_account(str(mcp_client["id"]))
            service_role = await self._realm_role("service")
            current = await self.request(
                "GET", f"/admin/realms/{self.realm}/users/{mcp_user['id']}/role-mappings/realm"
            )
            if service_role["id"] not in {item["id"] for item in current.json()}:
                await self.request(
                    "POST",
                    f"/admin/realms/{self.realm}/users/{mcp_user['id']}/role-mappings/realm",
                    json=[service_role],
                )

    # ---------------------------------------------------------------- users
    async def find_user(self, username: str) -> dict[str, Any] | None:
        response = await self.request(
            "GET",
            f"/admin/realms/{self.realm}/users",
            params={"username": username, "exact": "true"},
        )
        items = response.json()
        return items[0] if items else None

    async def realm_role_names(self, user_id: str) -> set[str]:
        response = await self.request(
            "GET", f"/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm"
        )
        return {item["name"] for item in response.json()}

    async def assign_role(self, user_id: str, role: str) -> None:
        current = await self.realm_role_names(user_id)
        if role in current:
            return
        representation = await self._realm_role(role)
        await self.request(
            "POST",
            f"/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm",
            json=[representation],
        )

    def _user_rep(self, spec: dict[str, Any], *, include_id: bool) -> dict[str, Any]:
        attributes = {
            "clinic_ids": list(spec.get("clinic_ids") or []),
            "locale": [str(spec.get("locale", "en-IN"))],
            "traffic_class": [str(spec.get("traffic_class", "real"))],
            "cohort": [str(spec.get("cohort", "demo"))],
        }
        if spec.get("patient_id"):
            attributes["patient_id"] = [str(spec["patient_id"])]
        if spec.get("doctor_display_name"):
            attributes["doctor_display_name"] = [str(spec["doctor_display_name"])]
        if spec.get("notify_email"):
            attributes["notify_email"] = [str(spec["notify_email"])]
        if spec.get("slack_id"):
            attributes["slack_id"] = [str(spec["slack_id"])]
            attributes["slack_audience"] = [str(spec.get("slack_audience") or "staff")]
        rep: dict[str, Any] = {
            "username": spec["username"],
            "enabled": True,
            "emailVerified": True,
            "email": spec["email"],
            "firstName": spec["first_name"],
            "lastName": spec["last_name"],
            "attributes": attributes,
            "requiredActions": [],
        }
        if include_id:
            rep["id"] = str(spec["id"])
        return rep

    async def upsert_user(
        self, spec: dict[str, Any], password: str, *, force_password: bool
    ) -> tuple[dict[str, Any], bool]:
        existing = await self.find_user(str(spec["username"]))
        created = existing is None
        if created:
            rep = self._user_rep(spec, include_id=True)
            rep["credentials"] = [{"type": "password", "value": password, "temporary": False}]
            response = await self.request(
                "POST", f"/admin/realms/{self.realm}/users", json=rep, expected=(201, 204)
            )
            created_id = response.headers.get("Location", "").rstrip("/").split("/")[-1]
            existing = await self.find_user(str(spec["username"]))
            if existing is None:
                raise KeycloakError(f"user {spec['username']} was not created ({created_id})")
        if existing is None:
            raise KeycloakError(f"user {spec['username']} disappeared during upsert")
        user_id = str(existing["id"])
        if not created:
            rep = self._user_rep(spec, include_id=False)
            await self.request("PUT", f"/admin/realms/{self.realm}/users/{user_id}", json=rep)
        if created or force_password:
            await self.request(
                "PUT",
                f"/admin/realms/{self.realm}/users/{existing['id']}/reset-password",
                json={"type": "password", "value": password, "temporary": False},
            )
        await self.assign_role(str(existing["id"]), str(spec["role"]))
        return existing, created

    async def sync(self) -> dict[str, Any]:
        created = await self.ensure_realm()
        await self.ensure_user_profile()
        await self.ensure_roles()
        clients = await self.ensure_clients()
        await self.ensure_mappers(clients["sahyog-web"])
        if "sahyog-cli" in clients:
            await self.ensure_mappers(clients["sahyog-cli"])
        await self.ensure_service_accounts(clients)
        return {
            "realm": self.realm,
            "realm_created": created,
            "clients": sorted(clients),
            "roles": list(APP_ROLES),
        }


async def _seed(args: argparse.Namespace) -> dict[str, Any]:
    from demo_contacts import enrich_demo_users

    password = _setting("SEED_DEMO_PASSWORD")
    if not password:
        raise KeycloakError("SEED_DEMO_PASSWORD is required")
    if len(password) < 12:
        raise KeycloakError("SEED_DEMO_PASSWORD must be at least 12 characters")
    if args.load_test < 0 or args.load_test > 100:
        raise KeycloakError("--load-test must be between 0 and 100")
    async with Keycloak() as keycloak:
        await keycloak.sync()
        users = enrich_demo_users([*DEMO_USERS, *loadtest_users(args.load_test)])
        created = 0
        updated = 0
        contacts_mapped = 0
        for spec in users:
            user, was_created = await keycloak.upsert_user(
                spec, password, force_password=args.force
            )
            if was_created:
                created += 1
            else:
                updated += 1
            slack_id = str(spec.get("slack_id") or "")
            audience = str(spec.get("slack_audience") or "")
            if slack_id and audience:
                await _record_slack_mapping(
                    subject=str(user["id"]),
                    patient_id=str(spec["patient_id"]) if spec.get("patient_id") else None,
                    slack_id=slack_id,
                    audience=audience,
                    verified=True,
                )
                contacts_mapped += 1
            notify_email = str(spec.get("notify_email") or "")
            if notify_email:
                await _record_email_mapping(
                    subject=str(user["id"]),
                    patient_id=str(spec["patient_id"]) if spec.get("patient_id") else None,
                    email=notify_email,
                    audience=audience or ("patient" if spec.get("patient_id") else "staff"),
                )
                contacts_mapped += 1
        return {
            "realm": keycloak.realm,
            "demo_users": len(DEMO_USERS),
            "load_test_users": args.load_test * 3,
            "created": created,
            "updated": updated,
            "contacts_mapped": contacts_mapped,
        }


async def _sync(_: argparse.Namespace) -> dict[str, Any]:
    async with Keycloak() as keycloak:
        return await keycloak.sync()


async def _sync_loadtest_links(args: argparse.Namespace) -> dict[str, Any]:
    from app.core.config import get_settings
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    if args.load_test < 0 or args.load_test > 100:
        raise KeycloakError("--load-test must be between 0 and 100")
    settings = get_settings()
    if not settings.database_url:
        raise KeycloakError("DATABASE_URL is required")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    updated = 0
    missing = 0
    try:
        async with Keycloak() as keycloak, sessionmaker() as session:
            for spec in loadtest_users(args.load_test):
                if spec.get("role") != "patient":
                    continue
                user = await keycloak.find_user(str(spec["username"]))
                if user is None:
                    missing += 1
                    continue
                result = await session.execute(
                    text("UPDATE patients SET keycloak_subject = :subject WHERE id = :patient_id"),
                    {"subject": str(user["id"]), "patient_id": str(spec["patient_id"])},
                )
                updated += int(result.rowcount or 0)
            await session.commit()
    finally:
        await engine.dispose()
    return {"updated": updated, "missing": missing, "load_test": args.load_test}


async def _sync_demo_links(_: argparse.Namespace) -> dict[str, Any]:
    from demo_contacts import contact_targets, enrich_demo_patients, enrich_demo_users

    from app.core.config import get_settings
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = get_settings()
    if not settings.database_url:
        raise KeycloakError("DATABASE_URL is required")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    updated = 0
    contacts_mapped = 0
    missing: list[str] = []
    targets = contact_targets()
    enriched_by_username = {
        str(item["username"]): item for item in enrich_demo_users()
    }
    try:
        async with Keycloak() as keycloak, sessionmaker() as session:
            for spec in DEMO_USERS:
                user = await keycloak.find_user(str(spec["username"]))
                if user is None:
                    missing.append(str(spec["username"]))
                    continue
                fixture = str(spec["id"])
                subject = str(user["id"])
                patient_id = spec.get("patient_id")
                enriched = enriched_by_username.get(str(spec["username"]), {})
                if patient_id:
                    result = await session.execute(
                        text(
                            "UPDATE patients SET keycloak_subject = :subject, "
                            "notify_email = :email, slack_user_id = :slack, deleted_at = NULL "
                            "WHERE id = :patient_id"
                        ),
                        {
                            "subject": subject,
                            "patient_id": str(patient_id),
                            "email": enriched.get("notify_email") or targets["patient_email"],
                            "slack": enriched.get("slack_id") or targets["patient_slack"],
                        },
                    )
                    updated += int(result.rowcount or 0)
                if fixture != subject:
                    for table, column in DEMO_SUBJECT_COLUMNS:
                        result = await session.execute(
                            text(
                                f"UPDATE {table} SET {column} = :subject "  # noqa: S608 - constants
                                f"WHERE {column} = :fixture"
                            ),
                            {"subject": subject, "fixture": fixture},
                        )
                        updated += int(result.rowcount or 0)
                slack_id = str(enriched.get("slack_id") or "")
                audience = str(enriched.get("slack_audience") or "")
                notify_email = str(enriched.get("notify_email") or "")
                await session.commit()
                if slack_id and audience:
                    await _record_slack_mapping(
                        subject=subject,
                        patient_id=str(patient_id) if patient_id else None,
                        slack_id=slack_id,
                        audience=audience,
                        verified=True,
                    )
                    contacts_mapped += 1
                if notify_email:
                    await _record_email_mapping(
                        subject=subject,
                        patient_id=str(patient_id) if patient_id else None,
                        email=notify_email,
                        audience=audience or ("patient" if patient_id else "staff"),
                    )
                    contacts_mapped += 1

            for item in enrich_demo_patients():
                if item.get("keycloak_subject"):
                    continue
                await session.execute(
                    text(
                        "UPDATE patients SET notify_email = :email, slack_user_id = :slack, "
                        "deleted_at = NULL WHERE id = :patient_id"
                    ),
                    {
                        "patient_id": str(item["id"]),
                        "email": item.get("notify_email") or targets["patient_email"],
                        "slack": item.get("slack_user_id") or targets["patient_slack"],
                    },
                )
            await session.commit()

            # Drop duplicate contact_channels left by fixture→real subject remaps.
            await session.execute(
                text(
                    """
                    DELETE FROM contact_channels a
                    USING contact_channels b
                    WHERE a.subject = b.subject
                      AND a.channel = b.channel
                      AND a.ctid < b.ctid
                    """
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return {
        "users": len(DEMO_USERS),
        "missing": missing,
        "rows_updated": updated,
        "contacts_mapped": contacts_mapped,
    }


def _write_private(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


async def _export_realm(args: argparse.Namespace) -> dict[str, Any] | None:
    async with Keycloak() as keycloak:
        response = await keycloak.request(
            "GET",
            f"/admin/realms/{keycloak.realm}/partial-export",
            params={"exportClients": "true", "exportGroupsAndRoles": "true"},
        )
        payload = response.json()
        if args.out:
            path = Path(args.out)
            await asyncio.to_thread(_write_private, path, payload)
            return {
                "realm": keycloak.realm,
                "out": str(path),
                "clients": len(payload.get("clients", [])),
                "roles": len(payload.get("roles", {}).get("realm", [])),
            }
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return None


async def _realm_status(_: argparse.Namespace) -> dict[str, Any]:
    async with Keycloak() as keycloak:
        exists = await keycloak.realm_exists()
        users = 0
        if exists:
            response = await keycloak.request("GET", f"/admin/realms/{keycloak.realm}/users/count")
            users = int(response.json())
        return {"realm": keycloak.realm, "exists": exists, "users": users}


async def _import_realm(args: argparse.Namespace) -> dict[str, Any]:
    if args.file == "-":
        raw = sys.stdin.read()
    else:
        source_path = Path(args.file)
        try:
            raw = await asyncio.to_thread(source_path.read_text, encoding="utf-8")
        except OSError as exc:
            raise KeycloakError(f"cannot read realm export {source_path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KeycloakError(f"realm export is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise KeycloakError("realm export must be a JSON object")
    async with Keycloak() as keycloak:
        if await keycloak.realm_exists():
            subset = {
                key: payload[key]
                for key in ("roles", "clients", "users", "groups", "identityProviders")
                if key in payload
            }
            await keycloak.request(
                "POST",
                f"/admin/realms/{keycloak.realm}/partialImport",
                json={"ifResourceExists": "OVERWRITE", **subset},
            )
            mode = "partial_import"
        else:
            realm = {key: value for key, value in payload.items() if key != "id"}
            realm["realm"] = keycloak.realm
            await keycloak.request("POST", "/admin/realms", json=realm)
            mode = "realm_created"
        return {
            "realm": keycloak.realm,
            "mode": mode,
            "clients": len(payload.get("clients", [])),
            "users": len(payload.get("users", [])),
        }


async def _upsert_contact_channel(
    *,
    subject: str,
    patient_id: str | None,
    channel: str,
    address: str,
    verified: bool,
    opt_in: bool,
    workspace_id: str | None,
    audit_action: str,
    audience: str,
) -> None:
    from app.core.config import get_settings
    from app.repositories.audit import AuditRepository
    from app.repositories.models import ContactChannel, Patient
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = get_settings()
    if not settings.database_url:
        return
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with async_sessionmaker(engine)() as session:
            existing = await session.scalar(
                select(ContactChannel).where(
                    ContactChannel.subject == subject,
                    ContactChannel.channel == channel,
                )
            )
            pid = uuid.UUID(patient_id) if patient_id else None
            # verified_at drives the 180-day re-verification job and G-07 coverage; a
            # verified mapping without it would be invisible to both.
            verified_at = dt.datetime.now(dt.UTC) if verified else None
            if existing is None:
                session.add(
                    ContactChannel(
                        subject=subject,
                        patient_id=pid,
                        channel=channel,
                        address=address,
                        verified=verified,
                        opt_in=opt_in,
                        workspace_id=workspace_id,
                        verified_at=verified_at,
                    )
                )
            else:
                existing.address = address
                existing.patient_id = pid
                existing.verified = verified
                existing.opt_in = opt_in
                existing.workspace_id = workspace_id
                existing.verified_at = verified_at
            if channel == "slack_patient" and pid is not None:
                patient = await session.get(Patient, pid)
                if patient is not None:
                    patient.slack_user_id = address
            AuditRepository(session).append(
                actor_subject="bootstrap:keycloak-admin",
                actor_role="admin",
                action=audit_action,
                resource_type="contact_channel",
                resource_id=subject,
                patient_id=pid,
                metadata={"channel": channel, "verified": verified, "audience": audience},
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _record_slack_mapping(
    *, subject: str, patient_id: str | None, slack_id: str, audience: str, verified: bool
) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    channel = "slack_patient" if audience == "patient" else "slack_staff"
    workspace = (
        settings.slack_patient_workspace_id
        if audience == "patient"
        else settings.slack_staff_workspace_id
    )
    await _upsert_contact_channel(
        subject=subject,
        patient_id=patient_id,
        channel=channel,
        address=slack_id,
        verified=verified,
        opt_in=audience == "patient",
        workspace_id=workspace or None,
        audit_action="admin.slack_identity_mapped",
        audience=audience,
    )


async def _record_email_mapping(
    *, subject: str, patient_id: str | None, email: str, audience: str
) -> None:
    await _upsert_contact_channel(
        subject=subject,
        patient_id=patient_id if audience == "patient" else None,
        channel="email",
        address=email,
        verified=True,
        opt_in=True,
        workspace_id=None,
        audit_action="admin.email_identity_mapped",
        audience=audience,
    )


async def _add_user(args: argparse.Namespace) -> dict[str, Any]:
    if args.role not in INTERACTIVE_ROLES:
        raise KeycloakError(f"unknown or service role: {args.role}")
    if args.role in {"patient", "caregiver"} and not args.patient_id:
        raise KeycloakError("--patient-id is required for patient and caregiver roles")
    if args.role in {"doctor", "front_desk", "pharmacist"} and not args.clinic:
        raise KeycloakError("--clinic is required for this staff role")
    if args.slack_id and not args.slack_audience:
        raise KeycloakError("--slack-audience is required with --slack-id")
    if args.slack_audience == "patient" and args.role not in {"patient", "caregiver"}:
        raise KeycloakError("patient Slack cannot be mapped to a staff account")
    password = _setting(args.password_env) or _setting("SEED_DEMO_PASSWORD")
    if not password:
        raise KeycloakError(f"{args.password_env} or SEED_DEMO_PASSWORD is required")

    async with Keycloak() as keycloak:
        await keycloak.sync()
        existing = await keycloak.find_user(args.username)
        existing_roles = await keycloak.realm_role_names(str(existing["id"])) if existing else set()
        changing_role = bool(existing_roles) and args.role not in existing_roles
        if existing and changing_role and not args.confirm:
            roles = sorted(existing_roles)
            raise KeycloakError(
                f"user exists with roles {roles}; pass --confirm to add {args.role}"
            )
        spec = {
            "id": str(uuid.uuid4()),
            "username": args.username,
            "first_name": args.first_name or args.username.split(".")[0].title(),
            "last_name": args.last_name or "User",
            "email": args.email or f"{args.username}@example.test",
            "role": args.role,
            "clinic_ids": args.clinic or [],
            "patient_id": args.patient_id,
            "locale": args.locale,
            "traffic_class": "synthetic" if args.cohort == "loadtest" else "real",
            "cohort": args.cohort,
        }
        user, created = await keycloak.upsert_user(
            spec, password, force_password=args.reset_password
        )
        if args.slack_id:
            await _record_slack_mapping(
                subject=str(user["id"]),
                patient_id=args.patient_id,
                slack_id=args.slack_id,
                audience=args.slack_audience,
                verified=bool(args.slack_verified),
            )
        return {
            "username": args.username,
            "keycloak_sub": str(user["id"]),
            "role": args.role,
            "clinic_ids": args.clinic or [],
            "patient_id": args.patient_id,
            "created": created,
            "password_reset": bool(created or args.reset_password),
            "slack_mapped": bool(args.slack_id),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="Create/sync the realm, roles, clients and mappers")

    sub.add_parser("status", help="Report whether the realm exists and how many users it has")

    export = sub.add_parser("export", help="Export the realm for an encrypted backup")
    export.add_argument("--out", help="Write the export to this path (mode 0600)")

    restore = sub.add_parser("import", help="Restore a realm export into an empty realm")
    restore.add_argument(
        "--file", required=True, help="Realm export path, or - to read JSON from stdin"
    )

    seed = sub.add_parser("seed-demo", help="Create demo and load-test users")
    seed.add_argument("--load-test", type=int, default=0, metavar="N")
    seed.add_argument("--force", action="store_true", help="Reset demo passwords")

    links = sub.add_parser(
        "sync-loadtest-links",
        help="Point seeded load-test patient rows at their Keycloak subjects",
    )
    links.add_argument("--load-test", type=int, required=True, metavar="N")

    sub.add_parser(
        "sync-demo-links",
        help="Point seeded demo rows at the Keycloak user IDs that were actually issued",
    )

    add = sub.add_parser("add-user", help="Add or update one user")
    add.add_argument("--username", required=True)
    add.add_argument("--role", required=True, choices=INTERACTIVE_ROLES)
    add.add_argument("--clinic", action="append", default=[])
    add.add_argument("--patient-id")
    add.add_argument("--email")
    add.add_argument("--first-name")
    add.add_argument("--last-name")
    add.add_argument("--locale", default="en-IN", choices=("en-IN", "hi-IN", "mr-IN"))
    add.add_argument("--cohort", default="demo")
    add.add_argument("--password-env", default="ADD_USER_PASSWORD")
    add.add_argument("--reset-password", action="store_true")
    add.add_argument("--confirm", action="store_true")
    add.add_argument("--slack-id")
    add.add_argument("--slack-audience", choices=("patient", "staff"))
    add.add_argument("--slack-verified", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    handler = {
        "sync": _sync,
        "seed-demo": _seed,
        "sync-loadtest-links": _sync_loadtest_links,
        "sync-demo-links": _sync_demo_links,
        "add-user": _add_user,
        "status": _realm_status,
        "export": _export_realm,
        "import": _import_realm,
    }[args.command]
    try:
        result = asyncio.run(handler(args))
    except KeycloakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except httpx.HTTPError as exc:
        print(f"error: Keycloak is unreachable: {exc}", file=sys.stderr)
        return 3
    if result is not None:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
