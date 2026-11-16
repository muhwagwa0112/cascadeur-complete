"""Small code-owned disposable fixtures using installed official SDK commands.

Not a wire operation or production object writer. Fixture edits never call a
SceneUpdater; evaluation must be requested separately by the owning helper.
"""
from __future__ import annotations

_OWNED = {}
SUPPORTED_BUILD = "2026.2.3.0.16863"


def create_disposable_scene(*, retain_on_failure=False):
    from .incident_admission import assert_current_setup_admission
    assert_current_setup_admission()
    import csc
    from . import guarded_runtime as guards
    from .native_adapters import installed_build
    guards.assert_loaded_package()
    if installed_build() != SUPPORTED_BUILD:
        raise ValueError("UNSUPPORTED_VERSION: independent fixture requires " + SUPPORTED_BUILD)
    manager = csc.app.get_application().get_scene_manager()
    previous = manager.current_scene()
    assert_current_setup_admission()
    scene = manager.create_application_scene()
    _OWNED[id(scene)] = {"scene": scene, "previous": previous, "objects": set()}
    try:
        assert_current_setup_admission()
        manager.set_current_scene(scene)
        return scene
    except Exception as error:
        # Finite setup never authorizes closing a native tab, including when
        # activation fails. Preserve the newly created scene for observation.
        try:
            if previous is not None:
                assert_current_setup_admission()
                manager.set_current_scene(previous)
        except Exception as restore_error:
            error.add_note("Original tab activation unobserved: " + str(restore_error)[:1000])
        raise


def _owned(scene):
    from .incident_admission import assert_current_setup_admission
    assert_current_setup_admission()
    import csc
    from . import guarded_runtime as guards
    from . import runtime as rt
    guards.assert_loaded_package()
    value = _OWNED.get(id(scene))
    if value is None or value["scene"] is not scene or rt._scene_view() is not scene:
        raise ValueError("FIXTURE_SCOPE_UNAVAILABLE: active code-owned disposable scene required")
    if csc.app.get_application().get_scene_manager().current_scene() is not scene:
        raise ValueError("FIXTURE_SCOPE_UNAVAILABLE: disposable scene is inactive")
    domain = rt._domain_scene(scene)
    if {rt._id_string(x) for x in domain.model_viewer().get_objects()} != value["objects"]:
        raise ValueError("FIXTURE_SCOPE_CHANGED: disposable object closure differs")
    return value, domain


def _modify(method, label, callback):
    from .incident_admission import assert_current_setup_admission
    errors, completed = [], []
    active, entered = [True], [False]
    def enter(*args):
        try:
            if not active[0] or entered[0]:
                raise ValueError("FIXTURE_CALLBACK_REPLAYED")
            assert_current_setup_admission()
            entered[0] = True
            callback(*args)
            completed.append(True)
        except Exception as exc:
            errors.append(exc)
            raise
    try:
        assert_current_setup_admission()
        result = method(label, enter)
    finally:
        active[0] = False
    if errors: raise errors[0]
    if result is not True or completed != [True]:
        raise ValueError("FIXTURE_CALLBACK_UNOBSERVED: synchronous callback completion required")


def _keys(keys, segment_modes):
    import numpy as np
    if (not isinstance(keys, (list, tuple)) or not 1 <= len(keys) <= 8
            or any(not isinstance(row, (list, tuple)) or len(row) != 2 for row in keys)):
        raise ValueError("FIXTURE_LIMIT_EXCEEDED: one to eight explicit keys required")
    frames = [row[0] for row in keys]
    if (frames[0] != 0 or any(type(f) is not int or not 0 <= f <= 32 for f in frames)
            or any(b <= a for a, b in zip(frames, frames[1:]))):
        raise ValueError("FIXTURE_LIMIT_EXCEEDED: exact increasing key grid within 33 frames required")
    positions = []
    for _, position in keys:
        vector = np.asarray(position, dtype=float)
        if vector.shape != (3,) or not np.isfinite(vector).all() or np.max(np.abs(vector)) > 10000:
            raise ValueError("FIXTURE_LIMIT_EXCEEDED: bounded finite native positions required")
        positions.append(vector.astype(np.float32).reshape(3, 1))
    modes = list(segment_modes)
    if len(modes) != len(frames)-1 or any(mode not in ("LINEAR", "STEP") for mode in modes):
        raise ValueError("FIXTURE_MODEL_UNSUPPORTED: explicit LINEAR/STEP segment modes required")
    return frames, positions, modes


def create_independent_transform(scene, name, keys, segment_modes):
    """Create one official Transform in an empty owned scene; do not evaluate."""
    from commands.add.add_transform import add_transform_mod
    from . import runtime as rt
    state, domain = _owned(scene)
    if state["objects"] or not isinstance(name, str) or not name or len(name) > 100:
        raise ValueError("FIXTURE_SCOPE_UNAVAILABLE: one named object in an empty owned scene required")
    _keys(keys, segment_modes)
    created = []
    def create(model, update, callback_scene, session):
        identifier = add_transform_mod(model, update, callback_scene, session, True)
        model.set_object_name(identifier, name)
        created.append(rt._id_string(identifier))
    _modify(domain.modify_with_session, "Create owned independent Transform fixture", create)
    if len(created) != 1:
        raise ValueError("FIXTURE_SCOPE_UNAVAILABLE: official Transform creation did not return one object")
    state["objects"].add(created[0])
    return set_independent_keys(scene, created[0], keys, segment_modes)


def set_independent_keys(scene, object_id, keys, segment_modes):
    """Rewrite only an owned fixture's existing transform data and sections."""
    import csc
    from . import runtime as rt
    state, domain = _owned(scene)
    if state["objects"] != {object_id}:
        raise ValueError("FIXTURE_SCOPE_UNAVAILABLE: exact owned single object required")
    frames, positions, modes = _keys(keys, segment_modes)
    obj = next(iter(domain.model_viewer().get_objects()))
    bv, dv, lv = domain.behaviour_viewer(), domain.data_viewer(), domain.layers_viewer()
    transform = bv.get_behaviour_by_name(obj, "Transform")
    layer_id = lv.layer_id_by_obj_id_or_null(obj)
    if transform.is_null() or layer_id.is_null():
        raise ValueError("FIXTURE_CHANNEL_UNAVAILABLE: official Transform/layer not observed")
    data = {}
    for space in ("local", "global"):
        identifier = bv.get_behaviour_data(transform, space+"_position")
        if identifier.is_null() or dv.get_data(identifier).mode.name != "Animation":
            raise ValueError("FIXTURE_CHANNEL_UNAVAILABLE: animated " + space + " position not observed")
        if rt._id_string(dv.get_data(identifier).object_id) != object_id:
            raise ValueError("FIXTURE_CHANNEL_UNAVAILABLE: transform data owner differs")
        data[space] = identifier
    def write(model, _update, _callback_scene):
        sections = {}
        for index, frame in enumerate(frames):
            section = csc.layers.layer.Section()
            section.interval.interpolation = getattr(csc.layers.layer.Interpolation, modes[min(index, len(modes)-1)]) if modes else csc.layers.layer.Interpolation.LINEAR
            section.interval.common.fixation = csc.layers.layer.Fixation.Free
            section.interval.common.ik_fk = csc.layers.layer.IkFk.FK
            section.key.common.fixation = csc.layers.layer.Fixation.Free
            section.key.common.ik_fk = csc.layers.layer.IkFk.FK
            section.key.label = csc.layers.layer.Key.no_label_id()
            section.key.tangents = csc.layers.layer.Tangents.Continuous
            sections[frame] = section
        model.layers_editor().set_sections(sections, layer_id)
        model.fit_animation_size_by_layers()
        for identifier in data.values():
            for frame, position in zip(frames, positions):
                model.data_editor().set_data_value(identifier, frame, position)
    _modify(domain.modify, "Author owned independent Transform keys", write)
    observed = domain.layers_viewer().layer(layer_id)
    if (list(map(int, observed.key_frame_indices())) != frames
            or int(domain.layers_viewer().frames_count()) != frames[-1]+1):
        raise ValueError("FIXTURE_TIMELINE_UNAVAILABLE: actual authored key grid/timeline differs")
    for index, frame in enumerate(frames[:-1]):
        if observed.interval(frame).interpolation.name != modes[index]:
            raise ValueError("FIXTURE_MODEL_UNAVAILABLE: actual interval mode differs")
    return {"object_id": object_id, "layer_id": rt._id_string(layer_id),
            "position_data_ids": {key: rt._id_string(value) for key, value in data.items()},
            "keys": [[frame, position[:,0].tolist()] for frame, position in zip(frames, positions)],
            "segment_modes": modes, "frames_count": frames[-1]+1}


def release_disposable_scene(scene):
    import csc
    state = _OWNED.get(id(scene))
    if state is None or state["scene"] is not scene:
        raise ValueError("FIXTURE_SCOPE_UNAVAILABLE: scene was not created by this helper")
    manager = csc.app.get_application().get_scene_manager()
    if state["previous"] is not None:
        manager.set_current_scene(state["previous"])
    manager.remove_application_scene(scene)
    del _OWNED[id(scene)]
