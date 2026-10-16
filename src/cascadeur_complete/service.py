from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from threading import Thread
from typing import Any

from .atomic_queue import atomic_write_json, read_json
from .bridge_client import BridgeClient
from .build_profile import DEVELOPER_BUILD
from .change_flow import ChangeFlowMixin
from .discovery import BASELINE_TOOLS, discover_commands, discover_installation, load_csc_schema
from .external import available_dependencies
from .feature_registry import build_registry, registry_json
from .host_postconditions import HostPostconditionsMixin, add_postconditions
from .jobs import JobStore
from .models import (
    PROTOCOL_VERSION,
    CapabilityState,
    ErrorCode,
    Evidence,
    ExecutionMode,
    FeatureRecord,
    Operation,
    ResultEnvelope,
    SafetyContext,
)
from .paths import RuntimePaths
from .product_catalog import PRODUCT_CATALOG
from .safety import ChangeManager
from .ui_file_flow import UiFileFlowMixin, expected_ui_flow
from .uia import (
    UIAutomationError,
    active_scene_title,
    cycle_scene_tab,
)
from .verification import LiveEvidenceStore

MUTATION_VERBS = (
    "add",
    "apply",
    "bake",
    "bind",
    "change",
    "clear",
    "close",
    "copy",
    "create",
    "delete",
    "erase",
    "export",
    "generate",
    "hide",
    "import",
    "load",
    "modify",
    "move",
    "open",
    "remove",
    "reset",
    "run",
    "save",
    "select",
    "set",
    "switch",
    "unbind",
    "unset",
    "update",
)


class CascadeurService(ChangeFlowMixin, UiFileFlowMixin, HostPostconditionsMixin):
    def __init__(self, paths: RuntimePaths | None = None, client: BridgeClient | None = None):
        self.paths = paths or RuntimePaths.discover()
        self.paths.ensure()
        self.client = client or BridgeClient(self.paths)
        self.changes = ChangeManager(self.paths)
        self.evidence_store = LiveEvidenceStore(self.paths.evidence_manifest)
        self.jobs = JobStore(self.paths)
        self.jobs.recover_incomplete()
        self.installation = discover_installation()
        self.schema = load_csc_schema()
        self.commands = discover_commands()
        self._live_tools = list(BASELINE_TOOLS)
        self._license_name, self._license_source, self._license_observed_at = self._cached_license()
        self._scene_available = False
        self._live_scene_id: str | None = None
        self._live_scene_revision: str | None = None
        self._dependencies = available_dependencies()
        self._features = []
        self._rebuild_features()
        self._write_registry()

    @property
    def _version_name(self) -> str:
        return self.installation.get("version") or "unknown"

    def _checked_status(self, status: ResultEnvelope) -> ResultEnvelope:
        """A successful status must carry the scene state dict that tokens are bound to."""
        if status.ok and not isinstance(status.result, dict):
            return self._host_error(
                "status", ErrorCode.POSTCONDITION_FAILED, "Cascadeur status returned no scene state"
            )
        return status

    @property
    def _license_path(self) -> Path:
        return self.paths.state / "license.json"

    def _cached_license(self) -> tuple[str, str, float | None]:
        """The license last reported by this Cascadeur build, so a closed app keeps its feature states."""
        try:
            cached = read_json(self._license_path)
        except (OSError, ValueError):
            return "Basic", "default", None
        if cached.get("cascadeur_version") != self._version_name or not isinstance(cached.get("license"), str):
            return "Basic", "default", None
        observed_at = cached.get("observed_at")
        return cached["license"], "cached", float(observed_at) if isinstance(observed_at, (int, float)) else None

    def _observe_license(self, license_name: Any) -> None:
        name = str(license_name or "Basic")
        changed = name != self._license_name or self._license_source != "live"
        self._license_name, self._license_source, self._license_observed_at = name, "live", time.time()
        if changed:
            atomic_write_json(
                self._license_path,
                {
                    "license": name,
                    "cascadeur_version": self._version_name,
                    "observed_at": self._license_observed_at,
                },
            )

    def _rebuild_features(self) -> None:
        self._features = build_registry(
            self.schema,
            self.commands,
            self._live_tools,
            license_name=self._license_name,
            scene_available=self._scene_available,
            version_name=self._version_name,
            verified_features=self.evidence_store.verified_features(
                self._version_name,
                license_name=self._license_name,
            ),
            developer_enabled=self._developer_policy(),
            available_dependencies=self._dependencies,
        )

    def _write_registry(self) -> None:
        payload = json.loads(registry_json(self._features))
        atomic_write_json(self.paths.registry, payload)

    def _remember_scene_result(self, result: ResultEnvelope, *, clear_missing: bool = False) -> None:
        """Keep later scene-bound requests attached to the document just observed.

        Scene-changing bridge operations return the new identity in the common
        envelope, while status also repeats it in its payload.  Remember both
        forms so a scene.open result cannot be followed by a request carrying
        the identity of the document that was just replaced.
        """
        if not result.ok:
            return
        payload = result.result if isinstance(result.result, dict) else {}
        scene_id = result.scene_id or payload.get("scene_id")
        revision = result.scene_revision or payload.get("revision")
        if scene_id:
            self._scene_available = True
            self._live_scene_id = str(scene_id)
            self._live_scene_revision = str(revision) if revision is not None else None
        elif clear_missing:
            self._scene_available = False
            self._live_scene_id = None
            self._live_scene_revision = None

    def refresh_live(self, timeout: float = 45.0, *, bind_to_cached: bool = False) -> ResultEnvelope:
        """Re-read live state and resynchronize the cached scene identity.

        Status is the resynchronization primitive, so it is unbound by
        default: binding it to the cached revision would make every later
        status (and therefore every prepare/commit) fail permanently after a
        scene finished loading or the user edited the scene in the UI.
        """
        result = self.client.execute(
            "status",
            [Operation(name="system.status")],
            scene_id=self._live_scene_id if bind_to_cached else None,
            expected_revision=self._live_scene_revision if bind_to_cached else None,
            timeout=timeout,
        )
        if result.ok and isinstance(result.result, dict):
            self._live_tools = result.result.get("tools") or list(BASELINE_TOOLS)
            self._observe_license(result.result.get("license", "Basic"))
            self._remember_scene_result(result, clear_missing=True)
            self._record_live_evidence("status", "system.status", result)
            self._rebuild_features()
            self._write_registry()
        return result

    def refresh_inventory(self, timeout: float = 120.0) -> dict[str, Any]:
        result = self.client.execute("inventory_refresh", [Operation(name="system.introspect")], timeout=timeout)
        if not result.ok or not isinstance(result.result, dict) or "schema" not in result.result:
            return result.model_dump(mode="json")
        self.schema = result.result["schema"]
        schema_path = self.paths.state / "csc_schema.json"
        atomic_write_json(schema_path, self.schema)
        status = self.refresh_live(timeout=30)
        live = status.result if status.ok and isinstance(status.result, dict) else {}
        self._live_tools = live.get("tools", BASELINE_TOOLS)
        self._scene_available = bool(live.get("scene_id"))
        self._rebuild_features()
        self._write_registry()
        if self.paths.registry.is_file() and self.paths.registry.stat().st_size > 0:
            add_postconditions(result, "Host rebuilt and persisted the feature registry", "feature_registry")
        self._record_live_evidence("inventory_refresh", "system.introspect", result)
        self._rebuild_features()
        self._write_registry()
        return {
            "ok": True,
            "schema_path": str(schema_path),
            "counts": result.result.get("counts"),
            "feature_count": len(self._features),
        }

    def capabilities(self, live: bool = True) -> dict[str, Any]:
        status = self.refresh_live() if live else None
        states: dict[str, int] = {}
        modes: dict[str, int] = {}
        for item in self._features:
            states[item.state.value] = states.get(item.state.value, 0) + 1
            modes[item.execution_mode.value] = modes.get(item.execution_mode.value, 0) + 1
        product_features = [item for item in self._features if item.truth_layer == "product"]
        product_states: dict[str, int] = {}
        for item in product_features:
            product_states[item.state.value] = product_states.get(item.state.value, 0) + 1
        # Supported: live evidence on this build, or a host-only feature (feature
        # search/describe) that never reaches Cascadeur and is proven by contract.
        supported = sum(
            item.state == CapabilityState.AVAILABLE
            and (
                item.verification.value == "verified_live"
                or (item.verification.value == "contract" and item.route.startswith("host."))
            )
            for item in product_features
        )
        return {
            "server": "cascadeur-complete",
            "server_version": "0.1.0",
            "baseline": PRODUCT_CATALOG.supported_build,
            "installation": self.installation,
            "bridge_protocol": PROTOCOL_VERSION,
            "transport": "stdio",
            "license": {
                "name": self._license_name,
                "source": self._license_source,
                "observed_at": self._license_observed_at,
            },
            "feature_count": len(self._features),
            "product_coverage": {
                "catalog_count": len(product_features),
                "supported": supported,
                "support_percent": round((supported / len(product_features)) * 100, 2) if product_features else 0,
                "states": product_states,
                "definition": (
                    "dedicated adapter + exact postconditions + live evidence on this build "
                    "(host-only features: contract evidence)"
                ),
            },
            "discovered_inventory_count": len(self._features) - len(product_features),
            "states": states,
            "execution_modes": modes,
            "connection": status.model_dump(mode="json") if status else {"live_checked": False},
            "ui_pump": self._pump_state(),
            "developer_execute_python": self._developer_policy(),
        }

    def _pump_state(self) -> dict[str, object]:
        probe = getattr(self.client, "pump_state", None)
        return probe() if callable(probe) else {"active": False}

    def _developer_policy(self) -> bool:
        if not self.paths.policy.is_file():
            return False
        try:
            return bool(json.loads(self.paths.policy.read_text(encoding="utf-8")).get("developer_execute_python"))
        except (OSError, ValueError):
            return False

    def _supported_build_error(self, feature_id: str) -> ResultEnvelope | None:
        if self._version_name == PRODUCT_CATALOG.supported_build:
            return None
        return self._host_error(
            feature_id,
            ErrorCode.UNSUPPORTED_VERSION,
            (
                f"Cascadeur {PRODUCT_CATALOG.supported_build} is required; "
                f"installed build is {self._version_name}"
            ),
            mode=ExecutionMode.GATED,
        )

    @property
    def features(self) -> list[FeatureRecord]:
        return list(self._features)

    def feature(self, feature_id: str) -> FeatureRecord:
        for feature in self._features:
            if feature.id == feature_id:
                return feature
        raise KeyError(feature_id)

    @staticmethod
    def _action_slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", ".", value.casefold()).strip(".")

    def action_allowed(self, feature_id: str, action_id: str) -> bool:
        """Bind ActionManager calls to an installed Python command record.

        C++/GUI actions that are not exported by the installed API remain
        UI-only until a version adapter provides an exact ID and postcondition.
        """
        feature = self.feature(feature_id)
        installed_names = {item["name"] for item in self.commands}
        if feature.route.startswith("action_invoke:"):
            expected = feature.route.removeprefix("action_invoke:")
            return action_id == expected and action_id in installed_names
        if feature.route.startswith("command."):
            target_slug = self._action_slug(feature.route.removeprefix("command."))
            matches = [name for name in installed_names if self._action_slug(name) == target_slug]
            return len(matches) == 1 and action_id == matches[0]
        return False

    def _generic_api_enabled(self) -> bool:
        if not DEVELOPER_BUILD:
            return False
        if not self.paths.policy.is_file():
            return False
        try:
            policy = json.loads(self.paths.policy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return bool(policy.get("developer_mode")) and bool(policy.get("generic_api"))

    def _path_policy(self) -> dict[str, bool]:
        try:
            policy = json.loads(self.paths.policy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            policy = {}
        return {
            "allow_unc_paths": bool(policy.get("allow_unc_paths", False)),
            "allow_device_paths": bool(policy.get("allow_device_paths", False)),
            "require_confirmation_for_overwrite": bool(
                policy.get("require_confirmation_for_overwrite", True)
            ),
        }

    def _feature_gate_error(
        self, feature: FeatureRecord, operation_name: str, arguments: dict[str, Any] | None
    ) -> ResultEnvelope | None:
        """Refuse a feature whose state cannot run, or an operation not bound to it (execute and prepare)."""
        if operation_name in {
            "system.csc_query",
            "system.csc_mutate",
            "system.tool_call",
            "system.developer_execute_python",
        }:
            binding_error = self._operation_binding_error(feature, operation_name, arguments)
            if binding_error:
                return self._host_error(feature.id, ErrorCode.INVALID_REQUEST, binding_error)
        if feature.state == CapabilityState.LICENSE_GATED:
            return self._host_error(
                feature.id, ErrorCode.LICENSE_GATED, f"{feature.name} requires {feature.license} license"
            )
        if feature.state == CapabilityState.MISSING_DEPENDENCY:
            return self._host_error(
                feature.id,
                ErrorCode.DEPENDENCY_MISSING,
                feature.dependency or "Required integration is unavailable",
                mode=ExecutionMode.EXTERNAL,
            )
        if feature.state == CapabilityState.UNSUPPORTED_VERSION:
            return self._host_error(
                feature.id,
                ErrorCode.UNSUPPORTED_VERSION,
                f"No verified adapter for installed Cascadeur {self.installation.get('version') or 'unknown'}",
                mode=ExecutionMode.GATED,
            )
        if feature.state == CapabilityState.UNSUPPORTED:
            return self._host_error(
                feature.id,
                ErrorCode.UNSUPPORTED_VERSION,
                f"Cascadeur {self._version_name} has no {feature.name} capability",
                mode=ExecutionMode.GATED,
            )
        if feature.state == CapabilityState.UI_ONLY and not feature.adapter_id:
            return self._host_error(
                feature.id,
                ErrorCode.UI_LOCKED,
                f"{feature.name} is identified as UI-only in Cascadeur {self._version_name}; "
                f"no postcondition-safe adapter is available (route: {feature.route})",
                mode=ExecutionMode.UIA,
            )
        if feature.state == CapabilityState.UNHEALTHY and not feature.adapter_id:
            return self._host_error(
                feature.id,
                ErrorCode.POSTCONDITION_FAILED,
                "Capability was inventoried but its dedicated execution adapter is not implemented",
                mode=feature.execution_mode,
            )
        binding_error = self._operation_binding_error(feature, operation_name, arguments)
        if binding_error:
            return self._host_error(feature.id, ErrorCode.INVALID_REQUEST, binding_error)
        return None

    def _operation_binding_error(
        self, feature: FeatureRecord, operation_name: str, arguments: dict[str, Any] | None = None
    ) -> str | None:
        arguments = arguments or {}
        generic_operations = {
            "system.csc_query",
            "system.csc_mutate",
            "system.tool_call",
            "system.developer_execute_python",
        }
        if operation_name in generic_operations:
            if not self._generic_api_enabled():
                return "Generic csc/tool/Python execution is disabled in production policy"
            expected_feature = {
                "system.csc_query": "csc_query",
                "system.csc_mutate": "csc_mutate",
                "system.developer_execute_python": "developer_execute_python",
            }.get(operation_name)
            if expected_feature and feature.id != expected_feature:
                return "Generic operation is not bound to this feature id"
            return None
        if operation_name == "system.action_invoke":
            action_id = str(arguments.get("action_id", ""))
            return None if self.action_allowed(feature.id, action_id) else "Action id is not bound to this feature"
        if operation_name == "system.ui_file_flow":
            expected = expected_ui_flow(feature.id, arguments)
            if expected is None:
                return "UI file flow is not bound to this feature"
            keys = (
                "action_id",
                "dialog_title",
                "options_title",
                "options_accept_title",
                "options_accept_index",
                "after_accept_title",
                "form",
                "file_type_extension",
            )
            if any(arguments.get(key) != expected[key] for key in keys):
                return "UI file flow arguments differ from the registered action and dialog for this feature"
            return None
        if feature.id == "view_mode" and operation_name in {"system.view_mode_get", "system.view_mode_set"}:
            return None
        aliases = {
            "auto_posing": "generation.auto_posing",
            "auto_physics": "physics.auto_snap",
        }
        expected = aliases.get(feature.id, feature.route)
        if operation_name != expected:
            return f"Operation {operation_name!r} is not bound to feature {feature.id!r}; expected {expected!r}"
        for name, value in feature.fixed_arguments.items():
            if name in arguments and arguments[name] != value:
                return f"Feature {feature.id!r} fixes argument {name!r} to {value!r}"
        return None

    def _bound_arguments(self, feature_id: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        """Merge the arguments a feature fixes (shared operations are feature-specific)."""
        merged = dict(arguments or {})
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return merged
        for name, value in feature.fixed_arguments.items():
            merged.setdefault(name, value)
        if feature.route.startswith(("action_invoke:", "command.")):
            merged["command"] = True  # dispatch through the Commands.* ActionManager id
        return merged

    def feature_search(
        self,
        query: str,
        family: str | None = None,
        state: str | None = None,
        limit: int = 100,
        layer: str = "product",
    ) -> list[dict[str, Any]]:
        needle = query.casefold()
        result = []
        for feature in self._features:
            if layer not in {"product", "discovered", "all"}:
                raise ValueError("layer must be product, discovered, or all")
            if layer != "all" and feature.truth_layer != layer:
                continue
            if family and feature.family != family:
                continue
            if state and feature.state.value != state:
                continue
            haystack = f"{feature.id} {feature.name} {feature.description} {feature.route}".casefold()
            if needle and needle not in haystack:
                continue
            result.append(feature.model_dump(mode="json"))
            if len(result) >= min(max(limit, 1), 500):
                break
        return result

    def submit_job(
        self,
        feature_id: str,
        operation_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        scene_id: str | None = None,
        expected_revision: str | None = None,
        timeout: float = 300,
        retry_of: str | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        feature = self.feature(feature_id)
        binding_error = self._operation_binding_error(feature, operation_name, arguments)
        if binding_error:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error).model_dump(mode="json")
        arguments = self._bound_arguments(feature_id, arguments)
        if self._operation_is_mutating(operation_name):
            return self._host_error(
                feature_id,
                ErrorCode.CONFIRMATION_REQUIRED,
                "Destructive operations cannot be submitted as background jobs; use change_prepare/change_commit",
            ).model_dump(mode="json")
        record = self.jobs.create(
            feature_id,
            operation_name=operation_name,
            arguments=arguments or {},
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            retry_of=retry_of,
            attempt=attempt,
        )

        def run() -> None:
            current = self.jobs.get(record.job_id)
            if current is None or current.status == "canceled":
                return
            self.jobs.update(record.job_id, status="running", progress=0.05, log="Bridge dispatch started")
            result = self.execute(
                feature_id,
                operation_name,
                arguments or {},
                scene_id=scene_id,
                expected_revision=expected_revision,
                timeout=timeout,
            )
            current = self.jobs.get(record.job_id)
            if current is None:
                return
            if current.cancel_requested:
                self.jobs.update(
                    record.job_id,
                    status="canceled",
                    progress=1,
                    log="Claimed operation completed after cancellation request; result retained",
                    result=result,
                )
            else:
                self.jobs.update(
                    record.job_id,
                    status="succeeded" if result.ok else "failed",
                    progress=1,
                    log="Bridge operation completed",
                    result=result,
                )

        Thread(target=run, name=f"cascadeur-job-{record.job_id}", daemon=True).start()
        return record.model_dump(mode="json")

    def retry_job(self, job_id: str) -> dict[str, Any]:
        try:
            record = self.jobs.get(job_id)
        except ValueError:
            record = None
        if record is None:
            return {"ok": False, "error_code": ErrorCode.INVALID_REQUEST, "error_message": "Unknown job id"}
        if record.status not in ("failed", "canceled"):
            return {
                "ok": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error_message": "Only failed or canceled jobs can be retried",
            }
        if not record.operation_name:
            return {
                "ok": False,
                "error_code": ErrorCode.INVALID_REQUEST,
                "error_message": "Legacy job does not retain an operation for retry",
            }
        return self.submit_job(
            record.feature_id,
            record.operation_name,
            record.arguments,
            scene_id=record.scene_id,
            expected_revision=record.expected_revision,
            timeout=record.timeout,
            retry_of=record.job_id,
            attempt=record.attempt + 1,
        )

    def execute(
        self,
        feature_id: str,
        operation_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        scene_id: str | None = None,
        expected_revision: str | None = None,
        timeout: float = 30.0,
    ) -> ResultEnvelope:
        """Run a read-only operation; every mutation is refused (prepare_change/commit_change own those)."""
        build_error = self._supported_build_error(feature_id)
        if build_error and not (feature_id == "status" and operation_name == "system.status"):
            return build_error
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, "Unknown feature id")
        gate_error = self._feature_gate_error(feature, operation_name, arguments)
        if gate_error:
            return gate_error
        arguments = self._bound_arguments(feature_id, arguments)
        if feature.requires_scene and scene_id is None and self._live_scene_id:
            scene_id = self._live_scene_id
            if expected_revision is None:
                expected_revision = self._live_scene_revision
        if self._operation_is_mutating(operation_name):
            return self._host_error(
                feature_id,
                ErrorCode.CONFIRMATION_REQUIRED,
                "All scene and file mutations require change_prepare and change_commit",
            )
        result = self.client.execute(
            feature_id,
            [Operation(name=operation_name, arguments=arguments or {})],
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            safety_context=SafetyContext(destructive=False, snapshot_required=False),
        )
        result.operation_id = operation_name
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = expected_revision
        result.scene_revision_after = result.scene_revision
        self._remember_scene_result(result)
        if result.ok and feature.adapter_id:
            self._record_live_evidence(feature_id, operation_name, result)
            self._rebuild_features()
            self._write_registry()
        return result

    def _record_live_evidence(self, feature_id: str, operation_name: str, result: ResultEnvelope) -> None:
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return
        product = PRODUCT_CATALOG.by_id.get(feature_id)
        if not feature.adapter_id or not result.ok or product is None:
            return
        observed = {
            str(item.get("id")): bool(item.get("ok"))
            for item in result.postconditions
            if isinstance(item, dict) and item.get("id")
        }
        if not product.live_test_id or not product.fixture_id:
            return
        if not product.postconditions or not all(observed.get(item) is True for item in product.postconditions):
            return
        self.evidence_store.record(
            feature_id,
            version=self._version_name,
            adapter_id=feature.adapter_id,
            operation=operation_name,
            scene_id=result.scene_id,
            evidence=[item.model_dump(mode="json") for item in result.evidence],
            license_name=self._license_name,
            dependencies={product.dependency: True} if product.dependency in self._dependencies else None,
            observed_postconditions=observed,
            fixture_id=product.fixture_id,
            test_id=product.live_test_id,
        )

    def batch(
        self,
        feature_id: str,
        operations: list[dict[str, Any]],
        *,
        scene_id: str | None,
        expected_revision: str | None,
        timeout: float = 60.0,
    ) -> ResultEnvelope:
        """Run read-only operations in one bridge entry; mutating batches are refused."""
        build_error = self._supported_build_error(feature_id)
        if build_error:
            return build_error
        parsed = [Operation.model_validate(item) for item in operations]
        for item in parsed:
            item.arguments = self._bound_arguments(feature_id, item.arguments)
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, "Unknown feature id")
        binding_errors = [self._operation_binding_error(feature, item.name, item.arguments) for item in parsed]
        if any(binding_errors):
            return self._host_error(
                feature_id,
                ErrorCode.INVALID_REQUEST,
                next(item for item in binding_errors if item),
            )
        mutating = any(self._operation_is_mutating(item.name) for item in parsed)
        if mutating:
            return self._host_error(
                feature_id,
                ErrorCode.CONFIRMATION_REQUIRED,
                "Mutating batches must be split into individually prepared changes",
            )
        result = self.client.execute(
            feature_id,
            parsed,
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            safety_context=SafetyContext(destructive=False),
        )
        result.operation_id = "batch"
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = expected_revision
        result.scene_revision_after = result.scene_revision
        self._remember_scene_result(result)
        return result










    @staticmethod
    def _same_path(left: str | None, right: str | None) -> bool:
        """Compare scene labels: absolute paths by file identity, untitled tabs by name."""
        if not left or not right:
            return False
        if os.path.isabs(left) and os.path.isabs(right):
            return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
        return left.strip().casefold() == right.strip().casefold()

    @staticmethod
    def _scene_label(state: dict[str, Any]) -> str | None:
        return state.get("path") or state.get("name")

    def _timeline_frame(self) -> int | None:
        observed = self.client.execute("timeline_get", [Operation(name="timeline.get")], timeout=30)
        if not observed.ok or not isinstance(observed.result, dict):
            return None
        return int(observed.result.get("current_frame", -1))

    def _playback_moving(self, interval: float = 1.2) -> bool | None:
        """Sample the playhead twice after the UI thread is free; None if unreadable."""
        self._wait_for_bridge_idle()
        first = self._timeline_frame()
        self._wait_for_bridge_idle()
        time.sleep(interval)
        second = self._timeline_frame()
        if first is None or second is None:
            return None
        return first != second

    def _active_tab_id(self) -> str | None:
        listed = self.client.execute("scene_list", [Operation(name="scene.list")], timeout=30)
        if not listed.ok or not isinstance(listed.result, list):
            return None
        return next((str(item.get("tab_id")) for item in listed.result if item.get("active")), None)

    def _wait_for_bridge_idle(self, limit: float = 3.0) -> None:
        """Wait until a lingering bridge drain released the UI thread."""
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline and self.client.lingering_until() is not None:
            time.sleep(0.1)

    def _wait_for_open_scene(
        self,
        initial: ResultEnvelope,
        expected_path: str,
        timeout: float,
        *,
        expected_tab_id: str | None = None,
    ) -> ResultEnvelope:
        """Require the expected scene to stay active after Cascadeur's UI settles.

        The bridge verifies the target inside the command, but Cascadeur's tab
        bar re-asserts its previous selection once the command returns. The
        host therefore re-observes the active scene with fresh reads (each
        dispatched after the event loop ran) and, when the UI reverted,
        selects tabs through the UI with Ctrl+Tab until the target is active.
        Untitled scenes are matched by session tab id instead of path.
        """
        deadline = time.monotonic() + max(5.0, timeout)
        tab_cycles = 0
        listed = self.client.execute("scene_list", [Operation(name="scene.list")], timeout=30)
        tab_count = len(listed.result) if listed.ok and isinstance(listed.result, list) else 40
        max_tab_cycles = tab_count + 2
        stable = 0
        latest = None
        while time.monotonic() < deadline:
            if expected_tab_id is not None:
                matched = self._active_tab_id() == expected_tab_id
            else:
                matched = self._same_path(active_scene_title(), expected_path)
            if matched:
                latest = self.refresh_live(timeout=min(30.0, max(1.0, deadline - time.monotonic())))
                label_ok = expected_tab_id is not None or (
                    latest.ok
                    and isinstance(latest.result, dict)
                    and self._same_path(self._scene_label(latest.result), expected_path)
                )
                if latest.ok and label_ok:
                    stable += 1
                    if stable >= 2:
                        break
                    self._wait_for_bridge_idle()
                    time.sleep(0.5)
                    continue
            stable = 0
            if tab_cycles >= max_tab_cycles:
                break
            self._wait_for_bridge_idle()
            try:
                cycle_scene_tab()
            except UIAutomationError:
                break
            tab_cycles += 1
            time.sleep(0.8)
        if stable < 2 or latest is None:
            failed = self._host_error(
                initial.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Scene did not stay active after the UI settled: " + (expected_tab_id or expected_path),
            )
            failed.snapshot_id = initial.snapshot_id
            if latest is not None:
                failed.evidence = list(latest.evidence)
            return failed
        initial.scene_id = latest.scene_id
        initial.scene_revision = latest.scene_revision
        initial.changed_entities = sorted(set(initial.changed_entities + ["scene"]))
        payload = dict(initial.result) if isinstance(initial.result, dict) else {}
        payload.update(
            {
                "path": latest.result.get("path"),
                "loaded": True,
                "stable_observations": stable,
                "ui_tab_cycles": tab_cycles,
            }
        )
        initial.result = payload
        initial.evidence.extend(latest.evidence)
        target = expected_tab_id or expected_path
        initial.evidence.append(
            Evidence(
                kind="host_window_postcondition",
                detail=f"Scene stayed active after UI settle ({tab_cycles} UI tab cycles): {target}",
                observed_at=time.time(),
            )
        )
        add_postconditions(initial, f"Active scene settled at {target}", "stable_scene_path")
        return initial





    def csc_mutate_allowed(self, chain: list[dict[str, Any]]) -> bool:
        if not chain:
            return False
        final = str(chain[-1].get("attr", "")).lower()
        if not final.startswith(MUTATION_VERBS):
            return False
        schema_methods = {
            method.lower()
            for feature in self._features
            if feature.family == "csc_api"
            for method in [feature.name.rsplit(".", 1)[-1]]
        }
        return final in schema_methods

    def _operation_is_mutating(self, name: str) -> bool:
        lowered = name.casefold()
        product_bindings = [item for item in PRODUCT_CATALOG.features if item.operation == name]
        if product_bindings:
            return any(item.mutation for item in product_bindings)
        return lowered not in {
            "system.status",
            "system.logs",
            "system.view_mode_get",
            "physics.auto_state",
            "physics.state",
            "rig.state",
            "rig.constraint_drivers",
            "generation.state",
            "system.tools",
            "system.introspect",
            "scene.summary",
            "scene.objects",
            "scene.list",
            "scene.validate",
            "object.hierarchy",
            "object.properties",
            "object.behaviors",
            "selection.get",
            "selection.filter",
            "timeline.get",
            "animation.transform_get",
            "layer.list",
            "animation.key_list",
            "animation.graph_query",
            "animation.cycle_query",
            "render.viewport_state",
            "render.camera_catalog",
        }

    @staticmethod
    def _host_error(
        feature_id: str, code: ErrorCode, message: str, mode: ExecutionMode = ExecutionMode.NATIVE
    ) -> ResultEnvelope:
        return ResultEnvelope(
            ok=False,
            feature_id=feature_id,
            execution_mode=mode,
            status="failed",
            error_code=code,
            error_message=message,
        )
