# Pitfalls Found in Practice

Each of these cost hours once. Check them before assuming the math is wrong.

## Reads

- **Stale frames past the playhead.** After an edit Cascadeur re-interpolates only from 0 to the playhead; later frames keep old values. Read with `transform_edit(get, refresh=true)` or commit `interpolation_refresh` first. `motion_cleanup_analyze` refreshes on its first read.
- **Wrong tab.** Measurements from one tab and writes into another look like "the write didn't persist" or "the styling vanished". Check `scene_file list` before writing *and before a final verification*; the cleanup tools abort if the active scene changes mid-read. Until 2026-10 the host itself could cause this: when a scene-bound request waited on a busy UI thread (autosave), the fallback trigger pressed Ctrl+Tab even though the target tab was already in front and left another tab active. Keep few tabs open (`close_working_tabs`) and re-check the active tab after long operations.

## Writes

- **Euler convention.** Reads report `to_euler_angles_x_y_z` (= scipy extrinsic `"xyz"`). Writing them back with `Rotation.from_euler` gave a different rotation (30–35° off on fingers). The bridge now writes through `euler_angles_to_quaternion_x_y_z`; when computing rotations yourself, produce `Rotation.as_euler("xyz")` (lowercase, extrinsic).
- **Only existing keys.** `position_keys` / `rotation_keys` rewrite keys; they never add keys. Writes must target each object's own layer keys.
- **Rig re-solving.** Knees and `Leg_AdditionalPoint`s are derived by the rig (leg boxes, limb direction, IK limb-length trimming). Writing them directly is overridden; move hips/feet and let the rig follow. List helper ids in `rig_solved_ids`.
- **AutoPosing overrides.** Controllers with an AutoPosing link are re-posed after the write. Switch AutoPosing off for exactly the controllers you rewrite (`auto_posing_state`).
- **Settled read-back.** Rotation/position commits are re-read in a separate request (0.2° / tolerance cm). A failure there triggers automatic restore — treat it as "something overrode the value", not a flaky test.

## Measuring the right thing

- **Median-relative limits miss static offsets.** A pose error present in every frame (the index splayed 20° from the middle finger) is the median, so limits around the median leave it. Measure anatomical relations between parts (finger gaps in the palm plane) as well as each joint's own variation.
- **Leg reach ends the foot solve.** Where the leg is already at its longest (a push-off, heel rising, toe on the floor), the solve cannot pin the toe without stretching the leg; the residual is a timing/placement issue, not a solver setting.
- **Skate numbers depend on the floor estimate.** The floor is the 3rd percentile of each contact point in the clip being measured; compare before/after with the same floors (`motion_cleanup_prepare` does) and expect small shifts between separate analyze runs.

- **Capsules are not the mesh.** The rig's collision capsules missed most arm-through-body cases (hips, chest, fingers). Measure on the skinned mesh (`mesh_sample`).
- **Keys are not the motion.** A fast limb can cut through the body between two clear keys; measure and constrain every frame, solve at the keys.
- **Dropping satisfied constraints makes an iterative solve oscillate.** Keep every contact constrained once found and cap the step per iteration.

- **The capture is not the choreography.** Mittens, gloves, props and loose sleeves are read as fingers and wrists. Check the reference before deciding that a hand shape or a hovering hand is what the performer did.
- **A wide "near the body" test pulls poses onto the body.** A raised hand 17 cm from the chest is a pose. Restrict resting-hand detection to the waist, hips and thighs and require a close seed.
- **Constraint normals do not survive deep penetration alone.** Keep contacts once found, cap the step, add slack; otherwise the arm solve oscillates and offsets grow to tens of centimetres.

## Interpolation and physics

- **Unbaking** leaves `FIXED` intervals with fixed frames inside; changing interpolation alone does nothing. `interpolation_range` clears them. Adjacent-key intervals stay STEP.
- **AutoPhysics on every-frame keys** changes nothing — reduce keys first.
- **AutoPhysics and Fulcrum do not cure sliding.** They preserve contacts where the animation puts them.

## Session hygiene

- **Working tabs pile up.** Each protected change opens a working clone; many rollbacks drove Cascadeur to 10 GB and a hang. Close them with `close_working_tabs` (safe only from the pump, never from a menu command).
- **Handler changes hot-reload**; `runtime.py` / `pump.py` changes need a Cascadeur restart.
- **Rig generation looks like a freeze.** Wait for Quick Rigging Tool bakes to finish.
- **A minimised Cascadeur screenshots black.** Use `viewport_capture` (renders to a file) to look at a frame.
- **Fix Collisions does not fix self-penetration**; it returns in milliseconds with no change.
- **Dialogs** are pressed via UI Automation Invoke without focus; if one still blocks, ask the user to press it.
