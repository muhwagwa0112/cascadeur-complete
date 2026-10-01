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

`motion_cleanup_analyze` samples every frame of the active character and reports
foot skating (cm/frame), slides, drags and finger spread/spikes.
`motion_cleanup_prepare` turns one whole-clip solve into a single protected key
write (commit it with `change_commit`):

- `foot_contacts`: one quadratic program over all frames finds a whole-body offset
  and per-foot offsets that stop planted feet sliding while keeping each leg within
  its original reach; leftover one-foot drags become short steps.
- `fingers`: soft-limits knuckle spread/twist and removes spikes while keeping curl.
- `finger_fan`: rotates each index knuckle about the palm normal so a claw-like
  index–middle splay settles near a natural gap (3° by default).

- `arm_clearance`: measures on the skinned mesh where each arm is inside the rest of
  the body (every frame) and solves elbow and wrist offsets that lift it out while
  keeping bone lengths; `mesh_sample` exposes the skinned mesh to the host.

- `wrist_soften`, `hand_pose`, `hand_rest`: styling passes for clips where the capture
  misread the hands (gloves, mittens, props) — soft wrist limits, coordinated finger
  poses between a relaxed hand and a loose fist (or one fixed shape), and hands that
  hover near the hips brought into contact.

On a 986-frame clip this took mean foot skating from 0.98 to 0.34 cm/frame with no
remaining slides or drags. The [`cascadeur-mocap-cleanup`](skills/cascadeur-mocap-cleanup/SKILL.md)
skill documents the full pipeline (key reduction, splines, AutoPhysics, fingers,
feet, arms, styling against a reference video) and the pitfalls behind it; its
`scripts/mesh_preview.py` renders contact sheets from a `mesh_sample` file.

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
