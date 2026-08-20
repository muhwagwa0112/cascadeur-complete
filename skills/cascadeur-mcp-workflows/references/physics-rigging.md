# Physics and Rigging Workflows

Use this reference for character rig creation/inspection, controllers, rigid bodies, IK, mass, Center of Mass, constraints, collisions, ballistics, AutoPhysics, Ragdoll, and physics cleanup.

## Inspect before entering rig or physics work

Call:

- `rig_state` for RigInfo, joints, rig elements, Point/Box controllers, rigid bodies, IK, Spline IK, twist, and Quick Rig state;
- `physics_state` for rigid-body masses, Center of Mass, constraints, collision behaviors, and physics data;
- `scene_objects` and `object_read(action="hierarchy")` for exact ownership and joint order;
- `generation_state` when the rig will feed AutoPosing, Root Motion, or Inbetweening.

Do not infer a usable rig merely because joints or a mesh exist. Cascadeur's AutoPosing and physics tools require a compatible control rig.

## Rig-mode safety

Entering Rig Mode can replace an existing rig with prototype objects, reset the character to its model pose, and temporarily make animation/timeline unavailable. Always protect the scene first and identify which character is being rigged. Do not enter or regenerate a rig through a generic UI action when the baseline reports `ui_only`.

For every rig mutation:

1. use explicit IDs and documented ordering;
2. call the relevant `*_prepare` tool;
3. inspect the impact and working scene;
4. commit the token;
5. re-read `rig_state` and affected object hierarchy;
6. preserve the snapshot until deformation and animation are validated.

## Manual rig construction

Use this dependency order, skipping only elements that are already verified:

1. **Joints:** `joint_create_prepare` for one new Joint at a time when needed.
2. **Rig ownership:** `rig_info_create_prepare(joint_ids, name)` links exact unassigned joint owners.
3. **Rig elements/rigid bodies:** `rig_elements_create_prepare(pairs, options, feature)` with explicit Joint/direction-Joint pairs.
4. **Additional controls:** `additional_point_controller_prepare` or `additional_box_controller_prepare` for an exact manual-rig element.
5. **IK:** `ik_chain_create_prepare(ordered_ids)`; order is main end, middle links, then secondary end as required by the adapter.
6. **Spline IK:** `spline_ik_create_prepare(start_joint_id, end_joint_id, name)` only when endpoints resolve to one hierarchy.
7. **Twist:** `twist_prepare(action="set", box_id, joint_id)` or `remove`; do not reverse box/joint roles.
8. **Mass:** `rigid_body_mass_prepare(total_mass, ids)` scales explicit rigid bodies to a positive target total.
9. **Validate:** check hierarchy, controller ownership, IK endpoints, twist binding, rigid bodies, mass totals, and representative deformation.

`rig_elements_create_prepare(feature="rigid_body")` requires actual rigid bodies; the adapter rejects `only_box_controller=true`. Use a clear direction Joint for each pair rather than guessing from selection order.

Quick Rig, rig regeneration, Blend Shapes, and some advanced prototype actions may be UI-only. Return their capability route and manual prerequisite. Do not fall back to mass-creating approximate rig elements and call that Quick Rig.

## Center of Mass

Use `center_of_mass_prepare` with explicit IDs and one mode:

- `from_rigids`: construct from selected rigid bodies;
- `composite`: construct a combined CoM;
- `connect_direction_controllers`: bind direction controls;
- `snap_mesh`: align the CoM to mesh data.

After commit, verify CoM identity, ownership/bindings, position, and `physics_state`. A main CoM is required for ballistics and AutoPhysics.

## Constraints

Read `constraint_driver_catalog` before creating a Point Constraint. It lists actual update-graph Triangle drivers; do not substitute an object that merely has a similar name.

- `transform_constraint_prepare(driver_id, constrained_id)`: exact driver and target.
- `point_constraint_prepare(driver_id, point_ids, spherical_position)`: one verified driver and explicit Point-controller IDs.

After commit, inspect constraint behaviors and test representative poses/frames. Cascadeur 2026.1 integrates Point Constraints with AutoPosing, AutoPhysics, and Ragdoll; this increases the need to verify multi-character ownership and prop attachment.

## Collision setup and cleaning

Use `collision_create_prepare(shape, ids, options)` with one supported shape:

- `box`;
- `capsule`;
- `kinematic_mesh`;
- `convex_decomposition`;
- `convex_by_skinning`.

Use `collision_delete_prepare(ids)` to remove supported collision behaviors from exact targets. Re-read physics state and object behaviors after both operations.

Collision Penetration Cleaning and the legacy collision-cleaning UI tool can be UI-only. Old scenes may require rig regeneration before 2026.1 penetration cleaning works. If regeneration or cleaning lacks a verified adapter, report the manual sequence and keep the snapshot; do not invoke an unverified UI action.

## Ballistic motion

Ballistics requires a Center of Mass and an interval spanning takeoff through landing.

1. Identify the last supported/contact frame and first landing/contact frame.
2. Select explicit animation layers/range.
3. Call `ballistic_create_prepare(center_of_mass_id, first_frame, last_frame, layer_ids)`.
4. Commit and verify that the ballistic trajectory persists in `physics_state`.
5. Inspect root/CoM positions and key contact frames. Ballistic Ghosts and Angular Momentum visualizers may remain UI-only visualization aids.

Do not use a ballistic curve as proof that the character pose or landing contact is correct.

## AutoPhysics

Use the exact sequence:

1. `auto_physics_state` to inspect CoM, selection, animation length, and readiness.
2. Fix missing rig/CoM/interval/constraint prerequisites.
3. `auto_physics_enable(scene_id, expected_revision)` to select the main CoM and enable Physics Assistant.
4. Refresh scene/revision and call `auto_physics_state` again.
5. Protect `physics.auto_snap` through `change_prepare(feature_id="auto_physics", operation_name="physics.auto_snap", arguments={})`, then commit. If the dedicated environment allows `auto_physics_snap`, still require its protected contract.
6. Compare the resulting keys, root/CoM trajectory, contacts, constraints, and final revision.

Do not call snap repeatedly when readiness is false. A warning dialog or timeout is not success; inspect logs/status and determine whether the operation was claimed.

## Ragdoll, fulcrums, and cleanup

Ragdoll, Fulcrum tools, Fulcrum Motion Cleaning, and penetration cleaning are distinct capabilities. Search and describe each one. The 2026.1.2 baseline may report them as UI-only even though the product supports them.

For manual handoff, provide:

- the protected working scene/snapshot;
- exact character/CoM/controller IDs and frame interval;
- constraints/collision state already configured;
- the named Cascadeur tool and expected postcondition;
- the state that must be re-read after the user completes the UI step.

Never classify a manual UI handoff as MCP-completed physics work.

## Completion evidence

Report rig element and controller counts, hierarchy/ownership, mass totals, CoM and constraint IDs, collision shapes, physics interval, key/trajectory changes, final scene revision, and snapshot. For a generated result, include representative takeoff/apex/landing or contact-frame checks.
