# Scene, Object, and I/O Workflows

Use this reference for scene tabs and files, object discovery and hierarchy, selection, CASC lifecycle, and media/3D interchange.

## Establish the scene baseline

1. Call `scene_file(action="list")` to identify tabs when tab identity matters.
2. Call `scene_summary` and retain `scene_id`, `scene_revision`, active layer, frame, selection, and object counts.
3. Use `scene_objects(offset, limit)` until the required hierarchy is covered. Do not assume the first page contains every character or camera.
4. Use `object_read` with the narrow action needed:
   - `hierarchy` for parents/children and types;
   - `properties` for object data;
   - `behaviors` for attached behaviors and optional values.
5. Use `selection_edit(action="get")` for the ordered live selection. For writes, prefer explicit IDs and a pivot ID when ordering matters.

## Scene lifecycle

| Intent | Feature and operation | Handling |
|---|---|---|
| List tabs | `scene_list` / `scene.list` | Direct read |
| Activate tab | `scene_activate` / `scene.activate` | Use tab ID, then refresh scene identity |
| Validate scene | `scene_validate` / `scene.validate` | Direct read |
| New scene | `scene_new` / `scene.new` | Protected prepare/commit |
| Open CASC | `scene_open` / `scene.open` with absolute `path` | Protected prepare/commit; verify loaded path twice |
| Save | `scene_save` / `scene.save` | Use current revision and verify resulting revision/path |
| Save as | `scene_save_as` / `scene.save_as` with `path` | Protected prepare/commit; overwrite needs explicit authorization |
| Close tab | `scene_close` / `scene.close` with exact tab/scene identity | Protected prepare/commit; ensure a replacement scene remains active |

Use `scene_file` for direct reads and ordinary saves. For operations that return `CONFIRMATION_REQUIRED`, call `change_prepare` with the feature/operation pair above, inspect the working scene and backup path, then call `change_commit`. Do not feed an arbitrary token back into `scene_file`.

## Selection and object changes

Use `selection_edit` actions `set`, `add`, `remove`, and `filter` for ordinary selection changes. Filter by type/name only to discover candidates; resolve the result to IDs before an actual edit.

Use `object_write` for:

- `rename`: one exact object ID and new name;
- `create`: explicit kind/name/position/size supported by the adapter;
- `parent` and `unparent`: exact object and parent IDs;
- `duplicate` and `delete`: only when the current feature state provides a verified adapter.

Creation, duplication, parenting changes, and deletion are protected. Prefer `object_delete_prepare` for deletion; if it returns the exact `UI_LOCKED` gate, report that deletion is manual for this adapter rather than calling a guessed action. The 2026.1.2 baseline likewise identifies duplicate through `CopierTool` as UI-only unless live capability data says otherwise.

After hierarchy changes, re-read `object_read(action="hierarchy")`; after property/name changes, re-read properties and search results. Never infer success from selection changes alone.

## Import and export decision table

Always call `feature_describe` for the exact format before choosing a route.

| Format or media | Preferred MCP route | Notes |
|---|---|---|
| CASC | `scene_file` | Native scene open/save lifecycle |
| FBX | `io_transfer` with `import_fbx` or `export_fbx` | Native baseline; protect import/export and verify artifact/scene change |
| DAE/Collada | `io_transfer` with `import_dae` or `export_dae` | Native baseline; useful fallback when FBX parsing/rotation is problematic |
| USD | `scene_exchange_prepare(direction, format="usd", preset, path)` | Exact UI file flow; `preset` is animation/model/scene |
| GLB/GLTF | `scene_exchange_prepare` with the requested format | Exact UI file flow; choose model/animation/scene intent first |
| VRM import | `scene_exchange_prepare(format="vrm")` when available | Import route exists in 2026.1; validate skeleton/material result |
| VRM export | Capability gate | Baseline is `unsupported_version`; do not rename GLB output to VRM |
| Audio | `io_transfer(feature_id="import_audio", ...)` | Confirm timeline/media attachment afterward |
| Reference image/video | Capability search, then exact UI flow if registered | Baseline may be UI-only; do not automate an unknown dialog |
| Still image | See render reference | Rendering/capture is a protected output operation |
| Video | See render reference | 2026.1.2 baseline is UI-only for the safe MCP adapter |

For USD/GLB/GLTF/VRM, the dedicated prepare tool returns a protected file-flow token. Commit it with `change_commit`; do not separately invoke `io_transfer` for the same transfer.

## Import planning

Before importing, record:

- whether the input is a complete scene, model only, animation only, or content for selected objects/frames;
- expected skeleton root, joint names/hierarchy, scale, up/forward axes, and frame range;
- whether the destination scene already contains a rig or character with the same hierarchy;
- which objects/layers should change and which must remain untouched.

Import into a protected working scene. After import, verify object count/hierarchy, expected joints and meshes, animation boundary/keys, root transform/scale, and warnings. For animation-only imports, name and hierarchy mismatch is a common cause of failure; use an explicit selected-object preset only after matching the shared joints.

## Export planning

Before export, establish:

- output format and consuming application;
- selected objects and selected frame interval, if any;
- whether animation, mesh, cameras, or the full scene must be included;
- bake/euler filtering, up axis, namespaces, root object, and model-pose requirements;
- overwrite authorization and exact destination.

Prepare and commit the export, then require a newly created or changed non-empty file. Report path, byte size, and relevant preset. When practical, re-import into a disposable protected scene and compare hierarchy, frame range, and root transforms.

## Full ingest-to-delivery skeleton

1. Protect/open a working scene.
2. Import model or scene and validate hierarchy.
3. Read `rig_state`; rig as needed using the physics/rigging reference.
4. Create animation using the animation reference.
5. Apply physics only after rig/CoM prerequisites pass.
6. Save a recoverable CASC checkpoint.
7. Export with explicit objects/range/options.
8. Validate the output artifact and leave the active scene in a documented state.
