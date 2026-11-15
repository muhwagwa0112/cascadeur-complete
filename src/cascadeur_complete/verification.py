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

EVIDENCE_SCHEMA_VERSION = 3


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _runtime_context_complete(context: Mapping[str, Any]) -> bool:
    # Installation presence or a local source-tree digest cannot stand in for
    # bytes actually loaded by the adapter. The runtime must supply this value.
    return (context.get("runtime_available") is True
            and _sha256(context.get("loaded_adapter_fingerprint"))
            and _sha256(context.get("adapter_settings_digest"))
            and isinstance(context.get("environment"), dict) and bool(context["environment"]))


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
            # V1/V2 did not bind actual source, test and fixture bytes. They are
            # readable historical data, never current schema-3 proof.
            migrated = self._empty()
            migrated["historical_payload"] = payload
            return migrated
        return payload

    @staticmethod
    def _binding(
        feature: ProductFeature,
        *,
        version: str,
        license_name: str,
        dependencies: Mapping[str, Any],
        runtime_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Normalize tuples before storage/comparison, so JSON roundtrips retain
        # precisely the same manifest representation.
        material = json.loads(_canonical(feature.binding_material()))
        binding = {
            "product_version": PRODUCT_CATALOG.product_version,
            "cascadeur_version": version,
            "license": license_name.strip().lower(),
            "dependencies": dict(sorted(dependencies.items())),
            **feature.binding_hashes(material),
            "byte_manifest": material,
            "byte_manifest_complete": feature.binding_complete(material),
            "runtime_context": dict(runtime_context or {}),
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
        runtime_context: Mapping[str, Any] | None = None,
    ) -> bool:
        if record.get("feature_id") != feature.id or record.get("valid") is not True:
            return False
        recorded_binding = record.get("binding")
        if not isinstance(recorded_binding, dict):
            return False
        if (runtime_context is None or not _runtime_context_complete(runtime_context)
                or recorded_binding.get("runtime_context") != dict(runtime_context)):
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
            runtime_context=recorded_binding.get("runtime_context"),
        )
        if recorded_binding != expected or not expected["byte_manifest_complete"]:
            return False
        context = expected["runtime_context"]
        if not _runtime_context_complete(context):
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
        runtime_context: Mapping[str, Any] | None = None,
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
                runtime_context=runtime_context,
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
        runtime_context: Mapping[str, Any] | None = None,
        evidence_grade: str = "execution_observed",
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
            runtime_context=runtime_context,
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
        if evidence_grade not in {"execution_observed", "quality_verified", "export_roundtrip_verified"}:
            raise ValueError("Unknown evidence grade")
        bound_runtime = dict(runtime_context or {})
        context_complete = context_complete and _runtime_context_complete(bound_runtime)
        if evidence_grade in {"quality_verified", "export_roundtrip_verified"}:
            context_complete = context_complete and all(_sha256(bound_runtime.get(key)) for key in (
                "capture_digest", "quality_policy_digest", "intent_digest"))
        if evidence_grade == "export_roundtrip_verified":
            context_complete = context_complete and all(_sha256(bound_runtime.get(key)) for key in (
                "export_profile_digest", "target_adapter_fingerprint", "sealed_artifact_digest"))
        valid = (bool(required) and required <= observed and identities_match and context_complete
                 and binding["byte_manifest_complete"])
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
            "evidence_grade": evidence_grade,
            "runtime_available": bound_runtime.get("runtime_available") is True,
            "implemented": feature.implementation_status == "implemented",
            "execution_observed": valid,
            "quality_verified": valid and evidence_grade in {"quality_verified", "export_roundtrip_verified"},
            "export_roundtrip_verified": valid and evidence_grade == "export_roundtrip_verified",
            "verified_at": time.time(),
        }
        with self._lock:
            payload = self._load()
            payload["records"].append(record)
            atomic_write_json(self.path, payload)
        return record
