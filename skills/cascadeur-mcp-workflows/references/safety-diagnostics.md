# Safety, Diagnostics, and Recovery

Use this reference whenever a request mutates a scene/file, spans a long operation, hits a gate/error, or requires a low-level route.

## Capability state is the first branch

| State | Meaning and response |
|---|---|
| `available` | Adapter can run without a scene; still satisfy arguments and authorization. |
| `needs_scene` | Open/activate a compatible scene, refresh, then satisfy selection/rig/layer prerequisites. |
| `ui_only` | Product feature exists but no postcondition-safe MCP adapter exists. Return exact route and manual handoff. |
| `license_gated` | Required license is absent. State license requirement; never bypass it. |
| `missing_dependency` | External app/plugin/configuration is absent. Return setup requirements. |
| `unsupported_version` | Installed version has no verified adapter. Do not apply another version's route. |
| `unhealthy` | Capability was discovered but adapter/evidence is insufficient. Diagnose or implement; do not invoke blindly. |

Call `feature_describe` immediately before a risky feature. Capability states can change with scene, license, installed version, dependencies, or new live evidence.

## Common result envelope

Every execution result should be interpreted through:

- `ok` and `error_code`;
- `feature_id` and `execution_mode`;
- `scene_id` and `scene_revision`;
- `result`;
- `warnings`;
- `changed_entities`;
- `snapshot_id` and `job_id`;
- `evidence`;
- `duration_ms`.

Do not discard warnings or use a stale revision from the request. For a mutation, absence of expected changed entities or postcondition evidence is a reason to re-read state before continuing.

## Protected change contract

Use a dedicated `*_prepare` tool when available. For other protected operations:

1. Call `change_prepare(feature_id, operation_name, arguments, ttl_seconds)`.
2. Confirm the response contains the exact operation, targets/destination, impact, working scene, immutable backup, snapshot ID, scene/revision, selection fingerprint, and expiry.
3. Commit only that token with `change_commit` while scene, revision, and selection still match.
4. Verify the operation-specific postcondition.

If the user has clearly authorized the exact mutation, do not ask again merely because the protocol uses two calls. If the prepare result reveals a materially different target, overwrite, object set, or scope, stop and obtain the missing authority.

Use `change_cancel` for an unused token. Tokens expire and are one-use; never retry a consumed token.

The snapshot operation opens a writable working clone. That scene can have a different scene ID and path. Refresh and use the post-snapshot identity; never force the original ID/revision into the commit.

## Rollback

Use `change_rollback(snapshot_id, expected_revision?)` when:

- a protected operation returns failure and automatic restoration did not finish;
- postconditions fail or the result is materially wrong;
- the user asks to undo the whole protected stage;
- continued work would compound an uncertain outcome.

Rollback opens a new `.working.casc` clone of the immutable snapshot. Verify loaded path, scene ID/revision, representative objects/layers, and snapshot hash/metadata when important. Do not delete the immutable snapshot as part of rollback.

Use `undo`/`redo` only for a known single-step history operation and pass the latest revision. Use rollback for scene/file operations, multi-step protected stages, or uncertain history.

## Jobs

Use `job_submit` only for a registered non-destructive operation that benefits from persistence. Then:

1. retain `job_id`;
2. poll `job_status` at reasonable intervals;
3. call `job_cancel` when the requested outcome is no longer needed or a prerequisite changed;
4. use `job_retry` only for a failed/canceled job after correcting the cause.

Do not retry unchanged failures indefinitely. A job result is completed only when the retained result envelope and operation postconditions pass.

## Error handling

| Error | Next action |
|---|---|
| `CASCADEUR_NOT_RUNNING` | Check process/registration; start Cascadeur only when allowed, then refresh. |
| `SCENE_CHANGED` | Re-read scene, selection, IDs, and revision; prepare a new plan/token. |
| `LICENSE_GATED` | Report required license and preserve prepared scene work. |
| `DEPENDENCY_MISSING` | Report named external dependency and setup/verification steps. |
| `UI_LOCKED` | Inspect for modal dialog or UI-only route; do not spam retries. |
| `TIMEOUT` | Check logs/request claim and postconditions before deciding whether retry is safe. |
| `POSTCONDITION_FAILED` | Re-read state; rollback protected work when the expected result is absent. |
| `UNSUPPORTED_VERSION` | Refresh inventory and implement/use the correct version adapter; do not force baseline actions. |
| `CONFIRMATION_REQUIRED` | Use dedicated prepare or `change_prepare`/`change_commit`; do not invent a token. |
| `INVALID_REQUEST` | Correct IDs, units, arguments, path, revision, or operation name before retrying. |

When a timeout or UI lock could have an unknown outcome, first check scene revision, output file signature, logs, and request/job state. Retrying a claimed mutation can duplicate it.

## Diagnostics

- `cascadeur_status(refresh=true)`: health, version, license, scene, feature-state counts.
- `cascadeur_logs(lines, pattern)`: bounded log evidence; filter narrowly and avoid exposing unrelated paths/data.
- Runtime tool introspection and arbitrary setting reads are not exposed in production builds; both are explicit `unsupported` safety-policy entries in the product manifest.
- `feature_search`/`feature_describe`: route and gate source of truth.
- `inventory_refresh`: use after Cascadeur/version/scripts change; it rebuilds the installed schema/registry.

Do not run inventory refresh in the middle of a protected commit or while the UI is in a modal file flow.

## Low-level route escalation

Use this order:

1. task-focused MCP tool;
2. registered dedicated `*_prepare` + commit;
3. exact registered `action_invoke` with an observable change/postcondition;
4. `tool_call` on a runtime-registered tool and explicit public chain;
5. `csc_query` for allowlisted reads;
6. protected `csc_mutate` only when the final installed method is registered and scene revision matches;
7. `developer_execute_python` only for explicit development/debugging with policy enabled.

Before `action_invoke`, use `feature_describe` and the official action ID; the action API is being deprecated and an invented label is not a valid ID. Require `expect_change=true` or an explicit postcondition.

Before `tool_call`, inspect the tool and use only public attributes. Set `mutate=true` only through a protected change contract.

For `csc_query`/`csc_mutate`, use typed JSON arguments, no dunder/private traversal, and the shortest chain. A schema entry proves discoverability, not semantic correctness; re-read the actual changed state.

## Final safety check

Before declaring success, confirm:

- active scene/path and final revision;
- expected object/layer/key/rig/physics result;
- no unknown or still-running jobs;
- output file exists and is non-empty when applicable;
- external target was validated or clearly left as an external gate;
- snapshot/rollback status is reported;
- user scene was not silently replaced by a sample or validation scene.
