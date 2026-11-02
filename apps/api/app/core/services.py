from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sahyog_common.feature_flags import FlagRegistry, load_registry
from sahyog_common.files import load_yaml

from app.core.config import Settings, load_finops_model
from app.core.db import Database
from app.core.features import FeatureStore
from app.core.malware import MalwareScanner
from app.core.ports import FhirGateway, NotificationPort
from app.core.storage import DocumentStorage


@dataclass
class Services:
    settings: Settings
    db: Database
    features: FeatureStore
    storage: DocumentStorage
    app_config: dict[str, Any]
    models_config: dict[str, Any]
    finops_model: dict[str, Any]
    notifications_config: dict[str, Any]
    notification_copy: dict[str, Any]
    red_flags: dict[str, Any]
    prices: dict[str, Any]
    specialties: dict[str, Any]
    metrics: dict[str, Any]
    stock_config: dict[str, Any]
    feature_registry: FlagRegistry
    malware: MalwareScanner
    prompts: dict[str, dict[str, Any]] = field(default_factory=dict)
    notifications: NotificationPort | None = None
    fhir: FhirGateway | None = None
    checkpointer: Any | None = None
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    def purpose(self, name: str) -> dict[str, Any]:
        try:
            purpose: dict[str, Any] = self.models_config["purposes"][name]
            return purpose
        except KeyError as exc:
            raise KeyError(f"unknown model purpose {name}") from exc

    def alias(self, name: str) -> dict[str, Any]:
        try:
            alias: dict[str, Any] = self.models_config["aliases"][name]
            return alias
        except KeyError as exc:
            raise KeyError(f"unknown model alias {name}") from exc

    def prompt(self, name: str) -> dict[str, Any]:
        try:
            return self.prompts[name]
        except KeyError as exc:
            raise KeyError(f"unknown prompt {name}") from exc

    def specialty_codes(self) -> set[str]:
        return {item["code"] for item in self.specialties.get("specialties", [])}

    def specialty_label(self, code: str, locale: str = "en-IN") -> str:
        language = locale.split("-")[0]
        for item in self.specialties.get("specialties", []):
            if item["code"] == code:
                return str(item.get(language) or item.get("en") or code)
        return code

    def model_cost(self, alias: str, prompt_tokens: int, completion_tokens: int) -> float:
        prices = self.prices.get("models", {}).get(alias)
        if prices is None:
            alias_config = self.models_config.get("aliases", {}).get(alias, {})
            input_price = float(alias_config.get("input_price_usd_per_million", 0))
            output_price = float(alias_config.get("output_price_usd_per_million", 0))
        else:
            input_price = float(prices.get("input_per_million_usd", 0))
            output_price = float(prices.get("output_per_million_usd", 0))
        cost = (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
        return round(cost, 8)


def build_services(settings: Settings) -> Services:
    config_dir = settings.config_dir
    prompts = {
        path.stem: load_yaml(path) for path in sorted((config_dir / "prompts").glob("*.yaml"))
    }
    return Services(
        settings=settings,
        db=Database(settings),
        features=FeatureStore.from_settings(settings),
        storage=DocumentStorage(settings),
        app_config=settings.app_config(),
        models_config=settings.models_config(),
        finops_model=load_finops_model(config_dir),
        notifications_config=load_yaml(config_dir / "notifications.yaml"),
        notification_copy=load_yaml(config_dir / "i18n" / "notifications.yaml"),
        red_flags=load_yaml(config_dir / "red_flags.yaml"),
        prices=load_yaml(config_dir / "prices.yaml"),
        specialties=load_yaml(config_dir / "specialties.yaml"),
        metrics=load_yaml(config_dir / "metrics.yaml"),
        stock_config=load_yaml(config_dir / "stock.yaml"),
        feature_registry=load_registry(config_dir / "features.yaml"),
        malware=MalwareScanner(settings),
        prompts=prompts,
    )


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services
