"""Client for the local PII gate.

The gateway treats the gate as mandatory for any external route. A detector that is
unreachable, reports a fallback engine or finds residual identifiers after redaction
blocks egress. No text is logged or retained here.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sahyog_common.context import ExecutionContext, Role, sign_context

from app.core.config import Settings


class PiiGateUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PiiGateResult:
    healthy: bool
    engine: str
    not_clinical_grade: bool
    count: int
    redacted_text: str
    reason: str | None = None


class PiiGate:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return bool(self._settings.pii_service_url and self._settings.mcp_context_secret)

    def _context(self, trace_id: str) -> ExecutionContext:
        now = int(dt.datetime.now(dt.UTC).timestamp())
        return ExecutionContext(
            actor_subject="system:pii_gate",
            actor_role=Role.SERVICE,
            patient_id=None,
            clinic_ids=(),
            trace_id=trace_id[:64],
            locale="en-IN",
            traffic_class="real",
            issued_at=now,
            expires_at=now + min(self._settings.mcp_context_ttl_seconds, 90),
        )

    async def _call(
        self, tool: str, text: str, trace_id: str, *, timeout_seconds: float
    ) -> dict[str, Any]:
        if not self.configured:
            raise PiiGateUnavailable("pii_gate_unconfigured")
        token = sign_context(self._context(trace_id), self._settings.mcp_context_secret)
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{self._settings.pii_service_url.rstrip('/')}/tools/{tool}",
                    json={"text": text},
                    headers={
                        "X-Sahyog-Context": token,
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise PiiGateUnavailable("pii_gate_unreachable") from exc
        if response.status_code >= 400:
            raise PiiGateUnavailable(f"pii_gate_http_{response.status_code}")
        try:
            payload = response.json()
            result = payload["result"]
        except (KeyError, TypeError, ValueError) as exc:
            raise PiiGateUnavailable("pii_gate_invalid_response") from exc
        if not isinstance(result, dict):
            raise PiiGateUnavailable("pii_gate_invalid_response")
        return result

    async def redact(self, text: str, *, trace_id: str) -> PiiGateResult:
        if not text.strip():
            return PiiGateResult(
                healthy=True,
                engine="not_needed",
                not_clinical_grade=False,
                count=0,
                redacted_text=text,
            )
        timeout = float(self._settings.pii_gate_timeout_seconds)
        try:
            redacted = await self._call("redact", text, trace_id, timeout_seconds=timeout)
            residual = await self._call(
                "detect",
                str(redacted.get("redacted_text", "")),
                trace_id,
                timeout_seconds=timeout,
            )
        except PiiGateUnavailable as exc:
            return PiiGateResult(
                healthy=False,
                engine="unavailable",
                not_clinical_grade=True,
                count=0,
                redacted_text="",
                reason=str(exc),
            )
        engine = str(redacted.get("engine", "unknown"))
        not_clinical_grade = bool(redacted.get("not_clinical_grade", True))
        residual_count = int(residual.get("count", 0) or 0)
        healthy = (
            engine == "composite"
            and not not_clinical_grade
            and residual_count == 0
            and isinstance(redacted.get("redacted_text"), str)
        )
        reason = None
        if engine != "composite":
            reason = "composite_engine_not_available"
        elif not_clinical_grade:
            reason = "engine_not_clinical_grade"
        elif residual_count:
            reason = "residual_identifiers_after_redaction"
        return PiiGateResult(
            healthy=healthy,
            engine=engine,
            not_clinical_grade=not_clinical_grade,
            count=int(redacted.get("count", 0) or 0),
            redacted_text=str(redacted.get("redacted_text", "")),
            reason=reason,
        )

    async def health(self) -> dict[str, Any]:
        if not self.configured:
            return {"status": "unconfigured", "composite_ready": False}
        try:
            result = await self._call(
                "detect", "no identifiers here", str(uuid.uuid4().hex), timeout_seconds=2.0
            )
        except PiiGateUnavailable as exc:
            return {"status": "down", "composite_ready": False, "reason": str(exc)}
        engine = str(result.get("engine", "unknown"))
        compatible = engine == "composite" and not bool(result.get("not_clinical_grade", True))
        return {"status": "up", "engine": engine, "composite_ready": compatible}
