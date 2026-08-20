# Rendering and External Workflows

Use this reference for viewports, cameras, lights, Filament presentation, still/video output, and Unreal/Unity/Blender/Daz/Roblox integration.

## Viewport and camera work

1. Call `viewport_camera(action="viewport_state")` to inventory viewports and the active camera.
2. Use `viewport_camera(action="camera_catalog")` to resolve camera IDs.
3. Create a Camera, aimed Camera rig, Point Light, or Spot Light with `render_object_create_prepare(kind=...)`, then commit its token.
4. Use the camera activation/update actions with explicit camera ID, position, target, and camera type; pass the latest scene revision.
5. Re-read viewport/camera state and affected object transforms.

Use `viewport_mode` to read or set a registered visualizer mode and verify the observed mode. Multiple-viewport layout, grid, composition, materials, and some Filament controls may be UI-only; search/describe the specific feature instead of assuming a generic viewport action can set it.

## Filament presentation

Cascadeur 2026.1 uses Filament for scene visualization and supports lights/material presentation. Treat these as separate state layers:

- camera position, aim, projection/type;
- viewport visualization mode;
- light objects and transforms;
- material/texture properties;
- grid/composition overlays;
- render/output settings.

Create and verify the native objects the MCP supports. For Material, Composition, Grid, or multi-viewport features that are `ui_only`, return the exact route and a manual handoff. Do not claim the final look is configured from a camera or light change alone.

## Still capture and render

Output operations are protected because they create or overwrite files. Use a generic protected operation rather than calling a direct output wrapper after it reports `CONFIRMATION_REQUIRED`.

For a viewport capture:

1. Choose an absolute destination and confirm overwrite intent.
2. Call `change_prepare(feature_id="viewport_capture", operation_name="render.viewport_capture", arguments={"path": ..., "width": ..., "height": ..., "samples": ..., "allow_overwrite": ...})`.
3. Commit the token.
4. Require a stable non-empty image and bridge/host evidence.

For a Filament still image, use the same flow with `feature_id="render_image"` and `operation_name="render.image"`.

Minimum width/height is 16 and samples must be positive. Use dimensions and samples appropriate to the requested deliverable, not the largest values by default. Report output path, dimensions, samples, byte size, and active camera.

## Video output

Describe `render_video` or `export_video` before attempting it. In the verified 2026.1.2 MCP baseline, the safe route is `ui_only` through `RenderToFile`; the native adapter is intentionally not exposed. Return the manual UI route and retain the snapshot. Do not loop, call developer Python, or treat the product's general video support as proof that the MCP can safely automate it.

The official 2026.1.2 notes mention a fix for video export with audio, but live adapter state still wins over documentation.

## General external-workflow rule

Use `external_workflow(feature_id, configuration)` only after `feature_describe`. A successful response may be a dependency/setup description rather than a completed connection. Require evidence from both Cascadeur and the target application before reporting a live integration as working.

External states have exact meanings:

- `missing_dependency`: install/configure the named plugin or target application first;
- `license_gated`: use the required Cascadeur license; do not bypass it;
- `ui_only`: complete the named UI flow manually and re-inspect state;
- `available`/`needs_scene`: run the registered adapter with the required scene and configuration.

## Unreal Engine Live Link

For Cascadeur 2026.1+ Live Link:

1. Confirm Windows, Cascadeur 2026.1+, a paid Indie/Pro/Teams license, Unreal Engine 5.5–5.8, and the Cascadeur Live Link plugin.
2. Prefer a character exported from Unreal or a known compatible Cascadeur sample.
3. Verify identical base-skeleton joint names and hierarchy.
4. Verify root orientation and scale. Cascadeur uses +Z forward/+Y up; Unreal uses +Y forward/+Z up. The documented Cascadeur root local rotation is `-90/0/0`, and scale should be `1/1/1` in both applications.
5. Open the target scenes/apps, enable the registered Live Link flow, and connect the Unreal source.
6. Map Cascadeur root to the intended UE skeleton and stream.
7. Change a known frame/pose and verify it inside Unreal, not merely in Cascadeur.

The Basic baseline returns a license/dependency gate. Report the plugin/license setup steps and any skeleton preparation completed.

## Unreal, Unity, Daz, Roblox, and Blender delivery

Use the registered external feature ID (`unreal_export`, `unity_export`, `daz_export`, `roblox_export`, or `blender_export`) and follow its dependency gate. The MCP does not install third-party plugins or modify another application's project unless the current request separately authorizes that scope.

For file-based interchange:

- **Unreal:** validate root orientation, unit/scale, skeleton names/hierarchy, and the consuming animation asset.
- **Unity:** validate scale, avatar/rig type, root motion, and clip frame range after import.
- **Daz:** preserve the expected skeleton/character workflow and validate joint mapping.
- **Roblox:** validate the target rig convention and exported hierarchy in Roblox Studio.
- **Blender:** prefer FBX in normal cases; binary FBX is recommended. Do not enable Blender's Automatic Bone Orientation because it changes joint rotations. DAE or USD can be fallback formats; GLB/GLTF is not the preferred documented Blender route.

For every DCC delivery, validate the artifact in the target application when that application is in scope. Otherwise report Cascadeur-side export evidence and state that target-side validation remains external.

## Completion evidence

Report camera/light IDs and transforms, viewport mode, render dimensions/samples, output path/size, export preset/options, target DCC/plugin/license state, and target-side observation when available. A local file alone is not evidence of a successful Live Link connection or correct DCC import.
