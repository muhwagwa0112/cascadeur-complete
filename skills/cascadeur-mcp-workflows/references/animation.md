# Animation Workflows

Use this reference for poses, transforms, keys, layers, interpolation/tangents, cycles, mirroring, generative tools, mocap/retargeting, and animation cleanup.

## Read the animation state first

1. `scene_summary`: scene/revision, selection, current frame, active layer.
2. `timeline_get`: verified playhead, total frame count, and animation boundary.
3. `layer_list`: exact layer/folder IDs, visibility, lock state, and keys.
4. `scene_objects` plus `object_read`: controller/object IDs and hierarchy.
5. `generation_state`: selected layers/interval, key availability, and rig support before generation.

Use `timeline_set_frame` to position and verify the playhead. Do not trust a cached frame value after a scene or tab switch.

## Draft poses and keys

- Read current transforms with `transform_edit(action="get", ids=[...], frame=..., space=...)`.
- Write position, rotation, or local scale with `transform_edit(action="set", ...)`, passing the latest scene ID/revision.
- Rotation input is Euler XYZ **radians**. Convert degrees using `radians = degrees * pi / 180` and keep the convention explicit.
- Use local space for controller-relative edits; use global space only when the tool action supports it and the intended world-space result is clear.
- Add or list keys with `key_edit`. Key deletion is protected and must use prepare/commit.
- Re-read transforms and key lists at every edited frame. A changed revision alone does not prove a correct pose.

When building several poses, work pose-by-pose so each result can be inspected. Batch only independent non-destructive reads or writes that share a revision and need no intervening evaluation.

## Layers, folders, and timing

Use `layer_list` before every layer-targeted operation. IDs, not names, are the mutation contract.

- `layer_write(action="create")`: create an animation layer. Use `folder_create`, `folder_move`, or `folder_rename` for folders.
- `layer_write` visibility/lock actions: set and verify the observed boolean state.
- Layer deletion is protected.
- `timeline_select_interval(first_frame, last_frame, layer_ids)`: select the exact interval required by generation or physics tools.
- `animation_curve(action="query")`: inspect curve sections before changing them.
- `animation_curve` interpolation/tangent actions: set an exact mode at an exact frame/layer and re-query.
- `cycle_list`: inspect normalized cycles. Cycle creation/editing and track stretching are UI-only in the baseline unless live capability data reports a verified route.

Do not edit a hidden or locked layer accidentally. State the active/target layers and frame range in the plan.

## Spline and polishing workflow

1. Establish main keys and timing.
2. Query curve sections and existing interpolation.
3. Apply interpolation and tangents conservatively.
4. Inspect intermediate frames using verified playhead changes and transform reads.
5. Use key reduction only after the motion is accepted and a snapshot exists.

`key_reduction_prepare` requires explicit layer IDs and frame bounds. Preserve endpoints unless the user specifically requests otherwise. Commit, then compare key counts and end transforms; rollback if the motion or contacts drift.

Animation Unbaking is staged:

- `prepare_keys_by_fulcrums`;
- `adjust_keys_and_interpolation`;
- `adjust_autoposing_lock_state`.

Call `animation_unbaking_prepare(step=...)` for one documented stage at a time. Verify keys/interpolation after each stage rather than treating the three stages as an opaque batch.

Trajectory display, Ghost, Fixing/Hiding, Tween, Interval Edit, Copy Animation, graph UI editing, and bake/stretch/playback controls may be UI-only. Use `feature_describe`; return the exact gate instead of simulating unknown mouse flows or action IDs.

## Mirror and cycles

Use `mirror_prepare` with explicit Box-controller IDs and either:

- `mode="frame"` plus `frame`; or
- `mode="interval"` plus first/last frame and layer IDs.

The default mirror plane is normal `[1, 0, 0]` through origin `[0, 0, 0]`. Override it only when the character/world plane is known. Commit and compare paired controllers at key frames.

Use `cycle_list` to diagnose existing cycles. If cycle editing is `ui_only`, report the route and leave a manual step; do not approximate a cycle by silently duplicating keys unless the user requested that alternate result.

## AutoPosing

AutoPosing requires a suitable Cascadeur rig and selected rig controls. Check `rig_state` and `generation_state` first.

For a protected AutoPosing add/update, use:

1. `change_prepare(feature_id="auto_posing", operation_name="generation.auto_posing", arguments={"action":"add"|"update"})`;
2. inspect snapshot/impact and commit the token;
3. re-read controller transforms and generation state.

The 2026.1 line improves quadruped AutoPosing and integrates Point Constraints. Finger AutoPosing remains a separate capability and may be UI-only.

## Inbetweening

Inbetweening requires selected keyframes/layers and a valid interval. In the Basic baseline it is license-gated.

1. Set the intended layer interval with `timeline_select_interval`.
2. Confirm surrounding keys/interpolation using `generation_state` and curve queries.
3. Call `inbetweening_prepare`.
4. If gated, report the required license; do not substitute Root Motion or Tween without user agreement.
5. If available, commit and verify generated frames, boundary poses, and interpolation continuity.

Cascadeur 2026.1.2 fixes rotated-character behavior and makes the maximum-interval setting not affect Inbetweening. Still validate a rotated-root case when that is the user's scene.

## Root Motion

Root Motion generation needs a rough motion draft with at least start/end keys and a selected interval.

1. Inspect rig, layers, keys, root transform, and animation boundary.
2. Select the exact interval across explicit layers.
3. Call `root_motion_prepare`, then commit its token.
4. Compare root trajectory, start/end transforms, character orientation, and generated keys.

The 2026.1.2 maximum-interval setting applies to Root Motion, and rotated-character issues were fixed. Do not assume a long interval is accepted; surface the live precondition/gate.

## Mocap and retargeting

Treat these as end-to-end transfers, not single button presses:

1. Validate source and target skeleton joint names, hierarchy, bind/model pose, root orientation, scale, and animation range.
2. Import source motion into a protected working scene.
3. Search/describe `mocap` or `retargeting` and inspect license/dependency state.
4. If available, run through the exact registered route and require postconditions on the target hierarchy/keys.
5. Verify representative frames, root motion, end effectors, rotations, and contacts.
6. Unbake/reduce/polish only after transfer quality is accepted.

In the Basic baseline, mocap and retargeting are license-gated. Return that gate and the scene preparation already completed; never report a successful transfer.

## Animation completion evidence

Report the edited layer IDs, frame interval, key-count changes, representative transform comparisons, interpolation/tangent modes, generator/cleanup state, final scene revision, and retained snapshot. Visual UI state without scene-data evidence is supporting evidence only.
