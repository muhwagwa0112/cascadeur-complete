# Support matrix policy

The package targets only Cascadeur `2026.1.2.0.15343` on Windows. It is a verified
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

## Known UI-only rows in 2026.1.2

Filament environment/shadows/dynamic lights/ambient occlusion/bloom, the
Settings window, Scene Linking and Blend Shape sliders exist only in Cascadeur's
QML UI. The build registers no ActionManager id and no Python API for them, and
Qt's accessibility tree for the main window cannot be enumerated reliably, so
they stay `ui_only` rather than being driven by screen coordinates.
