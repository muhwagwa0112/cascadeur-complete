# Sources and Version Notes

Use these sources to understand product behavior and preconditions. Use the live MCP registry to decide whether the installed adapter can execute that behavior.

## Primary product sources

- [Cascadeur Tools](https://cascadeur.com/help/tools): product-wide Animation, Timeline, Physics, Camera, and Rigging tool index.
- [Animation Pipeline](https://cascadeur.com/help/animation_pipeline): Reference → Drafting → Spline → Physics → Polishing workflow.
- [Rig overview](https://cascadeur.com/help/rig): rig purpose, creation flow, and rig dependence of AutoPosing/physics.
- [Rigging Tools](https://cascadeur.com/help/rig/rig_mode/rigging_tools): prototype rig elements, Quick Rig, controllers, CoM, twist, Spline IK, and rig-generation UI.
- [Rig Structure](https://cascadeur.com/help/rig/rig_structure): prototype objects, rig elements, behaviors, and physics requirements.
- [Physics workflow](https://cascadeur.com/help/animation/physics): Center of Mass, ballistics, angular momentum, and physics-based polishing.
- [File menu](https://cascadeur.com/help/interface/main_menu/file_menu): CASC lifecycle and supported import/export/media commands.
- [FBX/DAE export](https://cascadeur.com/help/getting_started/export_fbxdae): presets, selection/range, baking, Euler filter, axes, video UI, and interoperability issues.
- [USD export](https://cascadeur.com/help/category/213): model versus complete-scene export.
- [GLB/GLTF/VRM import](https://cascadeur.com/help/category/282): presets and selection/animation/model/scene behavior.

## Version baseline

- [Cascadeur 2026.1 release notes](https://cascadeur.com/help/category/312): Filament, rebuilt Unreal Live Link, Root Motion, Collision Penetration Cleaning, quadruped AutoPosing, constraints in AutoPhysics/Ragdoll, lights, neck Spline IK, and related changes.
- [Cascadeur 2026.1.2 release notes](https://cascadeur.com/help/category/314): rotated-character fixes for Retargeting/Inbetweening/Root Motion, constraint/Ragdoll fixes, Root Motion interval behavior, trajectory performance/crash fixes, neck Spline IK, FBX import, and video-with-audio crash fix.
- [Cascadeur 2026.1 overview](https://cascadeur.com/blog/view/cascadeur-2026-1-new-renderer-ue-live-link): official product overview for Filament, Live Link, Root Motion, collision cleaning, constraints, and quadrupeds.

The local adapter baseline is `2026.1.2.0.15343`. Do not use 2026.2-only Additive Layers or Easing unless `cascadeur_status` reports a newer compatible adapter and `feature_describe` reports an executable route.

## Automation and API sources

- [Python Scripting in Cascadeur](https://cascadeur.com/help/tools/animation_tools/python_scripting_in_cascadeur): application/scene managers, viewers/editors, modify sessions, behaviors, custom commands, and bundled samples.
- [Cascadeur Python API](https://cascadeur.com/help/category/215): installed `csc` module reference.
- [Action ID list](https://cascadeur.com/help/category/301): exact IDs for `call_action`; the documentation states that this mechanism is planned for gradual removal in favor of APIs.

The installed schema and runtime are more precise than prose documentation for callable signatures:

- MCP resource `cascadeur://capabilities` for live version/license/dependency state;
- `cascadeur://features` for the complete execution/gate matrix;
- `cascadeur://csc/schema` for normalized installed API symbols;
- `cascadeur://actions` for discovered actions/commands;
- `inventory_refresh` after a version or script change.

Schema discovery alone is not implementation evidence. Prefer dedicated tools with registered adapters and live postconditions.

## External workflow sources

- [Unreal Engine Live Link](https://cascadeur.com/help/category/268): license/OS/plugin versions, skeleton matching, root orientation/scale, connection, and streaming.
- [Export to Blender](https://cascadeur.com/help/category/300): preferred formats, model pose, binary FBX, and Blender bone-orientation guidance.
- [Interface and DCC workflow index](https://cascadeur.com/help/interface): Unreal, Unity, Daz, Roblox, Blender, Maya, 3ds Max, MetaHuman, Character Creator, and import/export guides.

For another DCC or plugin, read its current official target-side documentation as well. The Cascadeur manual cannot prove the target application accepted a file or stream.

## Reconciling sources

Use this precedence:

1. current user intent and authorization;
2. live `cascadeur-complete` capability/scene state;
3. installed 2026.1.2 API schema, tools, commands, and action IDs;
4. version-matched official manual/release notes;
5. general tutorials or examples.

If a product feature exists in the manual but the MCP says `ui_only`, `license_gated`, `missing_dependency`, `unsupported_version`, or `unhealthy`, return that exact state. Do not promote documented product availability into automated MCP availability.
