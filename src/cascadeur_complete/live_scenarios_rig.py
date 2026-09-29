"""Live scenarios for manual rigging on bare joints and Rig Mode prototype tooling."""

from __future__ import annotations

from typing import Any

from .live_validation import CASCADEUR_ROOT, LiveSession, LiveValidationError, scenario

THREE = "fixture.test.three_joints"
RIGMODE = "fixture.rigmode.cascy"


def joints(s: LiveSession) -> dict[str, str]:
    return {item["name"]: item["id"] for item in s.objects_of_type("Joint")}


# -- manual rigging on bare joints ---------------------------------------------------


@scenario("joint", THREE)
def _joint(s: LiveSession) -> Any:
    return s.change("joint", "rig.joint_create", {})


@scenario("rig_info", THREE)
def _rig_info(s: LiveSession) -> Any:
    names = joints(s)
    return s.change("rig_info", "rig.rig_info_create", {"joint_ids": [names["p1b"], names["p2b"], names["p3b"]]})


@scenario("manual_rig", THREE)
def _manual_rig(s: LiveSession) -> Any:
    names = joints(s)
    created = s.change(
        "manual_rig",
        "rig.rig_elements_create",
        {"pairs": [{"joint_id": names["p1b"], "direction_joint_id": names["p2b"]}]},
    )
    s.rig_element = created["created_rig_element_ids"][0]
    return created


def _rig_element(s: LiveSession) -> str:
    element = getattr(s, "rig_element", None)
    if element and any(item["id"] == element for item in s.objects()):
        return element
    return _manual_rig(s)["created_rig_element_ids"][0]


@scenario("controller_point", THREE)
def _controller_point(s: LiveSession) -> Any:
    return s.change("controller_point", "rig.additional_point_create", {"rig_element_id": _rig_element(s)})


@scenario("controller_box", THREE)
def _controller_box(s: LiveSession) -> Any:
    return s.change("controller_box", "rig.additional_box_create", {"rig_element_id": _rig_element(s)})


@scenario("rig_create", THREE)
def _rig_create(s: LiveSession) -> Any:
    names = joints(s)
    _rig_element(s)
    created = s.change(
        "rig_create",
        "rig.rig_elements_create",
        {"pairs": [{"joint_id": names["p2b"], "direction_joint_id": names["p3b"]}]},
    )
    s.second_element = created["created_rig_element_ids"][0]
    return created


@scenario("spline_ik", THREE)
def _spline_ik(s: LiveSession) -> Any:
    names = joints(s)
    if not getattr(s, "second_element", None):
        _rig_create(s)
    return s.change("spline_ik", "rig.spline_ik_create", {"start_joint_id": names["p1b"], "end_joint_id": names["p3b"]})


@scenario("twist", THREE)
def _twist(s: LiveSession) -> Any:
    # Cascadeur refuses Twist on rig elements with a rigid body (direction
    # point), so build an element without a direction joint and twist its box.
    names = joints(s)
    before = set(s.owners("ProtoBox"))
    s.change("manual_rig", "rig.rig_elements_create", {"pairs": [{"joint_id": names["p3b"]}]})
    boxes = sorted(set(s.owners("ProtoBox")) - before)
    if len(boxes) != 1:
        raise LiveValidationError(f"expected one new ProtoBox, found {len(boxes)}")
    result = s.change("twist", "rig.twist", {"action": "set", "box_id": boxes[0], "joint_id": names["p2b"]})
    s.change("twist", "rig.twist", {"action": "remove", "box_id": boxes[0]})
    return result


@scenario("rigid_body", THREE)
def _rigid_body(s: LiveSession) -> Any:
    first = s.change("joint", "rig.joint_create", {})["created_id"]
    second = s.change("joint", "rig.joint_create", {})["created_id"]
    return s.change(
        "rigid_body", "rig.rig_elements_create", {"pairs": [{"joint_id": first, "direction_joint_id": second}]}
    )


# -- Rig Mode prototype tooling ------------------------------------------------------


def elements(s: LiveSession) -> dict[str, str]:
    names = {item["id"]: item["name"] for item in s.objects()}
    return {names[item]: item for item in s.owners("TechnicalLinks")}


def element(s: LiveSession, *fragments: str, exclude: tuple[str, ...] = ()) -> str:
    for name, identifier in sorted(elements(s).items()):
        if all(item in name for item in fragments) and not any(item in name for item in exclude):
            return identifier
    raise LiveValidationError("no rig element matches " + "/".join(fragments))


def ensure_rig_mode(s: LiveSession) -> None:
    if not s.owners("AnimationInfo"):
        s.change("rig_mode_on", "rig.mode", {}, timeout=300)


@scenario("rig_mode_on", RIGMODE)
def _rig_mode_on(s: LiveSession) -> Any:
    return s.change("rig_mode_on", "rig.mode", {}, timeout=300)


@scenario("character_mirror_plane", RIGMODE)
def _mirror_plane(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    s.change("character_mirror_plane", "rig.character_mirror_plane", {"plane": 0})
    return s.change("character_mirror_plane", "rig.character_mirror_plane", {"plane": 2})


@scenario("autoposing_props", RIGMODE)
def _autoposing_props(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    target = element(s, "hand", "_l")
    s.change("autoposing_props", "rig.autoposing_props", {"rig_element_ids": [target], "enabled": True})
    return s.change("autoposing_props", "rig.autoposing_props", {"rig_element_ids": [target], "enabled": False})


@scenario("snap_rig", RIGMODE)
def _snap_rig(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change("snap_rig", "rig.snap", {"id": element(s, "forearm", "_l")})


def _hinge_pair(s: LiveSession) -> list[str]:
    return [element(s, "arm", "_r", exclude=("forearm",)), element(s, "forearm", "_r")]


@scenario("hinge_union", RIGMODE)
def _hinge_union(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change("hinge_union", "rig.hinge", {"rig_element_ids": _hinge_pair(s)})


@scenario("hinge_orthogonalize", RIGMODE)
def _hinge_orthogonalize(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change("hinge_orthogonalize", "rig.hinge", {"rig_element_ids": _hinge_pair(s)})


@scenario("hinge_straighten", RIGMODE)
def _hinge_straighten(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change("hinge_straighten", "rig.hinge", {"rig_element_ids": _hinge_pair(s)})


@scenario("virtual_joint_create", RIGMODE)
def _virtual_joint_create(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    parent = joints(s).get("hand_l") or next(iter(joints(s).values()))
    created = s.change("virtual_joint_create", "rig.virtual_joint", {"joint_id": parent})
    s.virtual_joint = created["created_id"]
    return created


@scenario("virtual_joint_delete", RIGMODE)
def _virtual_joint_delete(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    if not getattr(s, "virtual_joint", None):
        _virtual_joint_create(s)
    return s.change("virtual_joint_delete", "rig.virtual_joint", {"joint_id": s.virtual_joint})


@scenario("joint_delete", RIGMODE)
def _joint_delete(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    # Delete removes standard rig joints: create one under an existing joint first.
    parent = s.objects_of_type("Joint")[0]["id"]
    created = s.change("joint", "rig.joint_create", {"parent_joint_id": parent})["created_id"]
    return s.change("joint_delete", "rig.joint_delete", {"joint_id": created})


@scenario("root_constraint_add", RIGMODE)
def _root_constraint_add(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    root = s.change("object_create", "object.create", {"name": "MCP Root", "position": [0, 0, 0], "size": 0.5})["id"]
    created = s.change(
        "root_constraint_add", "rig.root_constraint", {"root_id": root, "rig_element_id": element(s, "pelvis")}
    )
    s.root_constraint = created["created_id"]
    return created


@scenario("root_constraint_remove", RIGMODE)
def _root_constraint_remove(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    if not getattr(s, "root_constraint", None):
        _root_constraint_add(s)
    return s.change("root_constraint_remove", "rig.root_constraint", {"constraint_id": s.root_constraint})


@scenario("prototype_fulcrum_groups", RIGMODE)
def _fulcrum_groups(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    members = [element(s, "foot", "_l"), element(s, "toe", "_l")]
    return s.change("prototype_fulcrum_groups", "rig.fulcrum_group", {"rig_element_ids": members})


@scenario("prototype_com_remove", RIGMODE)
def _proto_com_remove(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    centers = s.owners("ProtoCenterOfMass")
    if not centers:
        raise LiveValidationError("Rig Mode produced no prototype Center of Mass")
    return s.change("prototype_com_remove", "rig.proto_center_of_mass_remove", {"center_of_mass_ids": centers[:1]})


def _manual_point(s: LiveSession, target: str) -> str:
    return s.change("controller_point", "rig.additional_point_create", {"rig_element_id": target})["created_point_id"]


@scenario("custom_additional_point_set", RIGMODE)
def _custom_point_set(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    target = element(s, "hand", "_r")
    point = _manual_point(s, target)
    s.manual_point = (target, point)
    return s.change("custom_additional_point_set", "rig.technical_link", {"rig_element_id": target, "target_id": point})


@scenario("custom_additional_point_remove", RIGMODE)
def _custom_point_remove(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    if not getattr(s, "manual_point", None):
        _custom_point_set(s)
    return s.change("custom_additional_point_remove", "rig.technical_link", {"rig_element_id": s.manual_point[0]})


@scenario("additional_controller_remove", RIGMODE)
def _additional_controller_remove(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    target = element(s, "calf", "_l")
    point = _manual_point(s, target)
    return s.change(
        "additional_controller_remove", "rig.additional_controller_remove", {"kind": "point", "controller_id": point}
    )


@scenario("additional_joint_attach", RIGMODE)
def _additional_joint_attach(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    extra = s.change("joint", "rig.joint_create", {})["created_id"]
    target = element(s, "head")
    s.additional_joint = target
    return s.change("additional_joint_attach", "rig.technical_link", {"rig_element_id": target, "target_id": extra})


@scenario("additional_joint_detach", RIGMODE)
def _additional_joint_detach(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    if not getattr(s, "additional_joint", None):
        _additional_joint_attach(s)
    return s.change("additional_joint_detach", "rig.technical_link", {"rig_element_id": s.additional_joint})


@scenario("additional_parent", RIGMODE)
def _additional_parent(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change(
        "additional_parent",
        "rig.technical_link",
        {"rig_element_id": element(s, "hand", "_l"), "target_id": element(s, "hand", "_r"), "action": "set"},
    )


@scenario("custom_rotation", RIGMODE)
def _custom_rotation(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change(
        "custom_rotation",
        "rig.technical_link",
        {"rig_element_id": element(s, "foot", "_r"), "target_id": element(s, "calf", "_r"), "action": "set"},
    )


@scenario("prototype_mirror", RIGMODE)
def _prototype_mirror(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change(
        "prototype_mirror",
        "rig.prototype_mirror",
        {"rig_element_ids": [element(s, "clavicle", "_l")], "original_suffix": "_l", "mirror_suffix": "_r"},
    )


@scenario("rig_element_delete", RIGMODE)
def _rig_element_delete(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change("rig_element_delete", "rig.element_delete", {"rig_element_ids": [element(s, "toe", "_r")]})


@scenario("clear_animation_data", RIGMODE)
def _clear_animation_data(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change("clear_animation_data", "rig.clear_animation_data", {})


@scenario("rig_json_export", RIGMODE)
def _rig_json_export(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    result = s.change("rig_json_export", "rig.json_export", {"path": s.output("rig.json")})
    s.rig_json = result["path"]
    return result


@scenario("generate_rig", RIGMODE)
def _generate_rig(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change("generate_rig", "rig.mode", {}, timeout=300)


@scenario("rig_regenerate", RIGMODE)
def _rig_regenerate(s: LiveSession) -> Any:
    return s.change("rig_regenerate", "rig.mode", {}, timeout=600)


@scenario("rig_json_import", "fixture.test.ded")
def _rig_json_import(s: LiveSession) -> Any:
    # Mirrors Cascadeur's own proto_load test: Ded.casc joints + Ded.json in Rig Mode.
    if not s.owners("AnimationInfo"):
        s.change("rig_mode_on", "rig.mode", {}, timeout=300)
    source = str(CASCADEUR_ROOT / "resources/scripts/test_data/rig/Ded.json")
    return s.change("rig_json_import", "rig.json_import", {"path": source}, timeout=300)


@scenario("root_constraint", RIGMODE)
def _root_constraint(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    names = joints(s)
    root = names.get("root") or s.change("joint", "rig.joint_create", {})["created_id"]
    return s.change("root_constraint", "rig.root_constraint", {"root_id": root, "rig_element_id": element(s, "pelvis")})


@scenario("untwist", RIGMODE)
def _untwist(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    return s.change(
        "untwist",
        "rig.untwist",
        {
            "parent_element_id": element(s, "arm", "_l", exclude=("forearm",)),
            "target_element_id": element(s, "forearm", "_l"),
            "child_element_id": element(s, "hand", "_l"),
        },
    )


@scenario("quick_rig", "fixture.rigmode.ue5")
def _quick_rig(s: LiveSession) -> Any:
    ensure_rig_mode(s)
    template = str(CASCADEUR_ROOT / "resources" / "autorig_templates" / "UE5.qrigcasc")
    return s.change("quick_rig", "rig.quick_rig", {"template_path": template}, timeout=300)
