"""Proposed native Update capture and private serialization control flow.

The pure control flow is complete. Native role extraction is deliberately an
injected CODE-OWNED leaf: its installed SDK getter names remain unconfirmed.
Calling a reference constructor does not qualify that leaf. See the companion
document for its exact output and empirical prerequisites. No csc import runs
at module import, and this file has not been executed against Cascadeur.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from .serialization_equivalence import (
    DerivedPolicy, DerivedRule, canonical_digest, compare_projections,
    role_layout_digest, _validate_binding, _validate_rule,
)

# Only the native binding factory shares this store across request-scoped
# runners. It is not deserialized or populated by a public register function.
_NATIVE_SNAPSHOT_STORES: dict[tuple[str, str, str], dict[int, "UpdateSnapshot"]] = {}


def frozen_json(value: Any) -> bytes:
    canonical_digest(value)  # Reject non-JSON/non-finite values before freezing.
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class NativeDataFact:
    """Actual Update observation, not a classification inferred from a name.

    producer_kind must identify the installed typed producer implementation.
    authored_storage=False must be observed from that producer/input contract;
    None is unknown. An Animation mode or absent display-name match is neither.
    """
    data_id: str
    owner_id: str
    native_dtype: str
    sample_shape: tuple[int, ...]
    producer_id: str | None
    producer_kind: str | None
    authored_storage: bool | None
    upstream_data_ids: tuple[str, ...]
    consumer_ids: tuple[str, ...]


@dataclass(frozen=True)
class UpdateFacts:
    # Canonical full graph: nodes, typed ports, all edges, external links,
    # producer implementation identities and all data/setting dependencies.
    # This is an extractor result, NEVER a graph dictionary accepted over MCP.
    graph_bytes: bytes
    data: tuple[NativeDataFact, ...]

    def validate(self, projection: dict[str, Any]) -> None:
        graph = json.loads(self.graph_bytes)
        if frozen_json(graph) != self.graph_bytes or len(self.graph_bytes) > 2 * 1024**2:
            raise ValueError("UPDATE_GRAPH_ENCODING_OR_BUDGET_INVALID")
        ids = [row.data_id for row in self.data]
        actual = {row["id"] for row in projection["data"]}
        if len(ids) != len(set(ids)) or set(ids) != actual:
            raise ValueError("UPDATE_DATA_CLOSURE_INCOMPLETE")
        for row in self.data:
            if (not row.data_id or not row.owner_id or not row.native_dtype
                    or type(row.authored_storage) not in (bool, type(None))
                    or len(row.sample_shape) > 3
                    or any(type(n) is not int or not 1 <= n <= 16 for n in row.sample_shape)
                    or len(row.upstream_data_ids) != len(set(row.upstream_data_ids))
                    or not set(row.upstream_data_ids) <= actual):
                raise ValueError("UPDATE_TYPED_DATA_INVALID")
        # Completeness of graph enumeration is a property of the installed leaf
        # implementation, not a caller-provided `complete=True` flag.

    def material(self) -> dict[str, Any]:
        return {"graph": json.loads(self.graph_bytes), "data": [
            {"id": f.data_id, "owner": f.owner_id, "dtype": f.native_dtype,
             "shape": list(f.sample_shape), "producer": f.producer_id,
             "producer_kind": f.producer_kind, "authored_storage": f.authored_storage,
             "upstream": list(f.upstream_data_ids), "consumers": list(f.consumer_ids)}
            for f in sorted(self.data, key=lambda item: item.data_id)]}


@dataclass(frozen=True)
class UpdateSnapshot:
    projection_bytes: bytes
    facts: UpdateFacts
    context_bytes: bytes

    @property
    def projection(self) -> dict[str, Any]:
        return json.loads(self.projection_bytes)


class UpdateCaptureRunner:
    """One observed Update callback, immutable result, exact outer readback.

    Constructor callables are installed code bindings, never user data. `invoke`
    must be the existing guarded transact/modify_update route. The native leaf
    must first qualify no-yield callback completion and absence of post-return
    graph work for this finite profile; the runner cannot prove that from JSON.
    """
    def __init__(self, *, invoke: Callable, read_projection: Callable,
                 read_context: Callable, extract: Callable,
                 private_snapshot_store: dict[int, UpdateSnapshot] | None = None):
        self._invoke = invoke
        self._read_projection = read_projection
        self._read_context = read_context
        self._extract = extract
        self._issued = {} if private_snapshot_store is None else private_snapshot_store
        self._active = False

    def require(self, snapshot: UpdateSnapshot) -> UpdateSnapshot:
        if self._issued.get(id(snapshot)) is not snapshot:
            raise ValueError("UPDATE_SNAPSHOT_NOT_PRIVATELY_ISSUED")
        if snapshot.context_bytes != frozen_json(self._read_context()):
            raise ValueError("UPDATE_SNAPSHOT_CONTEXT_CHANGED")
        return snapshot

    def run(self, body: Callable | None = None, *, allow_projection_change: bool = False
            ) -> tuple[UpdateSnapshot, Any]:
        if self._active or len(self._issued) >= 256:
            raise ValueError("UPDATE_CAPTURE_REENTRANT_OR_RECORD_BUDGET")
        context = frozen_json(self._read_context())
        outer_before = frozen_json(self._read_projection())
        retained: list[tuple[UpdateSnapshot, Any]] = []
        self._active = True
        def capture(model, update, updater):
            if not self._active or retained:
                raise ValueError("UPDATE_CALLBACK_EXPIRED_OR_REPLAYED")
            if frozen_json(self._read_context()) != context:
                raise ValueError("UPDATE_CONTEXT_CHANGED")
            before = self._read_projection()
            if frozen_json(before) != outer_before:
                raise ValueError("UPDATE_CHANGED_SOURCE_BEFORE_OBSERVATION")
            facts = self._extract(model, update, updater)
            if not isinstance(facts, UpdateFacts):
                raise ValueError("UPDATE_EXTRACTOR_RETURN_TYPE_INVALID")
            facts.validate(before)
            value = None if body is None else body(model, update, updater, before, facts)
            after = self._read_projection()
            after_facts = self._extract(model, update, updater)
            if not isinstance(after_facts, UpdateFacts):
                raise ValueError("UPDATE_EXTRACTOR_RETURN_TYPE_INVALID")
            after_facts.validate(after)
            if frozen_json(after_facts.material()) != frozen_json(facts.material()):
                raise ValueError("UPDATE_GRAPH_OR_DTYPE_CHANGED_WITHIN_CALLBACK")
            if not allow_projection_change and frozen_json(after) != outer_before:
                raise ValueError("UPDATE_OBSERVATION_CHANGED_RAW_STATE")
            if frozen_json(self._read_context()) != context:
                raise ValueError("UPDATE_CONTEXT_CHANGED")
            retained.append((UpdateSnapshot(frozen_json(after), after_facts, context), value))
        try:
            self._invoke(capture)
        finally:
            self._active = False
        if len(retained) != 1:
            raise ValueError("UPDATE_CALLBACK_COMPLETION_UNOBSERVED")
        snapshot, value = retained[0]
        if (frozen_json(self._read_projection()) != snapshot.projection_bytes
                or frozen_json(self._read_context()) != context):
            raise ValueError("UPDATE_POST_RETURN_STATE_DIFFERS")
        self._issued[id(snapshot)] = snapshot
        return snapshot, value

    def transition(self, body: Callable) -> tuple[UpdateSnapshot, UpdateSnapshot, Any]:
        """Two actual bookends of ONE already-authorized evaluation callback.

        The pre-state becomes privately issued only after that same callback
        and exact outer readback complete. Never manufacture it from a receipt.
        """
        if len(self._issued) > 254:
            raise ValueError("UPDATE_TRANSITION_BOOKEND_BUDGET")
        before_values: list[UpdateSnapshot] = []
        def observe(model, update, updater, projection, facts):
            before_values.append(UpdateSnapshot(frozen_json(projection), facts,
                                               frozen_json(self._read_context())))
            return body(model, update, updater, projection, facts)
        after, value = self.run(observe, allow_projection_change=True)
        if len(before_values) != 1 or len(self._issued) >= 256:
            raise ValueError("UPDATE_TRANSITION_BOOKEND_UNAVAILABLE")
        before = before_values[0]
        self._issued[id(before)] = before
        return before, after, value


def bind_native_update_runner(scene, extract_installed_update_facts: Callable,
                              assert_admitted_effect: Callable) -> UpdateCaptureRunner:
    """CONDITIONAL native binding; imports are all existing source symbols.

    `extract_installed_update_facts` is the one missing SDK leaf. This binding is
    never installed by module import and may not be called as a read operation.
    `assert_admitted_effect` must check the ORIGINAL request's effect/admission,
    epoch, owned scene, callback allowance, and exact source before entry.
    """
    from cascadeur_complete import runtime as rt, guarded_runtime as guards
    from cascadeur_complete.handler_registry import transact
    from cascadeur_complete.native_adapters import installed_build
    from cascadeur_complete.native_export import selection_observation
    from cascadeur_complete.native_scene_reader import read_scene
    domain = rt._domain_scene(scene)
    def context():
        guards.assert_loaded_package()
        if rt._scene_view() is not scene:
            raise ValueError("UPDATE_SCENE_NOT_ACTIVE")
        return {"installed_build": installed_build(), "runtime_epoch": guards.RUNTIME_EPOCH,
                "runtime_fingerprint": guards.LOADED_FINGERPRINT,
                "scene": dict(guards.scene_instance(scene)),
                "selection": selection_observation(scene),
                "frame": int(domain.get_current_frame(False))}
    def invoke(callback):
        assert_admitted_effect()
        transact(domain.modify_update, "Cascadeur Complete: bounded typed graph capture",
                 callback, before_write=assert_admitted_effect)
    observed = context()
    store_key = (observed["installed_build"], observed["runtime_epoch"], observed["runtime_fingerprint"])
    snapshot_store = _NATIVE_SNAPSHOT_STORES.setdefault(store_key, {})
    return UpdateCaptureRunner(invoke=invoke, read_projection=lambda: read_scene(scene),
        read_context=context, extract=extract_installed_update_facts, private_snapshot_store=snapshot_store)


@dataclass(frozen=True)
class RoleSpec:
    """Code-reviewed installed producer rule and preselected numeric budget.

    These values are fixed BEFORE any save/load comparison, never fitted to the
    observed Cascy discrepancy. Only float32 component rules are enabled here;
    quaternion sign/norm semantics need an independent producer contract.
    """
    data_id: str
    data_owner_id: str
    behaviour_owner_id: str
    behaviour_id: str
    property_name: str
    property_kind: str
    property_index: int | None
    producer_kind: str
    sample_shape: tuple[int, ...]
    units: str
    max_ulps: int
    max_absolute_native: float


@dataclass(frozen=True)
class Anchor:
    projection_bytes: bytes
    exact_digest: str
    context_bytes: bytes
    facts_digest: str
    policy: DerivedPolicy | None


@dataclass(frozen=True)
class PhaseObservation:
    anchor_digest: str
    actual_projection_bytes: bytes
    observation_bytes: bytes


class SerializationPositivePath:
    """Issuer -> registration -> current Update read -> fixed-P0 consumer.

    Positive numeric acceptance exists after actual leaf qualification and
    source-bound role capture. This reference registry grants no native rights.
    """
    PHASES = frozenset({"checkpoint_save", "working_save", "project_load", "restored_save"})

    def __init__(self, runner: UpdateCaptureRunner, role_specs: tuple[RoleSpec, ...]):
        if len(role_specs) > 64 or len({x.data_id for x in role_specs}) != len(role_specs):
            raise ValueError("SERIALIZATION_ROLE_SPEC_BUDGET")
        self.runner = runner
        self.role_specs = role_specs
        self._anchors: dict[int, Anchor] = {}
        self._policies: dict[tuple[str, str, str, str], DerivedPolicy] = {}
        self._observations: dict[int, PhaseObservation] = {}
        self._phase_runners: dict[int, dict[int, bytes]] = {}
        self._loads: dict[int, tuple[Any, Any, bytes]] = {}

    def initialize_anchor(self) -> Anchor:
        snapshot, _ = self.runner.run()
        self.runner.require(snapshot)
        projection = snapshot.projection
        context = json.loads(snapshot.context_bytes)
        facts = {row.data_id: row for row in snapshot.facts.data}
        facts_digest = canonical_digest(snapshot.facts.material())
        rules = []
        rows = {row["id"]: row for row in projection["data"]}
        for spec in self.role_specs:
            fact = facts.get(spec.data_id)
            if (fact is None or fact.authored_storage is not False
                    or fact.native_dtype != "float32" or fact.sample_shape != spec.sample_shape
                    or fact.owner_id != spec.data_owner_id or not fact.producer_id
                    or fact.producer_kind != spec.producer_kind or not fact.upstream_data_ids):
                raise ValueError("SERIALIZATION_INSTALLED_DERIVED_ROLE_UNOBSERVED")
            native_type = canonical_digest({"dtype": fact.native_dtype,
                                           "shape": list(fact.sample_shape), "data": fact.data_id})
            rule = DerivedRule(spec.data_id, spec.data_owner_id, spec.behaviour_owner_id,
                spec.behaviour_id, spec.property_name, spec.property_kind, spec.property_index,
                spec.sample_shape, "float32_components", native_type, facts_digest, spec.units,
                spec.max_ulps, spec.max_absolute_native, 0.0, 0.0)
            _validate_rule(rule)
            _validate_binding(projection, rows[spec.data_id], rule)
            rules.append(rule)
        policy = None
        if rules:
            policy = DerivedPolicy(1, context["installed_build"], context["runtime_fingerprint"],
                facts_digest, role_layout_digest(projection), tuple(rules), 2_000_000)
        anchor = Anchor(snapshot.projection_bytes, canonical_digest(projection),
                        snapshot.context_bytes, facts_digest, policy)
        if len(self._anchors) >= 64:
            raise ValueError("SERIALIZATION_ANCHOR_BUDGET")
        self._anchors[id(anchor)] = anchor
        self._phase_runners[id(anchor)] = {id(self.runner): frozen_json(context["scene"])}
        if policy is not None:
            self._policies[(context["runtime_epoch"], anchor.exact_digest,
                            facts_digest, policy.expected_role_layout_digest)] = policy
        return anchor

    def status(self, anchor: Anchor) -> dict[str, Any]:
        private = self._anchors.get(id(anchor)) is anchor
        return {"native_execution_required": True, "anchor_registered": private,
                "typed_numeric_path_registered": private and anchor.policy is not None,
                "requires_fresh_update_at_each_use": True}

    def bind_current_request_runner(self, anchor: Anchor, scene, *,
                                    extract_installed_update_facts: Callable,
                                    assert_admitted_effect: Callable) -> UpdateCaptureRunner:
        """Fresh current-dispatch guard, for an already privately bound scene.

        Never reuse the anchor request's grant/closure. A new instance must go
        through load_checkpoint_copy first; this method only refreshes a request
        binding for an existing actual native identity, not a wire scene dict.
        """
        from cascadeur_complete import guarded_runtime as guards
        if self._anchors.get(id(anchor)) is not anchor:
            raise ValueError("SERIALIZATION_PRIVATE_ANCHOR_UNAVAILABLE")
        identity = frozen_json(dict(guards.scene_instance(scene)))
        if identity not in self._phase_runners[id(anchor)].values():
            raise ValueError("SERIALIZATION_SCENE_HAS_NO_PRIVATE_LOAD_BINDING")
        runner = bind_native_update_runner(scene, extract_installed_update_facts,
                                           assert_admitted_effect)
        self._phase_runners[id(anchor)][id(runner)] = identity
        return runner

    def observe_phase(self, anchor: Anchor, phase: str,
                      *, runner: UpdateCaptureRunner) -> PhaseObservation:
        if self._anchors.get(id(anchor)) is not anchor or phase not in self.PHASES:
            raise ValueError("SERIALIZATION_PRIVATE_ANCHOR_OR_PHASE_INVALID")
        expected_scene = self._phase_runners[id(anchor)].get(id(runner))
        if expected_scene is None:
            raise ValueError("SERIALIZATION_RUNNER_HAS_NO_PRIVATE_LOAD_BINDING")
        snapshot, _ = runner.run()
        runner.require(snapshot)
        # Deliberately no cached graph-revision shortcut. Every use re-reads it.
        context = json.loads(snapshot.context_bytes)
        original_context = json.loads(anchor.context_bytes)
        if any(context[k] != original_context[k] for k in (
                "installed_build", "runtime_epoch", "runtime_fingerprint")):
            raise ValueError("SERIALIZATION_ANCHOR_CONTEXT_CHANGED")
        if frozen_json(context["scene"]) != expected_scene:
            raise ValueError("SERIALIZATION_SCENE_HAS_NO_PRIVATE_LOAD_BINDING")
        if canonical_digest(snapshot.facts.material()) != anchor.facts_digest:
            raise ValueError("SERIALIZATION_CURRENT_PRODUCER_GRAPH_OR_DTYPE_CHANGED")
        policy = anchor.policy
        if policy is not None:
            key = (context["runtime_epoch"], anchor.exact_digest, anchor.facts_digest,
                   policy.expected_role_layout_digest)
            if self._policies.get(key) is not policy:
                raise ValueError("SERIALIZATION_PRIVATE_POLICY_UNAVAILABLE")
        candidate = compare_projections(json.loads(anchor.projection_bytes), snapshot.projection,
            expected_before_digest=anchor.exact_digest,
            installed_build=context["installed_build"], loaded_fingerprint=context["runtime_fingerprint"],
            policy=policy)
        if not candidate.accepted:
            raise ValueError("SERIALIZATION_EQUIVALENCE_UNAVAILABLE:" + ",".join(candidate.failure_codes))
        value = {"native_execution_required": True, "phase": phase, "reference_projection_digest": anchor.exact_digest,
                 "observed_projection_digest": candidate.after_digest, "comparison_kind": candidate.kind,
                 "serialization_policy_digest": candidate.policy_digest,
                 "exact_fields_digest": candidate.exact_fields_digest,
                 "current_graph_dtype_digest": anchor.facts_digest,
                 "observed_scene": context["scene"]}
        observation = PhaseObservation(anchor.exact_digest, snapshot.projection_bytes, frozen_json(value))
        if len(self._observations) >= 256:
            raise ValueError("SERIALIZATION_OBSERVATION_BUDGET")
        self._observations[id(observation)] = observation
        return observation

    def load_checkpoint_copy(self, anchor: Anchor, checkpoint_digest: str, parent_scene,
                             working_path, *, source_guard: Callable,
                             extract_installed_update_facts: Callable,
                             assert_admitted_effect: Callable):
        """CONDITIONAL native bridge: actual private file -> actual new scene.

        Replace the existing load_project_copy call at _restore_native, do NOT
        run this as a second load. No wire load observation/identity is accepted.
        Existing restore permit/source/lifecycle checks remain with the caller.
        """
        from cascadeur_complete import guarded_runtime as guards
        from cascadeur_complete.native_checkpoint_restore import _CHECKPOINTS
        from cascadeur_complete.native_serialization import require_anchor
        from cascadeur_complete.native_project_io import load_project_copy
        if self._anchors.get(id(anchor)) is not anchor:
            raise ValueError("SERIALIZATION_PRIVATE_ANCHOR_UNAVAILABLE")
        record = _CHECKPOINTS.get(checkpoint_digest)
        fixed = None if record is None else record.get("fixed_anchor")
        if fixed is None:
            raise ValueError("SERIALIZATION_PRIVATE_CHECKPOINT_UNAVAILABLE")
        native_anchor = require_anchor(fixed["immutable_anchor"])
        original_context = json.loads(anchor.context_bytes)
        if (native_anchor.reference_bytes != anchor.projection_bytes
                or native_anchor.reference_projection_digest != anchor.exact_digest
                or native_anchor.installed_build != original_context["installed_build"]
                or native_anchor.runtime_epoch != original_context["runtime_epoch"]
                or native_anchor.runtime_fingerprint != original_context["runtime_fingerprint"]):
            raise ValueError("SERIALIZATION_LOAD_FIXED_ANCHOR_DIFFERS")
        manifest = record["manifest"]
        parent_identity = dict(guards.scene_instance(parent_scene))
        if (manifest["working_scene_instance_id"] != parent_identity["scene_instance_id"]
                or manifest["document_lineage_id"] != parent_identity["document_lineage_id"]):
            raise ValueError("SERIALIZATION_LOAD_PARENT_IS_NOT_PRIVATE_WORKSPACE")
        assert_admitted_effect()
        source_guard()
        target, observation = load_project_copy(manifest["path"], working_path,
            expected_sha256=manifest["sha256"], expected_length=manifest["bytes"],
            source_guard=source_guard)
        source_guard()
        if (observation.get("native_completion") != "observed"
                or observation["source_file"]["sha256"] != manifest["sha256"]
                or observation["source_file"]["length"] != manifest["bytes"]
                or observation["working_file"]["sha256"] != manifest["sha256"]
                or observation["working_file"]["length"] != manifest["bytes"]):
            raise ValueError("SERIALIZATION_ACTUAL_PROJECT_LOAD_UNOBSERVED")
        runner = bind_native_update_runner(target, extract_installed_update_facts,
                                           assert_admitted_effect)
        target_identity = dict(guards.scene_instance(target))
        if target_identity["scene_instance_id"] == parent_identity["scene_instance_id"]:
            raise ValueError("SERIALIZATION_LOAD_DID_NOT_CREATE_NEW_INSTANCE")
        self._phase_runners[id(anchor)][id(runner)] = frozen_json(target_identity)
        self._loads[id(runner)] = (parent_scene, target, frozen_json({
            "parent": parent_identity, "provisional_target": target_identity,
            "checkpoint_digest": checkpoint_digest, "load": observation}))
        return target, observation, runner

    def bind_completed_clone_identity(self, anchor: Anchor, runner: UpdateCaptureRunner) -> None:
        """Memory-only continuation AFTER existing guards.link_clone succeeds.

        _restore_native currently links lineage only after both comparisons and
        original-tab restoration. Preserve that order and record the provisional
        load identity separately; never edit P0 or rewrite the earlier observation.
        """
        from cascadeur_complete import guarded_runtime as guards
        if self._anchors.get(id(anchor)) is not anchor or id(runner) not in self._loads:
            raise ValueError("SERIALIZATION_PRIVATE_LOAD_UNAVAILABLE")
        parent, target, raw = self._loads[id(runner)]
        retained = json.loads(raw)
        current = dict(guards.scene_instance(target))
        if (dict(guards.scene_instance(parent)) != retained["parent"]
                or current["scene_instance_id"] != retained["provisional_target"]["scene_instance_id"]
                or current["document_lineage_id"] != retained["parent"]["document_lineage_id"]):
            raise ValueError("SERIALIZATION_COMPLETED_CLONE_IDENTITY_DIFFERS")
        self._phase_runners[id(anchor)][id(runner)] = frozen_json(current)

    def verify(self, anchor: Anchor, observation: PhaseObservation, actual_projection: dict) -> None:
        if (self._anchors.get(id(anchor)) is not anchor
                or self._observations.get(id(observation)) is not observation
                or observation.anchor_digest != anchor.exact_digest
                or frozen_json(actual_projection) != observation.actual_projection_bytes):
            raise ValueError("SERIALIZATION_OBSERVATION_NOT_PRIVATE_OR_RAW_STATE_DIFFERS")
