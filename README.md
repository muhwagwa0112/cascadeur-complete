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

Host-only `feature_search` and `feature_describe` remain available without a
connected native adapter; this does not count as observed native execution.
Recipe export validation preserves explicit failures as terminal failures.
An unverified consumer result blocks publication and can be observed again only
on explicit resume, using the same sealed inputs and the original read-retry
budget. Retained consumer/export JSON reads enforce file-byte budgets and
descriptor consistency before parsing; these are not whole-process memory caps.
Quality policies must include `non_target_scope_rad` when the original capture
contains protected rotation channels, and `key_pose_rotation_rad` for observed
rotation locks or frames outside the editable interval. Recipes check these
observed obligations at baseline capture before solving or writing. Missing
thresholds or actual channels block the workflow.

See [the support matrix](docs/SUPPORT_MATRIX.md) for the evidence rules and
limitations, and [the support status](docs/SUPPORT_STATUS.md) for the per-feature
result of the latest live validation run. The generated feature registry remains the runtime source of
truth; neither tool count nor discovered Python symbols imply support.

### Installed 2026.2 native subset

On `2026.2.3.0.16863`, qualification now requires the finite, separately approved
`setup_prepare` / `setup_commit` flow described below. A direct menu invocation
without that admitted context is refused. Qualification creates owned scenes and
new checkpoint files, observes SDK callbacks, save completion and clone
equivalence, then restores the previous tab. All created tabs and files are
retained on success and failure. Qualification is local to the current
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

### R6 recovery and owned-pair continuation

The complete [R6 proposal](docs/implementation/cascadeur-motion-r6/IMPLEMENTATION_PLAN.md)
is retained at remote revision `d31bdf3210f83fea2964a05d185d9bc976ef04ca`.
Its historical `product_applied` fields describe the proposal, not current code.
R6 adds these concrete entry points:

- `manual_setup_prepare(steps, workspace)` drafts a bounded fixture setup with
  the exact two legacy incidents still unknown/open. The local interactive
  `incident_cli approve-manual-setup --plan-digest ...` command reviews its
  residual risks; `manual_setup_commit(plan_digest)` submits only that approved
  request and observes an existing request without replay.
  For an explicitly requested local test after another unknown, the CLI draft
  accepts repeated `--review-open-incident UUID` arguments. Name every current
  open incident: schema 2 binds the complete authenticated originals, heads,
  helper bytes and fresh workspace to the reviewed plan. A missing or newly
  added incident invalidates it at approval, dispatch and every effect. Omitting
  the option preserves the original exact-two restriction. This is reviewed
  local risk acceptance, not Hyper-V isolation or historical completion.
- `pair_continuation_prepare(setup_plan_digest, context, mutation)` requires an
  actual succeeded, retained owned-pair setup. The local interactive
  `incident_cli approve-pair-continuation --plan-digest ...` command reviews the
  full sequence; `pair_continuation_commit(plan_digest)` runs its fixed 10 or 12
  steps and stops on pending, unknown or failure. Unit, basis and rational FPS
  in `context` are explicit conversion policy, not SDK-observed metadata.
- `incident_producer_observation(request_id)` reads prospective signed host
  dispatch, actual process claim, first-effect boundary and original terminal
  archive. These are **partial observations**, not proof of complete producer,
  descendant, consumer or resource closure. They cannot repair old unknowns.

The owned-pair helper now uses the versioned
`owned_two_identity_bind_dense_translation_joint_meshes_v5` profile: two self-bound
meshes whose Joint behaviours reference their own Transform matrices and whose
bind shapes are exact identity matrices at every owned frame,
three dense keys at frames 0/1/2, and exact STEP sections. Cascadeur normalizes
adjacent keys to STEP; requiring LINEAR on that grid made the first actual setup
fail. Authoring, whole-position prediction and continuation all require the new
profile. This does not qualify sparse LINEAR or fractional-frame interpolation.
The failed requests remain `outcome_unknown` with their actual fixtures and
readback preserved. The exact-two-legacy route refuses another setup while
additional incidents are open; the explicit complete-open-set CLI route above
supports the user-requested local test. On installed Cascadeur 2026.2.3.0.16863,
the v5 setup completed its ten mesh calculations, perturbation, two evaluations
and two graph captures and retained both scene files. This qualifies only the
owned two-mesh, three-frame profile; general rigs remain unsupported.
After adding same-callback `SceneUpdater.run_update` to the position writer,
the 12-step continuation also completed: activation, position mutation,
evaluation, motion sampling, six actual mesh calculations, geometry manifest
readback and return to the original tab. FPS, unit and basis conversion remain
explicit fixture policy. Unbaking and the complete recipe/FBX consumer path
remain unqualified.
The owned-pair setup also executes the immutable-P0 roundtrip using
the same save and restore primitives as native checkpoint dispatch: checkpoint
save, working save, one actual project-copy load and restored save. Its reviewed
plan declares at most two new tabs, five `.casc` files and seven Update captures.
All four phases compare directly with the original P0 and re-observe typed graph
facts; unclassified fields remain exact. The loaded clone retains its own
observed identity and only inherits lineage after comparisons succeed. This
does not issue a rollback permit. A fresh-runtime local run on installed
2026.2.3.0.16863 completed all four phases with exact P0 equality, retained
both new tabs and all five files, and restored the original active tab.
The actual Windows/native path-separator mismatch found in the first run was
fixed without weakening projection or path identity checks. Earlier unknown
requests remain open; this finite observation does not qualify general rigs
or failure-triggered recovery.
The same loaded runtime then completed the 12-step position/motion/geometry
continuation and returned to the original tab; reload qualification did not
break the finite adapter's live continuation.
See the [current issue memo](docs/KNOWN_ISSUES_2026-11-15.md) for continuation
results and remaining limits.

Observing an authenticated terminal through `BridgeClient.reconcile_request`
also resumes an interrupted prospective archive from its exact retained prefix.
This uses existing signed records and original receipt bytes, including after a
host restart; it creates no producer claim and replays no native operation.
Archive tampering or I/O failure appears as `PRODUCER_ARCHIVE_UNAVAILABLE` in
the returned warnings while the independently authenticated native outcome stays
unchanged. Receipt authentication failures still reject the observation.

The source and frozen installer replace code in place while preserving the
physical runtime/state/snapshots/logs directories and authenticated state. Code
rollback and the transaction's own ownership/DACL changes are bounded separately.
This is not permission to replace a live bridge or close application tabs.

Owned-pair native code now includes an installed Update graph/type extractor,
same-callback source checks, full projection checks and immutable-P0 checkpoint
comparison. Snapshot issuance also requires an explicit `True` native
`modify_update` return; callback completion alone is insufficient. It must
qualify in a fresh loaded runtime; source code and SDK
declarations alone do not establish native success. Unbaking remains gated:
the selected installed action sources do not establish the three exact action
bindings, their arguments and operation-correlated completion.

Use `python scripts/collect_native_evidence.py --help` for bounded, non-executing
collection of explicitly selected installed SDK declarations and Python action
sources. It does not import the SDK or run the app. Current evidence gaps and
the original incident history are recorded in [the issue memo](docs/KNOWN_ISSUES_2026-11-15.md).

### R5 incident admission and finite setup

The [R5 source proposal](docs/implementation/cascadeur-motion-r5/IMPLEMENTATION_PLAN.md)
is retained unchanged as design input. Current implementation and remaining live
evidence gaps are recorded in [the issue memo](docs/KNOWN_ISSUES_2026-11-15.md).
New host and bridge bytes must be installed together; an older bridge cannot
admit new work through this host. Existing request IDs remain observation-only.

Incident admission covers every explicitly enrolled original authentication/store
domain. It preserves original keys, outboxes, receipts and unresolved history.
The canonical Local AppData store is mandatory; selecting a new runtime root does
not discard an enrolled incident. Enroll all known original stores once with the
source environment's Python, for example:

```powershell
.\.venv\Scripts\python.exe -m cascadeur_complete.incident_cli enroll --store "$env:LOCALAPPDATA\CascadeurMCP\cascadeur-complete" --store "D:\CS_MCP\artifacts\native-r4\isolated-runtime"
.\.venv\Scripts\python.exe -m cascadeur_complete.incident_cli inspect
```

`incident_inspect` is host-only. `incident_diagnostic` is the initial native
handshake and reads only bridge/epoch/admission metadata; it does not read a scene
or issue a source. `incident_observe_original` asks the exact original producer
for private completion evidence. Pass that diagnostic request ID to
`incident_observe` with the exact original reference and expected incident head.
Missing, revoked or lost original evidence leaves the incident open.

`incident_retirement_prepare` describes exact producer/process/resource operations
only when independently verified scope, pre-incident baseline and physical
separation are available. Missing evidence returns a non-executable draft.
Preparing a plan never approves or executes it. A ready plan requires the
operator's separate exact approval before `incident_retirement_commit`; retirement
preserves the original unknown outcome and still requires new-workspace lineage.
The currently retained legacy incidents lack the required producer closure.
After a durable start, retrying the same approved plan only observes its retained
OS attempt or revalidates its signed component result. It cannot dispatch another
termination after host loss. Expiry still rejects a plan that never started;
missing original attempt/result evidence leaves an already started plan pending.

When all enrolled incidents permit new work, `setup_prepare` accepts only these
finite helper IDs: `setup.qualify_native_adapter`,
`setup.qualify_independent_models`,
`setup.qualify_independent_position_writer`, and
`setup.qualify_geometry_calculation`. Models must precede the writer in
the approved sequence. The plan binds current epoch/full bridge bytes, all domain
heads, a fresh direct child of the runtime `snapshots` directory, and per-step
tab/file limits. Physical plan/step directory identities and the original tab's
projection are rechecked at effect and fixture callback boundaries. The geometry
prerequisite is bounded to one retained cube tab, two `.casc` files, five geometry
calculations, two evaluations and one driver mutation. Its observed coordinate
convention and sequential returns qualify only that owned fixture; they do not
enable production geometry capture. After reviewing and
separately approving that exact plan, the operator can issue its local token:

```powershell
.\.venv\Scripts\python.exe -m cascadeur_complete.incident_cli approve-setup --plan-digest <reviewed-plan-digest> --output <new-approval-json-path>
```

Supply that JSON to `setup_commit`; the plan ID is its single-use request ID.
Use `approve-retirement` instead only for a separately reviewed, executable
retirement plan. These local commands are approval issuers, not automatic setup
or recovery steps. The current legacy incidents block setup admission.

`verify-install.ps1 -InstallationProfile independent-2026.2` checks the exact
installed `2026.2.3.0.16863` profile separately from the default
`catalog-2026.1` / `2026.1.3.0.15619` profile. Disk/registration/stdio checks do
not qualify native operations or a running epoch.

Geometry capture is a file effect with explicit approved mesh/frame/byte budgets,
terminal-bound manifests and guarded NPZ reads. Actual coordinate, synchronization
and dependency calibration is still unqualified, so its native contract stays
closed. The older raw mesh sampler also requires file-effect admission.
Checkpoint schema v2 compares every serialization phase to one immutable P0
anchor and preserves actual restored raw projections; no numeric tolerance policy
is qualified. All three unbaking steps remain gated before preparation and native
selection until their exact lowering/completion contracts are qualified.

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
- `Cascadeur Complete.Qualify key insertion adapter`: explicit absent-frame
  position-key insertion observation on retained independent Transform tabs.
  First run the finite-model qualification in the same process and select an
  empty tab. On installed `2026.2.3.0.16863`, four LINEAR/STEP schedules inserted
  frames 2 and 6 among original keys 0, 4 and 8, preserving old sections, empty
  tracks and non-target data across full-projection readback and separate
  interpolation, including unkeyed frames 1, 3, 5 and 7. Each small `.casc` and
  tab remains available; failures are retained too. The private single-use
  source binds the scene, full projection, build, epoch and loaded fingerprint;
  unknown completion cannot be retried. Successful explicit qualification now
  registers `motion.key_topology_insert` for `position_keys_insert_prepare`
  followed by `change_commit`. Capture its exact operation source first; supply
  object/layer IDs, `additions=[{frame,position,mode}]`, explicit
  `allow_key_insertion=true` and `max_added_keys` (1–8). Positions are **local
  native scene units**. The route requires a native-owned working checkpoint
  with unchanged backup bytes. Every adjacent key in the resulting grid must
  remain at least two frames apart: the installed SDK rewrote section modes
  when a one-frame interval was introduced. Full native projection equality,
  one-use authorization and successor capture remain mandatory; explicit
  interpolation is a separate operation. Honest layer/frame locators do not
  become persistent native key GUIDs. Recipe topology authorization remains
  gated by actual native capability; standalone registration does not open it.
  `position_keys_insertion_plan` reads a private prediction from an exact
  runtime-issued evaluated key layout and explicit `KeyAddition` rows. It
  preserves the original capture/source and uses the executor's full-projection
  prediction. It grants no mutation authority. After a separately authorized
  insertion and explicit evaluation/capture, `position_keys_topology_verify`
  requires that exact private plan, original successful durable terminal receipt,
  unchanged checkpoint and full actual projection/driver. Unknown completion,
  a new process or changed package bytes cannot create completion evidence.
  These evidence routes are implemented but have not been observed in the app;
  fresh-process qualification is required after this native package change.
  The actual one-frame commit remains `outcome_unknown`; the existing global
  unresolved-effect barrier blocks further host source capture. Public success,
  successor and evaluation receipts for the two-frame route are not yet observed.
  The host cleanup path now falls back from insufficient existing-key fitting
  to explicitly budgeted sparse refinement for one independent local position
  driver. The solver keeps original keys fixed by default; the cleanup fallback
  explicitly enables a joint fit of eligible old and new values. It retains the original evaluated capture,
  exact topology delta and full prediction, converts solver metres to native
  float32 scene units, then rechecks the entire influence interval. Recipes
  predeclare separate insertion, evaluation and topology/readback stages; the
  insertion consumes its generated-key allocation once. A joint fit inserts
  neutral samples of the actual original curve first. Only the same cleanup's
  original successful receipt and authenticated topology/readback permit the
  separate `refinement_correction` planner to bind its retained final values to
  the existing-key writer. Intermediate integrity and final quality are separate:
  final readback must match the full retained curve and the original intent's
  complete quality policy. Protected rotations are actually captured in both
  spaces; missing channels are not filled in. General rigs, retarget
  refinement and unbaking completion remain outside its qualified scope. The
  new host integration has not been executed as a native recipe.
  Native unbaking plans now require explicit `motion.unbaking_limits` for
  maximum added, removed and written keys; insertion/interpolation flags come
  only from the original intent. Unbaking reserves its maximum added/written
  cost before prepare in the request-identity CAS and shares the original
  generated-key allowance with cleanup. The public
  `animation_unbaking_prepare` tool requires the same five-field
  `topology_policy`. Native projection comparison rejects visible scope,
  label, interpolation and key-budget violations, counting unique layer/frame
  effects conservatively. A post-dispatch snapshot remains an unverified
  completion observation; it never enables the three opaque action adapters.
  Installed SDK stubs expose no typed synchronous executor for all three
  steps. Native recipe execution and fresh loaded-byte qualification remain
  unobserved for this change.
  Opt-in plans must explicitly budget the numerical fit-iteration ceiling
  across three axes, all bounded refinement attempts and at most one stabilizing
  refit per grid; the default run
  budget is not expanded automatically. Solver memory limits are narrowed to
  the approved run ceiling before computation.
- `Cascadeur Complete.Qualify complete scene adapter`: shipped-file full reader,
  bootstrap, evaluation and checkpoint in disposable tabs.
- `Cascadeur Complete.Qualify independent scene adapter`: finite LINEAR/STEP
  observations followed by complete-projection file bootstrap, evaluation and
  checkpoint for one parentless Transform, optionally with observed `FbxExport`
  metadata, at most 33 frames and no assets, controllers, cycles or additive
  layers. This separate profile preserves exact save equality; it does not
  qualify the character route when Cascy's first save changes data channels.
  Qualification tabs/files remain open on success and failure, with retained
  IDs and paths returned; the original active tab and inventory are preserved.
  Native tab lifecycle crashes remain unresolved.
- `Cascadeur Complete.Qualify checkpoint restore adapter`: exact new-tab restore
  of the active owned checkpoint. It returns a pending qualification ID and
  retains the restored tab; a later source-idle callback verifies both scenes
  and the tab inventory before registering the adapter. Query
  `qualification_status(id)` for its in-process result. Repeating the command
  on the same source/checkpoint returns that observation without restoring
  again. Computed readback differences block it. It never closes the restored
  tab automatically; native tab lifecycle crashes remain under investigation.
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

The raw `animation.mesh_sample` reader uses the installed SDK entry
`csc.domain.calc_skinned_mesh` and accepts its declared `(vertices, 3, 1)`
position vectors as well as the existing flat-vector representation. The NPZ
layout and skin-weight metadata remain compatible. This reader does not
certify coordinate space, evaluation freshness or reskin completion. Its file
hash and vertex count cannot supply the authenticated canonical geometry
manifest required by actual mesh quality; that integration remains blocked
until those native observations are available.

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
An actual readback failure ends the run as failed. Resume also checks retained
failure artifacts from older runs before continuing or publishing.
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
confirmed handle exclusion. Actual source installation and subsequent native
metadata admission were observed on 2026-11-16; full frozen installer replacement
has not been observed. Older clients without the gate still require the process idle scan.
Source installation now also cleans staging after dependency/fingerprint/smoke
failure and restores `CASCADEUR_MCP_ROOT` if the staged smoke raises an exception.
Installation verification compares every installed bridge Python file with the
host's exact `bridge-package.json` map and fingerprint, reports missing, changed
and unexpected files, and checks Cascadeur's command/event import path. These
disk checks do not establish the bytes already loaded in a running app or grant
native capabilities. After backing up all ten open tabs and normally closing
Cascadeur, source installation populated the canonical runtime and user-script
bridge, including `bridge-package.json`, dependencies, Python path, Commands and
Events. Staged/final stdio smoke exposed 127 tools. Codex registration was
deliberately skipped. The installed build is `2026.2.3.0.16863`; the default
verifier's catalog baseline remains `2026.1.3.0.15619` (use the explicit
`independent-2026.2` profile for installation checks on this build).
IncidentStore now obtains full Win32 volume/file IDs through `FILE_ID_INFO` in
both host Python 3.12 and embedded Python 3.11, preserving the existing signed
store identity. Installer hooks retain Cascadeur's vendor `commands`/`events`
defaults when making omitted settings explicit, and repair the earlier
installer-owned event-only list. Actual vendor script-server dispatch resumed
after this fix. Installation and metadata connectivity do not qualify the
remaining native recipe or close unknown outcomes.
Native restore/cleanup and exit probes encountered `Qt6Core.dll` access
violations and an interpolator `bad allocation` fatal exit. The qualifier now
retains its restored tab and verifies it on a later source idle; that bounded
path completed on the installed build. Native tab and exit stability remain
unresolved; this is not a general crash fix or full-build qualification.
See [the issue memo](docs/KNOWN_ISSUES_2026-11-15.md) for the observation limits.

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
