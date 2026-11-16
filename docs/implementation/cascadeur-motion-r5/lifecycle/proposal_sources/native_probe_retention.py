"""Finite qualifier retention; no wire operation or cleanup command.

Reserve one observation per qualifier kind in one process, keep native tabs,
and never import qualification proof from disk.
Native heap allocation is not bounded by this Python bookkeeping.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

_ATTEMPTS = {}
_LIMITS = {
    "native_adapter": {"new_tabs": 2, "files": 5},
    "finite_models": {"new_tabs": 1, "files": 2},
    "position_writer": {"new_tabs": 1, "files": 2},
}
_SETUP_OPERATIONS = {
    "native_adapter": "setup.qualify_native_adapter",
    "finite_models": "setup.qualify_independent_models",
    "position_writer": "setup.qualify_independent_position_writer",
}


def _copy(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _context():
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    guards.assert_loaded_package()
    return (guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT, installed_build())


def retained_probe_result(kind):
    """Return only this process's prior returned observation; never rerun it."""
    context = _context()
    previous = _ATTEMPTS.get(kind)
    if previous is None:
        return None
    if previous.context != context:
        raise ValueError("QUALIFICATION_CONTEXT_CHANGED: clean runtime restart required")
    if previous.result is not None:
        return {**_copy(previous.result), "reused": True}
    raise ValueError("QUALIFICATION_ATTEMPT_RETAINED: inspect " + str(previous.directory))


class RetainedProbe:
    """Retain one bounded fixture set; close/delete is an explicit user action."""

    def __init__(self, kind):
        import csc
        from . import runtime as rt
        from . import guarded_runtime as guards
        from . import incident_admission
        from .native_scene_reader import read_scene
        if kind not in _LIMITS:
            raise ValueError("Unknown internal qualification kind")
        if kind in _ATTEMPTS:
            raise ValueError("QUALIFICATION_ATTEMPT_RETAINED: inspect " + str(_ATTEMPTS[kind].directory))
        self.setup_invocation_ref = getattr(guards._LOCAL, "setup_invocation_ref", None)
        self.setup_operation = _SETUP_OPERATIONS[kind]
        # The dispatcher claimed this immutable invocation once. This call only
        # rechecks its current helper step, native thread and resource revision.
        admission = incident_admission.assert_setup_admission(self.setup_operation, self.setup_invocation_ref)
        self.context = _context()
        self.manager = csc.app.get_application().get_scene_manager()
        self.previous = self.manager.current_scene()
        if self.previous is None or rt._domain_scene(self.previous).model_viewer().get_objects():
            raise ValueError("QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE")
        self.inventory = list(self.manager.scenes())
        if not any(item is self.previous for item in self.inventory):
            raise ValueError("QUALIFICATION_ORIGINAL_SCENE_UNOBSERVED")
        self.original_projection = read_scene(self.previous)
        self.original_path = str(self.previous.get_path_name())
        self.kind = kind
        self.limit = _LIMITS[kind]
        self.directory = Path(admission["workspace_path"]).resolve()
        if (self.directory.parent != (rt.runtime_root() / "snapshots").resolve()
                or type(admission["maximum_new_tabs"]) is not int
                or type(admission["maximum_casc_files"]) is not int
                or admission["maximum_new_tabs"] < self.limit["new_tabs"]
                or admission["maximum_casc_files"] < self.limit["files"]):
            raise ValueError("QUALIFICATION_SETUP_SCOPE_MISMATCH")
        self.directory.mkdir()
        self.identified = []
        self.finished = False
        self.retention_ok = False
        self.result = None
        self.public = {
            "schema_version": 1, "qualification_id": str(uuid.uuid4()), "kind": kind,
            "runtime_epoch": self.context[0], "runtime_fingerprint": self.context[1],
            "native_build": self.context[2], "retention_policy": "retain_qualification_tabs_and_files",
            "retained_directory": str(self.directory), "retention_status": "pending",
            "maximum_new_tabs": self.limit["new_tabs"], "maximum_casc_files": self.limit["files"],
            "original_scene_instance_id": guards.scene_instance(self.previous)["scene_instance_id"],
            "original_path": self.original_path, "retained_tabs": [], "saved_files": [],
            "attempted_files": [], "errors": [],
        }
        _ATTEMPTS[kind] = self

    def track(self, scene, role):
        from . import guarded_runtime as guards
        if self.finished or any(scene is item for item in self.inventory):
            raise ValueError("QUALIFICATION_SCENE_OWNERSHIP_UNAVAILABLE")
        if not any(scene is item for item in self.manager.scenes()):
            raise ValueError("QUALIFICATION_SCENE_UNOBSERVED")
        if any(scene is item[0] for item in self.identified):
            return
        if len(self.identified) >= self.limit["new_tabs"]:
            raise ValueError("QUALIFICATION_TAB_LIMIT_EXCEEDED")
        self.identified.append((scene, role, dict(guards.scene_instance(scene))))

    def record_file(self, manifest):
        path = Path(manifest["path"]).resolve()
        if (self.finished or path.parent != self.directory.resolve() or path.suffix.lower() != ".casc"
                or len(self.public["saved_files"]) >= self.limit["files"]
                or any(item["path"] == manifest["path"] for item in self.public["saved_files"])):
            raise ValueError("QUALIFICATION_FILE_SCOPE_UNAVAILABLE")
        self.public["saved_files"].append(_copy(manifest))

    def save_fixture(self, scene, name, reader):
        """Only the normal path saves; failure finalization never invokes save."""
        from .native_adapters import _save_observed
        from . import incident_admission
        if (self.finished or name not in {"fixture-before.casc", "fixture-after.casc"}
                or name in self.public["attempted_files"]
                or not any(scene is item[0] for item in self.identified)
                or len(self.public["attempted_files"]) >= self.limit["files"]):
            raise ValueError("QUALIFICATION_FILE_SCOPE_UNAVAILABLE")
        incident_admission.assert_setup_admission(self.setup_operation, self.setup_invocation_ref)
        before = reader(scene)
        self.public["attempted_files"].append(name)
        manifest = _save_observed(scene, self.directory / name)
        self.record_file(manifest)
        if reader(scene) != before:
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: qualification fixture changed during save")
        return manifest

    def finish(self, error=None):
        """Restore the original active empty tab; preserve every remaining tab."""
        from .native_scene_reader import read_scene
        from .native_fixture import _OWNED
        if self.finished:
            raise ValueError("QUALIFICATION_RETENTION_ALREADY_FINISHED")
        self.finished = True
        problems = []
        try:
            if _context() != self.context:
                raise ValueError("QUALIFICATION_CONTEXT_CHANGED")
            live = list(self.manager.scenes())
            if not any(item is self.previous for item in live):
                raise ValueError("QUALIFICATION_ORIGINAL_SCENE_REMOVED")
            # Never dereference a wrapper which is absent from the live inventory.
            self.manager.set_current_scene(self.previous)
            live = list(self.manager.scenes())
            original_present = all(any(item is value for value in live) for item in self.inventory)
            original_preserved = (
                original_present and self.manager.current_scene() is self.previous
                and str(self.previous.get_path_name()) == self.original_path
                and read_scene(self.previous) == self.original_projection
            )
            self.public["original_inventory_preserved"] = original_present
            self.public["original_active_projection_preserved"] = original_preserved
            if not original_preserved:
                problems.append("QUALIFICATION_ORIGINAL_SCENE_CHANGED")
            new_tabs = [item for item in live if not any(item is value for value in self.inventory)]
            self.public["new_tab_count"] = len(new_tabs)
            if len(new_tabs) > self.limit["new_tabs"]:
                problems.append("QUALIFICATION_TAB_LIMIT_EXCEEDED")
            # An unexpected tab is retained but is never claimed as owned.
            for scene in new_tabs[: self.limit["new_tabs"] + 1]:
                known = next((item for item in self.identified if item[0] is scene), None)
                row = {"role": "unidentified_new_tab", "ownership": "unverified", "path": None}
                if known is not None:
                    row = {"role": known[1], "ownership": "identified_qualification_tab", **known[2],
                           "path": str(scene.get_path_name())}
                else:
                    problems.append("QUALIFICATION_NEW_TAB_UNIDENTIFIED")
                self.public["retained_tabs"].append(row)
            for scene, role, identity in self.identified:
                if not any(scene is value for value in live):
                    problems.append("QUALIFICATION_IDENTIFIED_SCENE_REMOVED: " + role)
            self.retention_ok = not problems
        except Exception as observation_error:
            problems.append(str(observation_error)[:1000])
        finally:
            # Relinquish only the fixture-authoring helper's Python references.
            # Native tabs/files and guarded_runtime scene identities remain.
            for scene, _role, _identity in self.identified:
                owned = _OWNED.get(id(scene))
                if owned is not None and owned["scene"] is scene:
                    _OWNED.pop(id(scene))
            self.public["errors"] = problems
            self.public["retention_status"] = "observed" if self.retention_ok else "unverified"
            self.public["qualification_error"] = None if error is None else str(error)[:1000]
            try:
                payload = json.dumps(self.public, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                with (self.directory / "retention.json").open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception as record_error:
                self.retention_ok = False
                problems.append("QUALIFICATION_RETENTION_RECORD_FAILED: " + str(record_error)[:1000])
            self.manager = self.previous = self.original_projection = None
            self.inventory = []
            self.identified = []
        if error is not None:
            error.add_note("Retained qualification directory: " + str(self.directory))
            for problem in problems:
                error.add_note(problem)
        elif not self.retention_ok:
            raise ValueError("QUALIFICATION_RETENTION_UNVERIFIED: " + "; ".join(problems))
        return _copy(self.public)

    def complete(self, result):
        """Cache a returned result only after existing proof publication succeeds."""
        if not self.finished or not self.retention_ok:
            raise ValueError("QUALIFICATION_RETENTION_UNVERIFIED")
        self.result = _copy(result)
        return _copy(self.result)
