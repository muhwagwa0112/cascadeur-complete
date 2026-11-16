"""Code-owned bridge from existing checkpoints to fresh Update observations.

Missing installed facts preserves the existing exact comparator. A present
binding is never bypassed after it fails. P0 stays immutable across all phases.
"""
from __future__ import annotations

from contextlib import contextmanager
import json

from . import guarded_runtime as guards
from .native_scene_reader import read_scene
from .native_update_capture import SerializationPositivePath, bind_native_update_runner, frozen_json
from .native_owned_pair_binding import installed_leaf

_SESSIONS = {}
_LOADS = {}


@contextmanager
def _phase_window(scene, phase_guard):
    """Internal current-request guard for an already executed save/load phase.

    The original P0 source is historical after save/load. Only these concrete
    checkpoint callers may advance the guarded read window. The phase's actual
    raw state is frozen before Update and compared to private P0 afterwards.
    No scope, approval, or request is changed and no caller flag issues proof.
    """
    from .incident_admission import assert_request_admission
    if not callable(phase_guard):
        raise ValueError("SERIALIZATION_CURRENT_PHASE_GUARD_REQUIRED")
    request = getattr(guards._LOCAL, "request", None)
    if request is None:
        raise ValueError("SERIALIZATION_CURRENT_REQUEST_REQUIRED")
    operations = request.get("operations") or []
    if len(operations) != 1 or operations[0]["name"] not in (
            "safety.bootstrap", "safety.checkpoint", "safety.rollback"):
        raise ValueError("SERIALIZATION_PHASE_OPERATION_UNSUPPORTED")
    assert_request_admission()
    phase_guard()
    raw = frozen_json(read_scene(scene))
    identity = dict(guards.scene_instance(scene))
    prior = getattr(guards._LOCAL, "guard", None)
    def guard():
        assert_request_admission()
        phase_guard()
        if (getattr(guards._LOCAL, "request", None) is not request
                or dict(guards.scene_instance(scene)) != identity
                or frozen_json(read_scene(scene)) != raw):
            raise ValueError("SERIALIZATION_PHASE_SOURCE_CHANGED")
    guard()
    guards.set_write_guard(guard)
    try:
        yield guard
    finally:
        # This is a same-thread synchronous scope, not a reusable phase permit.
        changed = getattr(guards._LOCAL, "guard", None) is not guard
        guards.set_write_guard(prior)
        if changed:
            raise ValueError("SERIALIZATION_PHASE_GUARD_REPLACED")


def prepare_reference(scene, projection, *, phase_guard):
    leaf = installed_leaf(required=False)
    if leaf is None:
        return None
    roles = getattr(leaf, "serialization_role_specs", None)
    specs = () if roles is None else tuple(roles(scene))
    with _phase_window(scene, phase_guard) as guard:
        runner = bind_native_update_runner(scene, leaf.extract_installed_update_facts, guard)
        path = SerializationPositivePath(runner, specs)
        anchor = path.initialize_anchor()
    if anchor.projection_bytes != frozen_json(projection):
        raise ValueError("SERIALIZATION_REFERENCE_CHANGED_DURING_INITIALIZATION")
    return path, anchor


def register_reference(native_anchor, session):
    if session is None:
        return
    key = native_anchor.checkpoint_anchor_digest
    if key in _SESSIONS:
        raise ValueError("SERIALIZATION_TYPED_ANCHOR_ALREADY_REGISTERED")
    _SESSIONS[key] = session


def compare_phase(scene, native_anchor, phase, *, phase_guard):
    session = _SESSIONS.get(native_anchor.checkpoint_anchor_digest)
    if session is None:
        return None
    path, anchor = session
    leaf = installed_leaf()
    with _phase_window(scene, phase_guard) as guard:
        runner = path.bind_current_request_runner(anchor, scene,
            extract_installed_update_facts=leaf.extract_installed_update_facts,
            assert_admitted_effect=guard)
        observation = path.observe_phase(anchor, phase, runner=runner)
    path.verify(anchor, observation, json.loads(observation.actual_projection_bytes))
    return observation


def load_checkpoint_copy(record, parent_scene, working, *, source_guard):
    """Exactly one real load, then privately bind its returned native scene."""
    from .native_project_io import load_project_copy
    from .incident_admission import assert_request_admission
    fixed = record.get("fixed_anchor")
    native_anchor = None if fixed is None else fixed["immutable_anchor"]
    session = None if native_anchor is None else _SESSIONS.get(native_anchor.checkpoint_anchor_digest)
    manifest = record["manifest"]
    if session is None:
        return load_project_copy(manifest["path"], working,
            expected_sha256=manifest["sha256"], expected_length=manifest["bytes"], source_guard=source_guard)
    path, anchor = session
    leaf = installed_leaf()
    def admitted():
        assert_request_admission()
        source_guard()
    # load_checkpoint_copy itself makes no Update; graph observations follow
    # in project_load/restored_save under a fresh current-phase window.
    target, observation, runner = path.load_checkpoint_copy(anchor, guards.digest(manifest),
        parent_scene, working, source_guard=source_guard,
        extract_installed_update_facts=leaf.extract_installed_update_facts,
        assert_admitted_effect=admitted)
    _LOADS[(native_anchor.checkpoint_anchor_digest, id(target))] = (path, anchor, runner, target)
    return target, observation


def bind_completed_clone(native_anchor, target):
    loaded = _LOADS.pop((native_anchor.checkpoint_anchor_digest, id(target)), None)
    if loaded is None:
        if native_anchor.checkpoint_anchor_digest in _SESSIONS:
            raise ValueError("SERIALIZATION_ACTUAL_CLONE_LOAD_UNAVAILABLE")
        return
    path, anchor, runner, original_target = loaded
    if original_target is not target:
        raise ValueError("SERIALIZATION_CLONE_OBJECT_CHANGED")
    path.bind_completed_clone_identity(anchor, runner)
