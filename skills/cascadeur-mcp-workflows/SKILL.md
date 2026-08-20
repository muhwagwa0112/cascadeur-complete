---
name: cascadeur-mcp-workflows
description: Plan and execute Cascadeur 2026.1.x scene, animation, rigging, physics, rendering, import/export, and DCC-integration work through the cascadeur-complete MCP. Use for inspecting or changing a live Cascadeur project; do not use for generic animation theory or direct work inside another DCC.
---

# Cascadeur MCP Workflows

Use `cascadeur-complete` as the control plane for Cascadeur. Treat its live capability state, scene IDs, revisions, postconditions, and safety tokens as authoritative. The installed 2026.1.2 adapter is the baseline; never infer support from a newer manual page alone.

## Route the request

Read only the references needed for the current task:

| Task | Reference |
|---|---|
| Scene tabs, CASC files, selection, objects, hierarchy, FBX/DAE/USD/GLB/GLTF/VRM, audio/image/video | [scene-objects-io.md](references/scene-objects-io.md) |
| Posing, transforms, keys, curves, layers, cycles, mirror, Root Motion, Inbetweening, mocap, retargeting, cleanup | [animation.md](references/animation.md) |
| Quick/manual rigging, controllers, joints, rigid bodies, IK/Spline IK, twist, mass, constraints, collision, ballistics, AutoPhysics, Ragdoll | [physics-rigging.md](references/physics-rigging.md) |
| Cameras, viewports, Filament lights/materials, still/video output, Unreal Live Link, Blender/Unity/Daz/Roblox | [render-external.md](references/render-external.md) |
| Capability states, protected changes, jobs, errors, low-level calls, rollback, diagnosis | [safety-diagnostics.md](references/safety-diagnostics.md) |
| Exact catalog of all 75 public MCP tools | [tool-routing.md](references/tool-routing.md) |
| Version facts and source links | [official-sources.md](references/official-sources.md) |

For a multi-stage production workflow, read every domain reference that participates in the requested output. Do not load unrelated references merely because they exist.

## Operate in this order

1. Call `cascadeur_status(refresh=true)`. Confirm connection, executable version, adapter, license, active scene, and state counts.
2. Search before assuming. Use `feature_search` for the requested product feature and `feature_describe` for its exact route, state, preconditions, destructive flag, dependency, and test identity.
3. If the task touches a scene, call `scene_summary`; page through `scene_objects` when IDs or hierarchy matter. Read `timeline_get`, `layer_list`, `rig_state`, `physics_state`, `generation_state`, or `viewport_camera(action="viewport_state")` only when relevant.
4. Convert names to explicit object, layer, camera, and tab IDs. Preserve the latest `scene_id` and `scene_revision`; a successful mutation invalidates the old revision.
5. Prefer the narrow task-focused tool. Use `operation_batch` only for a cohesive, non-destructive group that shares one known revision and requires no intermediate selection or UI state.
6. For a protected change, call its dedicated `*_prepare` tool when one exists. Otherwise call `change_prepare` with the exact feature ID, operation name, and arguments. Commit only the returned token with `change_commit`.
7. Inspect the common result envelope. Require `ok=true`, the expected `changed_entities`, a new revision for scene mutations, operation-specific `evidence`, and the requested file or scene result.
8. Re-read the changed seam. Validate the exact frame, keys, transforms, rig/physics state, rendered file, export, or external connection—not merely that the call returned.
9. Preserve the `snapshot_id` until the user accepts the result. Use `change_rollback` when a protected operation fails, its postcondition is wrong, or the user requests restoration.

## Non-negotiable invariants

- A prepare token is not authorization. Commit only when the current request authorizes that exact mutation. Do not broaden approval from one scene, file, object set, or export destination to another.
- Do not reuse a scene revision after a successful write, scene activation, open, rollback, or snapshot transition. Refresh the scene and re-plan on `SCENE_CHANGED`.
- Do not target mutable entities by display name when an ID is available. Resolve the name, show ambiguity when multiple objects match, then use IDs.
- Cascadeur rotations in `transform_edit` are Euler XYZ radians. Convert degrees explicitly and report which unit was used.
- Treat `ui_only`, `license_gated`, `missing_dependency`, `unsupported_version`, and `unhealthy` as results, not invitations to bypass the gate. Return the route and the concrete prerequisite or manual step.
- Do not replace a missing adapter with guessed `action_invoke`, `tool_call`, or Python. Low-level routes are last-resort registered paths and still require observable postconditions.
- `developer_execute_python` is disabled by default. Use it only for an explicit development/debugging request after confirming local policy, and never as a substitute for product support.
- Use local absolute paths. Do not use UNC or device paths. Never overwrite an existing file unless the current request explicitly authorizes that destination and `allow_overwrite` is set during preparation.
- If Cascadeur is not running, locked, waiting on a modal dialog, or reports an unknown outcome, stop mutation attempts. Inspect status/logs and determine whether the request was claimed before retrying.

## Plan complete animation work as stages

Use Cascadeur's production pipeline as the default shape, adapting it to the user's actual deliverable:

1. **Reference and ingest:** establish source motion, character, FPS/range, units, axes, and output target.
2. **Scene and rig readiness:** import, resolve hierarchy, validate or create the rig, controllers, masses, and Center of Mass.
3. **Drafting:** establish key poses and timing on explicit layers.
4. **Spline/generation:** tune interpolation and tangents; use mirror, cycles, Inbetweening, Root Motion, mocap, or retargeting only when capability checks pass.
5. **Physics:** establish fulcrums/constraints/collisions, then ballistics or AutoPhysics.
6. **Polish:** inspect trajectories and contacts; unbake or reduce keys conservatively; clean collisions through a verified route or return the UI gate.
7. **Presentation and delivery:** set cameras/lights/view mode, render or capture, export to the target format/DCC, and validate the produced artifact.

Each stage must leave enough evidence to diagnose the next. Do not run a downstream generator when its rig, selection, key interval, dependency, or license prerequisite is unresolved.

## Report the outcome

State what changed, the active scene and final revision, important IDs and frame interval, snapshots retained, output paths and sizes, and any gates. Distinguish:

- completed and postcondition-verified work;
- work available only after a scene/selection prerequisite;
- manual UI-only work;
- license or external dependency gates;
- unsupported-version behavior;
- rollback performed or still available.

Do not describe a queued action, fire-and-forget call, or gate response as completed animation work.
