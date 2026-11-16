"""Finite two-mesh native implementation; explicit setup only.

Actual SDK calls below are copied/lowered from pinned current source. The new
two-object composition, calc inside Update callback, graph extractor and effect
contract have NOT been run/qualified. Importing this file performs no SDK work.
The reference registry is not the production _CONTRACTS or guards._ADAPTERS.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Callable

from .serialization_equivalence import canonical_digest
from .native_update_capture import UpdateCaptureRunner, UpdateSnapshot, frozen_json

PROFILE = "owned_two_self_bound_translation_meshes_v1"
SETUP_OPERATION = "setup.qualify_owned_pair_geometry"
KEYS = (
    ((0, (0., 0., 0.)), (1, (2., 1., 0.)), (2, (0., 2., 1.))),
    ((0, (8., 0., 0.)), (1, (9., 1., 0.)), (2, (10., 2., 1.))),
)
CALIBRATION_FRAMES = (0, 2, 1, 0)
LIMITS = {"tabs": 1, "casc_files": 2, "mesh_calculations": 10,
          "evaluations": 2, "driver_mutations": 1, "objects": 2,
          "maximum_vertices_per_mesh": 64, "maximum_frames": 3,
          "maximum_projection_bytes": 2 * 1024**2,
          "graph_capture_callbacks": 2}


def native_create_owned_pair(scene, retained) -> tuple[dict[str, Any], ...]:
    """New finite helper using existing SDK calls, not the single-object helper.

    create_independent_transform/set_independent_keys explicitly reject a second
    object. This function preserves that API and composes the underlying observed
    commands in a separately admitted owned scene. Its composition needs native
    qualification; no success of the old cube helper is reused as pair evidence.
    """
    import csc
    import numpy as np
    from commands.add.add_transform import add_transform_mod
    from common.mesh import set_mesh_object_data
    from cascadeur_complete import runtime as rt
    from cascadeur_complete.native_fixture import _owned, _modify
    state, domain = _owned(scene)
    if state["objects"]:
        raise ValueError("PAIR_FIXTURE_REQUIRES_EMPTY_OWNED_SCENE")
    created = []
    def create(model, update, callback_scene, session):
        for index in range(2):
            retained.before_effect()
            obj = add_transform_mod(model, update, callback_scene, session, True)
            model.set_object_name(obj, "MCPOwnedGeometryPair" + str(index))
            created.append(str(obj))
    _modify(domain.modify_with_session, "Create two owned geometry Transforms", create)
    actual = {str(obj): obj for obj in domain.model_viewer().get_objects()}
    if len(created) != 2 or len(set(created)) != 2 or set(created) != set(actual):
        raise ValueError("PAIR_FIXTURE_OBJECT_CLOSURE_DIFFERS")
    state["objects"].update(created)
    _owned(scene)
    bv, dv, lv = domain.behaviour_viewer(), domain.data_viewer(), domain.layers_viewer()
    fixtures = []
    for index, identifier in enumerate(created):
        obj = actual[identifier]
        transform = bv.get_behaviour_by_name(obj, "Transform")
        layer = lv.layer_id_by_obj_id_or_null(obj)
        if transform.is_null() or layer.is_null():
            raise ValueError("PAIR_FIXTURE_TYPED_TRANSFORM_OR_LAYER_MISSING")
        data = {space: bv.get_behaviour_data(transform, space + "_position")
                for space in ("local", "global")}
        if any(key.is_null() or dv.get_data(key).object_id != obj
               or dv.get_data(key).mode.name != "Animation" for key in data.values()):
            raise ValueError("PAIR_FIXTURE_TYPED_POSITION_OWNERSHIP_DIFFERS")
        fixtures.append({"object_id": identifier, "layer_id": str(layer),
                         "position_data_ids": {k: str(v) for k, v in data.items()},
                         "frames_count": 3, "index": index})
    if len({row["layer_id"] for row in fixtures}) != 2:
        raise ValueError("PAIR_FIXTURE_SHARED_LAYER_UNSUPPORTED")
    def author(model, update, callback_scene):
        for fixture in fixtures:
            retained.before_effect()
            obj = actual[fixture["object_id"]]
            layer = lv.layer_id_by_obj_id_or_null(obj)
            sections = {}
            for frame in range(3):
                section = csc.layers.layer.Section()
                section.interval.interpolation = csc.layers.layer.Interpolation.LINEAR
                section.interval.common.fixation = csc.layers.layer.Fixation.Free
                section.interval.common.ik_fk = csc.layers.layer.IkFk.FK
                section.key.common.fixation = csc.layers.layer.Fixation.Free
                section.key.common.ik_fk = csc.layers.layer.IkFk.FK
                section.key.label = csc.layers.layer.Key.no_label_id()
                section.key.tangents = csc.layers.layer.Tangents.Continuous
                sections[frame] = section
            model.layers_editor().set_sections(sections, layer)
        model.fit_animation_size_by_layers()
        for fixture in fixtures:
            for identifier in fixture["position_data_ids"].values():
                for frame, position in KEYS[fixture["index"]]:
                    retained.before_effect()
                    model.data_editor().set_data_value(csc.model.DataId(identifier), frame,
                                                       np.asarray(position, dtype=np.float32).reshape(3, 1))
            retained.before_effect()
            obj = actual[fixture["object_id"]]
            mesh = csc.domain.assets.AssetsManager.get_cube_mesh(2.0)
            dependency = csc.domain.assets.MeshDependency(mesh)
            set_mesh_object_data(callback_scene, model, update, update.get_object_by_id(obj),
                                 mesh, dependency, [obj], create_default_material=False)
    _modify(domain.modify, "Author and attach the owned geometry pair", author)
    if int(domain.layers_viewer().frames_count()) != 3:
        raise ValueError("PAIR_FIXTURE_TIMELINE_DIFFERS")
    for fixture in fixtures:
        obj = actual[fixture["object_id"]]
        layer = domain.layers_viewer().layer(domain.layers_viewer().layer_id_by_obj_id_or_null(obj))
        if (list(map(int, layer.key_frame_indices())) != [0, 1, 2]
                or any(layer.interval(f).interpolation.name != "LINEAR" for f in (0, 1))):
            raise ValueError("PAIR_FIXTURE_KEY_GRID_OR_INTERPOLATION_DIFFERS")
    return tuple(fixtures)


def native_read_pair_inputs(scene, fixtures) -> dict[str, Any]:
    """Two-object specialization of _fixture_inputs, using its exact getters.

    The existing _fixture_inputs returns domain,obj,positions,matrices,inputs
    and rejects len(objects)!=1. It must NOT be called with a fake one-object
    viewer, monkeypatched, or weakened globally to make this helper pass.
    """
    import csc
    import numpy as np
    from cascadeur_complete import runtime as rt
    from cascadeur_complete.native_scene_reader import native_value
    domain = rt._domain_scene(scene)
    mv, bv, dv = domain.model_viewer(), domain.behaviour_viewer(), domain.data_viewer()
    objects = {str(obj): obj for obj in mv.get_objects()}
    if len(fixtures) != 2 or set(objects) != {f["object_id"] for f in fixtures}:
        raise ValueError("PAIR_OBJECT_CLOSURE_DIFFERS")
    if int(domain.layers_viewer().frames_count()) != 3:
        raise ValueError("PAIR_FRAME_CLOSURE_DIFFERS")
    result = {}
    for fixture in fixtures:
        identifier = fixture["object_id"]
        obj = objects[identifier]
        names = [str(bv.get_behaviour_name(b)) for b in bv.get_behaviours(obj)]
        if len(names) != len(set(names)) or set(names) != {"Basic", "Node3d", "Transform", "FbxExport", "MeshObject"}:
            raise ValueError("PAIR_BEHAVIOUR_PROFILE_UNSUPPORTED")
        basic = bv.get_behaviour_by_name(obj, "Basic")
        if not bv.get_behaviour_object(basic, "parent").is_null():
            raise ValueError("PAIR_PARENT_PROFILE_UNSUPPORTED")
        node = bv.get_behaviour_by_name(obj, "Node3d")
        matrix_id = bv.get_behaviour_data(node, "global_matrix")
        if (matrix_id.is_null() or dv.get_data(matrix_id).object_id != obj
                or dv.get_data(matrix_id).mode.name != "Animation"):
            raise ValueError("PAIR_GLOBAL_MATRIX_OWNERSHIP_UNSUPPORTED")
        mesh_b = bv.get_behaviour_by_name(obj, "MeshObject")
        if (list(bv.get_behaviour_objects_range(mesh_b, "linked_objects")) != [obj]
                or bv.get_behaviour_data(mesh_b, "bindShapeMatrix") != matrix_id):
            raise ValueError("PAIR_SELF_BINDING_PROFILE_UNSUPPORTED")
        mesh_id, dependency_id = (bv.get_behaviour_asset(mesh_b, key) for key in ("mesh", "mesh_dependency"))
        manager = domain.assets_manager()
        mesh, dependency = manager.at(mesh_id), manager.at(dependency_id)
        if not isinstance(mesh, csc.domain.assets.Mesh) or not isinstance(dependency, csc.domain.assets.MeshDependency):
            raise ValueError("PAIR_TYPED_ASSET_PROFILE_UNSUPPORTED")
        positions = np.asarray(mesh.positions())
        if positions.ndim == 3 and positions.shape[1:] == (4, 1):
            positions = positions[:, :, 0]
        inverse = np.asarray(dependency.inverse_bind_matrices())
        weights = list(dependency.vertices_weights())
        if (positions.dtype != np.dtype("float32") or positions.ndim != 2 or positions.shape[1] != 4
                or not 3 <= len(positions) <= 64 or not np.isfinite(positions).all()
                or not np.array_equal(positions[:, 3], np.ones(len(positions)))
                or inverse.dtype != np.dtype("float32") or inverse.shape != (1, 4, 4)
                or not np.array_equal(inverse[0], np.eye(4))
                or len(weights) != len(positions)
                or any(len(w) != 1 or w[0].index != 0 or w[0].weight != 1.0 for w in weights)):
            raise ValueError("PAIR_GEOMETRY_OR_SKIN_PROFILE_UNSUPPORTED")
        matrices = []
        for frame in range(3):
            matrix = np.asarray(dv.get_data_value(matrix_id, frame))
            if (matrix.dtype != np.dtype("float32") or matrix.shape != (4, 4)
                    or not np.isfinite(matrix).all() or not np.array_equal(matrix[3], [0, 0, 0, 1])
                    or not np.array_equal(matrix[:3, :3], np.eye(3))):
                raise ValueError("PAIR_NON_TRANSLATION_MATRIX_UNSUPPORTED")
            matrices.append(matrix.copy())
        result[identifier] = {"object_id": identifier, "mesh_behaviour_id": str(mesh_b),
            "mesh_asset_id": str(mesh_id), "dependency_asset_id": str(dependency_id),
            "global_matrix_data_id": str(matrix_id), "positions": native_value(positions[:, :3].copy()),
            "matrices": native_value(matrices), "inverse_bind_matrices": native_value(inverse),
            "weights": [[[int(w.index), float(w.weight)] for w in row] for row in weights]}
    return result


def native_calculate_one(scene, object_id: str, frame: int, count: int):
    import csc
    import numpy as np
    from cascadeur_complete import runtime as rt
    domain = rt._domain_scene(scene)
    obj = {str(key): key for key in domain.model_viewer().get_objects()}[object_id]
    # Actual installed namespace and return normalization, not an invented API.
    returned = csc.domain.calc_skinned_mesh(domain, obj, frame)
    raw = np.asarray(returned.positions)
    if raw.shape == (count, 3, 1):
        raw = raw[:, :, 0]
    if raw.dtype != np.dtype("float32") or raw.shape != (count, 3) or not np.isfinite(raw).all():
        raise ValueError("PAIR_CALCULATION_RETURN_TYPE_UNSUPPORTED")
    return np.array(raw, dtype=np.float32, copy=True, order="C").tolist()


def native_evaluate_pair(scene, retained) -> None:
    from cascadeur_complete import runtime as rt
    from cascadeur_complete.native_fixture import _modify
    def refresh(_model, _update, updater):
        retained.before_effect()
        interpolator = updater.get_interpolator()
        interpolator.reload()
        interpolator.interpolate()
    retained.before_effect()
    _modify(rt._domain_scene(scene).modify_update, "Evaluate owned geometry pair", refresh)


def native_perturb_first_driver(scene, fixtures, retained) -> None:
    import csc
    import numpy as np
    from cascadeur_complete import runtime as rt
    from cascadeur_complete.native_fixture import _modify
    def mutate(model, _update, _callback_scene):
        retained.before_effect()
        model.data_editor().set_data_value(csc.model.DataId(fixtures[0]["position_data_ids"]["local"]),
            1, np.asarray([2.25, .75, .25], dtype=np.float32).reshape(3, 1))
    retained.before_effect()
    _modify(rt._domain_scene(scene).modify, "Perturb one owned pair driver", mutate)


def _expected(row: dict[str, Any], frame: int, raw_space: str):
    import struct
    if raw_space == "native_mesh_local":
        return row["positions"]
    translation = [row["matrices"][frame][axis][3] for axis in range(3)]
    # The finite fixture uses exactly representable dyadic values. Round only
    # to the native declared float32 output type; do not introduce a tolerance.
    def f32(value):
        return struct.unpack("!f", struct.pack("!f", value))[0]
    return [[f32(value + translation[axis]) for axis, value in enumerate(vertex)]
            for vertex in row["positions"]]


@dataclass(frozen=True)
class PairContract:
    scene_context_bytes: bytes
    graph_dtype_digest: str
    raw_space: str
    mesh_ids: tuple[str, str]
    fixture_bytes: bytes
    static_inputs_bytes: bytes
    evidence_bytes: bytes


class PairGeometryPositivePath:
    """Bounded real-calculation path with an actual positive private registry.

    The registry is limited to the EXACT owned two-mesh scene/profile and epoch,
    not arbitrary objects that merely look like Transform/MeshObject by name.
    It is useful to qualify the existing nonempty-pair route without changing
    the public pairs schema. No production capability is granted by this class.
    """
    def __init__(self, *, scene, retained, runner: UpdateCaptureRunner):
        self.scene, self.retained, self.runner = scene, retained, runner
        self._contracts: dict[tuple[str, str, str], PairContract] = {}
        self._fixtures: tuple[dict[str, Any], ...] = ()
        self._used_setup = False

    def _observe(self, schedule: tuple[tuple[str, int], ...], *, runner: UpdateCaptureRunner,
                 before_calculation: Callable, assert_inputs: Callable | None = None):
        if len(schedule) > 8 or any(type(frame) is not int or frame not in (0, 1, 2)
                                   for _, frame in schedule):
            raise ValueError("PAIR_CAPTURE_CALCULATION_BUDGET")
        def sample(_model, _update, _updater, projection, facts):
            if len(frozen_json(projection)) > LIMITS["maximum_projection_bytes"]:
                raise ValueError("PAIR_CAPTURE_PROJECTION_BUDGET")
            graph = json.loads(facts.graph_bytes)
            if graph.get("external_links") != [] or not graph.get("nodes"):
                raise ValueError("PAIR_CLOSED_TYPED_GRAPH_UNOBSERVED")
            node_owners = {frozen_json(row["id"]): row["owner"] for row in graph["nodes"]}
            for port in graph["ports"]:
                owner = node_owners[frozen_json(port["id"][0])]
                for leaf in port["connected_leaves"]:
                    other = node_owners[frozen_json(leaf[0])]
                    if owner is not None and other is not None and owner != other:
                        raise ValueError("PAIR_CROSS_OBJECT_TYPED_PORT_DEPENDENCY_UNSUPPORTED")
            owners = {row.data_id: row.owner_id for row in facts.data}
            if any(owners[key] != row.owner_id for row in facts.data for key in row.upstream_data_ids):
                raise ValueError("PAIR_CROSS_OBJECT_GRAPH_UNSUPPORTED")
            inputs = native_read_pair_inputs(self.scene, self._fixtures)
            if assert_inputs is not None:
                assert_inputs(inputs, projection, facts)
            trials = []
            for mesh_id, frame in schedule:
                if mesh_id not in inputs:
                    raise ValueError("PAIR_CAPTURE_MESH_SCOPE")
                before_calculation()
                raw = native_calculate_one(self.scene, mesh_id, frame, len(inputs[mesh_id]["positions"]))
                trials.append({"mesh_id": mesh_id, "frame": frame, "raw": raw})
            if native_read_pair_inputs(self.scene, self._fixtures) != inputs:
                raise ValueError("PAIR_INPUTS_CHANGED_DURING_CALCULATION")
            return inputs, trials
        # CONDITIONAL: calc inside this callback must be explicitly qualified
        # by this helper. There is no assumed SDK reentrancy/async completion.
        return runner.run(sample)

    @staticmethod
    def _key(context: dict[str, Any]) -> tuple[str, str, str]:
        return context["runtime_epoch"], context["runtime_fingerprint"], context["scene"]["scene_instance_id"]

    @staticmethod
    def _static(inputs):
        return {key: {name: value for name, value in row.items() if name != "matrices"}
                for key, row in inputs.items()}

    def initialize(self, complete_retained_setup: Callable[[dict], None]) -> PairContract:
        from cascadeur_complete.native_scene_reader import read_scene
        if self._used_setup:
            raise ValueError("PAIR_SETUP_ALREADY_ATTEMPTED_NO_AUTORETRY")
        self._used_setup = True
        self._fixtures = native_create_owned_pair(self.scene, self.retained)
        ids = tuple(row["object_id"] for row in self._fixtures)
        native_evaluate_pair(self.scene, self.retained)
        # The owner saves fixture-before.casc here using retained.save_fixture.
        # The binding in the document supplies this at complete step boundaries.
        self.retained.save_fixture(self.scene, "fixture-before.casc", read_scene)
        first, (before_inputs, trials) = self._observe(
            tuple((mesh, frame) for mesh in ids for frame in CALIBRATION_FRAMES),
            runner=self.runner, before_calculation=self.retained.before_effect)
        for index, mesh_id in enumerate(ids):
            if any([before_inputs[mesh_id]["matrices"][frame][axis][3] for axis in range(3)] != list(position)
                   for frame, position in KEYS[index]):
                raise ValueError("PAIR_INITIAL_DRIVER_MATRIX_EFFECT_UNOBSERVED")
        native_perturb_first_driver(self.scene, self._fixtures, self.retained)
        native_evaluate_pair(self.scene, self.retained)
        second, (after_inputs, changed) = self._observe(tuple((mesh, 1) for mesh in ids),
            runner=self.runner, before_calculation=self.retained.before_effect)
        from .native_owned_pair_binding import expected_pair_position
        if second.projection != expected_pair_position(first.projection, self._fixtures[0], 1, [2.25, .75, .25]):
            raise ValueError("PAIR_SETUP_COMPLETE_NATIVE_POSITION_CLOSURE_DIFFERS")
        if (first.context_bytes != second.context_bytes
                or frozen_json(first.facts.material()) != frozen_json(second.facts.material())
                or self._static(before_inputs) != self._static(after_inputs)):
            raise ValueError("PAIR_SETUP_CONTEXT_GRAPH_OR_STATIC_ASSET_CHANGED")
        spaces = []
        for space in ("native_mesh_local", "native_global"):
            if all(row["raw"] == _expected(before_inputs[row["mesh_id"]], row["frame"], space) for row in trials):
                spaces.append(space)
        if len(spaces) != 1:
            raise ValueError("PAIR_COORDINATE_CONVENTION_UNRESOLVED")
        raw_space = spaces[0]
        for mesh in ids:
            repeated = [row for row in trials if row["mesh_id"] == mesh and row["frame"] == 0]
            if len(repeated) != 2 or repeated[0]["raw"] != repeated[1]["raw"]:
                raise ValueError("PAIR_FRAME_ORDER_DEPENDENCY")
        if (before_inputs[ids[1]] != after_inputs[ids[1]]
                or before_inputs[ids[0]]["matrices"][1] == after_inputs[ids[0]]["matrices"][1]
                or any(before_inputs[ids[0]]["matrices"][frame] != after_inputs[ids[0]]["matrices"][frame]
                       for frame in (0, 2))
                or [after_inputs[ids[0]]["matrices"][1][i][3] for i in range(3)] != [2.25, .75, .25]):
            raise ValueError("PAIR_DRIVER_EFFECT_OR_NEGATIVE_CONTROL_DIFFERS")
        if any(row["raw"] != _expected(after_inputs[row["mesh_id"]], 1, raw_space) for row in changed):
            raise ValueError("PAIR_PERTURBATION_COORDINATE_OR_FRESHNESS_DIFFERS")
        self.retained.save_fixture(self.scene, "fixture-after.casc", read_scene)
        if frozen_json(read_scene(self.scene)) != second.projection_bytes:
            raise ValueError("PAIR_SETUP_SAVE_CHANGED_CLOSED_SOURCE_SNAPSHOT")
        evidence = {"profile": PROFILE, "limits": LIMITS, "raw_space": raw_space,
                    "before": before_inputs, "after": after_inputs, "trials": trials + changed,
                    "typed_graph": first.facts.material(), "context": json.loads(first.context_bytes),
                    "whole_position_closure_before": canonical_digest(first.projection),
                    "whole_position_closure_after": canonical_digest(second.projection),
                    "production_general_rig_qualified": False}
        # This callback must finish actual retention and return only after its
        # durable setup outcome. Failure leaves _contracts empty, no fake issuer.
        complete_retained_setup(evidence)
        contract = PairContract(first.context_bytes, canonical_digest(first.facts.material()), raw_space,
                                ids, frozen_json(list(self._fixtures)), frozen_json(self._static(after_inputs)),
                                frozen_json(evidence))
        self._contracts[self._key(json.loads(first.context_bytes))] = contract
        # Only data/contract survive setup. Later capture obtains its own guard
        # and runner; old setup admission cannot accidentally be consulted.
        self.retained = None
        self.runner = None
        return contract

    def status(self, current_context: dict[str, Any]) -> dict[str, Any]:
        contract = self._contracts.get(self._key(current_context))
        return {"native_execution_required": True, "registered": contract is not None,
                "profile": PROFILE if contract else None,
                "general_rig_supported": False, "requires_current_graph_capture": True}

    def capture(self, *, mesh_ids: tuple[str, str], pairs: tuple[tuple[str, str], ...],
                frames: tuple[int, ...], context: dict[str, Any], max_calculations: int,
                runner: UpdateCaptureRunner, before_calculation: Callable):
        # A NEW admitted capture request supplies these two bindings. Never use
        # self.runner/self.retained here: their setup grant has already ended.
        if (tuple(sorted(frames)) != frames or len(frames) != len(set(frames))
                or not frames or not set(frames) <= {0, 1, 2}
                or len(mesh_ids) != 2 or len(set(mesh_ids)) != 2
                or len(pairs) != 1 or set(pairs[0]) != set(mesh_ids)
                or tuple(context.get("frames", ())) != frames
                or type(max_calculations) is not int or len(frames) * 2 > max_calculations):
            raise ValueError("PAIR_CAPTURE_SCOPE_OR_BUDGET_INVALID")
        current = runner._read_context()
        contract = self._contracts.get(self._key(current))
        if (contract is None or set(mesh_ids) != set(contract.mesh_ids)
                or frozen_json(current) != contract.scene_context_bytes):
            raise ValueError("PAIR_CAPTURE_CONTRACT_UNAVAILABLE")
        def assert_current(inputs, _projection, facts):
            if (canonical_digest(facts.material()) != contract.graph_dtype_digest
                    or frozen_json(self._static(inputs)) != contract.static_inputs_bytes):
                raise ValueError("PAIR_CAPTURE_CURRENT_CONTRACT_DIFFERS")
        schedule = tuple((mesh, frame) for mesh in sorted(mesh_ids) for frame in frames)
        snapshot, (inputs, trials) = self._observe(schedule, runner=runner,
            before_calculation=before_calculation, assert_inputs=assert_current)
        current = json.loads(snapshot.context_bytes)
        contract = self._contracts.get(self._key(current))
        if (contract is None or set(mesh_ids) != set(contract.mesh_ids)
                or snapshot.context_bytes != contract.scene_context_bytes
                or canonical_digest(snapshot.facts.material()) != contract.graph_dtype_digest
                or frozen_json(self._static(inputs)) != contract.static_inputs_bytes):
            raise ValueError("PAIR_CAPTURE_CURRENT_CONTRACT_DIFFERS")
        basis, scale = context["scene_to_solver_basis"], context["metres_per_scene_unit"]
        if (type(scale) not in (float, int) or not math.isfinite(scale) or scale <= 0
                or len(basis) != 3 or any(len(row) != 3 for row in basis)
                or any(type(v) not in (float, int) or not math.isfinite(v) for row in basis for v in row)):
            raise ValueError("PAIR_DECLARED_CONVERSION_POLICY_INVALID")
        if any(abs(sum(basis[k][i] * basis[k][j] for k in range(3)) - (1.0 if i == j else 0.0)) > 1e-10
               for i in range(3) for j in range(3)):
            raise ValueError("PAIR_DECLARED_BASIS_NOT_ORTHONORMAL")
        determinant = sum(basis[0][i] * (basis[1][(i+1)%3] * basis[2][(i+2)%3]
                          - basis[1][(i+2)%3] * basis[2][(i+1)%3]) for i in range(3))
        if abs(determinant - 1.0) > 1e-10:
            raise ValueError("PAIR_DECLARED_BASIS_NOT_PROPER")
        canonical = []
        for row in trials:
            if row["raw"] != _expected(inputs[row["mesh_id"]], row["frame"], contract.raw_space):
                raise ValueError("PAIR_CAPTURE_FINITE_FORMULA_MISMATCH")
            matrix = inputs[row["mesh_id"]]["matrices"][row["frame"]]
            points = []
            for vertex in row["raw"]:
                world = [vertex[i] + (matrix[i][3] if contract.raw_space == "native_mesh_local" else 0.0) for i in range(3)]
                points.append([scale * sum(basis[i][j] * world[j] for j in range(3)) for i in range(3)])
            if any(not math.isfinite(value) for point in points for value in point):
                raise ValueError("PAIR_CANONICAL_OVERFLOW")
            canonical.append({**row, "canonical_positions_m": points})
        return {"native_execution_required": True, "profile": PROFILE, "raw_space": contract.raw_space,
                "rows": canonical, "full_projection_digest": canonical_digest(snapshot.projection),
                "graph_dtype_digest": contract.graph_dtype_digest,
                "coordinate_evidence_digest": canonical_digest(json.loads(contract.evidence_bytes))}


def bind_native_authenticated_terminal_lookup():
    from cascadeur_complete import runtime as rt
    from cascadeur_complete.native_checkpoint_restore import _original_terminal
    return lambda request_id: _original_terminal(rt.runtime_root(), request_id)


class MutationEvaluationRebind:
    """Actual observed full state bridges DIFFERENT operation scopes.

    Calls belong to native dispatch/finalizers, not MCP. Historical origin
    source is authenticated by its signed original request and terminal; it is
    never passed to assert_source against the post-mutation current scene.
    Finalizers seal memory only. Unknown/missing terminals never become success.
    """
    def __init__(self, runner: UpdateCaptureRunner, authenticated_terminal: Callable):
        self.runner = runner
        self._terminal = authenticated_terminal
        self._origins: dict[str, dict] = {}
        self._evaluations: dict[str, dict] = {}

    @staticmethod
    def _full_source(source, snapshot: UpdateSnapshot):
        context = json.loads(snapshot.context_bytes)
        scope_digest = canonical_digest(source["scope"])
        binding = source["binding"]
        if (source["sample_digest"] != canonical_digest(snapshot.projection)
                or binding["scope_digest"] != scope_digest
                or binding["content_revision"] != canonical_digest({"scope_digest": scope_digest,
                                                                    "content": snapshot.projection})
                or source["adapter_fingerprint"] != context["runtime_fingerprint"]
                or binding["runtime_epoch"] != context["runtime_epoch"]
                or any(binding[k] != context["scene"][k] for k in ("scene_instance_id", "document_lineage_id"))):
            raise ValueError("REBIND_REQUIRES_ACTUAL_COMPLETE_PROJECTION_SOURCE")

    def _success(self, request_id: str):
        request, receipt = self._terminal(request_id)
        result = (receipt or {}).get("terminal_result") or {}
        data = result.get("result") or {}
        if (not isinstance(request, dict) or receipt is None
                or receipt.get("phase") != "terminal" or receipt.get("outcome") != "succeeded"
                or not result.get("ok") or result.get("outcome") != "succeeded"
                or receipt.get("request_digest") != canonical_digest(request)
                or receipt.get("result_digest") != canonical_digest(result)
                or data.get("native_completion") != "observed"
                or not isinstance(data.get("post_source_binding"), dict)
                or receipt.get("scene_after") != data["post_source_binding"]["binding"]):
            raise ValueError("REBIND_AUTHENTICATED_NATIVE_SUCCESS_UNAVAILABLE")
        return request, receipt, data["post_source_binding"]

    def stage_mutation(self, request: dict, successor: dict, snapshot: UpdateSnapshot) -> None:
        self.runner.require(snapshot)
        self._full_source(successor, snapshot)
        if request["request_id"] in self._origins or len(self._origins) >= 64:
            raise ValueError("REBIND_ORIGIN_REPLAY_OR_BUDGET")
        self._origins[request["request_id"]] = {"request": frozen_json(request),
            "successor": frozen_json(successor), "snapshot": snapshot, "receipt": None}

    def seal_mutation(self, request_id: str) -> None:
        pending = self._origins.get(request_id)
        if pending is None:
            raise ValueError("REBIND_ORIGIN_CANDIDATE_UNAVAILABLE")
        request, receipt, successor = self._success(request_id)
        context = json.loads(pending["snapshot"].context_bytes)
        if (pending["request"] != frozen_json(request) or pending["successor"] != frozen_json(successor)
                or receipt.get("runtime_epoch") != context["runtime_epoch"]):
            raise ValueError("REBIND_ORIGIN_TERMINAL_DIFFERS")
        pending["receipt"] = frozen_json(receipt)

    def stage_evaluation(self, origin_id: str, request: dict, before: UpdateSnapshot,
                         after: UpdateSnapshot) -> None:
        self.runner.require(before)
        self.runner.require(after)
        origin = self._origins.get(origin_id)
        if origin is None or origin["receipt"] is None:
            raise ValueError("REBIND_ORIGIN_NOT_SEALED")
        prior = origin["snapshot"]
        if (request.get("operations") != [{"name": "animation.interpolation_refresh", "arguments": {}}]
                or before.projection_bytes != prior.projection_bytes
                or before.context_bytes != prior.context_bytes
                or frozen_json(before.facts.material()) != frozen_json(prior.facts.material())
                or before.context_bytes != after.context_bytes
                or frozen_json(before.facts.material()) != frozen_json(after.facts.material())
                or request["source_binding"]["inputs_digest"] != json.loads(origin["successor"])["inputs_digest"]):
            raise ValueError("REBIND_MUTATION_SUCCESSOR_TO_EVALUATION_PRESTATE_DIFFERS")
        self._full_source(request["source_binding"], before)
        request_id = request["request_id"]
        if request_id in self._evaluations or len(self._evaluations) >= 64:
            raise ValueError("REBIND_EVALUATION_REPLAY_OR_BUDGET")
        self._evaluations[request_id] = {"origin_id": origin_id, "request": frozen_json(request),
            "before": before, "after": after, "receipt": None, "post_source": None}

    def stage_baseline_evaluation(self, request: dict, before: UpdateSnapshot, after: UpdateSnapshot) -> None:
        """A real explicit evaluation is its own baseline origin; no fake write."""
        self.runner.require(before)
        self.runner.require(after)
        request_id = request["request_id"]
        if (request.get("operations") != [{"name": "animation.interpolation_refresh", "arguments": {}}]
                or before.context_bytes != after.context_bytes
                or frozen_json(before.facts.material()) != frozen_json(after.facts.material())
                or request_id in self._evaluations or len(self._evaluations) >= 64):
            raise ValueError("REBIND_BASELINE_EVALUATION_SCOPE_OR_BUDGET_DIFFERS")
        self._full_source(request["source_binding"], before)
        self._evaluations[request_id] = {"origin_id": request_id, "request": frozen_json(request),
            "before": before, "after": after, "receipt": None, "post_source": None}

    def seal_evaluation(self, request_id: str) -> None:
        pending = self._evaluations.get(request_id)
        if pending is None:
            raise ValueError("REBIND_EVALUATION_CANDIDATE_UNAVAILABLE")
        request, receipt, post_source = self._success(request_id)
        if pending["request"] != frozen_json(request):
            raise ValueError("REBIND_EVALUATION_TERMINAL_DIFFERS")
        self._full_source(post_source, pending["after"])
        pending["receipt"], pending["post_source"] = frozen_json(receipt), frozen_json(post_source)

    def require_capture(self, origin_id: str, private_capture: dict,
                        motion_source: dict, current: UpdateSnapshot) -> dict:
        self.runner.require(current)
        evaluation_id = private_capture["evaluation"]["request_id"]
        record = self._evaluations.get(evaluation_id)
        if record is None or record["receipt"] is None or record["origin_id"] != origin_id:
            raise ValueError("GEOMETRY_ORIGIN_SUCCESSOR_REBIND_UNAVAILABLE")
        after = record["after"]
        receipt_digest = canonical_digest(json.loads(record["receipt"]))
        if (current.projection_bytes != after.projection_bytes or current.context_bytes != after.context_bytes
                or frozen_json(current.facts.material()) != frozen_json(after.facts.material())
                or frozen_json(motion_source) != record["post_source"]
                or private_capture["evaluation_receipt_digest"] != receipt_digest
                or private_capture["full_projection_digest"] != canonical_digest(current.projection)
                or private_capture["canonical_batch"]["source_binding"] != motion_source
                or private_capture["evaluation"]["post_source_digest"] != canonical_digest(motion_source)):
            raise ValueError("GEOMETRY_ORIGIN_EVALUATION_CAPTURE_CHAIN_DIFFERS")
        origin = self._origins.get(origin_id)
        return {"native_execution_required": True, "origin_request_id": origin_id,
                "origin_receipt_digest": receipt_digest if origin is None else canonical_digest(json.loads(origin["receipt"])),
                "evaluation_request_id": evaluation_id, "evaluation_receipt_digest": receipt_digest,
                "successor_pre_evaluation_projection_digest": canonical_digest(record["before"].projection),
                "evaluated_projection_digest": canonical_digest(after.projection),
                "current_graph_dtype_digest": canonical_digest(current.facts.material())}
