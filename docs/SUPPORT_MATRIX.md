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
