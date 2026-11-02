"""Typed feature registry with environment precedence and locked safety flags.

Precedence: FEATURE_<KEY> process env > the provided environment mapping > YAML default.
Unknown FEATURE_* variables, invalid booleans, expired flags, duplicate keys, unsafe
locked defaults and attempts to disable a locked flag all fail validation.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class FeatureFlagError(ValueError):
    """Configuration is not a valid feature registry or flag value."""


class FlagClass(StrEnum):
    RUNTIME = "runtime"
    STARTUP = "startup"
    LOCKED = "locked"


class FlagDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    default: bool
    flag_class: FlagClass = Field(alias="class")
    environments: tuple[str, ...]
    owner: str = Field(min_length=1)
    expires: dt.date | None = None
    description: str = Field(min_length=1)

    @field_validator("key")
    @classmethod
    def _key_shape(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError("flag key must be lower_snake_case")
        return value

    @field_validator("environments")
    @classmethod
    def _environments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        allowed = {"dev", "staging", "production"}
        if not value or not set(value) <= allowed:
            raise ValueError(
                "flag environments must be a non-empty subset of dev/staging/production"
            )
        return value


class FlagRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    flags: tuple[FlagDefinition, ...]

    @field_validator("flags")
    @classmethod
    def _unique(cls, value: tuple[FlagDefinition, ...]) -> tuple[FlagDefinition, ...]:
        keys = [flag.key for flag in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate feature flag key")
        return value


@dataclass(frozen=True, slots=True)
class EffectiveFlag:
    key: str
    value: bool
    source: str
    flag_class: FlagClass
    owner: str
    expires: dt.date | None


def load_registry(path: str | Path) -> FlagRegistry:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        registry = FlagRegistry.model_validate(raw)
    except ValueError as exc:
        raise FeatureFlagError(f"invalid feature registry: {exc}") from exc
    for flag in registry.flags:
        if flag.flag_class is FlagClass.LOCKED and not flag.default:
            raise FeatureFlagError(f"locked flag {flag.key} must default to true")
    return registry


def _parse_bool(name: str, raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise FeatureFlagError(f"{name} must be a boolean, got {raw!r}")


def resolve_flags(
    registry: FlagRegistry,
    *,
    environ: Mapping[str, str] | None = None,
    app_env: str | None = None,
    today: dt.date | None = None,
) -> dict[str, EffectiveFlag]:
    env = os.environ if environ is None else environ
    environment = app_env or env.get("APP_ENV", "dev")
    if environment not in {"dev", "staging", "production"}:
        raise FeatureFlagError(f"unsupported APP_ENV {environment!r}")
    current_date = today or dt.date.today()
    known = {flag.key for flag in registry.flags}
    supplied = {
        name.removeprefix("FEATURE_").lower(): name for name in env if name.startswith("FEATURE_")
    }
    unknown = set(supplied) - known
    if unknown:
        raise FeatureFlagError(f"unknown feature flags: {', '.join(sorted(unknown))}")

    effective: dict[str, EffectiveFlag] = {}
    for flag in registry.flags:
        if flag.expires and flag.expires < current_date:
            raise FeatureFlagError(f"feature flag {flag.key} expired on {flag.expires.isoformat()}")
        if environment not in flag.environments:
            effective[flag.key] = EffectiveFlag(
                key=flag.key,
                value=False,
                source="not_applicable",
                flag_class=flag.flag_class,
                owner=flag.owner,
                expires=flag.expires,
            )
            continue
        env_name = f"FEATURE_{flag.key.upper()}"
        if env_name not in env:
            effective[flag.key] = EffectiveFlag(
                key=flag.key,
                value=flag.default,
                source="config",
                flag_class=flag.flag_class,
                owner=flag.owner,
                expires=flag.expires,
            )
            continue
        value = _parse_bool(env_name, env[env_name])
        if flag.flag_class is FlagClass.LOCKED and not value:
            raise FeatureFlagError(f"locked safety flag {flag.key} cannot be disabled")
        effective[flag.key] = EffectiveFlag(
            key=flag.key,
            value=value,
            source="env",
            flag_class=flag.flag_class,
            owner=flag.owner,
            expires=flag.expires,
        )
    return effective


def public_flags(flags: Mapping[str, EffectiveFlag]) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "value": flag.value,
            "source": flag.source,
            "class": flag.flag_class.value,
            "owner": flag.owner,
            "expires": flag.expires.isoformat() if flag.expires else None,
        }
        for key, flag in sorted(flags.items())
    }
