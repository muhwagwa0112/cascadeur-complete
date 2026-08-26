from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from threading import Thread
from typing import Any

from .atomic_queue import atomic_write_json
from .bridge_client import BridgeClient
from .build_profile import DEVELOPER_BUILD
from .discovery import BASELINE_TOOLS, discover_commands, discover_installation, load_csc_schema
from .feature_registry import build_registry, registry_json
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
from .safety import ChangeManager, SafetyError, validate_local_input_path, validate_local_path
from .uia import (
    UIAutomationError,
    cancel_file_flow,
    cascadeur_window_titles,
    complete_file_dialog,
    resolve_autophysics_snap_warning,
    resolve_optional_rig_mode_helper,
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


class CascadeurService:
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
        self._license_name = "Basic"
        self._scene_available = False
        self._live_scene_id: str | None = None
        self._live_scene_revision: str | None = None
        self._features = []
        self._rebuild_features()
        self._write_registry()

    @property
    def _version_name(self) -> str:
        return self.installation.get("version") or "unknown"

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

    def refresh_live(self, timeout: float = 45.0, *, bind_to_cached: bool = True) -> ResultEnvelope:
        result = self.client.execute(
            "status",
            [Operation(name="system.status")],
            scene_id=self._live_scene_id if bind_to_cached else None,
            expected_revision=self._live_scene_revision if bind_to_cached else None,
            timeout=timeout,
        )
        if result.ok and isinstance(result.result, dict):
            self._live_tools = result.result.get("tools") or list(BASELINE_TOOLS)
            self._license_name = result.result.get("license", "Basic")
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
        self._license_name = live.get("license", "Basic")
        self._scene_available = bool(live.get("scene_id"))
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
        supported = sum(
            item.verification.value == "verified_live" and item.state == CapabilityState.AVAILABLE
            for item in product_features
        )
        return {
            "server": "cascadeur-complete",
            "server_version": "0.1.0",
            "baseline": "2026.1.2.0.15343",
            "installation": self.installation,
            "bridge_protocol": PROTOCOL_VERSION,
            "transport": "stdio",
            "feature_count": len(self._features),
            "product_coverage": {
                "catalog_count": len(product_features),
                "supported": supported,
                "support_percent": round((supported / len(product_features)) * 100, 2) if product_features else 0,
                "states": product_states,
                "definition": "dedicated adapter + exact postconditions + live evidence on this build",
            },
            "discovered_inventory_count": len(self._features) - len(product_features),
            "states": states,
            "execution_modes": modes,
            "connection": status.model_dump(mode="json") if status else {"live_checked": False},
            "developer_execute_python": self._developer_policy(),
        }

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
            ui_file_features = {
                "import_usd",
                "export_usd",
                "import_glb",
                "export_glb",
                "import_gltf",
                "export_gltf",
                "import_vrm",
            }
            return None if feature.id in ui_file_features else "UI file flow is not bound to this feature"
        if feature.id == "view_mode" and operation_name in {"system.view_mode_get", "system.view_mode_set"}:
            return None
        aliases = {
            "auto_posing": "generation.auto_posing",
            "auto_physics": "physics.auto_snap",
        }
        expected = aliases.get(feature.id, feature.route)
        if operation_name != expected:
            return f"Operation {operation_name!r} is not bound to feature {feature.id!r}; expected {expected!r}"
        return None

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
        confirmation_token: str | None = None,
    ) -> ResultEnvelope:
        build_error = self._supported_build_error(feature_id)
        if build_error and not (feature_id == "status" and operation_name == "system.status"):
            return build_error
        try:
            feature = self.feature(feature_id)
        except KeyError:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, "Unknown feature id")
        if operation_name in {
            "system.csc_query",
            "system.csc_mutate",
            "system.tool_call",
            "system.developer_execute_python",
        }:
            binding_error = self._operation_binding_error(feature, operation_name, arguments)
            if binding_error:
                return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error)
        if feature.state == CapabilityState.LICENSE_GATED:
            return self._host_error(
                feature_id, ErrorCode.LICENSE_GATED, f"{feature.name} requires {feature.license} license"
            )
        if feature.state == CapabilityState.MISSING_DEPENDENCY:
            return self._host_error(
                feature_id,
                ErrorCode.DEPENDENCY_MISSING,
                feature.dependency or "Required integration is unavailable",
                mode=ExecutionMode.EXTERNAL,
            )
        if feature.state == CapabilityState.UNSUPPORTED_VERSION:
            return self._host_error(
                feature_id,
                ErrorCode.UNSUPPORTED_VERSION,
                f"No verified adapter for installed Cascadeur {self.installation.get('version') or 'unknown'}",
                mode=ExecutionMode.GATED,
            )
        if feature.state == CapabilityState.UI_ONLY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.UI_LOCKED,
                f"{feature.name} is identified as UI-only in Cascadeur {self._version_name}; "
                f"no postcondition-safe adapter is available (route: {feature.route})",
                mode=ExecutionMode.UIA,
            )
        if feature.state == CapabilityState.UNHEALTHY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Capability was inventoried but its dedicated execution adapter is not implemented",
                mode=feature.execution_mode,
            )
        binding_error = self._operation_binding_error(feature, operation_name, arguments)
        if binding_error:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error)
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
        if operation_name == "system.action_invoke" and not feature.route.startswith(
            ("action_invoke:", "command.")
        ):
            return self._host_error(
                feature_id, ErrorCode.INVALID_REQUEST, "Feature is not registered as an action or GUI tool"
            )
        if (
            operation_name == "system.action_invoke"
            and not bool((arguments or {}).get("expect_change", True))
            and not (arguments or {}).get("postcondition")
        ):
            return self._host_error(
                feature_id,
                ErrorCode.INVALID_REQUEST,
                "Actions must require an observable scene change or provide an explicit postcondition",
            )
        safety = SafetyContext(
            destructive=False,
            confirmation_token=confirmation_token,
            snapshot_required=False,
        )
        output_path = (arguments or {}).get("path") if operation_name == "render.viewport_capture" else None
        before_output = self._file_signature(output_path) if output_path else None
        result = self.client.execute(
            feature_id,
            [Operation(name=operation_name, arguments=arguments or {})],
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            safety_context=safety,
        )
        result.operation_id = operation_name
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = expected_revision
        result.scene_revision_after = result.scene_revision
        if result.ok and output_path:
            result = self._wait_for_output_file(result, str(output_path), timeout, before_output)
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
        confirmation_token: str | None = None,
    ) -> ResultEnvelope:
        build_error = self._supported_build_error(feature_id)
        if build_error:
            return build_error
        parsed = [Operation.model_validate(item) for item in operations]
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
        if any(self._operation_is_mutating(item.name) for item in parsed) and expected_revision is None:
            return self._host_error(
                feature_id, ErrorCode.INVALID_REQUEST, "expected_revision is required for mutating batches"
            )
        result = self.client.execute(
            feature_id,
            parsed,
            scene_id=scene_id,
            expected_revision=expected_revision,
            timeout=timeout,
            safety_context=SafetyContext(destructive=False, confirmation_token=confirmation_token),
        )
        result.operation_id = "batch"
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = expected_revision
        result.scene_revision_after = result.scene_revision
        self._remember_scene_result(result)
        return result

    def prepare_change(
        self, feature_id: str, operation_name: str, arguments: dict[str, Any], ttl: float = 300.0
    ) -> dict[str, Any]:
        build_error = self._supported_build_error(feature_id)
        if build_error:
            return build_error.model_dump(mode="json")
        feature = self.feature(feature_id)
        if operation_name in {
            "system.csc_query",
            "system.csc_mutate",
            "system.tool_call",
            "system.developer_execute_python",
        }:
            binding_error = self._operation_binding_error(feature, operation_name, arguments)
            if binding_error:
                return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error).model_dump(mode="json")
        if feature.state == CapabilityState.LICENSE_GATED:
            return self._host_error(
                feature_id, ErrorCode.LICENSE_GATED, f"{feature.name} requires {feature.license} license"
            ).model_dump(mode="json")
        if feature.state == CapabilityState.MISSING_DEPENDENCY:
            return self._host_error(
                feature_id,
                ErrorCode.DEPENDENCY_MISSING,
                feature.dependency or "Required integration is unavailable",
                mode=ExecutionMode.EXTERNAL,
            ).model_dump(mode="json")
        if feature.state == CapabilityState.UNSUPPORTED_VERSION:
            return self._host_error(
                feature_id,
                ErrorCode.UNSUPPORTED_VERSION,
                f"No verified adapter for installed Cascadeur {self.installation.get('version') or 'unknown'}",
                mode=ExecutionMode.GATED,
            ).model_dump(mode="json")
        if feature.state == CapabilityState.UI_ONLY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.UI_LOCKED,
                f"{feature.name} is identified as UI-only in Cascadeur {self._version_name}; "
                f"no postcondition-safe adapter is available (route: {feature.route})",
                mode=ExecutionMode.UIA,
            ).model_dump(mode="json")
        if feature.state == CapabilityState.UNHEALTHY and not feature.adapter_id:
            return self._host_error(
                feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Capability was inventoried but its dedicated execution adapter is not implemented",
                mode=feature.execution_mode,
            ).model_dump(mode="json")
        binding_error = self._operation_binding_error(feature, operation_name, arguments)
        if binding_error:
            return self._host_error(feature_id, ErrorCode.INVALID_REQUEST, binding_error).model_dump(mode="json")
        if not self._operation_is_mutating(operation_name):
            return self._host_error(
                feature_id,
                ErrorCode.INVALID_REQUEST,
                "Read-only operations must be executed directly and cannot mint change tokens",
            ).model_dump(mode="json")
        status = self.refresh_live()
        if not status.ok:
            return status.model_dump(mode="json")
        state = status.result
        if feature.requires_scene and not state.get("scene_id"):
            return self._host_error(
                feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                f"{feature.name} requires an active Cascadeur scene",
                mode=feature.execution_mode,
            ).model_dump(mode="json")
        destination = arguments.get("path") or arguments.get("destination")
        if destination:
            path_policy = self._path_policy()
            if (
                operation_name == "scene.open"
                or operation_name.startswith("io.import_")
                or bool(arguments.get("input"))
            ):
                validated = validate_local_input_path(
                    str(destination),
                    allow_unc_paths=path_policy["allow_unc_paths"],
                    allow_device_paths=path_policy["allow_device_paths"],
                )
            else:
                validated = validate_local_path(
                    str(destination),
                    allow_overwrite=(
                        bool(arguments.get("allow_overwrite"))
                        or not path_policy["require_confirmation_for_overwrite"]
                    ),
                    allow_unc_paths=path_policy["allow_unc_paths"],
                    allow_device_paths=path_policy["allow_device_paths"],
                )
            arguments = {**arguments, "path": str(validated)}
        snapshot_id = str(uuid.uuid4())
        working_id = str(uuid.uuid4())
        backup_path = None
        working_path = None
        if state.get("scene_id"):
            snapshot = self.client.execute(
                "snapshot",
                [
                    Operation(
                        name="safety.snapshot",
                        arguments={"snapshot_id": snapshot_id, "working_id": working_id},
                    )
                ],
                scene_id=state["scene_id"],
                expected_revision=state["revision"],
                timeout=120,
            )
            if not snapshot.ok:
                return snapshot.model_dump(mode="json")
            # safety.snapshot saves and activates a distinct writable working
            # document. Bind the post-snapshot status check to that returned
            # identity, not to the immutable source document cached above.
            self._remember_scene_result(snapshot)
            backup_path = snapshot.result["path"]
            working_path = snapshot.result.get("working_path", backup_path)
            if Path(backup_path).resolve() == Path(working_path).resolve():
                return self._host_error(
                    feature_id,
                    ErrorCode.POSTCONDITION_FAILED,
                    "Snapshot safety invariant failed: recovery and working paths are identical",
                ).model_dump(mode="json")
            # Bind the token to the writable working document created by the
            # snapshot operation, never to the original or immutable backup.
            post_snapshot = self.refresh_live()
            if not post_snapshot.ok:
                return post_snapshot.model_dump(mode="json")
            state = post_snapshot.result
        impact = {
            "feature": feature.name,
            "destructive": True,
            "selected_entities": len(state.get("selection", [])),
            "object_count": len(state.get("objects", [])),
            "destination": arguments.get("path"),
            "working_scene": working_path,
            "expected_result": "Operation-specific postconditions must pass",
        }
        record = self.changes.prepare(
            feature_id=feature_id,
            scene_id=state.get("scene_id"),
            scene_revision=state.get("revision"),
            selection_fingerprint=state.get("selection_fingerprint"),
            operation=Operation(name=operation_name, arguments=arguments),
            impact=impact,
            backup_path=backup_path,
            ttl=ttl,
        )
        return {
            "ok": True,
            "confirmation_token": record.token,
            "feature_id": feature_id,
            "scene_id": record.scene_id,
            "scene_revision": record.scene_revision,
            "selection_fingerprint": record.selection_fingerprint,
            "operation": record.operation.model_dump(mode="json"),
            "impact": impact,
            "backup_path": backup_path,
            "working_path": working_path,
            "snapshot_id": snapshot_id if backup_path else None,
            "expires_at": record.expires_at,
        }

    def commit_change(self, token: str, timeout: float = 120.0) -> ResultEnvelope:
        build_error = self._supported_build_error("change_commit")
        if build_error:
            return build_error
        try:
            record = self.changes.load(token)
        except SafetyError as exc:
            return self._host_error("change_commit", ErrorCode.INVALID_REQUEST, str(exc))
        status = self.refresh_live()
        if not status.ok:
            return status
        state = status.result
        try:
            self.changes.consume(
                token,
                scene_id=state.get("scene_id"),
                scene_revision=state.get("revision"),
                selection_fingerprint=state.get("selection_fingerprint"),
            )
        except SafetyError as exc:
            return self._host_error(record.feature_id, ErrorCode.SCENE_CHANGED, str(exc))
        output_path = record.operation.arguments.get("path")
        before_output = self._file_signature(output_path) if output_path else None
        if record.operation.name == "system.ui_file_flow":
            result = self._execute_ui_file_flow(record, timeout, before_output)
        else:
            result = self.client.execute(
                record.feature_id,
                [record.operation],
                scene_id=record.scene_id,
                expected_revision=record.scene_revision,
                timeout=timeout,
                safety_context=SafetyContext(
                    destructive=True,
                    confirmation_token=token,
                    snapshot_required=False,
                    selection_fingerprint=record.selection_fingerprint,
                    allow_overwrite=bool(record.operation.arguments.get("allow_overwrite")),
                ),
            )
        result.snapshot_id = Path(record.backup_path).stem if record.backup_path else None
        result.operation_id = record.operation.name
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = record.scene_revision
        result.scene_revision_after = result.scene_revision
        try:
            if result.ok and record.operation.name == "scene.open":
                result = self._wait_for_open_scene(result, str(record.operation.arguments["path"]), timeout)
            if result.ok and record.operation.name == "safety.rollback":
                working_path = self.paths.snapshots / (
                    str(record.operation.arguments["working_id"]) + ".working.casc"
                )
                result = self._wait_for_open_scene(result, str(working_path), timeout)
            if result.ok and record.operation.name == "physics.auto_snap":
                result = self._complete_auto_physics_snap(result, timeout)
            if result.ok and record.operation.name in {
                "render.viewport_capture",
                "render.image",
                "render.video",
                "io.export_image",
                "io.export_video",
            }:
                result = self._wait_for_output_file(
                    result, str(record.operation.arguments["path"]), timeout, before_output
                )
        except Exception as exc:
            bridge_evidence = list(result.evidence)
            result = self._host_error(
                record.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                f"Host postcondition failed: {exc}",
                mode=result.execution_mode,
            )
            result.snapshot_id = Path(record.backup_path).stem if record.backup_path else None
            result.evidence = bridge_evidence
        if result.ok:
            self._record_live_evidence(record.feature_id, record.operation.name, result)
            self._rebuild_features()
            self._write_registry()
        elif record.backup_path:
            result = self._restore_failed_change(record, result)
        result.operation_id = record.operation.name
        result.status = "succeeded" if result.ok else "failed"
        result.scene_revision_before = record.scene_revision
        result.scene_revision_after = result.scene_revision
        self._remember_scene_result(result)
        return result

    def _execute_ui_file_flow(self, record, timeout: float, before_output: tuple[int, int] | None) -> ResultEnvelope:
        """Coordinate a blocking Cascadeur action with its owned file dialog."""
        arguments = record.operation.arguments
        action_id = str(arguments["action_id"])
        responses: list[ResultEnvelope] = []
        failures: list[BaseException] = []

        def dispatch() -> None:
            try:
                responses.append(
                    self.client.execute(
                        record.feature_id,
                        [Operation(name="system.action_dispatch", arguments={"action_id": action_id})],
                        scene_id=record.scene_id,
                        expected_revision=record.scene_revision,
                        timeout=timeout,
                        safety_context=SafetyContext(
                            destructive=True,
                            confirmation_token=record.token,
                            selection_fingerprint=record.selection_fingerprint,
                            allow_overwrite=bool(arguments.get("allow_overwrite")),
                        ),
                    )
                )
            except BaseException as exc:  # pragma: no cover - thread boundary
                failures.append(exc)

        worker = Thread(target=dispatch, name="cascadeur-ui-file-flow", daemon=True)
        worker.start()
        try:
            dialog = complete_file_dialog(
                action_id=action_id,
                path=str(arguments["path"]),
                expected_dialog_title=str(arguments["dialog_title"]),
                options_title=arguments.get("options_title"),
                options_accept_title=arguments.get("options_accept_title"),
                file_type_extension=arguments.get("file_type_extension"),
                timeout=min(timeout, 30.0),
            )
        except Exception as exc:
            cancel_file_flow(
                expected_dialog_title=str(arguments["dialog_title"]),
                options_title=arguments.get("options_title"),
            )
            worker.join(min(10.0, max(0.1, timeout)))
            is_uia = isinstance(exc, UIAutomationError)
            return self._host_error(
                record.feature_id,
                (ErrorCode.CASCADEUR_NOT_RUNNING if is_uia and exc.not_running else ErrorCode.UI_LOCKED),
                f"UI file flow failed: {exc}",
                mode=ExecutionMode.UIA,
            )
        worker.join(max(0.1, timeout))
        if worker.is_alive():
            return self._host_error(
                record.feature_id,
                ErrorCode.TIMEOUT,
                f"Cascadeur action did not finish after file dialog acceptance: {action_id}",
                mode=ExecutionMode.UIA,
            )
        if failures:
            return self._host_error(
                record.feature_id,
                ErrorCode.UI_LOCKED,
                f"UI file flow dispatch failed: {failures[0]}",
                mode=ExecutionMode.UIA,
            )
        if not responses:
            return self._host_error(
                record.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "UI file flow produced no bridge response",
                mode=ExecutionMode.UIA,
            )
        result = responses[0]
        result.execution_mode = ExecutionMode.UIA
        result.evidence.append(
            Evidence(
                kind="host_ui_file_dialog",
                detail=(
                    f"Invoked {dialog.action_id}; matched {dialog.dialog_title}; "
                    f"set Edit {dialog.file_name_automation_id}; accepted Button {dialog.accept_automation_id}; "
                    f"file type {dialog.file_type or 'dialog default'}"
                ),
                observed_at=dialog.completed_at,
            )
        )
        if not result.ok:
            return result
        if bool(arguments.get("output")):
            return self._wait_for_output_file(result, str(arguments["path"]), timeout, before_output)
        before_revision = record.scene_revision
        try:
            helper = resolve_optional_rig_mode_helper(enter_rig_mode=False, timeout=min(12.0, timeout))
        except UIAutomationError as exc:
            failed = self._host_error(
                record.feature_id,
                ErrorCode.UI_LOCKED,
                f"Imported scene is waiting for an unresolved Rig Mode Helper: {exc}",
                mode=ExecutionMode.UIA,
            )
            failed.evidence = list(result.evidence)
            return failed
        if helper is not None:
            result.evidence.append(
                Evidence(
                    kind="host_ui_postcondition",
                    detail=f"Dismissed optional {helper.window_title} with {helper.button}",
                    observed_at=helper.dismissed_at,
                )
            )
        deadline = time.monotonic() + max(1.0, timeout)
        after = None
        while time.monotonic() < deadline:
            after = self.refresh_live(timeout=min(20.0, max(1.0, deadline - time.monotonic())))
            if after.ok and after.scene_revision and after.scene_revision != before_revision:
                break
            time.sleep(0.2)
        if after is None or not after.ok or not after.scene_revision or after.scene_revision == before_revision:
            failed = self._host_error(
                record.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "Import file dialog completed but the scene revision did not change",
                mode=ExecutionMode.UIA,
            )
            failed.evidence = list(result.evidence) + (list(after.evidence) if after is not None else [])
            return failed
        result.scene_id = after.scene_id
        result.scene_revision = after.scene_revision
        result.changed_entities = sorted(set(result.changed_entities + ["scene"]))
        result.evidence.extend(after.evidence)
        result.evidence.append(
            Evidence(
                kind="host_scene_postcondition",
                detail="Scene revision changed after UI file import",
                observed_at=time.time(),
            )
        )
        return result

    def _restore_failed_change(self, record, failed: ResultEnvelope) -> ResultEnvelope:
        """Restore the prepared snapshot after any failed destructive commit.

        A Cascadeur command may modify static update-graph data before its own
        postcondition fails.  Those partial writes are not always represented
        by the normal scene fingerprint, so every failed prepared change is
        restored from its already-created snapshot instead of guessing whether
        the scene is still clean.
        """
        snapshot_id = Path(record.backup_path).stem
        restored = self._rollback_internal(snapshot_id)
        if restored.ok:
            failed.scene_id = restored.scene_id
            failed.scene_revision = restored.scene_revision
            failed.warnings.append(f"Failed change was automatically restored from snapshot {snapshot_id}")
            failed.evidence.extend(restored.evidence)
            failed.evidence.append(
                Evidence(
                    kind="automatic_rollback",
                    detail=f"Restored prepared snapshot {snapshot_id} after failed commit",
                    observed_at=time.time(),
                )
            )
        else:
            failed.warnings.append(
                "Automatic rollback failed; use change_rollback with snapshot "
                f"{snapshot_id}. Rollback error: {restored.error_message or restored.error_code}"
            )
            failed.evidence.extend(restored.evidence)
        return failed

    def _complete_auto_physics_snap(self, initial: ResultEnvelope, timeout: float) -> ResultEnvelope:
        payload = dict(initial.result) if isinstance(initial.result, dict) else {}
        before_revision = payload.get("before_revision") or initial.scene_revision
        if payload.get("completed_synchronously"):
            initial.changed_entities = sorted(set(initial.changed_entities + ["scene.animation"]))
            return initial
        try:
            modal = resolve_autophysics_snap_warning(turn_off_single_use_features=True)
        except UIAutomationError as exc:
            failed = self._host_error(
                initial.feature_id,
                ErrorCode.POSTCONDITION_FAILED,
                "AutoPhysics produced no synchronous change and its confirmation could not be completed: " + str(exc),
            )
            failed.snapshot_id = initial.snapshot_id
            failed.scene_id = initial.scene_id
            failed.scene_revision = initial.scene_revision
            failed.evidence = list(initial.evidence)
            return failed

        deadline = time.monotonic() + max(1.0, timeout)
        latest = None
        while time.monotonic() < deadline:
            latest = self.client.execute("auto_physics", [Operation(name="system.status")], timeout=15)
            if latest.ok and latest.scene_revision and latest.scene_revision != before_revision:
                payload.update(
                    {
                        "after_revision": latest.scene_revision,
                        "completed_synchronously": False,
                        "confirmation_may_be_pending": False,
                        "confirmation_button": modal.button,
                    }
                )
                initial.result = payload
                initial.scene_id = latest.scene_id
                initial.scene_revision = latest.scene_revision
                initial.warnings = [
                    warning
                    for warning in initial.warnings
                    if warning != "Cascadeur may be waiting for the known AutoPhysics single-use-feature confirmation"
                ]
                initial.changed_entities = sorted(set(initial.changed_entities + ["scene.animation"]))
                initial.evidence.extend(latest.evidence)
                initial.evidence.append(
                    Evidence(
                        kind="host_ui_postcondition",
                        detail="; ".join(
                            (
                                f"Dismissed AutoPhysics {modal.window_title} with {modal.button}",
                                "scene revision changed",
                            )
                        ),
                        observed_at=modal.dismissed_at,
                    )
                )
                return initial
            time.sleep(0.1)
        failed = self._host_error(
            initial.feature_id,
            ErrorCode.POSTCONDITION_FAILED,
            "AutoPhysics confirmation closed but the animation revision did not change before timeout",
        )
        failed.snapshot_id = initial.snapshot_id
        failed.scene_id = latest.scene_id if latest else initial.scene_id
        failed.scene_revision = latest.scene_revision if latest else initial.scene_revision
        failed.evidence = list(initial.evidence)
        return failed

    @staticmethod
    def _file_signature(path: str | None) -> tuple[int, int] | None:
        if not path:
            return None
        candidate = Path(path)
        if not candidate.is_file():
            return None
        stat = candidate.stat()
        return stat.st_size, stat.st_mtime_ns

    def _wait_for_output_file(
        self,
        initial: ResultEnvelope,
        output_path: str,
        timeout: float,
        before_signature: tuple[int, int] | None,
    ) -> ResultEnvelope:
        path = Path(output_path)
        deadline = time.monotonic() + max(1.0, timeout)
        previous = None
        stable_observations = 0
        while time.monotonic() < deadline:
            signature = self._file_signature(output_path)
            if signature is not None and signature[0] > 0 and signature != before_signature:
                stable_observations = stable_observations + 1 if signature == previous else 1
                previous = signature
                if stable_observations >= 2:
                    payload = dict(initial.result) if isinstance(initial.result, dict) else {}
                    payload.update(
                        {
                            "path": str(path),
                            "bytes": signature[0],
                            "stable_observations": stable_observations,
                            "scheduled": False,
                        }
                    )
                    initial.result = payload
                    initial.evidence.append(
                        Evidence(
                            kind="host_file_postcondition",
                            detail=f"Output file became stable with {signature[0]} bytes",
                            observed_at=time.time(),
                        )
                    )
                    return initial
            time.sleep(0.2)
        failed = self._host_error(
            initial.feature_id,
            ErrorCode.POSTCONDITION_FAILED,
            f"Render output did not become stable before timeout: {output_path}",
        )
        failed.snapshot_id = initial.snapshot_id
        failed.scene_id = initial.scene_id
        failed.scene_revision = initial.scene_revision
        failed.evidence = list(initial.evidence)
        return failed

    def _wait_for_open_scene(self, initial: ResultEnvelope, expected_path: str, timeout: float) -> ResultEnvelope:
        deadline = time.monotonic() + max(1.0, timeout)
        expected = os.path.normcase(os.path.abspath(expected_path))
        expected_name = Path(expected_path).name.casefold()

        def window_evidence() -> str | None:
            return next(
                (title for title in cascadeur_window_titles() if expected_name and expected_name in title.casefold()),
                None,
            )

        def complete(observed_path: str, stable_observations: int, title: str | None) -> ResultEnvelope:
            initial.changed_entities = sorted(set(initial.changed_entities + ["scene"]))
            initial.result = {
                "path": observed_path,
                "loaded": True,
                "stable_observations": stable_observations,
            }
            if title:
                initial.result["window_title"] = title
                initial.evidence.append(
                    Evidence(
                        kind="host_window_postcondition",
                        detail=f"Cascadeur window shows loaded scene: {title}",
                        observed_at=time.time(),
                    )
                )
            return initial

        # The 2026.1 bridge verifies the active scene path synchronously after
        # load_scene returns. Cross-check that exact path with the native window
        # title instead of reopening the QML menu twice just to poll status.
        if isinstance(initial.result, dict) and initial.result.get("loaded"):
            observed_path = initial.result.get("path")
            observed = os.path.normcase(os.path.abspath(observed_path)) if observed_path else ""
            title = window_evidence()
            if observed == expected and title:
                return complete(str(observed_path), 2, title)

        previous_revision = None
        stable_observations = 0
        latest = None
        while time.monotonic() < deadline:
            latest = self.client.execute("scene_open", [Operation(name="system.status")], timeout=15)
            if latest.ok and isinstance(latest.result, dict):
                observed_path = latest.result.get("path")
                observed = os.path.normcase(os.path.abspath(observed_path)) if observed_path else ""
                if observed == expected:
                    revision = latest.result.get("revision")
                    title = window_evidence()
                    if title:
                        initial.scene_id = latest.scene_id
                        initial.scene_revision = latest.scene_revision
                        initial.evidence.extend(latest.evidence)
                        return complete(str(observed_path), 2, title)
                    stable_observations = stable_observations + 1 if revision == previous_revision else 1
                    previous_revision = revision
                    if stable_observations >= 2:
                        initial.scene_id = latest.scene_id
                        initial.scene_revision = latest.scene_revision
                        initial.evidence.extend(latest.evidence)
                        return complete(str(observed_path), stable_observations, None)
            time.sleep(0.1)
        failed = self._host_error(
            initial.feature_id,
            ErrorCode.POSTCONDITION_FAILED,
            f"Scene did not settle at expected path: {expected_path}",
        )
        failed.snapshot_id = initial.snapshot_id
        if latest is not None:
            failed.evidence = latest.evidence
        return failed

    def _snapshot_path(self, snapshot_id: str) -> Path | None:
        try:
            canonical = str(uuid.UUID(str(snapshot_id)))
        except (ValueError, TypeError, AttributeError):
            return None
        if canonical != str(snapshot_id).casefold():
            return None
        path = (self.paths.snapshots / f"{canonical}.casc").resolve()
        if path.parent != self.paths.snapshots.resolve() or not path.is_file():
            return None
        return path

    def prepare_rollback(self, snapshot_id: str, ttl: float = 300.0) -> dict[str, Any]:
        build_error = self._supported_build_error("change_rollback")
        if build_error:
            return build_error.model_dump(mode="json")
        path = self._snapshot_path(snapshot_id)
        if path is None:
            return self._host_error(
                "change_rollback", ErrorCode.INVALID_REQUEST, "Unknown snapshot"
            ).model_dump(mode="json")
        status = self.refresh_live()
        if not status.ok or not isinstance(status.result, dict):
            return status.model_dump(mode="json")
        state = status.result
        working_id = str(uuid.uuid4())
        operation = Operation(
            name="safety.rollback",
            arguments={"path": str(path), "working_id": working_id, "snapshot_id": snapshot_id},
        )
        impact = {
            "feature": "Rollback",
            "destructive": True,
            "snapshot_id": snapshot_id,
            "expected_result": "Replace the active document with a writable clone of the snapshot",
        }
        record = self.changes.prepare(
            feature_id="change_rollback",
            scene_id=state.get("scene_id"),
            scene_revision=state.get("revision"),
            selection_fingerprint=state.get("selection_fingerprint"),
            operation=operation,
            impact=impact,
            backup_path=str(path),
            ttl=ttl,
        )
        return {
            "ok": True,
            "confirmation_token": record.token,
            "feature_id": record.feature_id,
            "scene_id": record.scene_id,
            "scene_revision": record.scene_revision,
            "selection_fingerprint": record.selection_fingerprint,
            "operation": record.operation.model_dump(mode="json"),
            "impact": impact,
            "snapshot_id": snapshot_id,
            "working_id": working_id,
            "expires_at": record.expires_at,
        }

    def rollback(self, confirmation_token: str, timeout: float = 120.0) -> ResultEnvelope:
        try:
            record = self.changes.load(confirmation_token)
        except SafetyError as exc:
            return self._host_error("change_rollback", ErrorCode.INVALID_REQUEST, str(exc))
        if record.feature_id != "change_rollback" or record.operation.name != "safety.rollback":
            return self._host_error(
                "change_rollback", ErrorCode.INVALID_REQUEST, "Token is not bound to a rollback operation"
            )
        return self.commit_change(confirmation_token, timeout)

    def _rollback_internal(self, snapshot_id: str) -> ResultEnvelope:
        path = self._snapshot_path(snapshot_id)
        if path is None:
            return self._host_error("change_rollback", ErrorCode.INVALID_REQUEST, "Unknown snapshot")
        working_id = str(uuid.uuid4())
        working_path = (self.paths.snapshots / f"{working_id}.working.casc").resolve()
        result = self.client.execute(
            "change_rollback",
            [
                Operation(
                    name="safety.rollback_internal",
                    arguments={"path": str(path), "working_id": working_id},
                )
            ],
            timeout=120,
            safety_context=SafetyContext(destructive=True),
        )
        result.snapshot_id = snapshot_id
        if result.ok:
            result = self._wait_for_open_scene(result, str(working_path), 120)
        self._remember_scene_result(result)
        return result

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
