"""Private, fixed-reference observations of real save/load boundaries.

Numeric comparison is implemented by serialization_equivalence. An installed
field/producer classifier has not been observed, so unclassified differences
remain unsupported. Wire policies and comparison candidates are never issuers.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import guarded_runtime as guards
from .native_scene_reader import read_scene
from .serialization_equivalence import compare_projections, role_layout_digest

_ANCHORS = {}
_OBSERVATIONS = {}
# Only a future code-owned installed-role qualifier may populate this registry.
# No wire operation or registration-by-digest is provided.
_POLICIES = {}
_PHASES = frozenset({"checkpoint_save", "working_save", "project_load", "restored_save"})


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class ImmutableCheckpointAnchor:
    reference_bytes: bytes
    reference_projection_digest: str
    runtime_epoch: str
    runtime_fingerprint: str
    installed_build: str
    checkpoint_anchor_digest: str

    @property
    def reference_projection(self):
        return json.loads(self.reference_bytes)


@dataclass(frozen=True)
class NativeSerializationObservation:
    projection_bytes: bytes
    observation_bytes: bytes

    @property
    def projection(self):
        return json.loads(self.projection_bytes)

    def as_dict(self):
        return json.loads(self.observation_bytes)


def pin_reference(scene, *, phase_guard=None, expected_projection=None):
    """Read P0 once; its raw identity is never replaced by a later save."""
    from .native_adapters import installed_build
    guards.assert_loaded_package()
    projection = read_scene(scene)
    if expected_projection is not None and projection != expected_projection:
        raise ValueError("SERIALIZATION_PRE_SAVE_SOURCE_DIFFERS")
    from .native_serialization_binding import prepare_reference, register_reference
    typed = prepare_reference(scene, projection, phase_guard=phase_guard)
    raw = _bytes(projection)
    if len(raw) > 64 * 1024**2:
        raise ValueError("SERIALIZATION_REFERENCE_BUDGET_EXCEEDED")
    identity = {"reference_projection_digest": guards.digest(projection),
                "runtime_epoch": guards.RUNTIME_EPOCH,
                "runtime_fingerprint": guards.LOADED_FINGERPRINT,
                "installed_build": installed_build()}
    key_material = dict(identity)
    if typed is not None:
        key_material.update(typed_graph_digest=typed[1].facts_digest,
                            typed_scene=dict(guards.scene_instance(scene)))
    key = guards.digest(key_material)
    anchor = ImmutableCheckpointAnchor(raw, **identity, checkpoint_anchor_digest=key)
    prior = _ANCHORS.get(key)
    if prior is not None and prior != anchor:
        raise ValueError("SERIALIZATION_ANCHOR_CONFLICT")
    if prior is not None:
        return prior
    _ANCHORS[key] = anchor
    register_reference(anchor, typed)
    return anchor


def require_anchor(anchor):
    from .native_adapters import installed_build
    guards.assert_loaded_package()
    if (not isinstance(anchor, ImmutableCheckpointAnchor)
            or _ANCHORS.get(anchor.checkpoint_anchor_digest) is not anchor
            or anchor.runtime_epoch != guards.RUNTIME_EPOCH
            or anchor.runtime_fingerprint != guards.LOADED_FINGERPRINT
            or anchor.installed_build != installed_build()
            or guards.digest(anchor.reference_projection) != anchor.reference_projection_digest):
        raise ValueError("SERIALIZATION_PRIVATE_ANCHOR_UNAVAILABLE")
    return anchor


def compare_with_private_policy(scene, anchor, *, phase, phase_guard=None):
    """Read the actual phase result and compare directly with private P0."""
    require_anchor(anchor)
    if phase not in _PHASES:
        raise ValueError("SERIALIZATION_PHASE_UNSUPPORTED")
    from .native_serialization_binding import compare_phase
    typed = compare_phase(scene, anchor, phase, phase_guard=phase_guard)
    if typed is not None:
        actual = json.loads(typed.actual_projection_bytes)
        candidate = json.loads(typed.observation_bytes)
        comparison_kind = candidate["comparison_kind"]
        policy_digest = candidate["serialization_policy_digest"]
        exact_fields_digest = candidate["exact_fields_digest"]
    else:
        actual = read_scene(scene)
        policy_key = (anchor.installed_build, anchor.runtime_fingerprint,
                      role_layout_digest(anchor.reference_projection))
        policy = _POLICIES.get(policy_key)
        candidate = compare_projections(anchor.reference_projection, actual,
            expected_before_digest=anchor.reference_projection_digest,
            installed_build=anchor.installed_build, loaded_fingerprint=anchor.runtime_fingerprint,
            policy=policy)
        if not candidate.accepted:
            raise ValueError("SERIALIZATION_EQUIVALENCE_UNAVAILABLE: " + ",".join(candidate.failure_codes))
        comparison_kind, policy_digest = candidate.kind, candidate.policy_digest
        exact_fields_digest = candidate.exact_fields_digest
    observation = {"schema_version": 1, "kind": "private-serialization-observation",
        "phase": phase, "checkpoint_anchor_digest": anchor.checkpoint_anchor_digest,
        "reference_projection_digest": anchor.reference_projection_digest,
        "observed_projection_digest": guards.digest(actual), "comparison_kind": comparison_kind,
        "serialization_policy_digest": policy_digest,
        "exact_fields_digest": exact_fields_digest,
        "scene": dict(guards.scene_instance(scene)), "runtime_epoch": guards.RUNTIME_EPOCH,
        "runtime_fingerprint": guards.LOADED_FINGERPRINT, "installed_build": anchor.installed_build}
    record = NativeSerializationObservation(_bytes(actual), _bytes(observation))
    _OBSERVATIONS[guards.digest(observation)] = record
    return record


def verify_serialization_observation(observation, *, anchor, projection):
    require_anchor(anchor)
    record = _OBSERVATIONS.get(guards.digest(observation))
    if (record is None or record.as_dict() != observation or record.projection != projection
            or observation.get("checkpoint_anchor_digest") != anchor.checkpoint_anchor_digest
            or observation.get("observed_projection_digest") != guards.digest(projection)):
        raise ValueError("SERIALIZATION_OBSERVATION_UNVERIFIED")
    return record
