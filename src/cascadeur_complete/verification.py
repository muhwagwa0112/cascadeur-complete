from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .atomic_queue import atomic_write_json, read_json
from .product_catalog import PRODUCT_CATALOG, ProductFeature

EVIDENCE_SCHEMA_VERSION = 2


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _observed_postconditions(
    evidence: Iterable[dict[str, Any]], observed: Mapping[str, bool] | Iterable[str] | None
) -> set[str]:
    if isinstance(observed, Mapping):
        satisfied = {name for name, ok in observed.items() if ok is True}
    else:
        satisfied = set(observed or ())
    for item in evidence:
        if item.get("ok") is not True:
            continue
        postcondition = item.get("postcondition")
        if isinstance(postcondition, str):
            satisfied.add(postcondition)
        kind = item.get("kind")
        detail = item.get("detail")
        if kind == "postcondition" and isinstance(detail, str):
            satisfied.add(detail)
        elif isinstance(kind, str):
            satisfied.add(kind)
    return satisfied


class LiveEvidenceStore:
    """Append-only, binding-aware evidence for exact product postconditions."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"schema_version": EVIDENCE_SCHEMA_VERSION, "records": []}

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._empty()
        try:
            payload = read_json(self.path)
        except (OSError, ValueError):
            return self._empty()
        if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION or not isinstance(payload.get("records"), list):
            # V1 entries did not bind source/tests/fixtures or prove postconditions.
            return self._empty()
        return payload

    @staticmethod
    def _binding(
        feature: ProductFeature,
        *,
        version: str,
        license_name: str,
        dependencies: Mapping[str, Any],
    ) -> dict[str, Any]:
        binding = {
            "product_version": PRODUCT_CATALOG.product_version,
            "cascadeur_version": version,
            "license": license_name.strip().lower(),
            "dependencies": dict(sorted(dependencies.items())),
            **feature.binding_hashes(),
        }
        binding["fingerprint"] = _fingerprint(binding)
        return binding

    @staticmethod
    def _record_is_current(
        record: dict[str, Any],
        feature: ProductFeature,
        *,
        version: str,
        license_name: str | None,
        dependencies: Mapping[str, Any] | None,
    ) -> bool:
        if record.get("feature_id") != feature.id or record.get("valid") is not True:
            return False
        recorded_binding = record.get("binding")
        if not isinstance(recorded_binding, dict):
            return False
        recorded_license = str(recorded_binding.get("license", ""))
        recorded_dependencies = recorded_binding.get("dependencies")
        if not isinstance(recorded_dependencies, dict):
            return False
        if license_name is not None and recorded_license != license_name.strip().lower():
            return False
        if dependencies is not None and recorded_dependencies != dict(sorted(dependencies.items())):
            return False
        expected = LiveEvidenceStore._binding(
            feature,
            version=version,
            license_name=recorded_license,
            dependencies=recorded_dependencies,
        )
        if recorded_binding != expected:
            return False
        required = set(feature.postconditions)
        observed = set(record.get("observed_postconditions", ()))
        return bool(required) and required <= observed

    def verified_features(
        self,
        version: str,
        *,
        license_name: str | None = None,
        dependencies: Mapping[str, Any] | None = None,
    ) -> set[str]:
        payload = self._load()
        catalog = PRODUCT_CATALOG.by_id
        verified: set[str] = set()
        for record in payload["records"]:
            if not isinstance(record, dict):
                continue
            feature = catalog.get(str(record.get("feature_id", "")))
            if feature and self._record_is_current(
                record,
                feature,
                version=version,
                license_name=license_name,
                dependencies=dependencies,
            ):
                verified.add(feature.id)
        return verified

    def record(
        self,
        feature_id: str,
        *,
        version: str,
        adapter_id: str,
        operation: str,
        scene_id: str | None,
        evidence: list[dict[str, Any]],
        license_name: str = "unknown",
        dependencies: Mapping[str, Any] | None = None,
        observed_postconditions: Mapping[str, bool] | Iterable[str] | None = None,
        fixture_id: str | None = None,
        test_id: str | None = None,
    ) -> dict[str, Any]:
        feature = PRODUCT_CATALOG.by_id.get(feature_id)
        if feature is None:
            raise ValueError(f"Unknown product feature: {feature_id}")
        dependency_state = dict(dependencies or {})
        binding = self._binding(
            feature,
            version=version,
            license_name=license_name,
            dependencies=dependency_state,
        )
        observed = _observed_postconditions(evidence, observed_postconditions)
        required = set(feature.postconditions)
        identities_match = (
            feature.adapter_id == adapter_id
            and feature.fixture_id is not None
            and feature.fixture_id == fixture_id
            and feature.live_test_id is not None
            and feature.live_test_id == test_id
        )
        context_complete = license_name.strip().lower() not in {"", "unknown"}
        if feature.license == "pro":
            context_complete = context_complete and license_name.strip().lower() in {"pro", "indie", "teams"}
        if feature.dependency:
            context_complete = context_complete and dependency_state.get(feature.dependency) is True
        valid = bool(required) and required <= observed and identities_match and context_complete
        record = {
            "record_id": hashlib.sha256(
                f"{feature_id}\0{time.time_ns()}\0{binding['fingerprint']}".encode()
            ).hexdigest(),
            "feature_id": feature_id,
            "adapter_id": adapter_id,
            "operation": operation,
            "scene_id": scene_id,
            "evidence": evidence,
            "required_postconditions": sorted(required),
            "observed_postconditions": sorted(observed),
            "fixture_id": fixture_id,
            "test_id": test_id,
            "binding": binding,
            "valid": valid,
            "verified_at": time.time(),
        }
        with self._lock:
            payload = self._load()
            payload["records"].append(record)
            atomic_write_json(self.path, payload)
        return record
