"""G-24 memory allowlist, clinical reject, Forget/purge audit semantics (unit mocks)."""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sahyog_common.errors import ProblemError

from app.core.security import AuthContext, Role
from app.modules.memory.router import (
    ALLOWED_KEYS,
    MemoryUpsert,
    _reject_if_sensitive,
    delete_memory,
    purge_memory,
    router,
    upsert_memory,
)
from app.repositories.models import MemoryPreference


def test_allowlist_contains_opt_out() -> None:
    assert "opt_out" in ALLOWED_KEYS
    assert "preferred_locale" in ALLOWED_KEYS
    assert MemoryUpsert(key="opt_out", value="true").key == "opt_out"


def test_reject_phone_and_clinical() -> None:
    with pytest.raises(ProblemError) as phone:
        _reject_if_sensitive("call 9876543210")
    assert phone.value.code == "memory_value_rejected"
    with pytest.raises(ProblemError) as clinical:
        _reject_if_sensitive("insulin dose 10mg")
    assert clinical.value.code == "memory_value_rejected"
    with pytest.raises(ProblemError):
        _reject_if_sensitive("prescribed tablet daily")
    _reject_if_sensitive("en-IN")
    _reject_if_sensitive("BANER")


def test_purge_route_declared() -> None:
    paths = {getattr(route, "path", "") for route in router.routes}
    assert any(path.endswith("/purge") for path in paths)
    assert any(path.rstrip("/").endswith("/{key}") or "/{key}" in path for path in paths)


def test_purge_audit_marks_not_clinical_evidence() -> None:
    source = inspect.getsource(purge_memory)
    assert "not_clinical_evidence" in source
    assert "memory.purged" in source


def _context(subject: str = "patient-memory-test") -> AuthContext:
    return AuthContext(
        subject=subject,
        roles=(Role.PATIENT.value,),
        primary_role=Role.PATIENT,
        patient_id=uuid.uuid4(),
        clinic_ids=(),
        locale="en-IN",
        traffic_class="synthetic",
        token_id=None,
    )


class _Features:
    def enabled(self, key: str) -> bool:
        return key == "memory_preferences"


class _FakeSession:
    def __init__(self, rows: list[MemoryPreference] | None = None) -> None:
        self.rows = list(rows or [])
        self.deleted: list[Any] = []
        self.added: list[Any] = []
        self.committed = False

    async def scalars(self, _statement: Any) -> list[MemoryPreference]:
        return list(self.rows)

    async def scalar(self, _statement: Any) -> MemoryPreference | None:
        return self.rows[0] if self.rows else None

    async def delete(self, row: Any) -> None:
        self.deleted.append(row)
        if row in self.rows:
            self.rows.remove(row)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "updated_at", None) is None:
            import datetime as dt

            obj.updated_at = dt.datetime.now(dt.UTC)


@pytest.mark.asyncio
async def test_purge_writes_not_clinical_evidence_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    row = MemoryPreference(subject="patient-memory-test", key="preferred_clinic", value="Baner")
    row.id = uuid.uuid4()
    session = _FakeSession([row])
    audits: list[dict[str, Any]] = []

    class _Audit:
        def __init__(self, _session: Any) -> None:
            pass

        def append(self, **kwargs: Any) -> None:
            audits.append(kwargs)

    import app.modules.memory.router as memory

    monkeypatch.setattr(memory, "AuditRepository", _Audit)

    async def _noop_sync(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(memory, "_sync_mem0_delete", _noop_sync)

    await purge_memory(
        context=_context(),
        services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert session.committed is True
    assert len(session.deleted) == 1
    assert len(audits) == 1
    assert audits[0]["action"] == "memory.purged"
    assert audits[0]["metadata"]["provenance"] == "not_clinical_evidence"
    assert audits[0]["metadata"]["count"] == 1


@pytest.mark.asyncio
async def test_upsert_rejects_clinical_value(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    import app.modules.memory.router as memory

    monkeypatch.setattr(
        memory,
        "AuditRepository",
        type(
            "A",
            (),
            {"__init__": lambda self, s: None, "append": lambda self, **k: None},
        ),
    )
    with pytest.raises(ProblemError) as exc:
        await upsert_memory(
            body=MemoryUpsert(key="preferred_clinic", value="insulin dose reminder"),
            context=_context(),
            services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )
    assert exc.value.code == "memory_value_rejected"
    assert session.committed is False


@pytest.mark.asyncio
async def test_opt_out_upsert_skips_mem0_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    audits: list[dict[str, Any]] = []
    add_calls: list[Any] = []

    class _Audit:
        def __init__(self, _session: Any) -> None:
            pass

        def append(self, **kwargs: Any) -> None:
            audits.append(kwargs)

    import app.modules.memory.router as memory
    from app.core.config import Settings
    from app.modules.memory.router import _sync_mem0_add

    monkeypatch.setattr(memory, "AuditRepository", _Audit)

    class _Mem0:
        configured = True

        async def add(self, **kwargs: Any) -> dict[str, Any]:
            add_calls.append(kwargs)
            return {}

    monkeypatch.setattr(memory, "Mem0Client", lambda _settings: _Mem0())

    out = await upsert_memory(
        body=MemoryUpsert(key="opt_out", value="true"),
        context=_context(),
        services=SimpleNamespace(
            features=_Features(),
            settings=Settings(_env_file=None, app_env="test", mem0_url="http://mem0:8000"),
        ),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert out.key == "opt_out"
    assert out.value == "true"
    assert session.committed is True
    assert audits[0]["action"] == "memory.upserted"
    # Even when Mem0 is configured, opt_out must not sync clinical-adjacent vectors.
    await _sync_mem0_add(
        SimpleNamespace(settings=Settings(_env_file=None, app_env="test", mem0_url="http://mem0:8000")),
        subject="patient-memory-test",
        key="opt_out",
        value="true",
    )
    assert add_calls == []


@pytest.mark.asyncio
async def test_forget_delete_audits_key(monkeypatch: pytest.MonkeyPatch) -> None:
    row = MemoryPreference(subject="patient-memory-test", key="ui_density", value="compact")
    row.id = uuid.uuid4()
    session = _FakeSession([row])
    audits: list[dict[str, Any]] = []

    class _Audit:
        def __init__(self, _session: Any) -> None:
            pass

        def append(self, **kwargs: Any) -> None:
            audits.append(kwargs)

    import app.modules.memory.router as memory

    monkeypatch.setattr(memory, "AuditRepository", _Audit)

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(memory, "_sync_mem0_delete", _noop)

    await delete_memory(
        key="ui_density",
        context=_context(),
        services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert len(session.deleted) == 1
    assert audits[0]["action"] == "memory.deleted"
    assert audits[0]["resource_id"] == "ui_density"
