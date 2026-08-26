# Cascadeur MCP

`cascadeur-complete` is the compatibility package name for a clean-room MCP
server and in-process bridge targeting Cascadeur `2026.1.2.0.15343` on Windows.
The project is pre-1.0 and provides a **verified subset** of Cascadeur automation;
it does not claim that every user-facing Cascadeur feature is implemented.

The host uses MCP over stdio. A Python 3.11-compatible command package runs in
Cascadeur and drains the Local AppData request queue on the UI thread. Capability
discovery is not counted as feature support: a feature is supported only when a
dedicated adapter, exact postcondition, and version-matched live evidence exist.

## Support status

- Exact application baseline: Cascadeur `2026.1.2.0.15343`
- Host runtime: bundled Python 3.12 on Windows x64
- Primary client: Codex stdio registration
- License/dependency/UI gates are reported as gates, not successful execution
- Arbitrary developer Python is disabled by the production policy

See [the support matrix](docs/SUPPORT_MATRIX.md) for the current evidence rules
and limitations. The generated feature registry remains the runtime source of
truth; neither tool count nor discovered Python symbols imply support.

## Install an official release

1. Download the signed installer, SHA-256 manifest, SBOM, and provenance from the
   same GitHub release.
2. Verify the installer signature and checksum as described in
   [release verification](docs/RELEASE.md).
3. Run the per-user installer. It installs the isolated host and Cascadeur bridge,
   updates Cascadeur's user command registration, and registers the MCP with Codex
   when the `codex` command is available.
4. Restart Cascadeur and invoke
   `Commands > Cascadeur Complete > Process Pending` once if event-driven draining
   is not active.
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
- Backups: `%LOCALAPPDATA%\CascadeurMCP\backups`

## Security and license

Report vulnerabilities using [SECURITY.md](SECURITY.md). The project is available
under the [MIT License](LICENSE); bundled dependencies retain their own licenses as
described in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
