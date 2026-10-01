# Arms: Passing Through the Body

Mocap arms cut through the torso, hips or the other arm wherever the performer's body and the character's mesh differ: a hand "on the hip" sinks into it, an upper arm overlaps the ribs, a fast forearm swing crosses the flank.

## What does not work

- **Cascadeur "Fix Collisions" (`collision_clean`)** finishes in milliseconds and changes nothing for a character's own body parts; it resolves contact with other colliders, not self-penetration.
- **The rig's collision capsules** (`CapsuleCollision` on `*_Rigid`) are too coarse as the surface. On the reference clip they flagged 3 spans; the real mesh showed 20 on the left arm alone. They miss hips and chest (the mesh is wider than the capsule) and the fingers (the hand is one small box). Use them only to prototype.
- **Measuring at keys only.** Two clear keys 3 frames apart can interpolate straight through the body when the arm moves fast. Measure and solve on every frame.

## The method (`motion_cleanup_prepare(kind="arm_clearance")`)

1. **Real surface.** `mesh_sample` (read-only bridge operation) writes the skinned mesh for the requested frames to `state/mesh/<name>.npz`: float32 positions per frame, triangles, the bound joint names and each vertex's dominant joint. ~27 s and ~220 MB for 986 frames of an 18k-vertex character.
2. **Inside test.** Per arm, the obstacle is every vertex not bound to that arm or its shoulder (torso, hips, head, legs, the other arm). An arm vertex is inside when it lies behind the nearest obstacle vertex's outward normal (winding from the mesh's signed volume); depth = that signed distance. Tested vertices: upper arm from its midpoint down (the half next to the shoulder always touches the torso), the forearm, the hand and fingers.
3. **One QP per arm** for elbow and wrist offsets at the arm controllers' keys:
   - minimise the offsets plus their first and second differences (corrections ramp in and out);
   - every constrained vertex must end `margin` (0.2 cm) outside, linearised along the contact normal — a vertex moves with the elbow/wrist offsets blended along its bone; one slack per contact keeps the problem feasible where normals disagree;
   - upper-arm and forearm lengths stay constant (first order); the shoulder does not move;
   - offsets at in-between frames are the linear blend of the neighbouring keys, so constraints on those frames push the keys;
   - re-linearise up to 8 times with a 3 cm trust region. Constrained vertices stay constrained (dropping one as soon as it clears lets the next solve relax straight back inside — the solve then oscillates and offsets blow up).
4. **Writes.** `ForeArm_MainPoint`/`ForeArm_AdditionalPoint` get the elbow offset, `Hand_MainPoint`/`Hand_DirectionPoint`/`Hand_AdditionalPoint` the wrist offset, at existing keys through `position_keys` (tolerance 10 cm, `ForeArm_AdditionalPoint` in `rig_solved_ids`). Overlap up to `arm_allow_cm` (0.3) is left as soft contact.

## Procedure

1. `motion_cleanup_analyze(checks=["arms"], every_frame=true)` → per arm: `penetrating_samples`, `max_depth_cm`, `worst_frame`, `spans`. A few minutes.
2. Look at the worst frames before fixing (see "Seeing the result" below) so the numbers are tied to something visible.
3. `motion_cleanup_prepare(kind="arm_clearance")` (several minutes; reads every frame). Check `cleanup.sides.<Side>.before` / `predicted_after`, `elbow_offset_max_cm`, `wrist_offset_max_cm` (≈ the deepest penetration is normal; tens of cm means the solve diverged — do not commit).
4. Verify the active tab, `change_commit(token, timeout=900)`, commit `interpolation_refresh`.
5. Analyze again with `every_frame=true`. A leftover single frame under ~1 cm comes from Bezier vs. linear interpolation; run the prepare once more if it matters.
6. Re-check feet and fingers (they should be unchanged) and render the previously worst frames.

## Reference result (986 frames)

| | Before | After (re-sampled mesh, every frame) |
|---|---|---|
| Left arm frames inside the body | 71 of 330 keys, max 8.0 cm | 1 of 986 frames, 0.9 cm |
| Right arm | 17 of 330 keys, max 3.3 cm | 1 of 986 frames, 0.3 cm |
| Largest moves | – | wrist 10.6 cm, elbow 7.9 cm |

A hand that rested on the hip ends up just off the surface: the solve translates the hand until its deepest vertex (a fingertip) is out; it does not re-pose the wrist to lay the palm flat. Mention this, and re-pose by hand if the contact matters.

## Seeing the result

- `viewport_capture` (`render.viewport_capture`, protected) renders the viewport to a PNG even when Cascadeur is minimised; a window screenshot is black then.
- Point the camera with `camera_view` (position/target; protected) at the chest from the side of the arm, and set the frame with `timeline_set_frame` first.
- Each protected call leaves a working tab; close them (`close_working_tabs`) every few renders — a dozen tabs pushed Cascadeur to 7 GB.
