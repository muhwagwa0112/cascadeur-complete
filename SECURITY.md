# Security policy

## Supported versions

Only the latest published release is eligible for security fixes. The project
is currently pre-1.0 and supports only Cascadeur `2026.1.2.0.15343` on Windows.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open
a public issue for suspected token, queue, arbitrary-code-execution, installer,
or signing vulnerabilities. Include the affected release, reproduction steps,
impact, and whether a scene or local credential was exposed. Maintainers should
acknowledge a complete report within seven days.

Never attach real scenes, tokens, signing material, `%LOCALAPPDATA%` state, or
Codex configuration containing secrets. Use a minimal synthetic fixture.

## Local trust boundary

The queue MAC and per-user ACL prevent other Windows users and accidental file
injection from driving the bridge. They do not sandbox a malicious process that
already runs as the same Windows user. Treat every process in that user session
as part of the local trust boundary and do not run untrusted software alongside
Cascadeur MCP. Confirmation tokens are one-use on both the host and Cascadeur
sides, but their keys remain readable to that same user by design.

## Release trust

Official public binaries are Authenticode-signed and accompanied by SHA-256,
CycloneDX SBOM, and GitHub artifact provenance. Unsigned local builds are for
development only and are not official releases.
