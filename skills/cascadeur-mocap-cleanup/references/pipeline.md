# Cleanup Pipeline

Stage order matters: each stage assumes the previous one's key structure. Record the snapshot id and the metrics after every stage.

## 0. Preflight

1. `cascadeur_status(refresh=true)`: `connection.ok`, build `2026.1.3.0.15619`, `ui_pump` alive (requests are processed without focusing Cascadeur).
2. `scene_file(action="list")`: note the active tab id/path. Working-clone tabs named `<uuid>.working.casc` are MCP snapshots, not user scenes.
3. `timeline_get`: `frames_count` (e.g. 986 → frames 0..985).
4. `layer_list`: every animation layer id (body layers plus `Fingers_L/R`-style finger layers).
5. Baseline: `motion_cleanup_analyze(segments=[[a,b], ...])` with any ranges the user mentioned. Keep the JSON.

If the character has no rig yet, Quick Rigging Tool "Create rig from qrt" re-bakes the whole clip per bone (15-35 s per bone on ~1000 frames). Cascadeur looks frozen but CPU and log keep moving — wait; do not force-quit.

## 1. Key structure: bake → reduce → spline

Mocap arrives with a key on every frame, so AutoPhysics has nothing to change and interpolation is irrelevant.

1. `feature_prepare("bake", {"first_frame": 0, "last_frame": N-1})` → commit.
2. `key_reduction_prepare(first_frame=0, last_frame=N-1, layer_ids=[all layers], every_n=3, preserve_endpoints=true)` → commit. Keys land on 0, 3, 6, … and the last frame.
3. `feature_prepare("interpolation_range", {"first_frame": 0, "last_frame": N-1, "interpolation": "BEZIER"})` → commit. The adapter clears fixed frames inside intervals and skips adjacent-key intervals (which Cascadeur keeps as STEP).
4. `feature_prepare("interpolation_refresh")` → commit.
5. Compare against the baseline at many frames (e.g. `transform_edit(get, refresh=true)` on the hips/feet every 10 frames): the difference should be sub-centimetre. Roll back if the motion drifts.

Do **not** use Animation Unbaking to get sparse keys for mocap: it leaves `FIXED` intervals holding the raw data, and a CLAMPED_BEZIER over its sparse keys moved the body up to 76 cm. Every-3-frames reduction keeps the motion and still gives splines.

## 2. AutoPhysics

1. `auto_physics_state` → Center of Mass exists, animation length, prerequisites.
2. `change_prepare("auto_physics_enable", "physics.auto_enable", {})` → commit.
3. `change_prepare("auto_physics", "physics.auto_snap", {})` → commit. A confirmation dialog may appear; the MCP presses it through UI Automation Invoke without focusing the window. If it still blocks, ask the user to press OK and continue.
4. `auto_physics_state` → converged.

Expected effect on mocap: jitter down 25–68 % (hands most, feet least), body shifted ~2 cm on average to balance the CoM. Feet keep sliding: AutoPhysics holds contacts where the animation already puts them. Fulcrum marking on contact frames did not change sliding either.

Save as `<clip>_clean_physics.casc`.

## 3. Fingers

See [fingers.md](fingers.md). In short: switch AutoPosing off for the finger controllers, `motion_cleanup_prepare(kind="fingers")`, commit, refresh, re-analyze; then check `gaps` and run `kind="finger_fan"` when the index–middle gap is flagged. Save as `<clip>_clean_fingers.casc`.

## 4. Feet

See [foot-contacts.md](foot-contacts.md). In short: `motion_cleanup_prepare(kind="foot_contacts", segments=[...])`, check the predicted numbers, commit with `timeout=900`, refresh, re-analyze. Save as `<clip>_clean_final.casc`.

## 5. Arms

See [arms.md](arms.md). In short: `motion_cleanup_analyze(checks=["arms"], every_frame=true)`; when an arm is inside the body, `motion_cleanup_prepare(kind="arm_clearance")`, commit with `timeout=900`, refresh, re-analyze on every frame, render the worst frames. Run it after the feet (the foot solve moves the whole body, arms included). Save as `<clip>_clean_final.casc`.

## 6. Wrap up

1. Verify the active tab once more, then `change_prepare("scene_save_as", "scene.save_as", {"path": ..., "tab_id": ...})` → commit.
2. `feature_prepare("close_working_tabs")` → commit. Each prepare leaves a working-clone tab; dozens of them pushed Cascadeur past 10 GB and hung it.
3. Export when asked for a deliverable: `change_prepare("export_fbx", "io.export_fbx", {"path": "<clip>_clean_final_vN.fbx"})` → commit (about 10 s for 1000 frames). Check it with `scripts/fbx_check.py`: on the reference clip FBX 7.7, one take, 1062 curves × 986 keys (0–32.83 s), 116 joints, one skinned mesh. The writer leaves the file's global time span at one second although the curves cover the clip; mention that a DCC may need its range set to the take.
4. Report per stage: file name, metric before/after, remaining hot spans, snapshots kept, anything the user should look at in the viewport.
