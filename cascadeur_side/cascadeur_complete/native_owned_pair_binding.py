"""Explicit two-mesh setup and current-request integration.

The installed extractor is a required code dependency, not a flag accepted
from MCP. The installed SDK extractor is implemented; actual native qualification
is still required before these observations authorize a supported pair.
No binding is installed until the complete retained setup returns normally.
"""
from __future__ import annotations

import hashlib
import importlib
import json

from . import guarded_runtime as guards
from .native_owned_pair_geometry import (
    PairGeometryPositivePath, PROFILE, SETUP_OPERATION, LIMITS, INTERPOLATION,
    MutationEvaluationRebind, bind_native_authenticated_terminal_lookup,
    native_read_pair_inputs, _expected,
)
from .native_update_capture import bind_native_update_runner, frozen_json
from .native_update_source import (graph_scope, assert_historical_source,
    assert_callback_source, require_callback_check, MODE)

_BINDINGS = {}
_ACTIVATIONS = {}


def installed_leaf(*, required=True):
    """Load the implemented installed-SDK reader without claiming qualification.

    Its sole mandatory function is extract_installed_update_facts. Optional
    serialization_role_specs(scene) may return code-reviewed RoleSpec objects.
    An absent classifier means exact-only comparison, never guessed roles.
    The module must not register capabilities or execute SDK actions on import.
    """
    name = __package__ + ".native_installed_update_facts"
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        if not required:
            return None
        raise ValueError("INSTALLED_UPDATE_FACTS_IMPLEMENTATION_REQUIRED") from error
    if not callable(getattr(module, "extract_installed_update_facts", None)):
        raise ValueError("INSTALLED_UPDATE_FACTS_CALLABLE_MISSING")
    return module


def _key(scene):
    return (guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT,
            guards.scene_instance(scene)["scene_instance_id"])


def _context(scene):
    from . import runtime as rt
    from .native_adapters import installed_build
    from .native_export import selection_observation
    guards.assert_loaded_package()
    if rt._scene_view() is not scene:
        raise ValueError("PAIR_SCENE_NOT_ACTIVE")
    return {"installed_build": installed_build(), "runtime_epoch": guards.RUNTIME_EPOCH,
            "runtime_fingerprint": guards.LOADED_FINGERPRINT,
            "scene": dict(guards.scene_instance(scene)),
            "selection": selection_observation(scene),
            "frame": int(rt._domain_scene(scene).get_current_frame(False))}


def pair_status(scene=None):
    binding = None if scene is None else _BINDINGS.get(_key(scene))
    return {"qualified": binding is not None, "profile": PROFILE if binding else None,
            "code": None if binding else "OWNED_PAIR_NATIVE_SETUP_NOT_COMPLETED",
            "general_rig_supported": False,
            "scope": None if binding is None else {"mesh_ids": list(binding.contract.mesh_ids),
                "frames": [0, 1, 2], "maximum_vertices_per_mesh": 64},
            "current_graph_checked_at_execution": True}


def pair_binding(scene, *, required=True):
    guards.assert_loaded_package()
    binding = _BINDINGS.get(_key(scene))
    if binding is None and required:
        raise ValueError("OWNED_PAIR_NATIVE_SETUP_NOT_COMPLETED")
    return binding


def pair_ownership(scene, projection, ids, source):
    binding = pair_binding(scene, required=False)
    if binding is None:
        return None
    if (set(ids) != set(binding.contract.mesh_ids)
            or set(source.get("scope", {}).get("object_ids", ())) != set(ids)
            or source.get("scope", {}).get("profile", {}).get("character_id") is not None):
        return None
    binding.assert_current(scene, projection, {"mesh_ids": list(ids)})
    # Identity ownership only; never invent a RigInfo or a shared character.
    return {identifier: identifier for identifier in ids}


class _PairBinding:
    def __init__(self, scene, path, contract, original_scene, original_projection, setup_request_id):
        self.scene, self.path, self.contract = scene, path, contract
        self.original_scene, self.original_projection = original_scene, frozen_json(original_projection)
        from .native_scene_reader import read_scene
        self.initial_projection = frozen_json(read_scene(scene))
        self.setup_request_id = setup_request_id
        self.continuation_plan = None
        self.normal_activation_started = False
        from .handlers.scene import _tab_identity
        self.fixture_tab_id, self.original_tab_id = _tab_identity(scene), _tab_identity(original_scene)
        self.synchronous_calculation_evidence_digest = guards.digest(json.loads(contract.evidence_bytes))
        self.rebind = None
        self.pending = {}
        self.last_mutation = None
        self.window_matrices = {}
        self.window_snapshot = None

    def assert_continuation(self):
        from . import runtime as rt
        from .native_checkpoint_restore import _original_terminal
        from .incident_admission import assert_request_admission
        assert_request_admission()
        request = getattr(guards._LOCAL, "request", None)
        if request is None:
            raise ValueError("PAIR_CURRENT_REQUEST_REQUIRED")
        execution = request.get("execution_context") or {}
        _, receipt = _original_terminal(rt.runtime_root(), self.setup_request_id)
        # Normal admission has already checked all incident domains. It does
        # not require entry into a legacy-only route to use a healthy fixture.
        normal = execution.get("incident_route") is None and "finite_continuation" not in execution
        if normal:
            context = {"setup_request_id": self.setup_request_id,
                "setup_receipt_digest": guards.digest(receipt),
                "fixture_scene": dict(guards.scene_instance(self.scene)),
                "original_scene": dict(guards.scene_instance(self.original_scene)),
                "plan_digest": None, "normal_admission": True}
        else:
            context = execution.get("finite_continuation", {})
            if (context.get("setup_request_id") != self.setup_request_id
                    or context.get("fixture_scene") != dict(guards.scene_instance(self.scene))
                    or context.get("original_scene") != dict(guards.scene_instance(self.original_scene))
                    or not isinstance(context.get("plan_digest"), str)
                    or len(context["plan_digest"]) != 64
                    or self.continuation_plan is not None and self.continuation_plan != context["plan_digest"]):
                raise ValueError("PAIR_CONTINUATION_SETUP_OR_PLAN_DIFFERS")
        value = (receipt or {}).get("terminal_result") or {}
        results = (value.get("result") or {}).get("steps", ())
        observed = [row.get("result") for row in results if row.get("operation") == SETUP_OPERATION]
        if (receipt is None or receipt.get("outcome") != "succeeded" or not value.get("ok")
                or guards.digest(receipt) != context.get("setup_receipt_digest") or len(observed) != 1
                or observed[0].get("setup_request_id") != self.setup_request_id
                or observed[0].get("fixture_scene") != context["fixture_scene"]
                or observed[0].get("original_scene") != context["original_scene"]
                or set(observed[0].get("mesh_ids", ())) != set(self.contract.mesh_ids)
                or observed[0].get("fixture_projection_digest") != hashlib.sha256(self.initial_projection).hexdigest()):
            raise ValueError("PAIR_AUTHENTICATED_SETUP_TERMINAL_DIFFERS")
        return context

    def current_rebind(self, runner):
        if self.rebind is None:
            self.rebind = MutationEvaluationRebind(runner, bind_native_authenticated_terminal_lookup())
        else:
            # Snapshot ownership uses the shared native private store, while
            # the read context and effect guard always belong to this request.
            self.rebind.runner = runner
        return self.rebind

    def require_origin_chain(self, arguments, capture, projection):
        """Read-only chain lookup; current graph is checked in capture_window."""
        if self.rebind is None:
            raise ValueError("GEOMETRY_ORIGIN_SUCCESSOR_REBIND_UNAVAILABLE")
        record = self.rebind._evaluations.get(capture["evaluation"]["request_id"])
        if (record is None or record["receipt"] is None
                or record["origin_id"] != arguments["origin_request_id"]
                or record["after"].projection_bytes != frozen_json(projection)
                or record["post_source"] != frozen_json(arguments["motion_source_binding"])
                or guards.digest(json.loads(record["receipt"])) != capture["evaluation_receipt_digest"]):
            raise ValueError("GEOMETRY_ORIGIN_SUCCESSOR_REBIND_UNAVAILABLE")

    def assert_current(self, scene, projection, arguments):
        """Read-only preflight. Full graph is checked in the admitted Update.

        This method must not trigger an Update while system.capture_source or
        guards.assert_source is reading a source. Graph-only edits are rejected
        by capture_window before any actual positions are published.
        """
        from .native_scene_reader import read_scene
        self.assert_continuation()
        if (scene is not self.scene or frozen_json(_context(scene)) != self.contract.scene_context_bytes
                or set(arguments["mesh_ids"]) != set(self.contract.mesh_ids)
                or read_scene(scene) != projection):
            raise ValueError("PAIR_CURRENT_SCENE_OR_SCOPE_DIFFERS")
        inputs = native_read_pair_inputs(scene, self.path._fixtures)
        if frozen_json(self.path._static(inputs)) != self.contract.static_inputs_bytes:
            raise ValueError("PAIR_STATIC_DEPENDENCY_CHANGED")

    def coordinate_contract(self, context):
        from .geometry_policy import CoordinateContract
        return CoordinateContract(self.contract.raw_space, context["metres_per_scene_unit"],
            tuple(tuple(row) for row in context["scene_to_solver_basis"]),
            guards.digest(json.loads(self.contract.evidence_bytes)), guards.digest(context))

    def mesh_to_world(self, scene, mesh_id, frame):
        if scene is not self.scene or frame not in (0, 1, 2):
            raise ValueError("PAIR_MATRIX_SCOPE_DIFFERS")
        from .native_update_source import _snapshot
        if self.window_snapshot is None or (mesh_id, frame) not in self.window_matrices:
            raise ValueError("PAIR_MATRIX_NOT_OBSERVED_IN_CALCULATION_CALLBACK")
        _snapshot(scene, self.window_snapshot)
        from .native_scene_reader import read_scene
        if frozen_json(read_scene(scene)) != self.window_snapshot.projection_bytes:
            raise ValueError("PAIR_CALCULATION_MATRIX_SNAPSHOT_CHANGED")
        return json.loads(self.window_matrices[(mesh_id, frame)])

    def capture_window(self, scene, mesh_id, frames, count, *, request, before_calculation):
        import numpy as np
        if (scene is not self.scene or mesh_id not in self.contract.mesh_ids
                or not frames or tuple(sorted(set(frames))) != tuple(frames)
                or not set(frames) <= {0, 1, 2}):
            raise ValueError("PAIR_WINDOW_SCOPE_DIFFERS")
        from .incident_admission import assert_request_admission
        def admitted():
            assert_request_admission()
            if getattr(guards._LOCAL, "request", None) is not request:
                raise ValueError("PAIR_CURRENT_REQUEST_CHANGED")
            before_calculation()
        leaf = installed_leaf()
        runner = bind_native_update_runner(scene, leaf.extract_installed_update_facts, admitted)
        def assert_inputs(inputs, projection, facts):
            assert_callback_source(scene, request["source_binding"], projection, facts)
            self.assert_current(scene, projection, {"mesh_ids": list(self.contract.mesh_ids)})
            if (guards.digest(facts.material()) != self.contract.graph_dtype_digest
                    or len(inputs[mesh_id]["positions"]) != count):
                raise ValueError("PAIR_CURRENT_GRAPH_OR_VERTEX_COUNT_CHANGED")
        snapshot, (inputs, trials) = self.path._observe(
            tuple((mesh_id, frame) for frame in frames), runner=runner,
            before_calculation=admitted, assert_inputs=assert_inputs)
        runner.require(snapshot)
        self.window_snapshot = snapshot
        self.window_matrices = {(mesh_id, frame): frozen_json(inputs[mesh_id]["matrices"][frame]) for frame in frames}
        arguments = request["operations"][0]["arguments"]
        from .native_motion_capture import lookup_capture
        capture = lookup_capture(arguments["motion_capture_digest"])
        self.current_rebind(runner).require_capture(arguments["origin_request_id"], capture,
            arguments["motion_source_binding"], snapshot)
        if any(row["raw"] != _expected(inputs[mesh_id], row["frame"], self.contract.raw_space)
               for row in trials):
            raise ValueError("PAIR_CURRENT_CALCULATION_FORMULA_DIFFERS")
        return np.asarray([row["raw"] for row in trials], dtype=np.float32)


def _adapter_evidence(adapter, evidence):
    from .native_adapters import installed_build
    adapter.evidence_bytes = frozen_json(evidence)
    adapter.observed_build = installed_build
    adapter.verification = {"runtime_fingerprint": guards.LOADED_FINGERPRINT,
        "installed_build": installed_build(), "identity_stable": True,
        "operations": evidence["operations"], "dispatch_semantics": "synchronous_no_yield",
        "evidence_sha256": hashlib.sha256(adapter.evidence_bytes).hexdigest()}


def expected_pair_position(projection, fixture, frame, value):
    """Pure four-channel translation model; preserve the ENTIRE source.

    The one-object view below is only input to pure math, never a fake SDK
    viewer. All other objects, sections, values, links and assets stay exact.
    """
    import copy
    import numpy as np
    from .native_independent_position import _position_closure, _expected_projection
    identifier = fixture["object_id"]
    objects = [row for row in projection["objects"] if row["id"] == identifier]
    layers = [row for row in projection["layers"] if row["id"] == fixture["layer_id"]]
    if (projection["frames"] != 3 or len(objects) != 1 or len(layers) != 1
            or layers[0]["object_ids"] != [identifier] or layers[0]["locked"]
            or layers[0]["keys"] != [0, 1, 2]
            or [row["frame"] for row in layers[0]["sections"]] != [0, 1, 2]
            or any(row["interpolation"] != INTERPOLATION for row in layers[0]["sections"])
            or frame not in (0, 1, 2)):
        raise ValueError("PAIR_POSITION_EXISTING_INDEPENDENT_KEY_SCOPE_DIFFERS")
    view = {**projection, "objects": objects}
    driver = {"data_id": fixture["position_data_ids"]["local"], "frames": [0, 1, 2],
              "segment_modes": [INTERPOLATION, INTERPOLATION]}
    driver["position_closure"] = _position_closure(view, driver)
    return _expected_projection(projection, driver,
        [{"frame": frame, "position": np.asarray(value, dtype=np.float32).reshape(3).tolist()}])


def qualify_owned_pair_geometry():
    from .incident_admission import assert_setup_admission, _LOCAL as admission_local
    from .native_fixture import create_disposable_scene
    from .native_probe_retention import RetainedProbe, retained_probe_result
    from .native_geometry_capture import NativeGeometryCaptureAdapter, OPERATION
    grant = assert_setup_admission(SETUP_OPERATION)
    setup_request_id = admission_local.setup["invocation_ref"]
    if getattr(guards._LOCAL, "request", {}).get("request_id") != setup_request_id:
        raise ValueError("PAIR_SETUP_REQUEST_ID_DIFFERS")
    limits = {"maximum_geometry_calculations": 10, "maximum_evaluations": 2,
              "maximum_driver_mutations": 1, "maximum_update_graph_captures": 2}
    if any(getattr(grant, key, None) != value for key, value in limits.items()):
        raise ValueError("PAIR_SETUP_SEMANTIC_LIMITS_DIFFER")
    # Resolve the real leaf before a tab or file can be created.
    leaf = installed_leaf()
    prior = retained_probe_result("owned_pair_geometry")
    if prior is not None:
        if not any(value.contract.mesh_ids == tuple(prior["mesh_ids"]) for value in _BINDINGS.values()):
            raise ValueError("PAIR_PRIOR_RESULT_HAS_NO_PRIVATE_BINDING")
        return prior
    if OPERATION in guards._ADAPTERS:
        raise ValueError("PAIR_GEOMETRY_ADAPTER_ALREADY_REGISTERED")
    retained = RetainedProbe("owned_pair_geometry")
    original_scene, original_projection = retained.previous, retained.original_projection
    error = None
    completed = []
    prior_adapters = {name: guards._ADAPTERS.get(name) for name in (
        OPERATION, "animation.interpolation_refresh", "animation.transform_set", "scene.activate")}
    installed_adapters = {}
    try:
        retained.before_new_tab()
        scene = create_disposable_scene(retain_on_failure=True)
        retained.track(scene, "owned-geometry-pair")
        runner = bind_native_update_runner(scene, leaf.extract_installed_update_facts, retained.before_effect)
        path = PairGeometryPositivePath(scene=scene, retained=retained, runner=runner)
        def finish(evidence):
            from .handlers.scene import _tab_identity
            from .native_scene_reader import read_scene
            fixture_projection_digest = guards.digest(read_scene(scene))
            retention = retained.finish(None)
            completed.append(retained.complete({"profile": PROFILE, "limits": LIMITS,
                "mesh_ids": list(evidence["after"]), "retention": retention,
                "fixture_scene": dict(guards.scene_instance(scene)), "frames": [0, 1, 2],
                "setup_request_id": setup_request_id, "fixture_projection_digest": fixture_projection_digest,
                "fixture_tab_id": _tab_identity(scene), "original_tab_id": _tab_identity(original_scene),
                "original_scene": dict(guards.scene_instance(original_scene)),
                "layer_ids": [row["layer_id"] for row in path._fixtures],
                "general_rig_supported": False, "geometry_evidence_digest": guards.digest(evidence)}))
        contract = path.initialize(finish)
        binding = _PairBinding(scene, path, contract, original_scene, original_projection, setup_request_id)
        if hashlib.sha256(binding.initial_projection).hexdigest() != completed[0]["fixture_projection_digest"]:
            raise ValueError("PAIR_POST_RETENTION_FIXTURE_CHANGED")
        _BINDINGS[_key(scene)] = binding
        evidence = {"profile": PROFILE, "setup": json.loads(contract.evidence_bytes),
                    "retention": completed[0]["retention"], "operations": [OPERATION]}
        adapter = NativeGeometryCaptureAdapter()
        _adapter_evidence(adapter, evidence)
        retained.before_effect()
        guards.register_adapter(OPERATION, adapter)
        installed_adapters[OPERATION] = adapter
        for name, finite in (("animation.interpolation_refresh", _PairEvaluationAdapter(binding)),
                             ("animation.transform_set", _PairPositionAdapter(binding)),
                             ("scene.activate", _PairActivationAdapter(binding))):
            evaluator = _ProfileRouter(binding, finite, guards._ADAPTERS.get(name))
            _adapter_evidence(evaluator, {**evidence, "operations": [name],
                "previous_adapter": None if evaluator.previous is None else evaluator.previous.verification})
            retained.before_effect()
            guards.register_adapter(name, evaluator)
            installed_adapters[name] = evaluator
        return completed[0]
    except Exception as exc:
        error = exc
        if "scene" in locals():
            _BINDINGS.pop(_key(scene), None)
        for name, installed in installed_adapters.items():
            if guards._ADAPTERS.get(name) is installed:
                if prior_adapters[name] is None:
                    guards._ADAPTERS.pop(name)
                else:
                    guards._ADAPTERS[name] = prior_adapters[name]
        raise
    finally:
        if not retained.finished:
            retained.finish(error)


class _ProfileRouter:
    """Preserve prior exact scopes while selecting privately owned pair scenes."""
    def __init__(self, binding, finite, previous):
        self.binding, self.finite, self.previous = binding, finite, previous
        self.previous_evidence = None if previous is None else bytes(previous.evidence_bytes)

    def _select(self, scene):
        if isinstance(self.finite, _PairActivationAdapter) and any(scene is value for value in (self.binding.scene, self.binding.original_scene)):
            return self.finite
        if scene is self.binding.scene and pair_binding(scene, required=False) is self.binding:
            return self.finite
        if self.previous is None:
            raise ValueError("PAIR_PROFILE_REQUIRED_FOR_THIS_OPERATION")
        proof = self.previous.verification
        if (self.previous.evidence_bytes != self.previous_evidence
                or proof["runtime_fingerprint"] != guards.LOADED_FINGERPRINT
                or proof["installed_build"] != self.previous.observed_build()
                or proof["evidence_sha256"] != hashlib.sha256(self.previous_evidence).hexdigest()):
            raise ValueError("PREVIOUS_ADAPTER_EVIDENCE_CHANGED")
        return self.previous

    def required_scope(self, scene, scope):
        return self._select(scene).required_scope(scene, scope)

    def capture(self, scene, scope):
        return self._select(scene).capture(scene, scope)

    def accepts_update_boundary_source(self, scene, scope):
        selected = self._select(scene)
        return getattr(selected, "accepts_update_boundary_source", lambda *_: False)(scene, scope)

    def execute(self, scene, arguments, request):
        return self._select(scene).execute(scene, arguments, request)


class _PairEvaluationAdapter:
    """Finite evaluation and authenticated mutation-successor bookends."""
    adapter_id = "native-owned-pair-evaluation-v1"

    def __init__(self, binding):
        self.binding = binding

    def accepts_update_boundary_source(self, scene, scope):
        return (scene is self.binding.scene and pair_binding(scene, required=False) is self.binding
                and scope.get("validation_mode") == MODE
                and scope.get("expected_graph_dtype_digest") == self.binding.contract.graph_dtype_digest)

    def required_scope(self, scene, scope):
        from .native_scene_reader import read_scene
        if scope.get("operation_name") != "animation.interpolation_refresh" or scope.get("operation_arguments") != {}:
            raise ValueError("PAIR_EVALUATION_OPERATION_DIFFERS")
        projection = read_scene(scene)
        self.binding.assert_current(scene, projection, {"mesh_ids": list(self.binding.contract.mesh_ids)})
        return graph_scope({"operation_name": "animation.interpolation_refresh", "operation_arguments": {},
            "operation_arguments_digest": guards.digest({}), "adapter_id": self.adapter_id,
            "object_ids": [row["id"] for row in projection["objects"]],
            "layer_ids": [row["id"] for row in projection["layers"]], "frames": [0, 2]}, self.binding.contract.graph_dtype_digest)

    def capture(self, scene, scope):
        from .native_scene_reader import read_scene
        self.required_scope(scene, scope)
        projection = read_scene(scene)
        return {"coverage_complete": True, "authored_projection": projection, "sample_projection": projection}

    def execute(self, scene, arguments, request):
        from .native_scene_adapter import _EVALUATIONS
        from .incident_admission import assert_request_admission
        if self.binding.rebind is not None and len(self.binding.rebind._evaluations) >= 64:
            raise ValueError("PAIR_EVALUATION_RECORD_BUDGET")
        source = request["source_binding"]
        assert_historical_source(scene, source, operation_name="animation.interpolation_refresh", arguments={})
        leaf = installed_leaf()
        def admitted():
            assert_request_admission()
            if getattr(guards._LOCAL, "request", None) is not request:
                raise ValueError("PAIR_CURRENT_REQUEST_CHANGED")
            assert_historical_source(scene, source)
        runner = bind_native_update_runner(scene, leaf.extract_installed_update_facts, admitted)
        def refresh(_model, _update, updater, projection, facts):
            assert_callback_source(scene, source, projection, facts)
            self.binding.assert_current(scene, projection, {"mesh_ids": list(self.binding.contract.mesh_ids)})
            if guards.digest(facts.material()) != self.binding.contract.graph_dtype_digest:
                raise ValueError("PAIR_CURRENT_GRAPH_CHANGED")
            interpolator = updater.get_interpolator()
            interpolator.reload()
            interpolator.interpolate()
        before, after, _ = runner.transition(refresh)
        rebind = self.binding.current_rebind(runner)
        if self.binding.last_mutation is not None:
            rebind.stage_evaluation(self.binding.last_mutation, request, before, after)
        else:
            rebind.stage_baseline_evaluation(request, before, after)
        self.binding.pending[request["request_id"]] = ("evaluation", after)
        identity = dict(guards.scene_instance(scene))
        value = {"projection_digest": guards.digest(after.projection), "runtime_epoch": guards.RUNTIME_EPOCH,
                 "request_id": request["request_id"], "frames": [0, 2], "native_completion": "observed"}
        _EVALUATIONS[identity["scene_instance_id"]] = value
        guards.observe_effect("animation.interpolation_refresh", "completed", scene_before=identity,
            scene_after=identity, detail={"projection_digest": value["projection_digest"]})
        return {"native_completion": "observed", "evaluation": dict(value)}, []


class _PairPositionAdapter:
    """One explicit local-position write to an existing key in the owned pair."""
    adapter_id = "native-owned-pair-position-v1"

    def __init__(self, binding):
        self.binding = binding

    def accepts_update_boundary_source(self, scene, scope):
        return (scene is self.binding.scene and pair_binding(scene, required=False) is self.binding
                and scope.get("validation_mode") == MODE
                and scope.get("expected_graph_dtype_digest") == self.binding.contract.graph_dtype_digest)

    def required_scope(self, scene, scope):
        import numpy as np
        from .native_scene_reader import read_scene
        arguments = scope.get("operation_arguments")
        if (scope.get("operation_name") != "animation.transform_set"
                or not isinstance(arguments, dict) or set(arguments) != {"ids", "position", "frame", "space"}
                or type(arguments["ids"]) is not list or len(arguments["ids"]) != 1
                or arguments["ids"][0] not in self.binding.contract.mesh_ids
                or type(arguments["frame"]) is not int or arguments["frame"] not in (0, 1, 2)
                or arguments["space"] != "local"
                or type(arguments["position"]) is not list or len(arguments["position"]) != 3
                or any(type(value) not in (int, float) for value in arguments["position"])):
            raise ValueError("PAIR_POSITION_SCOPE_INVALID")
        value = np.asarray(arguments["position"], dtype=np.float32)
        if not np.isfinite(value).all():
            raise ValueError("PAIR_POSITION_FLOAT32_RANGE_INVALID")
        projection = read_scene(scene)
        self.binding.assert_current(scene, projection, {"mesh_ids": list(self.binding.contract.mesh_ids)})
        return graph_scope({"operation_name": "animation.transform_set", "operation_arguments": arguments,
            "operation_arguments_digest": guards.digest(arguments), "adapter_id": self.adapter_id,
            "object_ids": [row["id"] for row in projection["objects"]],
            "layer_ids": [row["id"] for row in projection["layers"]], "frames": [0, 2]}, self.binding.contract.graph_dtype_digest)

    def capture(self, scene, scope):
        from .native_scene_reader import read_scene
        self.required_scope(scene, scope)
        projection = read_scene(scene)
        return {"coverage_complete": True, "authored_projection": projection, "sample_projection": projection}

    def execute(self, scene, arguments, request):
        import csc
        import numpy as np
        from .incident_admission import assert_request_admission
        if self.binding.rebind is not None and len(self.binding.rebind._origins) >= 64:
            raise ValueError("PAIR_MUTATION_RECORD_BUDGET")
        source = request["source_binding"]
        assert_historical_source(scene, source, operation_name="animation.transform_set", arguments=arguments)
        self.required_scope(scene, source["scope"])
        leaf = installed_leaf()
        def admitted():
            assert_request_admission()
            if getattr(guards._LOCAL, "request", None) is not request:
                raise ValueError("PAIR_CURRENT_REQUEST_CHANGED")
            assert_historical_source(scene, source)
        runner = bind_native_update_runner(scene, leaf.extract_installed_update_facts, admitted)
        fixture = next(row for row in self.binding.path._fixtures if row["object_id"] == arguments["ids"][0])
        data_id, frame = fixture["position_data_ids"]["local"], arguments["frame"]
        value = np.asarray(arguments["position"], dtype=np.float32).reshape(3, 1)
        expected_values = []
        def mutate(model, _update, _updater, projection, facts):
            assert_callback_source(scene, source, projection, facts)
            self.binding.assert_current(scene, projection, {"mesh_ids": list(self.binding.contract.mesh_ids)})
            if guards.digest(facts.material()) != self.binding.contract.graph_dtype_digest:
                raise ValueError("PAIR_CURRENT_GRAPH_CHANGED")
            expected_values.append(expected_pair_position(projection, fixture, frame, value))
            model.data_editor().set_data_value(csc.model.DataId(data_id), frame, value)
        before, after, _ = runner.transition(mutate)
        if len(expected_values) != 1 or after.projection != expected_values[0]:
            raise ValueError("PAIR_POSITION_COMPLETE_NATIVE_CLOSURE_DIFFERS")
        self.binding.current_rebind(runner)
        self.binding.pending[request["request_id"]] = ("mutation", after)
        identity = dict(guards.scene_instance(scene))
        guards.observe_effect("animation.transform_set", "completed", scene_before=identity,
            scene_after=identity, detail={"data_id": data_id, "frame": frame,
                "projection_digest": guards.digest(after.projection)})
        return {"native_completion": "observed", "data_id": data_id, "frame": frame,
                "position": value[:, 0].tolist()}, []


def finalize_pair_operation(scene, request, result, receipt):
    """Only memory sealing after runtime has durably issued its real terminal."""
    _ACTIVATIONS.pop(request.get("request_id"), None)
    binding = pair_binding(scene, required=False)
    if binding is None:
        return
    pending = binding.pending.pop(request.get("request_id"), None)
    if pending is None:
        return
    if (not result.get("ok") or result.get("outcome") != "succeeded"
            or receipt.get("phase") != "terminal" or receipt.get("outcome") != "succeeded"):
        return
    kind, snapshot = pending
    if kind == "mutation":
        successor = result["result"]["post_source_binding"]
        binding.rebind.stage_mutation(request, successor, snapshot)
        binding.rebind.seal_mutation(request["request_id"])
        binding.last_mutation = request["request_id"]
    else:
        binding.rebind.seal_evaluation(request["request_id"])
        binding.last_mutation = None


class _PairActivationAdapter:
    """Switch between the two exact retained tabs; preserve both documents."""
    adapter_id = "native-owned-pair-activation-v1"

    def __init__(self, binding):
        self.binding = binding

    def _state(self, scene, arguments):
        import csc
        from .native_scene_reader import read_scene
        from .handlers.scene import _tab_identity
        binding = self.binding
        context = binding.assert_continuation()
        if not isinstance(arguments, dict) or set(arguments) != {"tab_id"}:
            raise ValueError("PAIR_ACTIVATION_EXACT_TAB_REQUIRED")
        targets = {binding.fixture_tab_id: binding.scene, binding.original_tab_id: binding.original_scene}
        if arguments["tab_id"] not in targets:
            raise ValueError("PAIR_ACTIVATION_TARGET_NOT_PRIVATELY_RETAINED")
        manager = csc.app.get_application().get_scene_manager()
        tabs = tuple(manager.scenes())
        if (manager.current_scene() is not scene
                or not any(scene is value for value in targets.values())
                or any(not any(value is live for live in tabs) for value in targets.values())
                or frozen_json(read_scene(binding.original_scene)) != binding.original_projection):
            raise ValueError("PAIR_ACTIVATION_RETAINED_SCENES_CHANGED")
        target = targets[arguments["tab_id"]]
        if binding.continuation_plan is None and not binding.normal_activation_started:
            if (target is not binding.scene or scene is not binding.original_scene
                    or frozen_json(read_scene(binding.scene)) != binding.initial_projection):
                raise ValueError("PAIR_INITIAL_ACTIVATION_BASELINE_CHANGED")
        projection = {"original": read_scene(binding.original_scene), "fixture": read_scene(binding.scene),
            "active_tab_id": _tab_identity(scene),
            "tabs": [{"tab_id": _tab_identity(value), "path": str(value.get_path_name())} for value in tabs]}
        return manager, target, projection

    def required_scope(self, scene, scope):
        if scope.get("operation_name") != "scene.activate":
            raise ValueError("PAIR_ACTIVATION_OPERATION_DIFFERS")
        arguments = scope.get("operation_arguments")
        _, _, projection = self._state(scene, arguments)
        fixture = projection["fixture"]
        return {"operation_name": "scene.activate", "operation_arguments": arguments,
            "operation_arguments_digest": guards.digest(arguments), "adapter_id": self.adapter_id,
            "object_ids": [row["id"] for row in fixture["objects"]],
            "layer_ids": [row["id"] for row in fixture["layers"]], "frames": [0, 2],
            "retained_scene_ids": [guards.scene_instance(self.binding.original_scene)["scene_instance_id"],
                                   guards.scene_instance(self.binding.scene)["scene_instance_id"]]}

    def capture(self, scene, scope):
        self.required_scope(scene, scope)
        _, _, projection = self._state(scene, scope["operation_arguments"])
        return {"coverage_complete": True, "authored_projection": projection, "sample_projection": projection}

    def execute(self, scene, arguments, request):
        source = request["source_binding"]
        guards.assert_source(scene, source, operation_name="scene.activate", arguments=arguments)
        manager, target, before = self._state(scene, arguments)
        source_identity, target_identity = dict(guards.scene_instance(scene)), dict(guards.scene_instance(target))
        guards.before_write()
        # Reserve this private fixture for the exact admitted continuation
        # before switching tabs; a failed switch cannot authorize another plan.
        admission = self.binding.assert_continuation()
        if admission.get("normal_admission"):
            self.binding.normal_activation_started = True
        else:
            self.binding.continuation_plan = admission["plan_digest"]
        manager.set_current_scene(target)
        _, observed_target, after = self._state(target, arguments)
        if (observed_target is not target or any(before[key] != after[key] for key in ("original", "fixture", "tabs"))
                or after["active_tab_id"] != arguments["tab_id"]):
            raise ValueError("PAIR_ACTIVATION_CURRENT_TAB_OR_DOCUMENTS_DIFFER")
        record = {"request_digest": guards.digest(request), "from": source_identity, "to": target_identity,
                  "before": frozen_json(before), "after": frozen_json(after), "target": target, "binding": self.binding}
        _ACTIVATIONS[request["request_id"]] = record
        guards.finish_write()
        guards.observe_effect("scene.activate", "completed", scene_before=source_identity, scene_after=target_identity,
            detail={"tab_id": arguments["tab_id"], "documents_preserved": True})
        return {"native_completion": "observed", "tab_id": arguments["tab_id"],
                "scene": target_identity, "previous_tab_id": before["active_tab_id"]}, []


def approve_pair_activation_successor(request, source, successor, result, observation):
    """Runtime-only approval of the actual same-request tab switch."""
    record = _ACTIVATIONS.get(request.get("request_id"))
    if (record is None or record["request_digest"] != guards.digest(request)
            or request.get("operations", [{}])[0].get("name") != "scene.activate"
            or source.get("binding", {}).get("scene_instance_id") != record["from"]["scene_instance_id"]
            or successor.get("binding", {}).get("scene_instance_id") != record["to"]["scene_instance_id"]
            or result.get("result", {}).get("native_completion") != "observed"
            or observation.get("completion") != "completed"):
        return False
    adapter = _PairActivationAdapter(record["binding"])
    _, target, current = adapter._state(record["target"], request["operations"][0]["arguments"])
    return target is record["target"] and frozen_json(current) == record["after"]
