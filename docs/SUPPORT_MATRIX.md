# Support matrix policy

The package targets only Cascadeur `2026.1.3.0.15619` on Windows. It is a verified
subset until every official user-facing feature has a dedicated adapter, exact
postcondition, and live evidence on the applicable license/dependency matrix.

Statuses have strict meanings:

- `supported`: adapter and current version-matched live evidence exist.
- `not_implemented`: product feature is inventoried but has no executable adapter.
- `ui_only`: known UI route without a verified automation/postcondition contract.
- `license_gated`: requires a Cascadeur license not present in the test environment.
- `dependency_gated`: requires an external application/plugin not present in the test environment.
- `unhealthy`: adapter is declared but current live evidence is absent or stale.
- `unsupported`: the exact target version does not expose the feature.

Tool availability, Python symbol discovery, a queued request, export-file creation,
or manual instructions do not qualify as support. External DCC routes require
target-side import/connection and animation validation.

The release pipeline may publish gated rows, but it must not label them supported
or claim complete product coverage. Detailed product-feature generation is owned
by the versioned feature manifest in the runtime implementation.

## How evidence is produced

- Every bridge handler declares the postconditions it asserts
  (`@handler(..., postconditions=...)`); the host adds the ones it verifies
  itself (stable output files, scene tabs that stay active after Cascadeur's UI
  settles, owned file dialogs, rendered-window changes for view toggles, playhead
  motion). `tests/test_postcondition_contract.py` fails if any catalog
  postcondition is asserted by neither side.
- Adapter-bound features are declared once in
  `src/cascadeur_complete/adapter_bindings.py`;
  `scripts/sync_adapter_catalog.py` writes them into the product catalog and
  `scripts/render_feature_reference.py` renders the skill reference.
- Live scenarios (`src/cascadeur_complete/live_scenarios*.py`) open pinned
  fixtures from the Cascadeur installation, drive each feature through the
  public prepare/commit contract and record evidence only when every catalog
  postcondition is observed. `scripts/sync_live_catalog.py` binds each
  catalog row to its scenario and fixture; changing either invalidates earlier
  evidence.

## Running live validation

```powershell
uv run python scripts/fetch_live_fixtures.py        # VRM sample (VRM Public License 1.0)
uv run python scripts/live_validate.py --all --skip-verified
uv run python scripts/support_report.py             # writes docs/SUPPORT_STATUS.md
```

The run drives Cascadeur's UI (foreground window, tab switching, file dialogs),
so do not use the machine while it runs. Fixtures are opened read-only; the first
protected change branches the scene into a snapshot working copy.

## Known UI-only rows in 2026.1.3

Filament environment/shadows/dynamic lights/ambient occlusion/bloom, the
Settings window and Scene Linking exist only in Cascadeur's QML UI. The build registers no ActionManager id and no Python API for them, and
Qt's accessibility tree for the main window cannot be enumerated reliably, so
they stay `ui_only` rather than being driven by screen coordinates.

Video export is not UI-only: File > Export > Video opens Cascadeur's own
"Export video" form, which the host fills after verifying its layout, then waits
for the rendered file (`export_video`, `render_video`). The `RenderToFile`
Python route stays unused because it crashes 2026.1.

Blend Shape sliders have a data route: an FBX imported with blend shapes stores
each channel as an animated `<channel>_Weight` datum on a `Blendshape <name>`
Dynamic behaviour (`common/mesh.py`), so `blend_shape` writes those weights on a
frame and reads them back. It has no live evidence yet (see the 2026.1.3 findings).

## Findings on 2026.1.3.0.15619

- **License gate.** Cascadeur itself shows "Feature not available" (Upgrade /
  Sync / Close) for USD and glTF/GLB export under this machine's license, although
  `is_pro_features_available()` reports Pro and the same exports worked under
  Basic on 2026.1.2. The host closes the gate (Close only; Upgrade and Sync are
  account actions left to the user), cancels the unclaimed request and returns
  `LICENSE_GATED`. Imports are validated from Blender-built fixtures instead.
- **Timeline cycles.** `Timeline.Create cycle` leaves Cascadeur's layer
  invariants broken on the sample scenes ("checkCycles: no keys",
  "checkAnimatedSettings"); the scene then cannot be saved and a later edit
  crashes. Every timeline edit (cycle, bake, stretch, interval edit/copy) now
  proves that Cascadeur still saves the scene, and rolls back otherwise, so
  `cycle` is reported as a failed postcondition instead of breaking the scene.
- **Blend shapes.** Importing a blend-shape FBX through the Python FBX loader
  crashed 2026.1.3; `blend_shape` is excluded from `--all` runs
  (`crash_risk`) and stays unverified.
- **Playback.** The playhead is part of the scene revision, so playback toggles
  are bound to the scene identity only (host and bridge both restrict this to
  `timeline.playback`). Opening a scene while playback runs crashed Cascadeur.
- **Crash resilience.** `scripts/live_validate.py` relaunches Cascadeur after a
  crash and marks the scenario that crashed.
- **API document gaps.** `csc.layers.Editor.normalize_sections` takes the domain
  scene and `csc.model.DataViewer.get_all_data_id` takes an object id, although
  `api_document.py` shows neither argument; the shipped scripts are authoritative.
- **Not observable.** `layer_activate` (the timeline selection lists every item),
  `control_picker` (`activate(session, {ObjectId: ObjectId})` has no documented
  mapping), `collision_clean` (the sample poses have nothing to fix) and
  `prototype_com_remove` (no sample has a prototype Center of Mass in Rig Mode)
  have adapters but no live evidence.
