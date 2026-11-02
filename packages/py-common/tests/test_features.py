from __future__ import annotations

import datetime as dt

import pytest
from sahyog_common.feature_flags import (
    FeatureFlagError,
    FlagClass,
    FlagDefinition,
    FlagRegistry,
    load_registry,
    public_flags,
    resolve_flags,
)


def _registry(*flags: FlagDefinition) -> FlagRegistry:
    return FlagRegistry(version=1, flags=flags)


def _flag(
    key: str, *, default: bool = True, flag_class: FlagClass = FlagClass.RUNTIME
) -> FlagDefinition:
    return FlagDefinition(
        key=key,
        default=default,
        **{"class": flag_class},
        environments=("dev", "staging", "production"),
        owner="product",
        description=f"Flag {key}",
    )


def test_yaml_registry_contains_locked_safety_flags() -> None:
    registry = load_registry("config/features.yaml")
    keys = {flag.key for flag in registry.flags}
    assert "chat_sessions" in keys
    assert "analytics_dashboard" in keys
    locked = {flag.key for flag in registry.flags if flag.flag_class is FlagClass.LOCKED}
    assert locked
    assert all(flag.default for flag in registry.flags if flag.flag_class is FlagClass.LOCKED)


def test_environment_overrides_default() -> None:
    registry = _registry(_flag("chat_sessions"))
    resolved = resolve_flags(registry, environ={"FEATURE_CHAT_SESSIONS": "false"}, app_env="dev")
    assert resolved["chat_sessions"].value is False
    assert resolved["chat_sessions"].source == "env"


def test_unknown_flag_fails_closed() -> None:
    registry = _registry(_flag("chat_sessions"))
    with pytest.raises(FeatureFlagError, match="unknown feature flags"):
        resolve_flags(registry, environ={"FEATURE_NOT_DECLARED": "true"}, app_env="dev")


def test_invalid_boolean_fails_closed() -> None:
    registry = _registry(_flag("chat_sessions"))
    with pytest.raises(FeatureFlagError, match="must be a boolean"):
        resolve_flags(registry, environ={"FEATURE_CHAT_SESSIONS": "maybe"}, app_env="dev")


def test_locked_flag_cannot_be_disabled() -> None:
    registry = _registry(_flag("safety_gate", flag_class=FlagClass.LOCKED))
    with pytest.raises(FeatureFlagError, match="cannot be disabled"):
        resolve_flags(registry, environ={"FEATURE_SAFETY_GATE": "0"}, app_env="dev")


def test_expired_flag_fails_closed() -> None:
    registry = _registry(_flag("temporary").model_copy(update={"expires": dt.date(2020, 1, 1)}))
    with pytest.raises(FeatureFlagError, match="expired"):
        resolve_flags(registry, environ={}, app_env="dev", today=dt.date(2026, 1, 1))


def test_flag_outside_environment_is_off() -> None:
    definition = _flag("staging_only").model_copy(update={"environments": ("staging",)})
    registry = _registry(definition)
    resolved = resolve_flags(registry, environ={}, app_env="production")
    assert resolved["staging_only"].value is False
    assert resolved["staging_only"].source == "not_applicable"


def test_public_payload_never_leaks_env_names() -> None:
    registry = _registry(_flag("chat_sessions"))
    payload = public_flags(resolve_flags(registry, environ={}, app_env="dev"))
    assert payload["chat_sessions"]["class"] == "runtime"
    assert set(payload["chat_sessions"]) == {"value", "source", "class", "owner", "expires"}


def test_duplicate_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _registry(_flag("chat_sessions"), _flag("chat_sessions"))
