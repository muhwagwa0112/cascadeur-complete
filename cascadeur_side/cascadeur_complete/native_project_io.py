"""Load a fresh owned project copy with the complete application loader.

The caller owns before_write/finish_write guards and native effect receipts.
This helper does not authorize a write, qualify a loader, save another tab, or
run on import. Failed copies and newly owned tabs are retained for reconciliation.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import threading
import uuid
from pathlib import Path

_MAX_BYTES = 512 * 1024 * 1024
_MAX_SCENES = 128
_MAX_EVENTS = 128


class ProjectCopyLoadError(ValueError):
    """A preserved attempt; observation is JSON and target_scene is native."""

    def __init__(self, message, observation, target_scene=None):
        super().__init__(message)
        self.observation = observation
        self.target_scene = target_scene


def _no_alias(path):
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("PROJECT_COPY_PATH_ALIAS_FORBIDDEN")


def _path(value):
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError("PROJECT_COPY_PATH_INVALID")
    path = Path(value)
    # Reject device/UNC aliases, ADS and traversal rather than resolving a
    # caller's alias into an otherwise permitted runtime directory.
    if (not path.is_absolute() or path.suffix.lower() != ".casc"
            or path.drive.startswith("\\\\") or ".." in path.parts
            or any(":" in part or part.endswith((".", " ")) for part in path.parts[1:])):
        raise ValueError("PROJECT_COPY_PATH_INVALID")
    _no_alias(path)
    resolved = path.resolve()
    if os.path.normcase(str(resolved)) != os.path.normcase(str(path)):
        raise ValueError("PROJECT_COPY_PATH_ALIAS_FORBIDDEN")
    return resolved


def _working_path(value):
    from . import runtime as rt
    path = _path(value)
    root = rt.runtime_root().resolve()
    _no_alias(root)
    allowed = path.is_relative_to(root / "snapshots")
    runs = root / "state" / "runs"
    if path.is_relative_to(runs):
        relative = path.relative_to(runs).parts
        if len(relative) == 3 and relative[1] in ("workspace", "checkpoints"):
            try:
                allowed = str(uuid.UUID(relative[0])) == relative[0]
            except ValueError:
                allowed = False
    if not allowed:
        raise ValueError("PROJECT_COPY_PATH_NOT_OWNED")
    if os.path.lexists(path):
        raise ValueError("PROJECT_COPY_TARGET_EXISTS")
    return path


def _scenes(manager):
    scenes = list(manager.scenes())
    if len(scenes) > _MAX_SCENES or len({id(scene) for scene in scenes}) != len(scenes):
        raise ValueError("PROJECT_COPY_SCENE_INVENTORY_UNAVAILABLE")
    return scenes


def _same_inventory(actual, expected):
    return len(actual) == len(expected) and all(any(item is wanted for item in actual) for wanted in expected)


def _copy_locked(source, working, expected_sha256, expected_length, observation, before_effect):
    """Copy the same locked stream that _locked_input hashed, never reopen it."""
    from .native_adapters import _locked_input
    lock = _locked_input(source)
    with lock as manifest:
        observation["source_file"] = dict(manifest)
        if (not 0 < manifest["length"] <= _MAX_BYTES
                or expected_sha256 is not None and manifest["sha256"] != expected_sha256
                or expected_length is not None and manifest["length"] != expected_length):
            raise ValueError("PROJECT_COPY_INPUT_DIGEST_MISMATCH")
        before_effect()
        working.parent.mkdir(parents=True, exist_ok=True)
        _no_alias(working)
        before_effect()
        descriptor = os.open(working, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
        observation["working_file_created"] = True
        digest, length = hashlib.sha256(), 0
        with os.fdopen(descriptor, "wb") as output:
            lock.stream.seek(0)
            while block := lock.stream.read(1024 * 1024):
                length += len(block)
                if length > _MAX_BYTES:
                    raise ValueError("RESOURCE_BUDGET_EXCEEDED: project copy exceeds 512 MiB")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        _no_alias(working)
        if (length != manifest["length"] or digest.hexdigest() != manifest["sha256"]
                or os.path.samefile(source, working)):
            raise ValueError("PROJECT_COPY_BYTES_DIFFER")
        # Lock and hash the destination as well; loading occurs under that
        # lock in load_project_copy, which independently checks these bytes.
        with _locked_input(working) as copied:
            if copied["sha256"] != manifest["sha256"] or copied["length"] != manifest["length"]:
                raise ValueError("PROJECT_COPY_BYTES_DIFFER")
            observation["working_file"] = dict(copied)


def load_project_copy(source_path, working_path, expected_sha256=None, expected_length=None, *, source_guard=None):
    """Return (owned target, JSON observation) only for synchronous reuse.

    The caller must run its source guard immediately before invoking this
    effectful helper and seal completion separately afterward. Only a fresh
    empty placeholder reused by DataSourceManager.load_scene is supported.
    The original current tab is restored on failure; no failed tab/file is
    removed, retried or silently treated as a successful project load.
    """
    import csc
    from events import event_message_manager
    from . import guarded_runtime as guards
    from . import runtime as rt
    from .native_adapters import _locked_input
    from .incident_admission import assert_request_admission

    if not callable(source_guard):
        raise ValueError("PROJECT_COPY_PRIVATE_SOURCE_GUARD_REQUIRED")
    def before_effect():
        assert_request_admission()
        source_guard()

    guards.assert_loaded_package()
    if expected_sha256 is not None and (not isinstance(expected_sha256, str)
            or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None):
        raise ValueError("PROJECT_COPY_EXPECTED_DIGEST_INVALID")
    if expected_length is not None and (type(expected_length) is not int or not 0 < expected_length <= _MAX_BYTES):
        raise ValueError("PROJECT_COPY_EXPECTED_LENGTH_INVALID")
    source, working = _path(source_path), _working_path(working_path)
    if source == working or not source.is_file():
        raise ValueError("PROJECT_COPY_SOURCE_INVALID")
    application = csc.app.get_application()
    manager = application.get_scene_manager()
    data_sources = application.get_data_source_manager()
    previous = manager.current_scene()
    original = _scenes(manager)
    # SceneManager has no documented 'activate None' operation. Reject before
    # effects when restoring an absent current tab could not be guaranteed.
    if previous is None or not any(scene is previous for scene in original):
        raise ValueError("PROJECT_COPY_CURRENT_SCENE_UNAVAILABLE")
    if len(original) >= _MAX_SCENES:
        raise ValueError("RESOURCE_BUDGET_EXCEEDED: no bounded project-copy tab slot")
    original_paths = [str(scene.get_path_name()) for scene in original]
    target = None
    observation = {"schema_version": 1, "loader": "DataSourceManager.load_scene",
        "native_completion": "not_started", "source_path": str(source), "working_path": str(working),
        "working_file_created": False, "scene_count_before": len(original), "events": []}
    try:
        _copy_locked(source, working, expected_sha256, expected_length, observation, before_effect)
        if (manager.current_scene() is not previous or not _same_inventory(_scenes(manager), original)
                or [str(scene.get_path_name()) for scene in original] != original_paths):
            raise ValueError("PROJECT_COPY_ORIGINAL_TABS_CHANGED")
        before_effect()
        target = manager.create_application_scene()
        if target is None or any(target is scene for scene in original):
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: loader placeholder is not a fresh scene")
        observation["owned_placeholder_created"] = True
        before_effect()
        manager.set_current_scene(target)
        domain = rt._domain_scene(target)
        if (manager.current_scene() is not target or str(target.get_path_name())
                or domain.model_viewer().get_objects()
                or not _same_inventory(_scenes(manager), original + [target])):
            raise ValueError("NATIVE_COMPLETION_UNKNOWN: fresh empty active placeholder not observed")
        messages, errors = observation["events"], set()
        owner_thread = threading.get_ident()
        active = [False]
        def message(emitter, full, level, simple):
            try:
                if not active[0] or threading.get_ident() != owner_thread:
                    errors.add("LOAD_EVENT_OUTSIDE_SYNCHRONOUS_CALL")
                    return
                full, simple = str(full), str(simple)
                level = str(getattr(level, "name", level))
                if len(messages) >= _MAX_EVENTS or len(full) + len(simple) > 8192:
                    errors.add("LOAD_EVENT_BUDGET_EXCEEDED")
                    return
                kind = "target" if emitter is target else "domain" if emitter is domain else "other"
                messages.append({"full": full, "simple": simple, "level": level, "emitter_kind": kind,
                    "emitter_type": (type(emitter).__module__ + "." + type(emitter).__name__)[:256]})
                if level not in {"0", "1", "4", "None", "Info", "Success"}:
                    errors.add("LOAD_ERROR_OR_WARNING_EVENT")
            except Exception:
                errors.add("LOAD_EVENT_CAPTURE_FAILED")
        # Deny replacement/write access throughout the actual native path load.
        _no_alias(working)
        with _locked_input(working) as copied:
            if copied != observation["working_file"]:
                raise ValueError("PROJECT_COPY_BYTES_CHANGED_BEFORE_LOAD")
            subscription = event_message_manager.subscribe(message)
            try:
                active[0] = True
                observation["native_completion"] = "unknown"
                before_effect()
                result = data_sources.load_scene(str(working))
                observation["synchronous_return"] = result is True
            finally:
                active[0] = False
                event_message_manager.unsubscribe(subscription)
            after = _scenes(manager)
            observation["scene_count_after"] = len(after)
            observation["target_path"] = str(target.get_path_name())
            observation["original_tabs_preserved"] = (_same_inventory(after, original + [target])
                and [str(scene.get_path_name()) for scene in original] == original_paths)
            observation["placeholder_reused"] = manager.current_scene() is target
            completed = [row for row in messages if row["full"].strip() == "Loading is completed"]
            observation["event_errors"] = sorted(errors)
            if (result is not True or errors or len(completed) != 1
                    or completed[0]["level"] not in {"1", "Info"}
                    or completed[0]["emitter_kind"] not in {"target", "domain"}
                    or not observation["original_tabs_preserved"] or not observation["placeholder_reused"]
                    or not observation["target_path"] or _path(observation["target_path"]) != working):
                raise ValueError("NATIVE_COMPLETION_UNKNOWN: exact project-copy load completion not observed")
            # Metadata/content equality belongs to the caller's complete native
            # reader. Do not infer FPS, units or rig metadata from file names.
            observation["native_completion"] = "observed"
        return target, observation
    except Exception as error:
        if observation["native_completion"] == "observed":
            observation["native_completion"] = "unknown"
        observation["failure_code"] = str(error).split(":", 1)[0][:128]
        try:
            inventory = _scenes(manager)
            observation["scene_count_after"] = len(inventory)
            observation["original_tabs_present"] = all(any(item is scene for item in inventory) for scene in original)
            if any(item is previous for item in inventory):
                before_effect()
                manager.set_current_scene(previous)
            observation["original_current_restored"] = manager.current_scene() is previous
        except Exception as restore_error:
            observation["original_current_restored"] = False
            observation["restore_error"] = str(restore_error)[:256]
        raise ProjectCopyLoadError(str(error), observation, target) from error
