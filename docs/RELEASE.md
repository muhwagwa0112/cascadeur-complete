# Release and verification

## Local development build

Run `scripts\build-release.ps1`. It creates an isolated Python 3.12 environment,
installs the exact PyInstaller version in `packaging/requirements-build.txt`,
resolves runtime packages from `uv.lock`, builds an onedir application, executes
an MCP initialize/list/call smoke, and emits an SBOM and SHA-256 manifest.

Unsigned local output is development-only. `-RequireSignature` fails unless every
shipped executable and installer has a valid Authenticode signature.

## Official release gate

Tag releases run on GitHub-hosted Windows and request Azure access using GitHub
OIDC. Repository variables must define `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`, `AZURE_TRUSTED_SIGNING_ACCOUNT`,
`AZURE_TRUSTED_SIGNING_PROFILE`, and `AZURE_TRUSTED_SIGNING_ENDPOINT`.
These are identifiers, not credentials. No certificate or client secret is stored
in GitHub.

The workflow signs application executables before installer compilation, signs
the installer, validates Authenticode, regenerates checksums, and creates GitHub
artifact provenance. A missing OIDC configuration, signing failure, unavailable
Inno compiler, or invalid signature blocks publishing.

## Verify a download

```powershell
$installer = '.\Cascadeur-MCP-0.1.0-windows-x64-setup.exe'
Get-AuthenticodeSignature -LiteralPath $installer | Format-List
Get-FileHash -Algorithm SHA256 -LiteralPath $installer
gh attestation verify $installer --repo muhwagwa0112/cascadeur-complete
```

Require `Status: Valid`, compare the SHA-256 to `SHA256SUMS.json`, and verify the
attestation against this repository. Treat an unsigned artifact as a local build.

The current foundation prepares release artifacts but does not itself provide a
publisher identity or paid Cascadeur/DCC licenses. Those remain external gates.
