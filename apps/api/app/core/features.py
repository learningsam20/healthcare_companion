from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sahyog_common.feature_flags import (
    EffectiveFlag,
    FeatureFlagError,
    FlagClass,
    load_registry,
    public_flags,
    resolve_flags,
)

from app.core.config import Settings


@dataclass
class FeatureStore:
    flags: dict[str, EffectiveFlag]

    @classmethod
    def from_settings(
        cls, settings: Settings, environ: dict[str, str] | None = None
    ) -> FeatureStore:
        registry = load_registry(settings.config_dir / "features.yaml")
        return cls(flags=resolve_flags(registry, environ=environ, app_env=settings.app_env))

    def enabled(self, key: str) -> bool:
        try:
            return self.flags[key].value
        except KeyError as exc:
            raise FeatureFlagError(f"unknown feature flag {key}") from exc

    def get(self, key: str) -> EffectiveFlag:
        try:
            return self.flags[key]
        except KeyError as exc:
            raise FeatureFlagError(f"unknown feature flag {key}") from exc

    def public(self) -> dict[str, dict[str, Any]]:
        return public_flags(self.flags)

    def set_runtime(self, key: str, value: bool) -> tuple[bool, bool]:
        flag = self.get(key)
        if flag.flag_class is not FlagClass.RUNTIME:
            raise FeatureFlagError(f"{key} is {flag.flag_class.value} and cannot change at runtime")
        old = flag.value
        self.flags[key] = EffectiveFlag(
            key=flag.key,
            value=value,
            source="runtime",
            flag_class=flag.flag_class,
            owner=flag.owner,
            expires=flag.expires,
        )
        return old, value
