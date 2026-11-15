"""Target-side verification for external DCC workflows.

An external route only counts when the target application accepted the data.
For Blender this means a background Blender process imported the exported FBX
and reported armatures, meshes and animation actions.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from .export_models import ArtifactRef, ExportExpectation, ExportProfile, ValidationReport
from .export_publisher import canonical_digest, write_immutable_json
from .fbx_validation import file_sha256

BLENDER_DEPENDENCY = "Blender integration"
_MARKER = "CASCADEUR_COMPLETE_BLENDER_REPORT="
_SCRIPT = r"""
import bpy, json, sys
path = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=path)
armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
report = {
    "objects": len(bpy.data.objects),
    "armatures": len(armatures),
    "bones": sum(len(o.data.bones) for o in armatures),
    "meshes": sum(1 for o in bpy.data.objects if o.type == "MESH"),
    "actions": [
        {"name": a.name, "frame_range": [float(a.frame_range[0]), float(a.frame_range[1])]}
        for a in bpy.data.actions
    ],
    "blender": bpy.app.version_string,
}
print("CASCADEUR_COMPLETE_BLENDER_REPORT=" + json.dumps(report))
"""


def find_blender() -> Path | None:
    """Return the newest installed Blender executable, if any."""
    configured = os.environ.get("CASCADEUR_MCP_BLENDER")
    if configured and Path(configured).is_file():
        return Path(configured)
    root = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Blender Foundation"
    candidates = []
    for folder in root.glob("Blender *"):
        executable = folder / "blender.exe"
        match = re.search(r"(\d+)\.(\d+)", folder.name)
        if executable.is_file() and match:
            candidates.append(((int(match.group(1)), int(match.group(2))), executable))
    return max(candidates)[1] if candidates else None


def available_dependencies() -> set[str]:
    return {BLENDER_DEPENDENCY} if find_blender() else set()


def verify_blender_fbx(path: str, timeout: float = 240.0) -> dict:
    """Import an FBX into a background Blender and return what Blender observed."""
    blender = find_blender()
    if blender is None:
        raise RuntimeError("Blender is not installed")
    completed = subprocess.run(
        [str(blender), "--background", "--factory-startup", "--python-expr", _SCRIPT, "--", str(path)],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=0x08000000 if os.name == "nt" else 0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Blender import failed with exit code {completed.returncode}: "
                           + (completed.stderr or completed.stdout)[-1500:])
    line = next((item for item in completed.stdout.splitlines() if item.startswith(_MARKER)), None)
    if line is None:
        raise RuntimeError("Blender did not report an import result: " + (completed.stderr or completed.stdout)[-1500:])
    report = json.loads(line[len(_MARKER) :])
    report["executable"] = str(blender)
    report["verification_grade"] = "legacy_import_observed"
    return report


def blender_export_adapter_fingerprint() -> str:
    return file_sha256(Path(__file__).with_name("blender_export_adapter.py"))


def _run_target_process(arguments, directory, *, timeout, max_log_bytes, cancel):
    """Bounded output and timeout; never execute caller-provided Python or a shell."""
    deadline = time.monotonic() + timeout
    log = directory / "blender.log"
    with log.open("xb") as stream:
        process = subprocess.Popen(arguments, stdout=stream, stderr=subprocess.STDOUT, shell=False,
                                   creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            while process.poll() is None:
                if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
                    raise RuntimeError("TARGET_VALIDATION_CANCELLED")
                if log.stat().st_size > max_log_bytes:
                    raise RuntimeError("TARGET_LOG_BUDGET_EXCEEDED")
                if time.monotonic() >= deadline:
                    raise RuntimeError("TARGET_VALIDATION_TIMEOUT")
                time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
            if log.stat().st_size > max_log_bytes:
                raise RuntimeError("TARGET_LOG_BUDGET_EXCEEDED")
            return process.returncode
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def validate_target_import(sealed_fbx: ArtifactRef, profile: ExportProfile, expected: ExportExpectation,
                           timeout: float = 240, cancel=None, *, roundtrip_validator=None) -> ValidationReport:
    """Compare actual imported joint motion and require the common quality gate.

    ``roundtrip_validator(capture, expected, profile)`` is an internal adapter to
    motion_quality.validate_export_roundtrip with the original intent/supports/
    policy. Without that context the artifact remains unverified.
    """
    def result(status, code, *, checks=(), capture=None):
        return ValidationReport(status=status, artifact_sha256=sealed_fbx.sha256,
                                reason_codes=(code,) if code else (), checks=checks,
                                coverage="sampled_frames", capture=capture)

    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("Target validation timeout must be finite and positive")
    blender = find_blender()
    if blender is None:
        return result("unverified", "ROUNDTRIP_ADAPTER_UNAVAILABLE")
    settings = profile.target_import_settings
    if profile.target_adapter != "blender_fbx_classic_v1" or settings is None:
        return result("unsupported", "TARGET_ADAPTER_PROFILE_UNAVAILABLE")
    if profile.target_adapter_fingerprint != blender_export_adapter_fingerprint():
        return result("unsupported", "TARGET_ADAPTER_FINGERPRINT_MISMATCH")
    if canonical_digest(settings) != profile.target_import_settings_digest:
        return result("fail", "TARGET_IMPORT_SETTINGS_MISMATCH")
    if tuple(settings.blender_version[:2]) not in ((4, 2), (4, 3), (4, 5)):
        return result("unsupported", "TARGET_ACTION_ADAPTER_UNSUPPORTED")
    if settings.blender_executable_sha256 is None or settings.importer_fingerprint is None:
        return result("unverified", "TARGET_INSTALLED_BYTES_UNBOUND")
    if file_sha256(blender, 512 * 1024**2) != settings.blender_executable_sha256:
        return result("unsupported", "TARGET_EXECUTABLE_FINGERPRINT_MISMATCH")
    if file_sha256(sealed_fbx.path, sealed_fbx.bytes) != sealed_fbx.sha256:
        return result("fail", "ARTIFACT_CHANGED")
    directory = Path(tempfile.mkdtemp(prefix="target-", dir=Path(sealed_fbx.path).parent))
    report_path, nonce = directory / "capture.json", secrets.token_hex(24)
    manifest = {"schema_version": 1, "nonce": nonce, "artifact": sealed_fbx.model_dump(mode="json"),
                "profile": profile.model_dump(mode="json"), "expected": expected.model_dump(mode="json"),
                "report_path": str(report_path)}
    manifest_path = directory / "manifest.json"
    write_immutable_json(manifest_path, manifest)
    adapter = Path(__file__).with_name("blender_export_adapter.py")
    try:
        returncode = _run_target_process([str(blender), "--background", "--factory-startup", "--python", str(adapter),
                                          "--", str(manifest_path)], directory, timeout=timeout,
                                         max_log_bytes=settings.max_log_bytes, cancel=cancel)
        if returncode != 0:
            return result("fail", "TARGET_PROCESS_FAILED",
                          checks=({"id": "target_process_exit", "ok": False, "returncode": returncode,
                                   "log": str(directory / "blender.log")},))
        if not report_path.is_file() or report_path.stat().st_size > settings.max_report_bytes:
            return result("fail", "TARGET_REPORT_MISSING_OR_OVERSIZED")
        observed = json.loads(report_path.read_text(encoding="utf-8"))
        fields = {"schema_version", "nonce", "artifact_sha256", "adapter_fingerprint", "blender_version",
                  "settings_digest", "actions", "capture"}
        if (set(observed) != fields or observed["schema_version"] != 1 or observed["nonce"] != nonce
                or observed["artifact_sha256"] != sealed_fbx.sha256
                or observed["adapter_fingerprint"] != profile.target_adapter_fingerprint
                or observed["blender_version"] != list(settings.blender_version)
                or observed["settings_digest"] != profile.target_import_settings_digest):
            return result("fail", "TARGET_REPORT_IDENTITY_MISMATCH")
        capture = observed["capture"]
        checks = _compare_target_capture(capture, expected, profile)
        if any(not item["ok"] for item in checks):
            return result("fail", "EXPORT_MOTION_QUALITY_FAILED", checks=tuple(checks), capture=capture)
        if roundtrip_validator is None:
            return result("unverified", "ROUNDTRIP_QUALITY_CONTEXT_UNAVAILABLE", checks=tuple(checks), capture=capture)
        quality = roundtrip_validator(capture, expected, profile)
        quality = quality.as_dict() if hasattr(quality, "as_dict") else quality
        # The common checker must actually measure every requested metric. A
        # caller cannot bypass it by returning a bare True or an empty pass.
        if (not isinstance(quality, dict) or quality.get("status") != "pass"
                or not quality.get("runtime_verified")
                or not quality.get("capture_digest")
                or any(not isinstance(quality.get("metrics", {}).get(name), dict)
                       or quality["metrics"][name].get("status") != "measured"
                       or quality["metrics"][name].get("sample_count", 0) <= 0
                       or quality["metrics"][name].get("pass") is not True
                       for name in expected.required_metrics)):
            status = "fail" if isinstance(quality, dict) and quality.get("status") == "fail" else "unverified"
            return result(status, "EXPORT_ROUNDTRIP_QUALITY_INCOMPLETE", checks=tuple(checks), capture=capture)
        checks.append({"id": "original_intent_roundtrip", "ok": True, "quality_report": quality,
                       "capture_sha256": canonical_digest(capture), "source_capture_digest": expected.source_capture_digest})
        return result("pass", None, checks=tuple(checks), capture=capture)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        return result("fail", "TARGET_VALIDATION_FAILED", checks=({"id": "target_validation", "ok": False,
                                                                   "detail": str(exc)[:1000]},))


def _compare_target_capture(capture: dict, expected: ExportExpectation, profile: ExportProfile) -> list[dict]:
    checks = []
    times = np.asarray(capture.get("time_s", []), dtype=float)
    expected_times = np.asarray(expected.time_s)
    if times.shape != expected_times.shape or not np.array_equal(times, expected_times):
        return [{"id": "target_time_grid", "ok": False}]
    for field in ("position_m", "rotation_delta_wxyz", "parent_paths"):
        if set(capture.get(field, {})) != set(getattr(expected, field)):
            return [{"id": "target_coverage", "ok": False, "field": field}]
    if capture["parent_paths"] != expected.parent_paths:
        return [{"id": "target_topology", "ok": False}]
    position_errors, rotation_errors = [], []
    worst_position = worst_rotation = None
    for path, source in expected.position_m.items():
        target = np.asarray(capture["position_m"][path], dtype=float)
        source = np.asarray(source)
        if target.shape != source.shape or not np.isfinite(target).all():
            return [{"id": "target_position_coverage", "ok": False, "path": path}]
        errors = np.linalg.norm(target - source, axis=1)
        if not position_errors or errors.max() > max(position_errors):
            worst_position = {"path": path, "sample": int(np.argmax(errors))}
        position_errors.extend(errors)
        target = np.asarray(capture["rotation_delta_wxyz"][path], dtype=float)
        source = np.asarray(expected.rotation_delta_wxyz[path])
        if (target.shape != source.shape or not np.isfinite(target).all()
                or np.any(np.abs(np.linalg.norm(target, axis=1) - 1) > 1e-3)):
            return [{"id": "target_rotation_coverage", "ok": False, "path": path}]
        errors = 2 * np.arccos(np.clip(np.abs(np.sum(target * source, axis=1)), 0, 1))
        if not rotation_errors or errors.max() > max(rotation_errors):
            worst_rotation = {"path": path, "sample": int(np.argmax(errors))}
        rotation_errors.extend(errors)
    for name, errors, limit, worst in (("target_position_m", position_errors, profile.tolerances.position_m, worst_position),
                                       ("target_rotation_rad", rotation_errors, profile.tolerances.rotation_rad, worst_rotation)):
        checks.append({"id": name, "ok": bool(errors) and max(errors) <= limit,
                       "max": float(max(errors)) if errors else None,
                       "p95": float(np.percentile(errors, 95)) if errors else None,
                       "limit": limit, "worst": worst, "sample_count": len(errors)})
    if profile.include_mesh and set(capture.get("mesh", {})) != set(profile.mesh_refs):
        checks.append({"id": "target_mesh_coverage", "ok": False})
    return checks
