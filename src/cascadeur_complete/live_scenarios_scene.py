"""Live scenarios for adapter-bound object/render features and generated-rig physics."""

from __future__ import annotations

from typing import Any

from .live_scenarios import CASCY, CUBE, _live_cube
from .live_validation import LiveSession, LiveValidationError, scenario

# -- objects and render (Cube) ------------------------------------------------------


@scenario("object_duplicate", CUBE)
def _object_duplicate(s: LiveSession) -> Any:
    return s.change("object_duplicate", "objects.duplicate", {"id": _live_cube(s)})


@scenario("object_delete", CUBE)
def _object_delete(s: LiveSession) -> Any:
    created = s.change("object_create", "object.create", {"name": "MCP Delete Me", "position": [0, 6, 0], "size": 1})
    return s.change("object_delete", "objects.delete", {"ids": [created["id"]]})


@scenario("camera_settings", CUBE)
def _camera_settings(s: LiveSession) -> Any:
    s.change("camera_create", "render.camera_create", {})
    return s.change("camera_settings", "render.camera_settings", {"values": {"field_of_view": 42.0}})


@scenario("point_light_properties", CUBE)
def _point_light_properties(s: LiveSession) -> Any:
    s.change("light_point", "render.light_point", {})
    return s.change(
        "point_light_properties",
        "render.point_light_properties",
        {"values": {"intensity": 1500.0, "falloff_radius": 60.0}},
    )


@scenario("spot_light_properties", CUBE)
def _spot_light_properties(s: LiveSession) -> Any:
    s.change("light_spot", "render.light_spot", {})
    return s.change("spot_light_properties", "render.spot_light_properties", {"values": {"intensity": 1200.0}})


def _mesh(s: LiveSession) -> str:
    # Earlier import scenarios add meshes to the shared scene; use one that
    # carries a Material, as the fixture's own cube does.
    meshes = s.objects_of_type("Mesh Object")
    if not meshes:
        raise LiveValidationError("fixture has no mesh object")
    with_material = s.owners("Material", meshes)
    return with_material[0] if with_material else meshes[0]["id"]


def behaviour_values(s: LiveSession, object_id: str, behaviour: str) -> dict[str, Any]:
    rows = s.read("object_properties", "object.properties", {"ids": [object_id], "include_values": True})["items"]
    for item in rows[0]["behaviors"]:
        if item["name"] == behaviour:
            return {
                prop["name"]: prop["value"]["value"]
                for prop in item["properties"]
                if prop["type"] == "DataType" and isinstance(prop.get("value"), dict) and "value" in prop["value"]
            }
    raise LiveValidationError(f"{object_id} has no {behaviour}")


@scenario("material", CUBE)
def _material(s: LiveSession) -> Any:
    mesh = _mesh(s)
    values = behaviour_values(s, mesh, "Material")
    name, value = next((key, item) for key, item in sorted(values.items()) if isinstance(item, float))
    return s.change("material", "render.material", {"ids": [mesh], "values": {name: round(value * 0.5 + 0.1, 4)}})


@scenario("material_textures", CUBE)
def _material_textures(s: LiveSession) -> Any:
    from .live_scenarios_extra import _render_png

    mesh = _mesh(s)
    image = _render_png(s)
    return s.change(
        "material_textures", "render.material_textures", {"ids": [mesh], "values": {"base_color_map": image}}
    )


@scenario("hiding", CUBE)
def _hiding(s: LiveSession) -> Any:
    mesh = _mesh(s)
    current = behaviour_values(s, mesh, "Basic")["visibility"]
    hidden = 0 if current != 0 else 1
    s.change("hiding", "objects.visibility", {"ids": [mesh], "values": {"visibility": hidden}})
    return s.change("hiding", "objects.visibility", {"ids": [mesh], "values": {"visibility": current}})


@scenario("viewport_layout", CUBE)
def _viewport_layout(s: LiveSession) -> Any:
    s.change("viewport_layout", "render.viewport_layout", {"count": 2})
    return s.change("viewport_layout", "render.viewport_layout", {"count": 1})


@scenario("viewport", CUBE)
def _viewport(s: LiveSession) -> Any:
    s.change("viewport", "render.viewport_layout", {"count": 4})
    return s.change("viewport", "render.viewport_layout", {"count": 1})


@scenario("fix_scene", CUBE)
def _fix_scene(s: LiveSession) -> Any:
    return s.change("fix_scene", "scene.fix", {})


# -- physics and rig on a generated rig (Cascy) --------------------------------------


def rigid_ids(s: LiveSession) -> list[str]:
    return [item["id"] for item in s.objects_of_type("Rigid Body")]


def center_of_mass(s: LiveSession) -> str:
    ids = s.read("physics_state", "physics.state")["center_of_mass_ids"]
    if not ids:
        raise LiveValidationError("fixture has no Center of Mass")
    return ids[0]


@scenario("physics_state", CASCY)
def _physics_state(s: LiveSession) -> Any:
    return {"rigid_bodies": s.read("physics_state", "physics.state")["rigid_body_count"]}


@scenario("rig_state", CASCY)
def _rig_state(s: LiveSession) -> Any:
    return {"rig_infos": s.read("rig_state", "rig.state")["rig_info_count"]}


@scenario("constraint_drivers", CASCY)
def _constraint_drivers(s: LiveSession) -> Any:
    return {"drivers": s.read("constraint_drivers", "rig.constraint_drivers")["count"]}


@scenario("auto_physics_state", CASCY)
def _auto_physics_state(s: LiveSession) -> Any:
    return s.read("auto_physics_state", "physics.auto_state")["missing_preconditions"]


@scenario("generation_state", CASCY)
def _generation_state(s: LiveSession) -> Any:
    return s.read("generation_state", "generation.state")["missing_preconditions"]


@scenario("mass", CASCY)
def _mass(s: LiveSession) -> Any:
    return s.change("mass", "rig.mass_set", {"total_mass": 72.5})


@scenario("collision_create", CASCY)
def _collision_create(s: LiveSession) -> Any:
    rigid = rigid_ids(s)
    with_box = set(s.owners("BoxCollision", [item for item in s.objects() if item["id"] in rigid]))
    target = next(item for item in rigid if item not in with_box)
    s.collision_target = target
    return s.change("collision_create", "physics.collision_create", {"shape": "box", "ids": [target]})


@scenario("collision_delete", CASCY)
def _collision_delete(s: LiveSession) -> Any:
    target = getattr(s, "collision_target", None) or _collision_create(s)["target_ids"][0]
    return s.change("collision_delete", "physics.collision_delete", {"ids": [target]})


@scenario("center_of_mass", CASCY)
def _center_of_mass_create(s: LiveSession) -> Any:
    return s.change("center_of_mass", "physics.center_of_mass", {"mode": "from_rigids", "ids": rigid_ids(s)})


@scenario("constraint_point", CASCY)
def _constraint_point(s: LiveSession) -> Any:
    driver = s.read("constraint_drivers", "rig.constraint_drivers")["items"][0]
    prefix = driver["name"].split("_")[0]
    point = next(
        item["id"]
        for item in s.objects_of_type("Point")
        if not item["name"].startswith(prefix) and "MainPoint" in item["name"]
    )
    return s.change("constraint_point", "physics.constraint_point", {"driver_id": driver["id"], "point_ids": [point]})


@scenario("constraint_transform", CASCY)
def _constraint_transform(s: LiveSession) -> Any:
    # Transform constraints bind independent transform objects (Add > Transform
    # dummies carry the Position/Rotation/Enforce Global inputs they rewire).
    before = {item["id"] for item in s.objects()}
    for _ in range(2):
        s.change("command.add.transform", "system.action_invoke", {"action_id": "Add.Transform", "expect_change": True})
    created = [item["id"] for item in s.objects() if item["id"] not in before and item["name"].startswith("Transform")]
    if len(created) != 2:
        raise LiveValidationError(f"expected two new transform objects, found {len(created)}")
    return s.change(
        "constraint_transform",
        "physics.constraint_transform",
        {"driver_id": created[0], "constrained_id": created[1]},
    )


@scenario("ik", CASCY)
def _ik(s: LiveSession) -> Any:
    point_rows = s.objects_of_type("Point")
    points = {item["name"]: item["id"] for item in point_rows}
    attraction = set(s.owners("AttractionPoint", point_rows))
    connection = set(s.owners("ConnectionPointTwoBody", point_rows))
    reasons = []
    for side in ("_l", "_r"):
        names = [f"hand_MainPoint{side}", f"forearm_MainPoint{side}", f"arm_MainPoint{side}"]
        chain = [points.get(name) for name in names]
        if not all(chain):
            reasons.append(f"{side}: missing {[n for n, i in zip(names, chain, strict=True) if not i]}")
            continue
        # Like Cascadeur's add_ik, a middle link needs exactly one ConnectionPointTwoBody.
        middle = s.behaviour_names([chain[1]])[chain[1]].count("ConnectionPointTwoBody")
        if chain[0] in attraction and chain[-1] in attraction and chain[1] in connection and middle == 1:
            return s.change("ik", "rig.ik_chain_create", {"ordered_ids": chain})
        reasons.append(
            f"{side}: ends attraction={chain[0] in attraction}/{chain[-1] in attraction}, middle connections={middle}"
        )
    raise LiveValidationError("fixture has no IK-capable arm chain: " + "; ".join(reasons))


def autophysics_points(s: LiveSession) -> list[str]:
    points = s.owners("AutoPhysicsApply", s.objects_of_type("Point"))
    if not points:
        raise LiveValidationError("fixture has no AutoPhysics points")
    return points


@scenario("autophysics_priority_frames", CASCY)
def _priority_frames(s: LiveSession) -> Any:
    return s.change(
        "autophysics_priority_frames",
        "physics.autophysics_priority_frames",
        {"ids": [center_of_mass(s)], "values": {"frame_weight": 0.5}},
    )


@scenario("autophysics_smooth_trajectory", CASCY)
def _smooth_trajectory(s: LiveSession) -> Any:
    return s.change(
        "autophysics_smooth_trajectory",
        "physics.autophysics_smooth_trajectory",
        {"ids": [center_of_mass(s)], "values": {"vertical_jerk": 0.5, "horizontal_jerk": 0.5}},
    )


@scenario("autophysics_smooth_rotation", CASCY)
def _smooth_rotation(s: LiveSession) -> Any:
    return s.change(
        "autophysics_smooth_rotation",
        "physics.autophysics_smooth_rotation",
        {"ids": [center_of_mass(s)], "values": {"rotation_blending": 60.0}},
    )


@scenario("autophysics_point_settings", CASCY)
def _point_settings(s: LiveSession) -> Any:
    point = autophysics_points(s)[0]
    current = behaviour_values(s, point, "AutoPhysicsApply")["keep_global_rotation"]
    toggled = (not current) if isinstance(current, bool) else (0 if current else 1)
    if isinstance(current, float):
        toggled = 0.0 if current else 1.0
    return s.change(
        "autophysics_point_settings",
        "physics.autophysics_point_settings",
        {"ids": [point], "values": {"keep_global_rotation": toggled}},
    )


def _motion(s: LiveSession, feature_id: str, operation: str, values: dict[str, Any]) -> Any:
    return s.change(feature_id, operation, {"ids": autophysics_points(s)[:2], "values": values, "add_missing": True})


@scenario("autophysics_compensation_motion", CASCY)
def _compensation(s: LiveSession) -> Any:
    return _motion(s, "autophysics_compensation_motion", "physics.compensation_motion", {"muscle_stiffness": 0.4})


@scenario("autophysics_separation_motion", CASCY)
def _separation(s: LiveSession) -> Any:
    return _motion(s, "autophysics_separation_motion", "physics.separation_motion", {"muscle_stiffness": 0.4})


@scenario("autophysics_secondary_motion", CASCY)
def _secondary(s: LiveSession) -> Any:
    return _motion(s, "autophysics_secondary_motion", "physics.secondary_motion", {"damping": 0.3})


@scenario("autophysics_restore_unbound", CASCY)
def _restore_unbound(s: LiveSession) -> Any:
    return s.change(
        "autophysics_restore_unbound",
        "physics.autophysics_restore",
        {"center_of_mass_id": center_of_mass(s), "point_ids": autophysics_points(s)},
    )


@scenario("autophysics_corrector", CASCY)
def _corrector(s: LiveSession) -> Any:
    return s.change(
        "autophysics_corrector", "physics.autophysics_corrector", {"ids": [center_of_mass(s)], "enabled": True}
    )


@scenario("penetration_clean", CASCY)
def _penetration(s: LiveSession) -> Any:
    return s.change("penetration_clean", "physics.penetration_cleaning", {"ids": [center_of_mass(s)], "enabled": True})


@scenario("ragdoll", CASCY)
def _ragdoll(s: LiveSession) -> Any:
    return s.change(
        "ragdoll",
        "physics.ragdoll",
        {"ids": [center_of_mass(s)], "values": {"global_stiffness": 0.5}, "add_missing": True},
    )
