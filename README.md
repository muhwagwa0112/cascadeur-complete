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
- Additional finite adapter: installed build `2026.2.3.0.16863`, explicitly qualified per running process as described below
- Host runtime: bundled Python 3.12 on Windows x64
- Primary client: Codex stdio registration
- License/dependency/UI gates are reported as gates, not successful execution
- Arbitrary developer Python is disabled by the production policy

See [the support matrix](docs/SUPPORT_MATRIX.md) for the evidence rules and
limitations, and [the support status](docs/SUPPORT_STATUS.md) for the per-feature
result of the latest live validation run. The generated feature registry remains the runtime source of
truth; neither tool count nor discovered Python symbols imply support.

### Installed 2026.2 native subset

On `2026.2.3.0.16863`, run the installed command
`Cascadeur Complete.Qualify native adapter` explicitly. It creates disposable
scenes and new checkpoint files, observes SDK callbacks, save completion and clone
equivalence, then restores the previous tab. Qualification is local to the current
runtime epoch and loaded bridge fingerprint; changing bridge bytes requires a
clean application restart and qualification again.

This adapter accepts exactly one independent object with `Basic`, `Node3d` and
`Transform` behaviours, one visible unlocked layer, one existing key at frame 0,
at most 256 frames and no cycles. It supports local position changes at that key,
initial cloning from an already saved matching source, and successor checkpoints.
Initial bootstrap is authorized through the recipe's exact signed grant; ordinary
preparation requires an issued source and an owned checkpoint. Qualification does
not authorize arbitrary scene writes or make a full humanoid recipe executable.

The installed app was directly observed cloning a disposable source, committing
position `[3.25, -1.5, 0.75]`, reading it back, saving a successor checkpoint and
returning the original receipt on duplicate commit. The source file hash remained
unchanged. This observation does not expand the pinned 2026.1 product inventory.

`inspect_motion_inputs` reads native stable IDs, channels, layer/key metadata and
available rig metadata into an authenticated draft. `resolve_motion_inputs`
rechecks that observation before resolving semantic overrides. Missing physical
FPS, units, basis, rest data or ownership remains a blocker; object names and
caller-provided evidence strings cannot establish those facts.

An additional `native-model-assets-v1` reader and explicit scene qualification
path cover model properties/references, data/settings, layers/sections, clusters
and supported embedded mesh assets for checkpoint and evaluation. A shipped
`Cascy.casc` was loaded into a new document lineage, checkpointed and evaluated;
an authenticated capture then read one actual RigInfo-owned joint at frame 0.
This was observed at an earlier bridge fingerprint, not certified for every
subsequent bridge revision. File bootstrap planning now binds the exact `.casc`
bytes and native capability before authorization. FBX input remains gated.

Evaluated captures require the current issued source and durable native
evaluation receipt. Their FPS, length scale and basis are an explicit conversion
policy; they do not establish missing native physical metadata. Authored-key
inspection is separate and optional. Existing keys use layer/frame locators
because the SDK exposes no persistent key ID. No interpolation model or key
insertion route is qualified by those earlier observations.

The additional explicit setup commands are:

- `Cascadeur Complete.Qualify independent motion adapter`: finite LINEAR/STEP
  perturbation and existing position-key writer probes on an owned independent
  Transform. It requires an empty current tab and never enables key insertion.
- `Cascadeur Complete.Qualify complete scene adapter`: shipped-file full reader,
  bootstrap, evaluation and checkpoint in disposable tabs.
- `Cascadeur Complete.Qualify independent scene adapter`: finite LINEAR/STEP
  observations followed by complete-projection file bootstrap, evaluation and
  checkpoint for one parentless Transform, optionally with observed `FbxExport`
  metadata, at most 33 frames and no assets, controllers, cycles or additive
  layers. This separate profile preserves exact save equality; it does not
  qualify the character route when Cascy's first save changes data channels.
- `Cascadeur Complete.Qualify checkpoint restore adapter`: exact new-tab restore
  of the active owned checkpoint. Computed readback differences block it.
  Restoring a real failed request additionally requires its authenticated
  terminal failure, an observed partial-write contract and the signed permit.
- `Cascadeur Complete.Qualify independent export adapter`: two real animated
  selected-object exports with artifact-derived settings and strict FBX readback,
  after complete-scene qualification. It does not establish target motion quality.

Each command registers only after its actual native observations succeed in the
current process. A failed probe leaves that route unavailable. These commands
are included by the source and packaged bridge installers; they are not automatic
startup work. Exact observed results and remaining limitations are in the memo.

Complete-scene qualification is separate from the default independent-transform
command. A later diagnostic with the character scene open caused native memory
growth before its first export artifact; its exact failing SDK call is unknown.
The process was stopped and recovered with an empty scene. The export diagnostic
now rejects a populated current scene before scanning it and records native
call phases. This is not a hard bound on native allocation. Subsequent empty-scene
animated fixtures passed strict FBX structure/settings readback and an actual
Blender import with five sampled frames. The explicit export qualification can
register only the observed independent-object profile; production execution also
requires a durable evaluation receipt. On installed Cascadeur 2026.2.3.0.16863
and Blender 4.5.8, a fresh public recipe completed file bootstrap, evaluation,
native quality, checkpoint, selected export, independent source-rest/intent
roundtrip validation and final publication for one parentless Transform over
frames 0..4. This finite observation does not qualify general rigs or meshes.

The finite independent export route now binds an initially empty selector and
its observed pivot position/rotation, temporarily selects only the approved
profile object, and restores those observations before reporting completion.
The full authored projection must remain identical. A nonempty original
selection is unsupported; the SDK does not expose pivot identity, so hidden
pivot identity restoration is explicitly unobserved. Sealing checks the native
selection lifecycle against the dispatch's authenticated source.

For animated parentless FBX Nulls, the Blender decoder separates the importer's
root frame `G` from the explicit Blender-to-canonical basis `B`, using
`B @ R_blender @ (B @ G).T` for rest and sampled rotations. Static artifact rest
is independently decoded and compared with native source rest. This finite
rule does not change armature/mesh decoding or qualify other transform domains.
Pre-export native quality explicitly defers only the two consumer readback
metrics; final export validation still requires the complete approved policy
and the original motion intent.
The observed roundtrip measured at most `4.9981e-10 m` position error and
`1.6293e-7 rad` rotation error against limits declared before import (`1e-6`
for each). The sealed and published FBX hashes matched. See the memo for the
run identity, preserved blocked attempts and remaining runtime limitations.

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

Recipe declarations now lower to a persisted `StageEffect` containing both the
approved declaration digest and exact native argument digest. An initial signed
bootstrap grant protects a new working clone; later checkpoints each have their
own request and terminal receipt. Imported targets use exact producer receipts
and role paths, then retain an immutable concrete mapping. Resume reconciles the
original request and schedules remaining observation work without replaying it.

**Current runtime limit:** native capabilities are build- and scene-specific.
The narrow independent-transform adapter does not establish humanoid rig,
controller, mesh, retarget, native export settings/completion, or full recipe
support. Preflight lists missing observed adapters. Export preparation, sealing,
consumer validation and journaled publication are connected. Native export is
qualified only for the explicitly observed independent Transform profile;
general character export and end-to-end quality/publication remain gated.

Motion input discovery reads ordered skin inverse-bind assets as native rest
evidence where joint mapping and parent closure are complete. An explicit
`overrides.conversion_policy` may fill missing rational FPS, length scale and
proper coordinate basis without replacing observations or certifying native
physical metadata. Missing ownership, root, rest and joint evidence still blocks
profile resolution. Observed ancestor rest matrices retain native coordinates;
rotation styling converts native local rest into the solver basis once.
Recovery reconciles the original request without replay; native restore requires
its exact successor scope and an authenticated, bounded original failure.
Bootstrap and restore open a fresh owned file copy through the complete project
loader so persisted scene settings survive; a domain-only load resets FPS/units.
This preserves saved metadata without certifying live physical input metadata.
Recipe capture retains its runtime-issued source and evaluation evidence. Cleanup
candidates obtain a new exact write scope from the native reader; host sample
digests are not substituted for the native dependency projection. Resume can
continue checkpoint verification from the original terminal receipt.
Recipe preflight can obtain a separate runtime-issued target observation when
the exact source has no embedded profile/ownership. It rechecks the current
source, actual ownership, declared layer membership, parents and supplied native
bind rest; role names and constraints remain explicit declarations. A private
verifier re-reads that target before accepting it. This observation grants no
write capability and does not establish complete recipe support.

A five-frame independent Transform preservation recipe has now completed the
real host plan/authorization/runner, authenticated bootstrap and evaluation,
global/local source and baseline capture, sampled preservation quality and final
checkpoint. It preserves existing rig/motion, uses an explicit conversion policy
and includes no correction or export. The six required preservation metrics had
zero measured error. This does not establish humanoid cleanup or consumer
roundtrip/publication. Preflight now includes required rotation quality, and
export rejects missing original-intent target dependencies and changed rig/rest
context before accepting roundtrip quality.

See [the r4 known issues memo](docs/KNOWN_ISSUES_2026-11-15.md) for current blockers,
the limits of checks performed, and the next implementation steps.

A separate real five-frame keypose recipe has also completed existing-key
position writes, exact native float32 readback, evaluation, sampled quality and
checkpoint on installed `2026.2.3.0.16863`. The independent scene and motion
qualification commands now reuse their current private model observation so
running both commands preserves the first adapter's qualification. For this
qualified parentless Transform only, recipe target rest can be authenticated
from its stored `Node3d.model_local_*` model pose. This is distinct from skin
inverse binds, current animation, physical metadata and FBX defaults. The
keypose recipe's source capture follows authored motion; its zero preservation
errors do not establish preservation of the input animation or cleanup quality.

For the privately qualified parentless Transform, `inspect_motion_inputs` and
`resolve_motion_inputs` can now construct an observed root profile without raw
rig JSON. They read stored model rest, rotation channels, ownership and the
registered writer's actual closure. Joint axes and limits are inapplicable to
this independent object; general character profiles still require those
observations. FPS, scale and basis remain explicit conversion policy.
The `independent-parentless-position-v1` host retarget controller supports one
root's global positions at existing qualified LINEAR/STEP keys. It authenticates
current native input and exact controller output before protected writing;
mapping, root anchor and scale are explicit declarations. It does not support
character IK, coupled channels, rotation writes or inserted keys.
One real five-frame mapped-position retarget has completed writing, evaluation,
sampled quality and checkpoint on installed `2026.2.3.0.16863`. Its quality source
follows authored retarget motion; this does not establish input preservation,
general character quality or FBX delivery.

`prepare_blender_export_profile(profile)` observes the installed Blender in a
background process and fills absent version, executable/importer byte pins,
adapter fingerprint and settings digest before recipe planning. Supply explicit
axes, units, take, destination, mappings and import options. Existing conflicting
pins are rejected; deliberately remove old pins to prepare a different consumer.
The tool returns `profile` and `profile_digest`; it does not import an artifact,
authorize a recipe or establish roundtrip quality or publication.

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

Close Cascadeur and the installed MCP before upgrading. Source installation
prepares dependencies without copying mutable state, then migrates the final
pre-activation backup before importing the incoming runtime. It preserves
authentication keys, request/receipt/unknown history, consumed recovery claims,
recipe records, snapshots, logs and user policy. Frozen upgrades retain that
state in place; post-install hooks never merge a stale backup into it. Temporary
Windows roots confirmed authenticated history and one-attempt consumption after
copying. A stable sibling `.cascadeur-complete.maintenance.lock` now coordinates
clients using the same runtime root: host/bridge processes retain shared Windows
handles, while source installation and the parent frozen installer hold an
exclusive handle through activation, hooks and rollback. The gate remains valid
when the runtime directory moves; its existence alone never blocks startup.
Verification uses disposable state and the shared source/frozen stdio smoke client.
Windows subprocess checks and a clean restart of the installed Cascadeur build
confirmed handle exclusion; full source/frozen installer replacement has not been
observed. Older clients without the gate still require the process idle scan.

## Build an unsigned local package

```powershell
./scripts/build-release.ps1
```

This creates a PyInstaller onedir application, installer when Inno Setup is
available, SBOM, and SHA-256 manifest under `artifacts/`. Unsigned output is
explicitly marked development-only. Tag releases use OIDC signing and provenance
gates defined in `.github/workflows/release.yml`.
Rebuilding cleans only named build outputs under `artifacts/`; independent
runtime and retained evidence directories such as `artifacts/native-r4/` survive.

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
