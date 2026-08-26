from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

CATALOG_FILE_NAME = "product_features_2026_1_2.json"
SUPPORTED_BUILD = "2026.1.2.0.15343"


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ProductFeature:
    id: str
    family: str
    name: str
    source_url: str
    license: str
    dependency: str | None
    route: str | None
    action: str | None
    operation: str | None
    mutation: bool
    requires_scene: bool
    execution_mode: str
    implementation_status: str
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    adapter_id: str | None
    contract_test_ids: tuple[str, ...]
    live_test_id: str | None
    fixture_id: str | None
    since: str

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> ProductFeature:
        return cls(
            id=value["id"],
            family=value["family"],
            name=value["name"],
            source_url=value["source_url"],
            license=value.get("license", "any"),
            dependency=value.get("dependency"),
            route=value.get("route"),
            action=value.get("action"),
            operation=value.get("operation"),
            mutation=bool(value.get("mutation", False)),
            requires_scene=bool(value.get("requires_scene", True)),
            execution_mode=value.get("execution_mode", "Gated"),
            implementation_status=value.get("implementation_status", "not_implemented"),
            preconditions=tuple(value.get("preconditions", ())),
            postconditions=tuple(value.get("postconditions", ())),
            adapter_id=value.get("adapter_id"),
            contract_test_ids=tuple(value.get("contract_test_ids", ())),
            live_test_id=value.get("live_test_id"),
            fixture_id=value.get("fixture_id"),
            since=value.get("since", "2026.1"),
        )

    def binding_material(self) -> dict[str, Any]:
        """Return the implementation inputs whose changes invalidate live evidence."""
        return {
            "source": {"url": self.source_url, "since": self.since},
            "adapter": {
                "id": self.adapter_id,
                "route": self.route,
                "action": self.action,
                "operation": self.operation,
                "preconditions": self.preconditions,
                "postconditions": self.postconditions,
            },
            "tests": self.contract_test_ids + ((self.live_test_id,) if self.live_test_id else ()),
            "fixture": self.fixture_id,
        }

    def binding_hashes(self) -> dict[str, str]:
        material = self.binding_material()
        return {
            "source_hash": _canonical_hash(material["source"]),
            "adapter_hash": _canonical_hash(material["adapter"]),
            "test_hash": _canonical_hash(material["tests"]),
            "fixture_hash": _canonical_hash(material["fixture"]),
        }


@dataclass(frozen=True)
class ProductCatalog:
    schema_version: int
    product_version: str
    supported_build: str
    sources: tuple[str, ...]
    features: tuple[ProductFeature, ...]

    @property
    def by_id(self) -> dict[str, ProductFeature]:
        return {item.id: item for item in self.features}

    @property
    def core_features(self) -> tuple[ProductFeature, ...]:
        return tuple(item for item in self.features if not item.id.startswith("official_gap."))

    @property
    def official_gaps(self) -> tuple[ProductFeature, ...]:
        return tuple(item for item in self.features if item.id.startswith("official_gap."))


def default_catalog_path() -> Path:
    checkout_or_bundle = Path(__file__).resolve().parents[2] / "inventory" / CATALOG_FILE_NAME
    if checkout_or_bundle.is_file():
        return checkout_or_bundle
    packaged = files("cascadeur_complete").joinpath("data", CATALOG_FILE_NAME)
    return Path(str(packaged))


@lru_cache(maxsize=4)
def load_product_catalog(path: Path | None = None) -> ProductCatalog:
    catalog_path = (path or default_catalog_path()).resolve()
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported product feature catalog schema")
    if payload.get("product_version") != "2026.1.2":
        raise ValueError("Product feature catalog must be pinned to Cascadeur 2026.1.2")
    if payload.get("supported_build") != SUPPORTED_BUILD:
        raise ValueError(f"Product feature catalog build must be {SUPPORTED_BUILD}")
    features = tuple(ProductFeature.from_json(item) for item in payload.get("features", ()))
    ids = [item.id for item in features]
    if len(ids) != len(set(ids)):
        raise ValueError("Product feature catalog contains duplicate feature IDs")
    if not features:
        raise ValueError("Product feature catalog is empty")
    for item in features:
        if not item.source_url.startswith("https://cascadeur.com/"):
            raise ValueError(f"Feature {item.id} does not cite an official Cascadeur source")
        if item.implementation_status == "implemented" and not item.contract_test_ids:
            raise ValueError(f"Implemented feature {item.id} has no real contract test node")
        if item.implementation_status == "implemented" and (not item.route or not item.adapter_id):
            raise ValueError(f"Implemented feature {item.id} has no adapter binding")
    return ProductCatalog(
        schema_version=payload["schema_version"],
        product_version=payload["product_version"],
        supported_build=payload["supported_build"],
        sources=tuple(payload.get("sources", ())),
        features=features,
    )


PRODUCT_CATALOG = load_product_catalog()
