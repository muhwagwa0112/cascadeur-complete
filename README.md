# cascadeur-complete

`cascadeur-complete` is a clean-room MCP server and in-process Cascadeur bridge for
Cascadeur 2026.1.x on Windows. It does not import or depend on Poppet.

The host runs on Python 3.12 over stdio. A Python 3.11-compatible command package
runs inside Cascadeur and drains an atomic Local AppData request queue on the UI
thread. Every capability is represented in a generated registry as a native API,
known action, UI Automation flow, external integration, or an explicit gate.

Destructive changes use `change_prepare` / `change_commit`, scene revision checks,
and CASC snapshots. Developer Python execution is disabled unless explicitly
enabled in the runtime policy file.

## Verified baseline

- Installed executable: `2026.1.2.0.15343` with the `2026.1` adapter
- Embedded bridge: Python 3.11; host: Python 3.12
- Live inventory: 372 symbols, 223 classes, 42 functions, 1,344 callable/property
  members, and 118 enum/value members (1,462 total class members)
- Runtime GUI tools: 56; bundled Python commands: 104
- Generated feature rows: over 2,100, each with an execution mode, verification state, and test ID

Discovery is not treated as implementation. A product feature is reported as
`available` only after its versioned adapter has produced live evidence on the
installed Cascadeur version. Inventoried features without a dedicated adapter are
reported as `unhealthy`; absent integrations are `missing_dependency`; and
unverified action-only paths are `ui_only`.

The current dedicated native adapters cover health/inventory, scene summaries and
objects, scene new/open/save, FBX import/export, verified timeline positioning,
selection read/set/add/remove/filter, object hierarchy/properties/behaviors/create/
duplicate/rename/parenting, current-frame local/global transform reads and verified
position/rotation/local-scale writes, structured graph interpolation/tangents,
layer/folder editing, camera state/editing, protected Filament still/video rendering,
AutoPosing session calls, postcondition-checked AutoPhysics snap (which requires a
working AutoPhysics state), typed settings/log reads,
snapshots/rollback, and persistent cancelable/retryable background jobs. The
complete feature matrix remains the source of truth for routes that still require
a dedicated adapter and real-scene evidence.

## Safety model

`change_prepare` validates local paths, rejects UNC/device paths, creates a CASC
snapshot, and binds an HMAC confirmation token to scene identity, revision, and
selection. Cascadeur 2026.1 exposes save-as but no non-mutating live-scene
serialization, so the saved snapshot becomes a copy-on-write working scene; the
original file is left untouched. `change_commit` revalidates the token, and scene
open/rollback only succeed after two stable path/revision observations.

UI Automation is isolated behind a bounded daemon trigger. Failed or timed-out
triggers cancel unclaimed queue files so a request cannot execute during a later,
unrelated invocation. A request already claimed by Cascadeur is reported as
`UI_LOCKED` with an unknown outcome unless a response is recovered.

## Development

```powershell
uv sync --extra dev
uv run pytest
uv run cascadeur-complete-inventory
```

## Runtime locations

- Host: `%LOCALAPPDATA%\CascadeurMCP\cascadeur-complete`
- Bridge: `%LOCALAPPDATA%\Nekki Limited\Cascadeur\user_scripts\cascadeur_complete`
- Queue and snapshots: `%LOCALAPPDATA%\CascadeurMCP\cascadeur-complete\state`

Install or refresh with `scripts\install.ps1`, then restart Cascadeur. The command
must appear at `Commands > Cascadeur Complete > Process Pending`. Validate the
host, registration, feature manifest, and Poppet preservation with
`scripts\verify.ps1`.
