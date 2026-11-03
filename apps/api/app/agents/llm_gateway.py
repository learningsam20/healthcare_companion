"""LiteLLM client. Product code asks for a purpose, never a provider model.

Identified content must never take an external route. Any external alias is gated by the
local composite PII service; a gate that is unreachable, reports a fallback engine or
finds residual identifiers forces the purpose's local fallback. That is a deliberate
fail-closed state, not a missing feature flag.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.agents.pii_gate import PiiGate, PiiGateResult
from app.core.config import Settings
from app.core.tracing import content_digest, trace_span

LOCAL_PROVIDERS = {"ollama", "local"}
MESSAGE_SEPARATOR = "\n\u241e\n"


class LlmGatewayError(RuntimeError):
    pass


class ExternalEgressBlocked(LlmGatewayError):
    pass


@dataclass(frozen=True, slots=True)
class LlmResult:
    content: str
    model_alias: str
    prompt_tokens: int
    completion_tokens: int
    gateway_request_id: str | None = None


def _external(alias_config: dict[str, Any]) -> bool:
    return str(alias_config.get("provider", "")).lower() not in LOCAL_PROVIDERS


@dataclass(frozen=True, slots=True)
class _Route:
    alias_name: str
    purpose_config: dict[str, Any]
    alias_config: dict[str, Any]
    gate: PiiGateResult | None = None

    @property
    def external(self) -> bool:
        return _external(self.alias_config)


class LlmGateway:
    def __init__(
        self,
        settings: Settings,
        models_config: dict[str, Any],
        *,
        pii_gate: PiiGate | None = None,
    ) -> None:
        self._settings = settings
        self._purposes = models_config.get("purposes", {})
        self._aliases = models_config.get("aliases", {})
        self._language_routing = models_config.get("language_routing", {}) or {}
        self._pii_gate = pii_gate or PiiGate(settings)

    def resolve(
        self, purpose: str, *, language: str | None = None
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        try:
            purpose_config = self._purposes[purpose]
        except KeyError as exc:
            raise LlmGatewayError(f"unknown model purpose {purpose}") from exc
        alias_name = purpose_config["primary"]
        lang = (language or "").strip().lower().replace("_", "-")
        if lang:
            primary = lang.split("-", 1)[0]
            override = (self._language_routing.get(purpose) or {}).get(primary) or {}
            if isinstance(override, dict) and override.get("primary"):
                alias_name = str(override["primary"])
        try:
            alias_config = self._aliases[alias_name]
        except KeyError as exc:
            raise LlmGatewayError(f"alias {alias_name} is not defined") from exc
        return alias_name, purpose_config, alias_config

    def _local_fallback(self, purpose_config: dict[str, Any]) -> _Route | None:
        fallback_name = purpose_config.get("fallback")
        if not fallback_name:
            return None
        try:
            fallback_config = self._aliases[fallback_name]
        except KeyError as exc:
            raise LlmGatewayError(f"fallback alias {fallback_name} is not defined") from exc
        if _external(fallback_config):
            return None
        return _Route(fallback_name, purpose_config, fallback_config)

    async def _route(self, purpose: str, text: str, *, language: str | None = None) -> _Route:
        alias_name, purpose_config, alias_config = self.resolve(purpose, language=language)
        if not _external(alias_config):
            return _Route(alias_name, purpose_config, alias_config)
        fallback = self._local_fallback(purpose_config)
        if not self._settings.external_egress_enabled:
            if fallback is None:
                raise ExternalEgressBlocked(
                    f"purpose {purpose} requires external egress and has no local fallback"
                )
            return fallback
        gate = await self._pii_gate.redact(text, trace_id="-")
        if not gate.healthy:
            if fallback is None:
                raise ExternalEgressBlocked(
                    f"purpose {purpose} external gate refused: {gate.reason}"
                )
            return _Route(fallback.alias_name, fallback.purpose_config, fallback.alias_config, gate)
        return _Route(alias_name, purpose_config, alias_config, gate)

    @staticmethod
    def _redacted_messages(
        messages: list[dict[str, str]], gate: PiiGateResult
    ) -> list[dict[str, str]] | None:
        redacted = gate.redacted_text
        pieces = redacted.split(MESSAGE_SEPARATOR)
        if len(pieces) != len(messages):
            return None
        return [
            {**message, "content": piece} for message, piece in zip(messages, pieces, strict=True)
        ]

    async def _attach_redacted_io(
        self,
        attributes: dict[str, Any],
        *,
        messages: list[dict[str, str]],
        content: str,
        trace_id: str | None,
    ) -> None:
        if not getattr(self._settings, "langfuse_redacted_io", False):
            return
        joined = "\n".join(f"{m.get('role', '')}: {m.get('content', '')}" for m in messages)[
            :12000
        ]
        tid = (trace_id or "-")[:64]
        try:
            in_gate = await self._pii_gate.redact(joined, trace_id=tid)
            out_gate = await self._pii_gate.redact(str(content or "")[:8000], trace_id=tid)
        except Exception:  # noqa: BLE001 - never fail the turn for telemetry
            return
        if in_gate.healthy and in_gate.redacted_text:
            attributes["redacted_input"] = in_gate.redacted_text[:12000]
        if out_gate.healthy and out_gate.redacted_text:
            attributes["redacted_output"] = out_gate.redacted_text[:8000]

    async def complete(
        self,
        *,
        purpose: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.2,
        trace_id: str | None = None,
        language: str | None = None,
    ) -> LlmResult:
        if not self._settings.litellm_base_url or not self._settings.litellm_master_key:
            raise LlmGatewayError("LiteLLM is not configured")
        joined = MESSAGE_SEPARATOR.join(str(message.get("content", "")) for message in messages)
        with trace_span("pii.pregate", {"purpose": purpose, "message_count": len(messages)}):
            route = await self._route(purpose, joined, language=language)
        if route.alias_config.get("kind") != "chat":
            raise LlmGatewayError(f"alias {route.alias_name} is not a chat model")
        outbound = messages
        gate_used = False
        if route.external and route.gate is not None and route.gate.healthy:
            redacted = self._redacted_messages(messages, route.gate)
            if redacted is None:
                fallback = self._local_fallback(route.purpose_config)
                if fallback is None:
                    raise ExternalEgressBlocked(
                        f"purpose {purpose} could not be de-identified for external egress"
                    )
                route = fallback
            else:
                outbound = redacted
                gate_used = True
        max_output = int(max_tokens or route.alias_config.get("max_output_tokens", 800))
        payload = {
            "model": route.alias_name,
            "messages": outbound,
            "temperature": temperature,
            "max_tokens": max_output,
            "stream": False,
            "metadata": {
                "trace_id": trace_id or "",
                "purpose": purpose,
                "tags": [
                    "sahyog",
                    purpose,
                    "external" if route.external else "local",
                ],
                "content_digest": content_digest(
                    "\n".join(str(message.get("content", "")) for message in outbound)
                )
                or "",
            },
        }
        headers = {
            "Authorization": f"Bearer {self._settings.litellm_master_key}",
            "Content-Type": "application/json",
        }
        attributes = {
            "purpose": purpose,
            "model_alias": route.alias_name,
            "provider": str(route.alias_config.get("provider", "")),
            "message_count": len(messages),
            "max_tokens": max_output,
            "temperature": float(temperature),
            "deidentified": gate_used,
            "gate_reason": route.gate.reason if route.gate is not None else "",
        }
        timeout = float(route.purpose_config.get("timeout_seconds", 30))
        with trace_span("llm.complete", attributes, kind="generation"):
            data: dict[str, Any] | None = None
            request_id: str | None = None
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self._settings.litellm_base_url.rstrip('/')}/v1/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()
                request_id = (
                    str((data or {}).get("id") or "")
                    or response.headers.get("x-litellm-call-id")
                    or response.headers.get("x-request-id")
                ) or None
            except httpx.HTTPError as exc:
                if route.external or not self._settings.ollama_base_url:
                    raise LlmGatewayError("model gateway unavailable") from exc
                # LiteLLM down — fall through to local Ollama for local aliases.
                data, request_id = await self._complete_ollama(
                    route=route,
                    messages=outbound,
                    max_tokens=max_output,
                    temperature=temperature,
                    timeout=timeout,
                )
                attributes["provider"] = "ollama_direct"
            try:
                content = (data or {})["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LlmGatewayError("model gateway returned an invalid response") from exc
            usage = (data or {}).get("usage", {}) if isinstance(data, dict) else {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            attributes["prompt_tokens"] = prompt_tokens
            attributes["completion_tokens"] = completion_tokens
            attributes["gateway_request_id"] = request_id or ""
            await self._attach_redacted_io(
                attributes,
                messages=outbound,
                content=str(content),
                trace_id=trace_id,
            )
        return LlmResult(
            content=str(content),
            model_alias=route.alias_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            gateway_request_id=request_id,
        )

    async def _complete_ollama(
        self,
        *,
        route: _Route,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> tuple[dict[str, Any], str | None]:
        """OpenAI-compatible chat against a local Ollama when LiteLLM is down."""
        model = str(route.alias_config.get("model") or "").strip()
        if not model:
            raise LlmGatewayError("ollama model missing for local alias")
        base = self._settings.ollama_base_url.rstrip("/")
        # Prefer host loopback when Docker DNS leaked into host-local runs.
        if "host.docker.internal" in base:
            base = "http://127.0.0.1:11434"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{base}/v1/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LlmGatewayError("model gateway unavailable") from exc
        if not isinstance(data, dict):
            raise LlmGatewayError("ollama returned an invalid response")
        return data, str(data.get("id") or "") or None

    async def stream(
        self,
        *,
        purpose: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.2,
        trace_id: str | None = None,
        language: str | None = None,
    ) -> AsyncIterator[str | LlmResult]:
        """Yield token deltas (str), then a final LlmResult. PII gate runs before first token (G-47)."""
        if not self._settings.litellm_base_url or not self._settings.litellm_master_key:
            raise LlmGatewayError("LiteLLM is not configured")
        joined = MESSAGE_SEPARATOR.join(str(message.get("content", "")) for message in messages)
        with trace_span("pii.pregate", {"purpose": purpose, "message_count": len(messages)}):
            route = await self._route(purpose, joined, language=language)
        if route.alias_config.get("kind") != "chat":
            raise LlmGatewayError(f"alias {route.alias_name} is not a chat model")
        outbound = messages
        gate_used = False
        if route.external and route.gate is not None and route.gate.healthy:
            redacted = self._redacted_messages(messages, route.gate)
            if redacted is None:
                fallback = self._local_fallback(route.purpose_config)
                if fallback is None:
                    raise ExternalEgressBlocked(
                        f"purpose {purpose} could not be de-identified for external egress"
                    )
                route = fallback
            else:
                outbound = redacted
                gate_used = True
        max_output = int(max_tokens or route.alias_config.get("max_output_tokens", 800))
        payload = {
            "model": route.alias_name,
            "messages": outbound,
            "temperature": temperature,
            "max_tokens": max_output,
            "stream": True,
            "stream_options": {"include_usage": True},
            "metadata": {
                "trace_id": trace_id or "",
                "purpose": purpose,
                "tags": [
                    "sahyog",
                    purpose,
                    "external" if route.external else "local",
                    "stream",
                ],
                "content_digest": content_digest(
                    "\n".join(str(message.get("content", "")) for message in outbound)
                )
                or "",
            },
        }
        headers = {
            "Authorization": f"Bearer {self._settings.litellm_master_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        attributes = {
            "purpose": purpose,
            "model_alias": route.alias_name,
            "provider": str(route.alias_config.get("provider", "")),
            "message_count": len(messages),
            "max_tokens": max_output,
            "temperature": float(temperature),
            "deidentified": gate_used,
            "streaming": True,
        }
        pieces: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        request_id: str | None = None
        with trace_span("llm.stream", attributes, kind="generation"):
            try:
                timeout = float(route.purpose_config.get("timeout_seconds", 60))
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{self._settings.litellm_base_url.rstrip('/')}/v1/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        response.raise_for_status()
                        request_id = (
                            response.headers.get("x-litellm-call-id")
                            or response.headers.get("x-request-id")
                        )
                        async for line in response.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if not data or data == "[DONE]":
                                continue
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if not request_id and isinstance(chunk, dict) and chunk.get("id"):
                                request_id = str(chunk["id"])
                            usage = chunk.get("usage") if isinstance(chunk, dict) else None
                            if isinstance(usage, dict):
                                prompt_tokens = int(usage.get("prompt_tokens", 0) or prompt_tokens)
                                completion_tokens = int(
                                    usage.get("completion_tokens", 0) or completion_tokens
                                )
                            try:
                                delta = chunk["choices"][0].get("delta") or {}
                                piece = delta.get("content")
                            except (KeyError, IndexError, TypeError, AttributeError):
                                continue
                            if piece:
                                pieces.append(str(piece))
                                yield str(piece)
            except httpx.HTTPError as exc:
                raise LlmGatewayError("model gateway unavailable") from exc
            content = "".join(pieces)
            if not completion_tokens and content:
                completion_tokens = max(1, len(content.split()))
            attributes["prompt_tokens"] = prompt_tokens
            attributes["completion_tokens"] = completion_tokens
            attributes["gateway_request_id"] = request_id or ""
            await self._attach_redacted_io(
                attributes,
                messages=outbound,
                content=content,
                trace_id=trace_id,
            )
        yield LlmResult(
            content=content,
            model_alias=route.alias_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            gateway_request_id=request_id,
        )

    async def embed(self, *, texts: list[str], purpose: str = "embedding") -> list[list[float]]:
        if not texts:
            return []
        if not self._settings.litellm_base_url or not self._settings.litellm_master_key:
            raise LlmGatewayError("LiteLLM is not configured")
        alias_name, purpose_config, alias_config = self.resolve(purpose)
        if alias_config.get("kind") != "embedding":
            raise LlmGatewayError(f"alias {alias_name} is not an embedding model")
        outbound = texts
        deidentified = False
        if _external(alias_config):
            gate = await self._pii_gate.redact(MESSAGE_SEPARATOR.join(texts), trace_id="-")
            if not gate.healthy:
                raise ExternalEgressBlocked(
                    f"embedding purpose {purpose} external gate refused: {gate.reason}"
                )
            pieces = gate.redacted_text.split(MESSAGE_SEPARATOR)
            if len(pieces) != len(texts):
                raise ExternalEgressBlocked(
                    f"embedding purpose {purpose} de-identification changed the batch shape"
                )
            outbound = pieces
            deidentified = True
        dimensions = int(alias_config.get("dimensions", 1024))
        headers = {
            "Authorization": f"Bearer {self._settings.litellm_master_key}",
            "Content-Type": "application/json",
        }
        attributes = {
            "purpose": purpose,
            "model_alias": alias_name,
            "batch_size": len(texts),
            "dimensions": dimensions,
            "deidentified": deidentified,
        }
        with trace_span("llm.embed", attributes, kind="generation"):
            try:
                async with httpx.AsyncClient(
                    timeout=float(purpose_config.get("timeout_seconds", 30))
                ) as client:
                    response = await client.post(
                        f"{self._settings.litellm_base_url.rstrip('/')}/v1/embeddings",
                        json={
                            "model": alias_name,
                            "input": outbound,
                            "metadata": {"purpose": purpose, "tags": ["sahyog", purpose]},
                        },
                        headers=headers,
                    )
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPError as exc:
                raise LlmGatewayError("embedding gateway unavailable") from exc
            usage = data.get("usage", {}) if isinstance(data, dict) else {}
            attributes["prompt_tokens"] = int(usage.get("prompt_tokens", 0) or 0)
            attributes["completion_tokens"] = 0
        try:
            rows = sorted(data["data"], key=lambda item: item["index"])
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LlmGatewayError("embedding gateway returned an invalid response") from exc
        if len(vectors) != len(texts) or any(len(vector) != dimensions for vector in vectors):
            raise LlmGatewayError("embedding response does not match the configured shape")
        return vectors
