"""Retain finite qualification fixtures without granting native authority.

Only the authenticated setup dispatcher can supply admission. Process-local
attempts prevent automatic replay; disk diagnostics never reconstruct proof.
These bookkeeping limits are not a hard bound on native heap allocation.
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
    "geometry_calculation": {"new_tabs": 1, "files": 2},
    "owned_pair_geometry": {"new_tabs": 2, "files": 5},
}
_SETUP_OPERATIONS = {
    "native_adapter": "setup.qualify_native_adapter",
    "finite_models": "setup.qualify_independent_models",
    "position_writer": "setup.qualify_independent_position_writer",
    "geometry_calculation": "setup.qualify_geometry_calculation",
    "owned_pair_geometry": "setup.qualify_owned_pair_geometry",
}
_FILENAMES = {
    "native_adapter": {"source.casc", "backup.casc", "working.casc", "next-backup.casc", "next-working.casc"},
    "finite_models": {"fixture-before.casc", "fixture-after.casc"},
    "position_writer": {"fixture-before.casc", "fixture-after.casc"},
    "geometry_calculation": {"fixture-before.casc", "fixture-after.casc"},
    "owned_pair_geometry": {"fixture-before.casc", "fixture-after.casc", "checkpoint.casc",
                            "checkpoint-working.casc", "checkpoint-restored.casc"},
}


def _copy(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _context():
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    guards.assert_loaded_package()
    return guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT, installed_build()


def retained_probe_result(kind):
    """Query only a previously returned result, never replay a native attempt."""
    if kind not in _LIMITS:
        raise ValueError("Unknown internal qualification kind")
    previous = _ATTEMPTS.get(kind)
    if previous is None:
        return None
    if previous.context != _context():
        raise ValueError("QUALIFICATION_CONTEXT_CHANGED: clean runtime restart required")
    if previous.result is not None:
        return {**_copy(previous.result), "reused": True}
    raise ValueError("QUALIFICATION_ATTEMPT_RETAINED: inspect " + str(previous.directory))


class RetainedProbe:
    """One code-owned, bounded fixture set; never close or delete a tab/file."""

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
        self.setup_operation = _SETUP_OPERATIONS[kind]
        admission = incident_admission.assert_setup_admission(self.setup_operation)
        self.context = _context()
        self.kind, self.limit = kind, dict(_LIMITS[kind])
        self.directory = Path(admission.workspace_path).resolve()
        self.grant_limits = admission.maximum_new_tabs, admission.maximum_casc_files
        if (self.directory.parent.parent != (rt.runtime_root() / "snapshots").resolve()
                or self.directory.name not in {"0", "1", "2", "3"}
                or any(type(value) is not int for value in self.grant_limits)
                or self.grant_limits[0] < self.limit["new_tabs"]
                or self.grant_limits[1] < self.limit["files"]):
            raise ValueError("QUALIFICATION_SETUP_SCOPE_MISMATCH")
        self.manager = csc.app.get_application().get_scene_manager()
        self.inventory = list(self.manager.scenes())
        self.previous = self.manager.current_scene()
        if self.previous is None or not any(item is self.previous for item in self.inventory):
            raise ValueError("QUALIFICATION_ORIGINAL_SCENE_UNOBSERVED")
        if rt._domain_scene(self.previous).model_viewer().get_objects():
            raise ValueError("QUALIFICATION_REQUIRES_EMPTY_CURRENT_SCENE")
        self.original_projection = _copy(read_scene(self.previous))
        self.original_path = str(self.previous.get_path_name())
        # Capture these references in the request-private guard, rather than
        # retaining native wrappers in the cached result after the step ends.
        manager, previous = self.manager, self.previous
        inventory, paths = tuple(self.inventory), tuple(str(item.get_path_name()) for item in self.inventory)
        original_projection, original_path, context = self.original_projection, self.original_path, self.context
        def original_unchanged():
            live = list(manager.scenes())
            if (context != _context()
                    or not all(any(item is value for item in live) for value in inventory)
                    or tuple(str(item.get_path_name()) for item in inventory) != paths
                    or str(previous.get_path_name()) != original_path
                    or read_scene(previous) != original_projection):
                raise ValueError("QUALIFICATION_ORIGINAL_SCENE_CHANGED")
        incident_admission._bind_setup_source_guard(self.setup_operation, original_unchanged)
        self.identified, self.finished, self.retention_ok, self.result = [], False, False, None
        self.public = {
            "schema_version": 1, "qualification_id": str(uuid.uuid4()), "kind": kind,
            "runtime_epoch": self.context[0], "runtime_fingerprint": self.context[1], "native_build": self.context[2],
            "retention_policy": "retain_qualification_tabs_and_files", "retained_directory": str(self.directory),
            "retention_status": "pending", "maximum_new_tabs": self.limit["new_tabs"],
            "maximum_casc_files": self.limit["files"],
            "original_scene_instance_id": guards.scene_instance(self.previous)["scene_instance_id"],
            "original_path": self.original_path, "retained_tabs": [], "saved_files": [],
            "attempted_files": [], "errors": [],
        }
        self.before_effect()
        # Reserve the attempt before the first filesystem effect. A collision
        # cannot trigger a new UUID/workspace or another native attempt.
        _ATTEMPTS[kind] = self
        self.directory.mkdir()
        incident_admission.assert_setup_admission(self.setup_operation)

    def before_effect(self):
        """Recheck the claimed helper; this never claims/consumes another token."""
        from . import incident_admission
        admission = incident_admission.assert_setup_admission(self.setup_operation)
        if (self.context != _context() or Path(admission.workspace_path).resolve() != self.directory
                or (admission.maximum_new_tabs, admission.maximum_casc_files) != self.grant_limits
                or (self.finished and not self.retention_ok)):
            raise ValueError("QUALIFICATION_SETUP_SCOPE_CHANGED")

    def before_new_tab(self):
        self.before_effect()
        if self.finished:
            raise ValueError("QUALIFICATION_RETENTION_ALREADY_FINISHED")
        count = sum(not any(scene is item for item in self.inventory) for scene in self.manager.scenes())
        if count >= self.limit["new_tabs"]:
            raise ValueError("QUALIFICATION_TAB_LIMIT_EXCEEDED")

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
        self.identified.append((scene, role, dict(guards.scene_instance(scene)), str(scene.get_path_name())))

    def plan_file(self, name):
        self.before_effect()
        if (self.finished or name not in _FILENAMES[self.kind]
                or name in self.public["attempted_files"]
                or len(self.public["attempted_files"]) >= self.limit["files"]):
            raise ValueError("QUALIFICATION_FILE_SCOPE_UNAVAILABLE")
        path = self.directory / name
        if path.exists() or path.is_symlink():
            raise ValueError("QUALIFICATION_FILE_ALREADY_EXISTS")
        self.public["attempted_files"].append(name)
        return path

    def record_file(self, manifest):
        path = Path(manifest["path"]).resolve()
        if (self.finished or path.parent != self.directory or path.name not in self.public["attempted_files"]
                or len(self.public["saved_files"]) >= self.limit["files"]
                or any(Path(item["path"]).resolve() == path for item in self.public["saved_files"])):
            raise ValueError("QUALIFICATION_FILE_SCOPE_UNAVAILABLE")
        self.public["saved_files"].append(_copy(manifest))

    def save_fixture(self, scene, name, reader):
        """Only normal execution saves. Finalization never saves failed tabs."""
        from .native_adapters import _save_observed
        if not any(scene is item[0] for item in self.identified):
            raise ValueError("QUALIFICATION_SCENE_OWNERSHIP_UNAVAILABLE")
        path = self.plan_file(name)
        before = reader(scene)
        self.before_effect()
        manifest = _save_observed(scene, path)
        self.record_file(manifest)
        if reader(scene) != before:
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: qualification fixture changed during save")
        return manifest

    def finish(self, error=None):
        """Restore original active observations, retain all tabs and files."""
        from .native_scene_reader import read_scene
        from .native_fixture import _OWNED
        if self.finished:
            raise ValueError("QUALIFICATION_RETENTION_ALREADY_FINISHED")
        problems = []
        # Retain historical IDs/paths even if admission/context prevents any
        # further native wrapper observation. Presence is then unverified.
        self.public["retained_tabs"] = [
            {"role": role, "ownership": "last_observed_qualification_tab", **identity,
             "path": path, "presence": "unobserved"}
            for _scene, role, identity, path in self.identified
        ]
        try:
            self.before_effect()
            live = list(self.manager.scenes())
            if not any(item is self.previous for item in live):
                raise ValueError("QUALIFICATION_ORIGINAL_SCENE_REMOVED")
            self.manager.set_current_scene(self.previous)
            live = list(self.manager.scenes())
            original_present = all(any(item is value for value in live) for item in self.inventory)
            original_preserved = (original_present and self.manager.current_scene() is self.previous
                and str(self.previous.get_path_name()) == self.original_path
                and read_scene(self.previous) == self.original_projection)
            self.public["original_inventory_preserved"] = original_present
            self.public["original_active_projection_preserved"] = original_preserved
            if not original_preserved:
                problems.append("QUALIFICATION_ORIGINAL_SCENE_CHANGED")
            new_tabs = [item for item in live if not any(item is value for value in self.inventory)]
            self.public["new_tab_count"] = len(new_tabs)
            self.public["retained_tabs"] = []
            self.public["retained_tabs_omitted_count"] = max(0, len(new_tabs) - self.limit["new_tabs"] - 1)
            if len(new_tabs) > self.limit["new_tabs"]:
                problems.append("QUALIFICATION_TAB_LIMIT_EXCEEDED")
            for scene in new_tabs[:self.limit["new_tabs"] + 1]:
                known = next((item for item in self.identified if item[0] is scene), None)
                row = {"role": "unidentified_new_tab", "ownership": "unverified", "path": None}
                if known is not None:
                    row = {"role": known[1], "ownership": "identified_qualification_tab", **known[2],
                           "path": str(scene.get_path_name()), "presence": "observed"}
                else:
                    problems.append("QUALIFICATION_NEW_TAB_UNIDENTIFIED")
                self.public["retained_tabs"].append(row)
            for scene, role, _identity, _path in self.identified:
                if not any(scene is value for value in live):
                    problems.append("QUALIFICATION_IDENTIFIED_SCENE_REMOVED: " + role)
            self.retention_ok = not problems
        except Exception as observation_error:
            problems.append(str(observation_error)[:1000])
        finally:
            self.finished = True
            # Release authoring-helper references, never native scene identity.
            for scene, _role, _identity, _path in self.identified:
                owned = _OWNED.get(id(scene))
                if owned is not None and owned["scene"] is scene:
                    _OWNED.pop(id(scene))
            self.public["errors"] = problems
            self.public["retention_status"] = "observed" if self.retention_ok else "unverified"
            self.public["qualification_error"] = None if error is None else str(error)[:1000]
            try:
                # A failed experiment still cannot write through a replaced
                # directory or an invalidated admission/source guard.
                from . import incident_admission
                incident_admission.assert_setup_admission(self.setup_operation)
                payload = json.dumps(self.public, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                with (self.directory / "retention.json").open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception as record_error:
                self.retention_ok = False
                self.public["retention_status"] = "unverified"
                problems.append("QUALIFICATION_RETENTION_RECORD_FAILED: " + str(record_error)[:1000])
            self.manager = self.previous = self.original_projection = None
            self.inventory, self.identified = [], []
        if error is not None:
            error.add_note("Retained qualification directory: " + str(self.directory))
            for problem in problems:
                error.add_note(problem)
        elif not self.retention_ok:
            raise ValueError("QUALIFICATION_RETENTION_UNVERIFIED: " + "; ".join(problems))
        return _copy(self.public)

    def complete(self, result):
        if not self.finished or not self.retention_ok or self.public.get("qualification_error") is not None:
            raise ValueError("QUALIFICATION_RETENTION_UNVERIFIED")
        self.before_effect()
        self.result = _copy(result)
        return _copy(self.result)
