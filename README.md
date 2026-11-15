# Cascadeur MCP

<p align="center">
  <strong>If Cascadeur MCP saves you time, consider supporting its continued development, testing, and maintenance.</strong>
</p>

<p align="center">
  <a href="https://ko-fi.com/muhwagwa0112">
    <img src="docs/assets/kofi-support-red.png"
         alt="Support Muhwagwa0112 on Ko-fi"
         width="420">
  </a>
</p>

`cascadeur-complete` is the compatibility package name for a clean-room MCP
server and in-process bridge targeting Cascadeur `2026.1.3.0.15619` on Windows.
The project is pre-1.0 and provides a **verified subset** of Cascadeur automation;
it does not claim that every user-facing Cascadeur feature is implemented.

The host uses MCP over stdio. A Python 3.11-compatible command package runs in
Cascadeur and drains the Local AppData request queue on the UI thread. A hidden
message-only window with a Win32 timer on that thread (the UI-thread pump)
claims requests as they arrive, so Cascadeur is never brought to the foreground
and nothing is clicked; the host posts a wake-up message and waits for the claim
while the pump's heartbeat in `state/pump.json` is fresh. When the pump is stale,
disabled (`state/pump.disabled`), or cannot claim a request (another scene tab,
a modal dialog), the host falls back to invoking `Process Pending` through UI
Automation. The bridge yields to Cascadeur's event loop after rendering, file
dialogs, scene loads and view toggles. Capability
discovery is not counted as feature support: a feature is supported only when a
dedicated adapter, exact postcondition, and version-matched live evidence exist.

## Support status

- Exact application baseline: Cascadeur `2026.1.3.0.15619`
- Host runtime: bundled Python 3.12 on Windows x64
- Primary client: Codex stdio registration
- License/dependency/UI gates are reported as gates, not successful execution
- Arbitrary developer Python is disabled by the production policy

See [the support matrix](docs/SUPPORT_MATRIX.md) for the evidence rules and
limitations, and [the support status](docs/SUPPORT_STATUS.md) for the per-feature
result of the latest live validation run. The generated feature registry remains the runtime source of
truth; neither tool count nor discovered Python symbols imply support.

## Mocap cleanup

Production preparation requires an explicit stable-ID rig profile, rational FPS,
length scale, coordinate basis, original motion intent, and a complete source
binding issued by the loaded bridge. Finger repair uses quaternion rotations;
contact repair measures the declared support motion and preserves its contact
schedule. Styling requires explicit styling intent. Missing rotation, geometry,
controller, key interpolation, or authored dependency access blocks the affected
pass instead of selecting a guessed rig or reporting predicted quality as actual.

The bridge protocol is `3.0`. Scene revision checks, single-use change tokens,
durable request receipts, and a verified native guard apply to protected changes,
including evaluation refresh. Install matching host and bridge bytes and restart
Cascadeur after changing bridge code; an old process cannot certify new code.

## Finite recipes

| Tool | Behavior |
|---|---|
| `recipe_plan(spec)` | Read-only preflight and immutable plan with exact scope, budgets, native blockers, and host/loaded-bridge fingerprints. |
| `recipe_authorize(plan_id, plan_digest, scope_digest, expires_at)` | Issue an expiring grant for that displayed plan. Blocked plans cannot receive a grant. |
| `recipe_start(plan_id, authorization_id, idempotency_key)` | Allocate one persisted run per grant. Repeating the same key returns the original run. |
| `recipe_status(run_id, after_seq)` | Read persisted state without advancing native work. |
| `recipe_cancel(run_id)` | Persist cancellation; an already dispatched native request still needs its terminal receipt. |
| `recipe_resume(run_id, authorization_id)` | Reconcile the original request and checkpoint. It never replays an unknown or completed mutation. |
| `recipe_artifacts(run_id)` | List content-hashed captures, receipts, quality, and checkpoint artifacts. |

Recipes accept a strict declarative schema, not arbitrary operations or Python.
Required acceptance metrics come from the rig, original intent, contacts and
declared geometry as well as the caller's policy; a policy that omits a mandatory
metric is blocked. Missing observations cannot become a pass through a narrower
metric list.
Native execution outcome, measured quality, checkpoint state, and publication are
separate. `ok=true` requires a completed run with passing actual quality and, when
requested, a validated and published export. An unknown outcome remains blocked;
cancellation preserves both the intent and any already observed native result.

**Current runtime limit:** this checkout does not install a verified no-yield
native guard, authored dependency/identity reader, checkpoint adapter, or native
export settings/completion adapter for the pinned Cascadeur SDK. Preflight reports
these missing capabilities and blocks live recipes. Host math and durable
orchestration do not establish live Cascadeur or FBX delivery support. Export
utilities independently stage, seal, inspect, import-validate, and publish bytes;
native export remains gated until the matching adapters are verified.

See [the r3 known issues memo](docs/KNOWN_ISSUES_2026-11-15.md) for current blockers,
the limits of checks performed, and the next implementation steps.

See [the cleanup workflow](docs/MOCAP_CLEANUP_WORKFLOW.md) for intent and evidence
requirements. Its earlier production example is historical context, not evidence
that this guarded runtime supports every listed stage.

## Install an official release

1. Download the signed installer, SHA-256 manifest, SBOM, and provenance from the
   same GitHub release.
2. Verify the installer signature and checksum as described in
   [release verification](docs/RELEASE.md).
3. Run the per-user installer. It installs the isolated host and Cascadeur bridge,
   updates Cascadeur's user command registration and Python path, and registers
   the MCP with Codex when the `codex` command is available.
4. Restart Cascadeur. The UI-thread pump starts with it; `ui_pump.active` in
   `cascadeur_status` confirms it.
5. Run `scripts\verify-install.ps1` or the installed Start Menu verification link.

The installer does not require Python, `uv`, or Poppet. Poppet is neither modified
nor required.

## Development

```powershell
uv sync --extra dev
uv run pytest
./scripts/install.ps1
./scripts/verify.ps1
```

The source install script is for contributors. Public releases use the signed
Inno Setup installer and bundled runtime.

## Build an unsigned local package

```powershell
./scripts/build-release.ps1
```

This creates a PyInstaller onedir application, installer when Inno Setup is
available, SBOM, and SHA-256 manifest under `artifacts/`. Unsigned output is
explicitly marked development-only. Tag releases use OIDC signing and provenance
gates defined in `.github/workflows/release.yml`.

## Runtime locations

- Host: `%LOCALAPPDATA%\CascadeurMCP\cascadeur-complete`
- Bridge: `%LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete`
- Queue/snapshots: `%LOCALAPPDATA%\CascadeurMCP\cascadeur-complete\state`
- Pump heartbeat: `state\pump.json` (create `state\pump.disabled` to turn the pump off)
- Backups: `%LOCALAPPDATA%\CascadeurMCP\backups`

## Security and license

Report vulnerabilities using [SECURITY.md](SECURITY.md). The project is available
under the [MIT License](LICENSE); bundled dependencies retain their own licenses as
described in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
