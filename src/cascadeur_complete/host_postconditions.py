"""Postconditions the host proves itself after a committed change: re-read writes, window
captures, output files, AutoPhysics completion and target-application imports."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from glob import escape as glob_escape
from pathlib import Path
from typing import Any

from .external import verify_blender_fbx
from .models import ErrorCode, Evidence, ExecutionMode, Operation, ResultEnvelope
from .uia import UIAutomationError, capture_window_sample, resolve_autophysics_snap_warning, sample_difference

# Writes whose values Cascadeur may re-solve after the transaction (AutoPosing,
# rig updates). The bridge verifies them inside its own request; the host
# re-reads a sample in a separate request so an override is not reported as
# success.
SETTLED_ROTATION_OPERATIONS = frozenset(
    {"animation.rotation_keys_set", "animation.transform_set", "animation.position_keys_set"}
)


SETTLED_POSITION_TOLERANCE = 0.05


SETTLED_SAMPLE_LIMIT = 64


# Cascadeur converts Euler input through float32; real overrides are tens of degrees.
SETTLED_TOLERANCE_DEGREES = 0.2


def euler_xyz_to_quaternion(euler: list[float]) -> list[float]:
    """Cascadeur's rotation_euler_xyz_radians (extrinsic x, y, z) as wxyz."""
    half = [value / 2.0 for value in euler]
    cx, cy, cz = (math.cos(value) for value in half)
    sx, sy, sz = (math.sin(value) for value in half)
    return [
        cx * cy * cz + sx * sy * sz,
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
    ]


def quaternion_angle_degrees(first: list[float], second: list[float]) -> float:
    dot = min(1.0, abs(sum(a * b for a, b in zip(first, second, strict=True))))
    return math.degrees(2.0 * math.acos(dot))


def settled_rotation_samples(operation_name: str, arguments: dict[str, Any], frame: int | None) -> list[tuple]:
    """(object id, frame, expected wxyz) pairs to re-read after a rotation write."""
    if operation_name == "animation.position_keys_set":
        writes = list(arguments.get("writes") or [])
        step = max(1, len(writes) // SETTLED_SAMPLE_LIMIT)
        return [
            (str(item["id"]), int(item["frame"]), [float(value) for value in item["position"]])
            for item in writes[::step][:SETTLED_SAMPLE_LIMIT]
        ]
    if operation_name == "animation.rotation_keys_set":
        writes = list(arguments.get("writes") or [])
        step = max(1, len(writes) // SETTLED_SAMPLE_LIMIT)
        return [
            (str(item["id"]), int(item["frame"]), euler_xyz_to_quaternion(item["rotation_euler_xyz_radians"]))
            for item in writes[::step][:SETTLED_SAMPLE_LIMIT]
        ]
    euler = arguments.get("rotation_euler_xyz_radians")
    ids = [str(item) for item in arguments.get("ids") or []]
    if euler is None or not ids or frame is None:
        return []
    expected = euler_xyz_to_quaternion([float(value) for value in euler])
    return [(object_id, int(arguments.get("frame", frame)), expected) for object_id in ids[:SETTLED_SAMPLE_LIMIT]]


# View toggles only change what Cascadeur draws; the host proves the effect by
# comparing captures of the Cascadeur window before and after the action.
VIEW_OPERATIONS = frozenset(
    {
        "view.silhouette",
        "view.isometric_grid",
        "view.composition",
        "view.trajectory",
        "view.trajectory_translate",
        "view.trajectory_rotate",
        "view.trajectory_direction",
        "view.trajectory_edit",
        "view.ballistic_ghosts",
        "view.fingers_drawing",
        "physics.autophysics_freeze",
        "view.ghost",
        "view.node_editor",
        "view.control_picker",
    }
)


VIEW_CHANGE_FRACTION = 0.002


# Operations whose success is a new or replaced file at arguments["path"]. Video
# output only runs as a UI file flow, which waits for its file in _execute_ui_file_flow.
OUTPUT_OPERATIONS = frozenset(
    {
        "render.viewport_capture",
        "render.image",
        "io.export_image",
        "io.export_fbx",
        "io.export_dae",
        "scene.save_as",
    }
)


# Postconditions verified by the host itself (file system, native windows,
# UI Automation or the persisted registry) after the bridge response.
HOST_POSTCONDITIONS = {
    **{operation: ("output_file", "nonzero_bytes") for operation in OUTPUT_OPERATIONS},
    "scene.open": ("stable_scene_path",),
    "scene.open_autosave": ("stable_scene_path",),
    "scene.activate": ("stable_scene_path",),
    "scene.new": ("stable_scene_path",),
    "safety.rollback": ("stable_scene_path",),
    "system.ui_file_flow": (
        "exact_file_dialog",
        "exact_options_window",
        "registered_uia_flow_token",
        "scene_revision_changed",
        "output_file",
        "nonzero_bytes",
    ),
    "system.action_invoke": ("registered_action_binding",),
    "physics.auto_snap": ("scene_revision_changed",),
    "system.introspect": ("feature_registry",),
    "io.export_fbx": ("output_file", "nonzero_bytes", "target_import_verified"),
    "timeline.playback": ("playback_frames_advance", "playback_frame_stable"),
    **{operation: ("viewport_render_changed",) for operation in VIEW_OPERATIONS},
}


def add_postconditions(result: ResultEnvelope, detail: str, *identifiers: str) -> None:
    """Record host-verified postconditions next to the bridge-asserted ones."""
    present = {str(item.get("id")) for item in result.postconditions if isinstance(item, dict)}
    for identifier in identifiers:
        if identifier not in present:
            result.postconditions.append({"id": identifier, "ok": True, "detail": detail})
            present.add(identifier)


@dataclass(frozen=True)
class CommitObservation:
    """What the host sampled just before running a prepared change."""

    timeout: float
    output: tuple[int, int] | None = None
    view: Any = None


def _operation_in(*names: str) -> Callable[[Any], bool]:
    wanted = frozenset(names)
    return lambda record: record.operation.name in wanted


# Host-side checks run in this order after a successful bridge response; each
# one returns the (possibly replaced) envelope or raises to fail the change.
HOST_POSTCONDITION_CHECKS: tuple[tuple[Callable[[Any], bool], str], ...] = (
    (_operation_in("scene.open"), "_await_opened_scene"),
    (_operation_in("scene.open_autosave"), "_await_opened_autosave"),
    (_operation_in("scene.activate", "scene.new"), "_await_target_tab"),
    (_operation_in("safety.rollback"), "_await_rollback_scene"),
    (_operation_in("physics.auto_snap"), "_await_auto_physics_snap"),
    (_operation_in(*SETTLED_ROTATION_OPERATIONS), "_check_settled_writes"),
    (lambda record: record.feature_id == "blender_export", "_check_blender_import"),
    (_operation_in(*VIEW_OPERATIONS), "_check_view_changed"),
    (_operation_in("timeline.playback"), "_check_playback_state"),
    (_operation_in(*OUTPUT_OPERATIONS), "_await_output_file"),
)


class HostPostconditionsMixin:
    """CascadeurService methods; they rely on the service's state and helpers."""

    def _observe_before_commit(self, record, timeout: float) -> CommitObservation:
        output_path = record.operation.arguments.get("path")
        view = None
        if record.operation.name in VIEW_OPERATIONS:
            self._wait_for_bridge_idle()
            view = capture_window_sample()
        return CommitObservation(
            timeout=timeout,
            output=self._file_signature(output_path) if output_path else None,
            view=view,
        )

    def _apply_host_postconditions(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        for matches, check in HOST_POSTCONDITION_CHECKS:
            if result.ok and matches(record):
                result = getattr(self, check)(record, result, observed)
        return result

    def _await_opened_scene(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        return self._wait_for_open_scene(result, str(record.operation.arguments["path"]), observed.timeout)

    def _await_opened_autosave(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        return self._wait_for_open_scene(result, str(result.result["path"]), observed.timeout)

    def _await_target_tab(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        payload = result.result if isinstance(result.result, dict) else {}
        if not payload.get("tab_id"):
            raise RuntimeError("Scene change result does not identify the target tab")
        return self._wait_for_open_scene(
            result, str(payload.get("path") or ""), observed.timeout, expected_tab_id=str(payload["tab_id"])
        )

    def _await_rollback_scene(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        working_path = self.paths.snapshots / (str(record.operation.arguments["working_id"]) + ".working.casc")
        return self._wait_for_open_scene(result, str(working_path), observed.timeout)

    def _await_auto_physics_snap(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        return self._complete_auto_physics_snap(result, observed.timeout)

    def _check_settled_writes(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        checked = self._verify_settled_rotations(record, result)
        if checked:
            add_postconditions(
                result,
                f"{checked} written value(s) re-read unchanged in a separate request",
                "rotations_persist_after_update",
            )
        return result

    def _check_blender_import(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        report = verify_blender_fbx(str(record.operation.arguments["path"]))
        if report["armatures"] < 1 or not report["actions"]:
            raise RuntimeError(f"Blender imported no armature/animation: {report}")
        result.result = {**(result.result if isinstance(result.result, dict) else {}), "blender": report}
        add_postconditions(
            result,
            f"Blender {report['blender']} imported {report['armatures']} armature(s), "
            f"{report['bones']} bones and {len(report['actions'])} action(s)",
            "target_import_verified",
        )
        return result

    def _check_view_changed(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        self._wait_for_bridge_idle()
        time.sleep(1.0)
        changed = sample_difference(observed.view, capture_window_sample())
        if changed < VIEW_CHANGE_FRACTION:
            raise RuntimeError(f"the rendered window did not change after the view action ({changed:.4%})")
        add_postconditions(result, f"{changed:.2%} of sampled window pixels changed", "viewport_render_changed")
        return result

    def _check_playback_state(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        wants_play = record.operation.arguments.get("state") == "play"
        moving = self._playback_moving()
        if moving is None or moving != wants_play:
            raise RuntimeError("playhead motion after the toggle does not match the requested state")
        add_postconditions(
            result,
            "Playhead sampled twice after the UI thread was released",
            "playback_frames_advance" if wants_play else "playback_frame_stable",
        )
        return result

    def _await_output_file(self, record, result: ResultEnvelope, observed: CommitObservation) -> ResultEnvelope:
        return self._wait_for_output_file(
            result,
            str(record.operation.arguments["path"]),
            observed.timeout,
            observed.output,
        )

    def _verify_settled_rotations(self, record, result: ResultEnvelope) -> int:
        payload = result.result if isinstance(result.result, dict) else {}
        frame = payload.get("frame") if isinstance(payload, dict) else None
        samples = settled_rotation_samples(record.operation.name, dict(record.operation.arguments), frame)
        if not samples:
            return 0
        is_position = record.operation.name == "animation.position_keys_set"
        default_space = "global" if is_position else "local"
        space = str(record.operation.arguments.get("space", default_space))
        time.sleep(0.3)
        by_frame: dict[int, list[tuple[str, list[float]]]] = {}
        for object_id, sample_frame, expected in samples:
            by_frame.setdefault(sample_frame, []).append((object_id, expected))
        operations = [
            Operation(
                name="animation.transform_get",
                arguments={"ids": [item[0] for item in items], "frame": sample_frame, "space": space},
            )
            for sample_frame, items in sorted(by_frame.items())
        ]
        reread = self.client.execute("transform_get", operations, timeout=120)
        if not reread.ok:
            raise RuntimeError(f"settled read-back failed: {reread.error_code}: {reread.error_message}")
        rows = reread.result if len(operations) > 1 else [{"result": reread.result}]
        worst = (0.0, None, None)
        for (sample_frame, items), row in zip(sorted(by_frame.items()), rows, strict=True):
            skipped = {str(item) for item in record.operation.arguments.get("rig_solved_ids") or []}
            for item in row["result"]:
                object_id = str(item["id"])
                expected = dict(items).get(object_id)
                if expected is None or object_id in skipped:
                    continue
                if is_position:
                    error = max(abs(a - b) for a, b in zip(item["position"], expected, strict=True))
                else:
                    error = quaternion_angle_degrees(expected, item["rotation"]["quaternion_wxyz"])
                if error > worst[0]:
                    worst = (error, object_id, sample_frame)
        if is_position:
            requested = float(record.operation.arguments.get("tolerance_cm", 0.0) or 0.0)
            tolerance, unit = max(SETTLED_POSITION_TOLERANCE, min(requested, 10.0)), "cm"
        else:
            tolerance, unit = SETTLED_TOLERANCE_DEGREES, "deg"
        if worst[0] > tolerance:
            raise RuntimeError(
                f"written value did not persist: {worst[1]} at frame {worst[2]} differs by {worst[0]:.2f} {unit} "
                "after the update (AutoPosing or the rig re-solved it)"
            )
        return len(samples)

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
            self._wait_for_bridge_idle()
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
                add_postconditions(
                    initial, "Scene revision changed after the AutoPhysics confirmation", "scene_revision_changed"
                )
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

    def _wait_for_rendered_video(
        self, initial: ResultEnvelope, stem_path: Path, timeout: float, started: float
    ) -> ResultEnvelope:
        """Wait for the file Cascadeur renders under the requested name (extension set by its format)."""
        deadline = time.monotonic() + max(1.0, timeout)
        while time.monotonic() < deadline:
            candidates = sorted(
                (
                    item
                    for item in stem_path.parent.glob(glob_escape(stem_path.name) + ".*")
                    if item.is_file() and item.stat().st_mtime >= started - 1.0
                ),
                key=lambda item: item.stat().st_mtime,
            )
            if candidates:
                remaining = max(1.0, deadline - time.monotonic())
                return self._wait_for_output_file(initial, str(candidates[-1]), remaining, None, stable_seconds=3.0)
            time.sleep(0.5)
        return self._host_error(
            initial.feature_id,
            ErrorCode.POSTCONDITION_FAILED,
            f"No rendered video named {stem_path.name}.* appeared in {stem_path.parent}",
            mode=ExecutionMode.UIA,
        )

    def _wait_for_output_file(
        self,
        initial: ResultEnvelope,
        output_path: str,
        timeout: float,
        before_signature: tuple[int, int] | None,
        *,
        stable_seconds: float = 0.0,
    ) -> ResultEnvelope:
        path = Path(output_path)
        deadline = time.monotonic() + max(1.0, timeout)
        previous = None
        stable_observations = 0
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            signature = self._file_signature(output_path)
            if signature is not None and signature[0] > 0 and signature != before_signature:
                if signature != previous:
                    stable_since = time.monotonic()
                stable_observations = stable_observations + 1 if signature == previous else 1
                previous = signature
                if stable_observations >= 2 and time.monotonic() - stable_since >= stable_seconds:
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
                    add_postconditions(
                        initial,
                        f"Output file became stable with {signature[0]} bytes",
                        "output_file",
                        "nonzero_bytes",
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
