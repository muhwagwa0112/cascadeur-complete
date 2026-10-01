---
name: cascadeur-mocap-cleanup
description: Clean up imported mocap in Cascadeur through the cascadeur-complete MCP as one measured pipeline — key reduction, spline interpolation, AutoPhysics, finger spread/spike cleanup, whole-clip foot-sliding correction and arm-through-body clearance, each verified by numbers over every frame. Use when the user asks to clean up, polish or fix mocap/imported motion, foot sliding/skating, root-motion glide, jittery, splayed or claw-like fingers, arms or hands clipping through the body mesh, or to apply AutoPhysics to captured motion.
---

# Cascadeur Mocap Cleanup

Turn a raw imported clip into clean motion with `cascadeur-complete`, fixing whole classes of problems in one pass instead of chasing spots the user points at. Every stage is measured over **all frames** before and after, and every write goes through the protected prepare → commit contract.

This skill sits on top of `cascadeur-mcp-workflows` (general routing, safety contract). Load that skill's references only when a stage needs a tool not described here.

## Route the request

| Need | Reference |
|---|---|
| Full pipeline order, exact tool calls per stage | [pipeline.md](references/pipeline.md) |
| Foot sliding / skating / root glide (the global contact solve) | [foot-contacts.md](references/foot-contacts.md) |
| Finger spread, twist, spikes, claw-like index splay | [fingers.md](references/fingers.md) |
| Arms passing through the torso, hips or the other arm (mesh-based clearance solve) | [arms.md](references/arms.md) |
| Cascadeur and MCP quirks that silently break cleanup | [pitfalls.md](references/pitfalls.md) |
| Metrics, thresholds, what to report | [verification.md](references/verification.md) |

## Operating rules

1. **Protect the user's files.** Never overwrite the source or an earlier result. Save each accepted stage with `scene_file` save_as under a new name (e.g. `clip_clean_physics.casc`, `clip_clean_final_v3.casc`).
2. **Verify the active tab before every write and every save.** `scene_file(action="list")` → exactly one tab has `active: true`; it must be the scene you measured. The user switching tabs (Ctrl+Tab) mid-session is the most common cause of "the write didn't stick".
3. **Measure first, then fix, then re-measure the live scene.** Use `motion_cleanup_analyze` for the baseline. A `motion_cleanup_prepare` result carries *predicted* numbers; after commit, run `feature_prepare("interpolation_refresh")` + commit and analyze again — only the re-read numbers count.
4. **Fix classes, not spots.** When the user reports a frame range, treat it as a symptom: find the metric that catches it (skate per frame, survey, finger steps), confirm the metric flags it, then fix the whole clip with one solve.
5. **One stage per commit, snapshot kept.** Each commit returns a `snapshot_id`; keep it until the user accepts the stage. Roll back with `change_rollback_prepare` + `change_rollback` when a stage makes things worse.
6. **Long commits need long timeouts.** Whole-clip key writes (10k+ writes) take minutes: `change_commit(token, timeout=900)`.
7. **Report honestly.** Say which frames were processed, what remains above threshold, and what was predicted vs. re-measured. Never claim "all frames fixed" from a detector that only covers some frames.

## Default pipeline (summary)

1. `cascadeur_status` → pump alive, correct build; `scene_file list` → active tab.
2. Bake the clip, reduce keys every 3 frames on every layer, set interpolation to BEZIER over the range, refresh interpolation.
3. AutoPhysics enable + snap (removes jitter, balances the Center of Mass). It does **not** fix foot sliding.
4. Fingers: switch AutoPosing off for the finger controllers, `motion_cleanup_prepare(kind="fingers")`, commit; if `gaps` flags an index–middle splay (claw look), `motion_cleanup_prepare(kind="finger_fan")`, commit.
5. Feet: `motion_cleanup_prepare(kind="foot_contacts")`, commit, refresh, re-analyze.
6. Arms: `motion_cleanup_analyze(checks=["arms"], every_frame=true)`; if an arm is inside the body, `motion_cleanup_prepare(kind="arm_clearance")`, commit, refresh, re-analyze.
7. Save as a new file; close stale working tabs with `feature_prepare("close_working_tabs")`.

Details, arguments and the evidence to collect at each step are in [pipeline.md](references/pipeline.md).
