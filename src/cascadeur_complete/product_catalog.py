from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

# The single pin for the Cascadeur build this package verifies against.
SUPPORTED_BUILD = "2026.1.3.0.15619"
PRODUCT_VERSION = ".".join(SUPPORTED_BUILD.split(".")[:3])
CATALOG_FILE_NAME = f"product_features_{PRODUCT_VERSION.replace('.', '_')}.json"

# Explicit dependency declarations, rather than a directory hash or metadata IDs.
# A missing file remains missing in the manifest and prevents evidence promotion.
_COMMON_IMPLEMENTATION = (
    "src/cascadeur_complete/product_catalog.py", "src/cascadeur_complete/adapter_bindings.py",
    "src/cascadeur_complete/feature_registry.py", "src/cascadeur_complete/service.py",
    "src/cascadeur_complete/models.py", "src/cascadeur_complete/verification.py",
    "src/cascadeur_complete/host_postconditions.py", "src/cascadeur_complete/bridge_client.py",
    "src/cascadeur_complete/safety.py", "src/cascadeur_complete/atomic_queue.py",
    "src/cascadeur_complete/live_validation.py",
    "src/cascadeur_complete/change_flow.py", "src/cascadeur_complete/ui_file_flow.py",
    "src/cascadeur_complete/uia.py", "src/cascadeur_complete/paths.py",
    "src/cascadeur_complete/request_ledger.py", "src/cascadeur_complete/state_lock.py",
    "src/cascadeur_complete/store_lock.py",
    "src/cascadeur_complete/effects.py", "src/cascadeur_complete/recovery.py",
    "src/cascadeur_complete/queue_auth.py", "src/cascadeur_complete/package_fingerprint.py",
    "cascadeur_side/cascadeur_complete/handler_registry.py",
    "cascadeur_side/cascadeur_complete/runtime.py", "cascadeur_side/cascadeur_complete/guarded_runtime.py",
    "cascadeur_side/cascadeur_complete/native_serialization.py",
    "cascadeur_side/cascadeur_complete/serialization_equivalence.py",
)
_HANDLERS = {name: name for name in (
    "animation", "behaviours", "editing", "files", "generation", "io", "layers", "mesh",
    "objects", "physics", "render", "rigging", "rig_prototypes", "scene", "system",
    "timeline", "timeline_edit", "view",
)}
_MOTION_DEPENDENCIES = tuple("src/cascadeur_complete/" + name + ".py" for name in (
    "motion_context", "motion_math", "motion_quality", "motion_solvers", "motion_geometry", "motion_cleanup",
    "capture", "retargeting", "motion_styling", "cleanup_workflow",
    "export_models", "export_workflow", "fbx_validation", "export_publisher", "external",
    "blender_export_adapter",
    "geometry_contract",
))
_FIXTURE_RELATIVE = {
    "fixture.sample.cube": "samples/Cube.casc", "fixture.sample.cascy": "samples/Cascy.casc",
    "fixture.sample.backflip": "samples/Backflip_animation.casc",
    "fixture.test.three_joints": "resources/scripts/test_data/casc/three_joints.casc",
    "fixture.rigmode.cascy": "samples/Cascy.casc", "fixture.rigmode.ue5": "samples/UE5_Manny.casc",
    "fixture.test.ded": "resources/scripts/test_data/casc/Ded.casc",
}


def _implementation_files(route: str | None) -> tuple[str, ...]:
    prefix = (route or "").split(".")[0]
    handler = _HANDLERS.get(prefix)
    result = _COMMON_IMPLEMENTATION + ((f"cascadeur_side/cascadeur_complete/handlers/{handler}.py",) if handler else ())
    if prefix in {"animation", "physics", "rigging", "io", "files", "motion", "export"}:
        result += _MOTION_DEPENDENCIES
    if route in {"system.observe_geometry_capture", "system.get_geometry_capture"}:
        result += _MOTION_DEPENDENCIES + ("cascadeur_side/cascadeur_complete/native_geometry_capture.py",
            "cascadeur_side/cascadeur_complete/geometry_policy.py", "cascadeur_side/cascadeur_complete/handlers/mesh.py")
    if route == "generation.unbaking":
        result += ("src/cascadeur_complete/unbaking_contract.py", "cascadeur_side/cascadeur_complete/native_unbaking.py")
    return result


def _file_manifest(names: tuple[str, ...]) -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[2]
    result = []
    for name in sorted(set(names)):
        path = Path(name)
        path = path if path.is_absolute() else root / path
        try:
            digest, count = hashlib.sha256(), 0
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    count += len(block)
                    digest.update(block)
            result.append({"path": name, "bytes": count, "sha256": digest.hexdigest()})
        except OSError:
            result.append({"path": name, "missing": True})
    return result


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
    arguments: tuple[tuple[str, str], ...] = ()
    fixed_arguments: tuple[tuple[str, Any], ...] = ()
    implementation_files: tuple[str, ...] = ()
    fixture_files: tuple[str, ...] = ()

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
            arguments=tuple(sorted((value.get("arguments") or {}).items())),
            fixed_arguments=tuple(sorted((value.get("fixed_arguments") or {}).items())),
            implementation_files=tuple(value.get("implementation_files", _implementation_files(value.get("route")))),
            fixture_files=tuple(value.get("fixture_files", ())),
        )

    def binding_material(self) -> dict[str, Any]:
        """Return the implementation inputs whose changes invalidate live evidence."""
        test_ids = self.contract_test_ids + ((self.live_test_id,) if self.live_test_id else ())
        fixture_files = self.fixture_files
        if not fixture_files and self.fixture_id in _FIXTURE_RELATIVE:
            fixture_files = (str(Path(os.environ.get("CASCADEUR_ROOT", r"C:\Program Files\Cascadeur")) / _FIXTURE_RELATIVE[self.fixture_id]),)
        if not fixture_files and self.fixture_id in {"fixture.none", "fixture.empty_scene"}:
            fixture_files = ("src/cascadeur_complete/live_validation.py",)
        return {
            "source": {"url": self.source_url, "since": self.since},
            "adapter": {
                "id": self.adapter_id,
                "route": self.route,
                "action": self.action,
                "operation": self.operation,
                "preconditions": self.preconditions,
                "postconditions": self.postconditions,
                "fixed_arguments": [list(item) for item in self.fixed_arguments],
            },
            "implementation_files": _file_manifest(self.implementation_files),
            "tests": {"ids": test_ids, "files": _file_manifest(tuple(node.split("::", 1)[0] for node in test_ids))},
            "fixture": {"id": self.fixture_id, "files": _file_manifest(fixture_files)},
        }

    def binding_hashes(self, material: dict[str, Any] | None = None) -> dict[str, str]:
        material = material or self.binding_material()
        return {
            "source_hash": _canonical_hash({"source": material["source"], "files": material["implementation_files"]}),
            "adapter_hash": _canonical_hash({"adapter": material["adapter"], "files": material["implementation_files"]}),
            "test_hash": _canonical_hash(material["tests"]),
            "fixture_hash": _canonical_hash(material["fixture"]),
        }

    def binding_complete(self, material: dict[str, Any] | None = None) -> bool:
        material = material or self.binding_material()
        groups = (material["implementation_files"], material["tests"]["files"], material["fixture"]["files"])
        return all(group and all("sha256" in item for item in group) for group in groups)


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
    if payload.get("product_version") != PRODUCT_VERSION:
        raise ValueError(f"Product feature catalog must be pinned to Cascadeur {PRODUCT_VERSION}")
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
