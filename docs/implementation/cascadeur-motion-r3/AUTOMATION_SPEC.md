# Cascadeur 자동화 구현 명세

기준: main `82b350cad4deda2ff5df288f46764a899115252d`, PR #8 `1bb447898e8ced16b6931b72cfeb0f563127f746`. 이 문서는 구현 설계다. 실제 코드 수정·프로그램 실행·테스트·설치·commit/push를 수행하지 않았다. 설계상 완료 조건은 전체 단계 누락 0, 완료 mutation의 자동 재실행 0, 승인 범위 이탈 0, 취소/실패/미확정 상태의 정확한 구분, 긴 클립 전체 범위 처리, 기존 공개 기능의 호환이다. 실제 기기에서의 품질 통과는 별도 결과다.

## 1. 코드에서 확인한 출발점

| 근거 | 현재 동작 | 변경이 필요한 이유 |
|---|---|---|
| `src/cascadeur_complete/service.py:submit_job`, `jobs.py` | `job_submit`은 모든 mutation을 거부한다. `update/cancel`의 get→modify→save 전체가 하나의 잠금 안에 있지 않고 worker 예외 경계가 없다. | mutation background 허용으로 우회하지 않는다. 기존 job을 고치고 recipe 실행기는 별도 계약으로 만든다. |
| `models.py:JobRecord` | queued/running/succeeded/failed/canceled 다섯 상태, `owner_pid`, operation/arguments 저장 | 기존 상태 이름을 바꾸지 않고 additive 필드만 추가한다. recipe에는 별도의 상태 모델을 쓴다. |
| `safety.py:ChangeManager`, PR8 `change_flow.py` | exact operation/scene/revision/selection을 HMAC 토큰으로 묶고 단회 소비한다. prepare 중 snapshot과 working document 생성·활성화가 일어난다. | 계획 생성은 읽기 전용이어야 하며, 실행 단계의 prepare 자체도 side effect로 추적해야 한다. 토큰 소비를 생략하지 않는다. |
| `bridge_client.py` | timeout 뒤 queue에서 제거했는지, 이미 claim됐는지 구별하지만 후자는 일반 실패 envelope로 반환한다. | claimed outcome unknown을 mutation 실패로 간주해 rollback/retry하면 중복 적용/충돌이 생긴다. |
| PR8 `cleanup_workflow.py:_read` | main의 raw client 호출 대신 gated service.batch를 사용한다. scene_id는 비교하지만 변경 중 revision/content를 묶지 않는다. | PR8 개선을 보존하고 SourceBinding 기반 읽기 epoch를 추가한다. |
| `cleanup_workflow.py:sample` | bridge 요청 25개씩 읽으나 클립 전체 배열을 미리 zero-fill한다. | transport 분할과 memory 분할은 다르다. missing sample을 0으로 취급하면 안 된다. |
| `handlers/generation.py` | Root Motion/Inbetweening은 선택 layer/interval/keyframes/RigInfo를 검사하고 action을 호출한다. retargeting은 source/target point와 frame interval을 받는다. | text-to-motion, arbitrary skeleton autorig, headless Cascadeur API가 있다고 가정하지 않는다. |
| `runtime.py:io.export_fbx` | `FbxSceneLoader.export_all_objects`를 호출한다. | target character만 내보냈다고 주장할 수 없다. export scope 격리가 필요하다. |
| `external.py`와 PR8 `host_postconditions.py` | Blender import 후 armature/action 존재 확인 | 잘못된 캐릭터·take·fps·root motion·부분 클립도 통과할 수 있다. |
| `skills/cascadeur-mocap-cleanup/scripts/fbx_check.py` | binary FBX 구조의 일부를 집계하고 항상 legacy KTIME를 사용한다. | 보고 도구와 승인 가능한 validator를 구분하고 format/timebase/connection 검증을 구현한다. |

코드 근거의 `파일:심볼`은 구현자가 좁혀 읽을 위치다. 새 SDK 이름을 확인된 API처럼 제시하지 않는다. 이하 새 함수는 프로젝트가 구현할 Python 인터페이스이지 기존 Cascadeur API 이름이 아니다.

## 2. 책임 경계와 공용 모델

`recipe_runner.py`는 host에서 다음 step을 결정하는 supervisor다. CPU solve·분석·파일 parse는 host worker에서 실행할 수 있다. Cascadeur API 호출, scene 평가, selection, snapshot, key write, native action, scene save는 모두 기존 UI thread pump에서 직렬 실행한다. recipe와 단건 도구도 같은 runtime lease를 통과한다. host worker가 `csc` 객체나 app의 Python handle을 보유하지 않는다.

operation 이름만으로 read-only를 판정하지 않는다. 공용 `classify_effect(operation_name, normalized_arguments) -> EffectClass`를 execute/batch/job_submit/runner 모두 사용한다. `animation.transform_get(refresh=False)`는 확인된 무부작용 reader이고 `refresh=True`는 evaluation effect다. 기존 `job_submit`은 evaluation effect도 거부하며, unknown reconcile은 이름이 read인 경로로 evaluation을 우회할 수 없다.

공용 타입은 안정성 명세와 동일하게 사용한다.

```python
SceneBinding(
    schema_version: int,
    runtime_epoch: str,
    scene_instance_id: str,
    document_lineage_id: str,
    revision_kind: Literal["scope_digest"],
    scope_digest: str,
    content_revision: str,
    selection_digest: str | None,
)
SourceBinding(
    schema_version: int,
    binding: SceneBinding,
    scope: CaptureScope,
    sample_digest: str,
    inputs_digest: str,
    adapter_fingerprint: str,
    complete: bool,
)
RequestReceipt(
    schema_version: int,
    request_id: str,
    request_digest: str,
    session_id: str,
    runtime_epoch: str,
    host_instance_id: str,
    lease_epoch: int | None,
    run_id: str | None,
    step_id: str | None,
    attempt_id: str | None,
    operation_digest: str,
    phase: str,
    outcome: str,
    dispatched: bool | None,
    scene_before: SceneBinding | None,
    scene_after: SceneBinding | None,
    effect_class: Literal["none", "evaluation", "scene", "file", "mixed"],
    mutation_observed: bool | None,
    write_phase: Literal["not_started", "started", "completed", "unknown"],
    failure_kind: str | None,
    recovery: RecoveryGuard | None,
    terminal_result: ResultEnvelope | None,
    result_digest: str | None,
    seq: int,
    mac: str,
)
```

- `content_revision`은 playhead/선택/UI 표시 revision과 구별한다. scope 밖의 scene mutation이 중요한 단계에서는 scope-only hash를 전체 scene guard처럼 쓰지 않는다.
- `document_lineage_id`는 확인된 snapshot→working clone→checkpoint 연쇄를 뜻한다. 동일 파일 경로나 scene name을 동일 인스턴스 증명으로 쓰지 않는다.
- `scope_digest`는 canonical scope descriptor hash이며 `content_revision`은 `scope_digest`와 그 범위의 실제 authored object/layer/key/curve/rig dependency 값·metadata를 함께 hash한 값이다. `SourceBinding.sample_digest`는 평가된 sample bytes의 별 hash다. 서로 다른 projection의 두 hash를 동일 값으로 비교하지 않는다. descriptor 또는 요청 인자 hash를 actual content 검증으로 쓰지 않는다. 위 표기는 필드 연계 설명이며 실제 canonical 모델은 `STABILITY_SPEC.md`의 단일 정의를 import한다.
- receipt의 `terminal_result`는 runtime dispatch와 runtime postcondition의 불변 결과다. host quality/target import/checkpoint 결과는 `StepRecord`에 따로 남긴다.
- runtime이 receipt의 claimed 이후 단독 writer다. host outbox/cancel intent와 runtime receipt를 여러 프로세스가 같은 JSON에 덮어쓰지 않는다.
- lease는 다른 host의 충돌을 막는다. 사용자의 GUI 편집까지 막는다고 가정하지 않는다. 매 dispatch와 postcondition/recovery 시 실제 binding을 다시 확인한다.

## 3. 공개 API와 하위 호환

새 공개 도구는 아래 계약으로 추가한다. 모든 payload는 Pydantic 모델로 `extra="forbid"`, finite 숫자, strict frame integer, positive timeout을 검사하고 canonical JSON hash를 계산한다. dtype/object pickle나 사용자 Python 코드를 입력 형식으로 받지 않는다.

```python
recipe_plan(spec: RecipeSpec) -> PlanResult
recipe_authorize(plan_id: str, plan_digest: str, scope_digest: str,
                 expires_at: float) -> AuthorizationResult
recipe_start(plan_id: str, authorization_id: str,
             idempotency_key: str) -> RunHandle
recipe_status(run_id: str, after_seq: int | None = None) -> RecipeRunView
recipe_cancel(run_id: str) -> RecipeRunView
recipe_resume(run_id: str, authorization_id: str | None = None) -> RecipeRunView
recipe_artifacts(run_id: str) -> ArtifactIndex
```

`recipe_plan`은 읽기 전용 preflight와 구체적 계획 생성만 수행한다. snapshot/selection/edit/export를 하지 않는다. `PlanResult`에는 승인에 필요한 입력 hash, 캐릭터, 프레임, side effects, write bounds, 생성/교정 의도, 목적지, overwrite 방식, 최대 실행 횟수, 실행 불가능한 capability가 모두 보인다. 지원되지 않는 mandatory stage가 있으면 `status="blocked"`이며 authorize/start는 거부한다.

`recipe_authorize`는 사용자 또는 상위 호출자가 이미 승인한 정확한 계획을 persisted capability로 만드는 행위다. authorization을 모델의 추측이나 `auto_approve=True`로 생성하지 않는다. 한 번 승인된 범위 안의 내부 단계마다 사용자 승인을 반복해서 요청하지 않는다. plan 내용·대상·경로·budget이 바뀌면 새 plan_digest가 필요하다. authorization lifetime만 연장하려는 경우에도 명시적 승인 증거를 새 authorization record로 연결한다.

`recipe_start`의 idempotency key는 `(authorization_id, idempotency_key)` unique이며 같은 hash의 재호출은 기존 run만 반환한다. 다른 plan_digest를 같은 key로 보내면 거부한다. 한 authorization은 기본 한 run에만 배정한다. 같은 recipe를 다시 실행하려면 새 실행 grant가 필요하다.

기존 API 정책:

- `job_submit/status/cancel/retry`, `cascadeur://jobs/{id}` 응답과 다섯 status literal은 유지한다. job은 계속 read-only이며 recipe run_id를 job_id로 위장하지 않는다.
- `change_prepare/commit/cancel/rollback*`, `feature_prepare/read`, `motion_cleanup_*`, native generation 준비 도구는 기존 인자를 유지한다. 내부 구현을 공용 service에 위임하고 direct tools가 자동 commit하도록 바꾸지 않는다.
- PR8에서 없어지는 기존 mutation convenience 이름은 같은 signature의 migration alias를 제공한다. alias는 `ok=False`, 기존 `error_code="CONFIRMATION_REQUIRED"`, `status="needs_prepare"`, `result.error_details.code="NEEDS_PREPARE"`, `replacement_tool`, exact `replacement_arguments`만 돌려준다. migration alias는 write/selection/snapshot 0건이며 실제 prepare도 호출하지 않는다. read-only alias는 기존 read 동작을 유지한다.
- `blender_export`의 과거 armature/action 존재 postcondition은 기존 호출을 위해 유지 가능하나 `verified_export`의 strict 성공으로 승격하지 않는다. 새 recipe는 strict profile validator를 필수로 호출한다.
- protocol 3의 session/receipt/v3 token 경로와 protocol 2는 같은 session에 섞지 않는다. handshake version 불일치 시 mutation은 `error_code="UNSUPPORTED_VERSION"`, `result.error_details.code="PROTOCOL_MISMATCH"`; v2 token을 v3 receipt로 재해석하거나 무검증 downgrade하지 않는다. 새 detail code 때문에 기존 ErrorCode enum을 바꾸지 않는다. 공개 Python/MCP parameter 호환과 wire protocol 호환은 별개다. 기존 pending v2 작업은 기록을 보존하고 별도 legacy session의 기존 정책으로 조회/종료하며 v3에서 재실행하지 않는다.

## 4. Recipe 입력과 immutable plan

```python
RecipeSpec(
    schema_version=1,
    input: InputSpec,
    character: CharacterSpec,
    clip: ClipSpec,
    rig: RigStageSpec,
    motion: MotionStageSpec,
    intent: IntentConstraints,
    references: ReferenceInputs,
    cleanup: tuple[CleanupPassSpec, ...],
    quality: QualityPolicy,
    export: ExportProfile | None,
    budgets: RunBudgets,
)
```

| 모델 | 필수 값과 의미 |
|---|---|
| `InputSpec` | `kind=active_scene|casc_file|fbx_file`; absolute local path일 때 bytes SHA256; active scene은 SceneBinding; import `mode=new_working_scene|merge_into_working`; 원본 파일의 변경은 허용하지 않는다. |
| `CharacterSpec` | stable root/object/layer ID 집합 또는 source asset의 canonical skeleton path mapping; semantic `RigProfile` hash; required/optional mesh IDs; source/target 구별. 여러 동일 이름을 임의 첫 항목으로 선택하지 않는다. |
| `ClipSpec` | inclusive `[first_frame,last_frame]`, rational `fps_num/fps_den`, time origin, axis basis, metres-per-scene-unit; `segments`는 분석 label로만 쓰며 requested clip 범위를 몰래 줄이지 않는다. |
| `RigStageSpec` | `mode=existing|template|explicit_mapping`; template file hash 또는 joint-role mapping; generated controller kinds/target lineage; 기존 지원 binding만 사용. arbitrary mesh auto-rig는 verified adapter 없으면 blocked. |
| `MotionStageSpec` | `mode=existing|retarget|keyposes|native_root_motion|native_inbetweening|external_motion_asset`; mode별 discriminated model, 명시적 trajectory/keypose 또는 source clip; retarget은 `route=native|host` 필수. unstructured text는 설명 metadata일 뿐 native API 입력이 아니다. |
| `IntentConstraints` | 품질 명세의 canonical 타입을 필수 전달한다. 접촉 schedule, root/keypose/timing/prop/role locks, key insertion/interpolation 변경 허용, correction envelope를 여기에 둔다. 각 cleanup pass의 intent가 이 상위 허가와 모순되면 거부한다. |
| `ReferenceInputs` | `support_tracks: tuple[ArtifactRef, ...]`, `geometry: tuple[ArtifactRef, ...]`, `prop_tracks: tuple[ArtifactRef, ...]`; 각 artifact는 content SHA256/schema/shape/time-grid/unit/basis를 가진다. `intent.contacts[*].support_id`가 정확한 SupportTrack을 참조하고 ContactSegment/provenance 및 trace hash를 plan과 SourceBinding.inputs_digest에 묶는다. |
| `CleanupPassSpec` | exact kind, numeric units, joint set, relative effect bounds, `intent=preserve_motion|stylize_hands|add_wrist_accent`; hand_pose/hand_rest/wrist_accent처럼 의도 변경은 preserve_motion에서 묵시적으로 활성화하지 않는다. |
| `QualityPolicy` | `QUALITY_SPEC.md`의 canonical 타입: profile id/revision, calibration_status, required_metrics, limits_si, coverage, collision_semantics, permitted_contact_allowances, required_export_roundtrip. 별 중복 schema를 만들지 않는다. 미확인 metric을 pass 처리하지 않는다. |
| `RunBudgets` | total wall seconds, bridge request 수, read retry 수, solve iterations, `max_correction_passes`, generated/written key 수, memory/disk bytes, output bytes, per-step deadlines. 모두 finite이고 plan summary에 실제 값이 보인다. 후보 variant 목록과 순서는 StepPermit에만 둔다. |

동작 범위는 다음 StepPermit으로 계획에 박제한다.

```python
StepPermit(
    step_id: str,
    feature_id: str,
    operation_name: str,
    effect: Literal["read", "host_compute", "evaluation", "scene_mutation", "file_stage", "publish"],
    intent: str,
    target: ExactTarget | DerivedTargetRef,
    frame_ranges: tuple[FrameRange, ...],
    allowed_channels: tuple[str, ...],
    fixed_parameters_digest: str,
    candidate_variants: tuple[VariantEnvelope, ...],
    max_effect_from_baseline: EffectBounds,
    max_calls: int,
    prerequisite_step_ids: tuple[str, ...],
    required_postconditions: tuple[str, ...],
)
```

`DerivedTargetRef`는 이전 import/rig 생성 receipt의 `created_ids` 또는 validated role map에서만 해석한다. arbitrary string template, current selection wildcard, 모든 future object를 허용하는 root wildcard는 없다. source asset hash/topology/expected roles가 허가 범위를 결정하고 관측 결과가 달라지면 blocked다. 각 성공 step의 관측 successor binding만 다음 단계의 source가 된다.

calibration profile 선택, 어떤 detector/threshold/provenance로 접촉 schedule을 승인할지, 허용된 key insertion/bake/interpolation 변경은 최초 plan의 concrete 범위에 포함해 한 번 승인할 수 있다. 범위 안의 detector 결과와 bounded candidate마다 승인 절차를 반복하지 않는다. 실제로 서로 다른 모션 의미를 구별할 정보가 없는 경우는 `needs_input`이며 자동으로 planted/free 중 편리한 값을 고르지 않는다.

`max_effect_from_baseline`은 매 correction 직전 값이 아니라 승인된 원본 capture 대비 누적 변위를 검사한다. 작은 correction을 여러 번 쌓아 총 bound를 벗어나는 경우를 막는다. root trajectory, joint angle, position displacement, added key count, allowed controller activation state, output path도 각각 scope에 포함한다.

`WorkflowPlan`에는 순환 없는 DAG 및 모든 conditional branch의 최대 횟수가 포함된다. skip 가능한 stage는 `not_required` 이유와 satisfied precondition을 남기고 stage 자체를 생략하지 않는다. solve variant를 바꾸는 분기는 승인된 variant 목록만 순서대로 사용하며 exhaustion은 실패다. threshold를 낮추거나 실패 metric을 optional로 바꿔 성공시키지 않는다.

## 5. 전체 단계와 구체적 수행 계약

| stage | 파라미터/입력 | 구현 호출 경계 | 완료 근거·실패 처리 |
|---|---|---|---|
| preflight | file hashes, binding, rig profile, clip, budgets | read-only capability/version/license/paths checks | 모든 필수 adapter와 범위를 해결. 누락이면 scene 변경 전 blocked. |
| input | exact source hash, import mode | approved working clone/open/import의 prepare→commit | expected file/lineage/object graph, timeline span 확인. source 바뀌면 stale. |
| rig | target roles/template | 기존 `rig.*` binding에 대한 exact steps | target character의 RigInfo/Point/Box/Joint 관계 검증. scene 전체 RigInfo count만으로 통과 금지. |
| keyposes/trajectory | explicit poses, frames, space, interpolation, trajectory root | typed write plan→prepare/commit; layer/selection도 각각 scope에 포함 | exact pose와 trajectory readback, intended interval coverage. 새 key 추가는 승인 범위에 포함. |
| retarget | source/target rig, explicit mapping, interval, `route=native|host` | native는 기존 `generation.retargeting`; host는 신규 `retargeting.py:retarget_pose/controller_targets/world_to_local` 후 공용 exact write 경로 | source/target 독립성, target-space constraints와 전체 interval readback. verified controller adapter가 없으면 blocked. 자동 native↔host fallback 금지. |
| native generation | target layers, interval, keyposes/trajectory | existing `generation.root_motion/inbetweening` action; UI-thread serial | action receipt와 observable completion의 구별. 변경 revision만으로 generation/quality 완료를 판정하지 않는다. |
| evaluation refresh | source binding, target frame/layer scope | journaled protected evaluation refresh | 기존 `animation.transform_get(refresh=True)`는 내부 modify_update를 실행하므로 순수 read로 취급하지 않는다. unknown 요청이 있으면 금지. |
| baseline capture | complete SourceBinding, MotionContext/RigProfile | streaming read epochs via gated batch, `refresh=False` | 범위 전체 finite values+valid mask+content binding; mixed scene/revision이면 capture 전체 폐기. |
| analyze | complete capture, required metrics | pure host analysis | per-metric eligibility, semantic intent/locks, units 기록. unsupported required metric이면 blocked. |
| solve | immutable capture, global key grid, bounded variants | pure host worker | `no_change|candidate|failed|unsupported|cancelled`; candidate는 실제 품질 합격이 아니다. |
| prepare correction | exact write artifact digest, source/permit | scoped auth 검증→기존 snapshot/working clone→v3 exact token mint | snapshot 결과 및 source 재검증. prepare effect도 receipt로 추적. |
| apply correction | exact prepared token/chunk hash | 기존 single-use consume→UI dispatch | authoritative receipt와 written scope readback. partial이면 correction 미완료; known-safe recovery만 가능. |
| settle/readback | predicted effect scope, all clip frames | 별도 UI requests, pipeline lock와 content guards | derived solver가 뒤늦게 덮은 결과까지 capture. unknown ongoing action이면 downstream 금지. |
| quality | source+actual post capture | pure host `QualityReport` | 모든 required measured gates pass, no missing coverage, no forbidden regressions. bounded approved repair 또는 실패. |
| checkpoint | verified continuation binding | 기존 save/snapshot primitive를 감싼 신규 protected handler | unique checkpoint file hash+source binding+receipt. 완료 mutation 재실행 없이 재개하는 근거. |
| export preflight | quality report, ExportProfile | target closure, exporter/target adapter capability | profile 설정을 실제 제어/관측할 수 있어야 진행. 모델명을 입력했다고 export_all_objects가 selection export가 되지 않는다. |
| export stage | exact target export scene, staging path | protected native export | runtime terminal, output stable/closed 관측, sealed candidate hash. final path 쓰기 금지. |
| structure validate | sealed candidate hash/profile | host FBX parser | target/take/time/axis/unit/channel graph checks. unknown format은 unsupported. |
| target validate | exact target app version/import settings + expected animation capture | isolated target import adapter | target skeleton/bind pose + all required frames의 motion equivalence. |
| publish | validated artifact hash/final path/overwrite mode | exact scoped local atomic file publish | publish receipt+actual final hash. unknown export/quality fail이면 publish 금지. |

의존성 순서는 recipe mode에 맞춰 고정한다. 예: external motion import→source rig→retarget→target generation(optional)→cleanup. `keyposes` mode는 target rig→key writes→native generation이다. 어떤 mode든 baseline/actual quality/export gate는 동일하다.

host retarget의 함수 계약은 `retarget_pose(source_batch, source_rig, target_rig, mapping, supports, intent) -> SolverResult`, `controller_targets(target_joint_goal, target_rig, planned_parent_transforms) -> CorrectionPlan`, `world_to_local(world_goal, planned_parent_transform) -> LocalTarget`다. math/target constraints는 QUALITY_SPEC의 canonical retarget 알고리즘을 따른다. 원본 source bone의 세계 좌표를 다른 비율의 target bone에 그대로 강제하지 않으며, 완성된 target-space actual capture가 export comparison baseline이 된다.

현재 native inbetweening handler의 nearest-key-gap ≤120 검사는 preflight에 반영한다. 긴 interval을 임의로 잘라 의미 없는 중간 pose를 만들어 통과시키지 않는다. keypose density가 부족하면 승인된 keypose/trajectory 생성 variant가 있어야 한다. license gate, missing native action, modal UI를 지원하지 않는 상태는 명확히 blocked한다. native 기능의 headless API 존재는 가정하지 않으며, Cascadeur UI runtime이 필요하다는 것을 실행 조건에 표시한다.

## 6. 승인 → prepare → commit의 실제 알고리즘

```python
validate_step_authorization(
    grant: ScopedAuthorization,
    plan: WorkflowPlan,
    step: StepPermit,
    source: SourceBinding,
    operation: Operation,
    effect: MeasuredEffectEnvelope,
    usage: BudgetUsage,
) -> AuthorizedStep

prepare_authorized_step(
    authorized: AuthorizedStep,
    correction: CorrectionPlan | None,
) -> PreparedStep

commit_authorized_step(prepared: PreparedStep) -> CommitHandle
```

`AuthorizedStep`는 host 내부 타입이며 wire에서 임의 생성할 수 없다. validation은 grant signature/plan_digest/run binding/expiry/revocation, scene lineage, target identity, operation whitelist/fixed arguments, input/source/write blob hash, cumulative effect, call count와 budget을 한꺼번에 검사한다. `reserve(step_id, attempt_id)`와 budget debit는 store의 atomic CAS에서 수행한다. 실패한 claim을 다른 worker가 재사용하지 않는다.

exact token은 이 검증 뒤에도 필요하다. v3 token HMAC에는 기존 모든 안전 필드에 더해 미리 배정한 request_id, operation_digest, SourceBinding/correction digest, run_id/step_id/attempt_id/lease_epoch를 묶는다. snapshot 뒤 source가 달라지지 않았음을 검증하고 snapshot lineage의 exact working binding으로 mint한다. commit은 기존 single-use 소비 및 UI-thread scene/revision/selection 재확인을 거친다. runner가 `client.execute(...destructive=True)`로 우회하는 경로를 만들지 않는다.

자동 내부 준비/commit은 허가된 step에 대해 사용자 상호작용 없이 실행할 수 있다. 다음은 새 승인이 필요하므로 blocked 상태로 멈춘다: 새 캐릭터/파일/외부 destination, 새 operation/intent, 승인된 key/효과/range/budget 초과, overwrite 범위 확대, expired/revoked authorization, unsupported action을 arbitrary script/UI 탐색으로 대체하려는 경우. 단순 polling, continuation checkpoint, 이미 승인된 variant, known-safe rollback은 처음 계획에 포함된 범위 안에서 반복 승인하지 않는다.

token TTL이 끝났을 때 이미 dispatch한 token을 다시 mint하지 않는다. `not_dispatched`가 receipt/outbox로 확정되고 source/authorization/remaining budget이 여전히 유효한 경우에만 미실행 단계의 새 exact token을 준비한다. snapshot/prepare가 이미 완료되었으면 그 receipt와 working binding을 재사용하며 snapshot을 중복 생성하지 않는다.

## 7. 유한 상태 실행기와 저장소

```python
RunState = Literal[
    "planned", "authorized", "queued", "running", "cancel_requested",
    "blocked", "succeeded", "failed", "canceled",
]
StepState = Literal[
    "pending", "ready", "preparing", "prepared", "dispatching", "awaiting_result",
    "verifying", "checkpointing", "succeeded", "no_change", "skipped",
    "failed", "canceled", "blocked",
]
ExecutionOutcome = Literal[
    "not_dispatched", "canceled_pre_dispatch", "rejected_pre_dispatch",
    "succeeded", "failed_after_dispatch", "outcome_unknown",
]

RecipeRunRecord(
    schema_version=1, run_id, plan_digest, authorization_id,
    owner_host_instance_id, lease_epoch, seq,
    state, blocked_reason, cancel_requested, deadline,
    current_step_id, current_binding, budgets_used,
    steps: tuple[StepRecord, ...],
    artifacts: tuple[ArtifactRef, ...],
)

StepRecord(
    step_id, state, attempt_id, execution_outcome, request_id,
    request_digest, token_ref, source_binding, expected_successor,
    receipt_ref, verification_status, verification_report_ref,
    checkpoint_ref, correction_id, artifact_refs, error,
)
```

주요 전이:

| 전이 | 조건 |
|---|---|
| planned→authorized→queued | immutable plan+exact grant, start idempotency claim 성공 |
| queued→running | lease와 input binding, 미완료 prerequisite 확인 |
| pending→ready | prerequisite 모두 succeeded/no_change 또는 명시적 not_required skip |
| ready→preparing→prepared | source와 effect grant 검증, snapshot receipt 확인, exact token 저장 |
| prepared→dispatching→awaiting_result | dispatch intent persisted, one request identity로 submit |
| awaiting_result→verifying | authoritative runtime terminal receipt |
| verifying→checkpointing→succeeded | host postconditions/actual quality가 해당 stage 기준 통과, continuation checkpoint 확인 |
| running→cancel_requested | durable cancel intent; 새 step 진입/dispatch 금지 |
| *→blocked | outcome unknown, lost binding, unavailable capability, expired grant, missing checkpoint 등 안전한 진행 조건 부재 |
| *→failed | 알려진 operation/quality/resource failure, 허용 retry/variant exhaustion, 실패 상태·recovery 결과 저장 완료 |
| cancel_requested→canceled | in-flight outcome이 해소되고 추가 mutation이 없거나 허가된 복원이 완료됨 |
| running→succeeded | required stages 모두 완료, publish가 요청됐으면 final hash+publish receipt까지 확인 |

`outcome_unknown`은 succeeded/failed/canceled 중 하나로 강제 변환하지 않는다. run은 blocked이고 `cancel_requested=true`를 함께 유지할 수 있다. 늦게 들어온 authoritative result가 unknown을 해소할 때 receipt 결과와 run 취소 의도를 각각 반영한다. terminal run record는 임의로 덮지 않는다. late evidence는 append-only evidence 항목으로 남기고 별도 recovery decision에서만 해석한다.

```python
class RecipeRunStore:
    def create(self, plan, grant, idempotency_key) -> RecipeRunRecord: ...
    def compare_and_update(self, run_id, *, expected_seq, lease_epoch,
                           transition: RunTransition) -> RecipeRunRecord: ...
    def record_cancel_intent(self, run_id) -> RecipeRunRecord: ...
    def read(self, run_id) -> RecipeRunRecord: ...

class RecipeRunner:
    def advance_once(self, run_id: str) -> RecipeRunView: ...
    def reconcile(self, run_id: str) -> ReconciliationResult: ...
    def resume(self, run_id: str) -> RecipeRunView: ...
```

각 `advance_once`는 한 상태 전이 또는 한 bounded unit만 수행한다. 지속 supervisor는 nonterminal run을 scheduling하지만 deadline/request/iteration caps가 모든 loop의 종료 근거다. blind retry loop나 성공할 때까지 quality threshold 변경은 없다. worker exception은 sanitize하여 StepError로 기록하고 finally에서 owner/active worker 상태를 정리한다. crash가 기록 자체를 못 끝낸 경우 startup reconciliation이 맡는다.

저장 위치는 `paths.runs/<run_id>/` 아래 plan/grant/step/manifest와 immutable artifact로 분리한다. 파일은 임시 이름→flush/fsync→atomic rename 후 manifest를 마지막에 commit한다. partial 파일은 completed manifest가 참조하지 않는다. seq CAS와 OS/runtime lease 계약은 안정성 명세의 동일 helper를 재사용한다. terminal step, consumed token, applied receipt는 덮어써서 재시도 가능한 것으로 바꾸지 않는다.

기존 `JobStore`는 새 framework로 전면 교체하지 않는다. `update/cancel/claim`의 read-modify-write 전체를 같은 RLock 안에 넣고 store writer lease를 검사한다. queued→running claim과 cancel은 경쟁하면 한쪽만 이긴다. cancel flag를 늦은 worker update가 지울 수 없게 한다. worker는 try/except/finally로 예외를 failed 결과에 저장하며 기존 terminal status는 불변이다. owner PID만으로 살아 있다고 판단하지 않고 host instance/OS process start/lease identity를 사용한다. 기존 legacy record의 모르는 execution은 명시 unknown으로 보존하고 자동 재시도하지 않는다. read-only retry 도구는 사용자 명시 호출일 때 현재 gate를 다시 검사한다.

## 8. 중단·취소·resume·late response

### 8.1 Crash window별 재개

| 마지막 durable evidence | 재시작 동작 |
|---|---|
| plan만 있음 | grant가 없으면 실행하지 않는다. |
| prepared token, outbox에 submit intent 없음 | token/source/grant가 유효하면 아직 실행되지 않은 exact step을 제출 가능. 만료되면 predispatch 확정 후 새 prepare. |
| queued request, claimed receipt 없음 | atomic queue cancel/claim 경쟁을 해소한다. 단순 파일 부재만 보고 미실행이라 판단하지 않는다. 동일 request status를 조회한다. |
| claimed 또는 dispatch_started | 새 mutation, rollback, export/publish 금지. 기존 request의 runtime receipt/응답만 reconcile한다. runtime 생존 여부를 lease TTL 하나로 결정하지 않는다. |
| runtime terminal succeeded, host quality 미완료 | mutation 재실행 금지. 동일 successor binding에서 누락 readback/quality만 수행한다. |
| runtime succeeded, app crash로 메모리 결과 소실, usable checkpoint 없음 | `blocked: checkpoint_missing_after_apply`. 성공한 mutation을 자동 재생하지 않는다. |
| successor checkpoint durable, step record update만 유실 | checkpoint digest/receipt/source chain을 검증해 완료 stage로 복구하고 다음 단계부터 진행한다. |
| solve artifact 완료, apply 미시작 | capture/correction/solver digest가 일치하면 solve를 재실행하지 않고 artifact를 사용한다. |
| publish intent durable, final record만 유실 | expected final path의 SHA256와 publish artifact identity를 확인해 완료로 reconcile. 다른 bytes면 blocked; 무조건 재export/replace하지 않는다. |

자동 resume의 보장은 “완료된 mutation을 다시 실행하지 않는다”이다. 저장하지 못한 app 메모리 상태까지 항상 복구 가능하다는 보장은 아니다. 무결한 checkpoint가 없는 crash gap은 blocked로 정직하게 남긴다.

### 8.2 취소

- pending/ready: step canceled; mutation 없음.
- host solve: cooperative cancel flag를 solver의 정해진 iteration/geometry batch 경계에서 검사한다. host worker가 취소를 못 받은 경우 결과는 보관 가능하나 apply하지 않는다. budget을 넘긴 worker는 isolated process를 쓰는 구성에서만 종료하고 Cascadeur process는 종료하지 않는다.
- queued app request: queue의 atomic cancel이 이겼음을 확인했을 때만 canceled_pre_dispatch. claim이 이겼으면 awaiting_result로 남는다.
- dispatched app action: UI thread 강제 중단/중복 action/즉시 rollback을 하지 않는다. 원 request outcome을 해소하고 applied 결과를 기록한다.
- partial correction: plan에 `cancel_recovery=restore_pre_correction`이 있고 exact recovery guard가 맞으면 실패 branch를 보존한 새 working clone으로 복구한다. user GUI 편집이나 unknown outcome이면 복구하지 않고 blocked+cancel intent를 유지한다.
- publish 전: candidate는 run-owned staging에 남고 final path를 쓰지 않는다. publish가 이미 원자적으로 완료됐다면 취소와 별개로 artifact를 `published=true`로 보고한다. 취소됐다고 이미 배포한 파일을 몰래 삭제하지 않는다.

### 8.3 Late response

응답을 받아들이는 조건은 request/session/runtime_epoch/lease_epoch/operation digest/HMAC 일치다. 오래된 session의 응답은 새 작업의 결과로 쓰지 않는다. known terminal receipt를 conflicting response가 덮지 못한다. unknown의 늦은 성공 응답은 원 step을 succeeded runtime outcome으로 해결하되 actual readback/checkpoint/취소 정책을 거쳐야 run이 진행한다. 어떤 outcome unknown에도 새 request_id로 동일 mutation을 보내지 않는다. unknown 해소 중에는 비변경 status/receipt만 조회한다. `animation.transform_get(refresh=True)`처럼 이름은 read지만 evaluation update를 실행하는 경로는 금지하며, 원 request가 terminal/idle로 해소된 뒤에만 별도 journaled refresh를 수행한다.

rollback은 original runtime failed_after_dispatch 또는 runtime success 뒤 host verification failure가 **이미 확정**되었고, write_phase/effect가 실제 변경 가능성을 증명하며 same runtime/scene instance와 완전한 RecoveryGuard를 확인한 경우만 실행한다. handler dispatch 뒤 지연 callback의 source guard가 첫 write 전에 거부한 경우는 dispatched=True여도 `write_phase=not_started, failure_kind=guard_rejected_before_first_write`이며 rollback 대상이 아니다. predispatch/stale/unknown에는 rollback하지 않는다. PR8의 실패 branch를 닫지 않는 `close_previous=False`는 보존한다. 새 recovery 요청에도 별도 receipt/scene guard/token scope가 필요하다.

## 9. 긴 클립: 전체 범위와 bounded memory

품질 담당의 global solve 계약을 채택한다. 독립 chunk별 correction을 평균하거나 이어 붙이지 않는다.

1. capture는 최대 2,000 frame의 파일 window로 나누고 각 window 내부 bridge transport는 기존 25 operations 이하와 payload byte cap을 적용한다. 이 둘은 서로 다른 한도다. 2,000은 hard correctness limit이 아니라 계획에 보이는 기본 memory window이며 byte cap이 더 작으면 frame/object 두 축으로 더 분할한다.
2. `MotionContext`는 실제 frame IDs `int64[N]`, time seconds `float64[N]`, rational fps, basis, metres-per-scene-unit을 가진다. array row index를 scene frame으로 추정하지 않는다. `numpy.memmap`/`.npy`(allow_pickle=False)와 manifest에 shape/dtype/hash/coverage를 기록한다.
3. `CaptureManifest`는 SourceBinding, MotionContext/RigProfile hashes, requested frame/object/channel set, received coverage, valid masks, per-block hashes를 갖는다. zero-fill은 missing data의 대체값이 아니다. NaN sentinel+valid mask로 누락을 보존하며 incomplete capture에서 solve/quality pass를 내지 않는다.
4. global contact anchors와 key grid, D1/D2 temporal rows는 클립 전체를 유지한다. 작은 전역 상태는 host sparse QP에 두고 geometry constraints만 streaming 재평가해 같은 global variables에 추가한다. file window 경계를 motion 경계로 취급하지 않는다.
5. memory 추정에는 variables, sparse nnz, factorization headroom, capture file windows, geometry cache를 포함한다. cap을 넘으면 `resource_budget`으로 blocked한다. 앞부분만 처리하고 whole clip success로 표시하지 않는다. 자원 budget을 늘리는 새 plan 또는 다른 명시적 solver variant만 허용한다.
6. solve 결과의 writes는 deterministic order `(frame, object_id, channel)`로 정렬한다. `CorrectionPlan` 전체 hash와 각 write chunk hash를 함께 저장한다. 동일 frame 내부의 driver 의존성 때문에 순서가 달라져야 하는 adapter는 검증된 dependency group order를 별도 고정하고 그 order를 candidate digest에 포함한다.
7. write chunk는 count와 byte cap으로 나누되 같은 frame/controller의 coupled write group은 갈라서 intermediate solve가 생기지 않게 한다. 한 group이 cap보다 크면 payload 방식 확장 또는 blocked; 절반만 적용하지 않는다.
8. 각 write chunk는 개별 exact prepare/commit token과 receipt가 있으며 global correction의 완료 목록을 CAS 기록한다. 성공한 chunk는 다시 dispatch하지 않는다. successor checkpoint 후에만 재개 가능한 완료로 확정한다. 일부 chunk만 적용된 상태는 candidate incomplete이며 quality/export로 가지 않는다.
9. 같은 candidate의 다음 chunk는 원본 SourceBinding을 current scene과 비교해서 stale 처리하는 대신, 정확한 이전 chunk의 observed successor와 아직 쓰지 않은 source scope를 검증한다. 외부 변경이 끼면 blocked한다.
10. actual readback은 요청 전체 frame set과 수정 영향의 controller/derived joint/mesh 범위를 다시 읽는다. quality의 전체 범위와 chunk-boundary 인접 항을 포함한다. 중간 key/보간 손상은 원래 source sample grid와 QualityPolicy의 adaptive subframe 규칙으로 평가한다.

최소 인터페이스:

```python
capture_motion(scope, binding, budget, cancel) -> CaptureManifest
analyze_capture(capture, rig_profile, policy) -> AnalysisReport
solve_capture(capture, analysis, variant, budget, cancel) -> SolverResult
plan_write_chunks(correction, adapter_caps, budget) -> tuple[WriteChunk, ...]
verify_actual(before, after, correction, policy) -> QualityReport
```

`SolverResult.status=no_change`는 actual baseline이 quality gates를 이미 만족하는 경우만 apply를 생략할 수 있다. “writes 없음”이 unsupported input이나 solver 실패를 숨기는 수단이 되지 않는다. actual required quality pass 전에는 자동 export하지 않는다.

## 10. ExportProfile과 target 격리

```python
ExportProfile(
    schema_version=1,
    character_ref: ExactTarget,
    skeleton_map: tuple[ExportBoneMap, ...],
    allowed_helper_nodes: tuple[HelperNodeSpec, ...],
    include_mesh: bool,
    mesh_refs: tuple[str, ...],
    take_name: str,
    first_frame: int, last_frame: int,
    fps_num: int, fps_den: int,
    time_origin: Literal["preserve", "zero"],
    axes: AxisConvention,
    metres_per_export_unit: float,
    bake: Literal["dense", "sparse_equivalent"],
    required_channels: tuple[ChannelSpec, ...],
    root_motion: RootMotionProfile,
    target_adapter: str,
    target_adapter_fingerprint: str,
    target_import_settings_digest: str,
    tolerances: ExportTolerances,
    destination: str,
    overwrite_mode: Literal["fail_if_exists", "replace_path"],
    overwrite_semantics: Literal["none", "replace_any_current_content"],
)
```

`RootMotionProfile`은 root node/ground up vector/translation axes/yaw 규칙과 `preserve_world|in_place|extract_to_root`를 명시한다. `in_place`는 어떤 평면 성분을 고정하고 어느 yaw를 유지할지까지 정한다. `extract_to_root`는 pelvis/world movement가 새 root와 local animation의 곱으로 재구성되는지 비교한다.

선택 캐릭터 export 방법은 아래 우선순위 하나를 계획 단계에서 고정한다.

1. 설치 버전에서 export 대상·take·fps·axes·unit·bake 설정을 **제어하고 읽어 확인할 수 있는** dedicated adapter가 있으면 사용한다.
2. 없으면 verified continuation snapshot에서 별도 export working clone을 만들고 target skeleton/skin/mesh/ancestry/constraint 참조의 dependency closure를 보존한다. unrelated exact IDs만 clone 안에서 제거하도록 미리 승인된 steps를 사용한다. 원래 scene을 export용으로 파괴하지 않는다. closure를 읽을 수 없는 opaque binding은 지원 불가다.
3. current `export_all_objects`는 격리된 export clone 또는 명시적으로 scene 전체를 허용한 profile에서만 strict export에 쓴다. UI selection을 바꿨다는 이유로 selected-only export라고 가정하지 않는다.

현 native exporter가 profile의 fps/axis/unit/bake를 직접 제어하지 못한다면, verified isolated scene settings 또는 버전이 고정된 외부 conversion adapter가 있어야 한다. 없는 옵션을 인자에 추가해 되는 것처럼 보이지 않는다. output validator가 mismatch를 잡더라도 자동화 성공이 아니라 `unsupported_export_profile` 또는 validation failure다.

## 11. FBX 구조 validator의 정확한 판정

`fbx_check.py`의 보고 함수는 유지하고 `src/cascadeur_complete/fbx_validation.py`에 validation contract를 새로 둔다. 기존 key count summary를 통과 판정으로 재활용하지 않는다.

```python
read_fbx_structure(path, limits: ParseLimits) -> FbxDocument
validate_fbx_structure(doc, profile, expected: ExportExpectation) -> ValidationReport
```

### 11.1 파일 형식과 bounded parse

- 23-byte binary magic, version uint32를 먼저 확인한다. binary 32-bit/64-bit node header 분기는 기존 reader의 <7500/≥7500 규칙을 bounded parser로 구현한다. 지원 version은 exporter/fixture로 명시한 allowlist이며 unknown/new version을 generic pass하지 않는다. ASCII FBX는 이 binary parser의 unsupported 입력이다.
- 각 node end offset은 현재 위치보다 크고 파일 길이 안에 있어야 한다. property count, property byte length, name length, child 범위, null terminator를 검증한다. recursion depth, total nodes, property bytes, array length, decompressed bytes 상한을 둔다.
- compressed array는 예상 `count * dtype.itemsize` bytes만 허용하고 zlib bounded output 뒤 exact 길이를 검사한다. unknown property tag/encoding은 unsupported 또는 malformed로 거부한다. 무제한 `read_bytes()/zlib.decompress()`로 대형 파일을 전부 메모리에 올리지 않는다.
- header 뒤 임의의 `len(data)-200`까지 읽는 기준을 제거하고 root terminator/footer가 allowlisted format과 맞는지 확인한다. 파싱을 못한 영역을 빈 scene으로 간주하지 않는다.

### 11.2 시간과 fps

legacy KTIME=46,186,158,000 ticks/s는 모든 FBX에 공통이 아니다. Blender 공식 구현은 7700–7xxx에서 `FBXHeaderExtension/OtherFlags/TCDefinition=0`을 141,120,000 ticks/s, 127을 legacy로 구별한다. 해당 flag가 없는 지원 버전의 legacy 기본 경로만 허용하고 모르는 flag/version은 unsupported로 둔다. 8000 동작은 추정 문구가 있는 자료를 확정 규칙으로 사용하지 않는다. [공식 Blender 구현](https://github.com/blender/blender-addons/blob/main/io_scene_fbx/fbx_utils.py)

TimeMode를 rational fps로 변환한다. 지원 map은 1→120, 2→100, 3→60, 4→50, 5→48, 6/7→30, 8/9→30000/1001, 10→25, 11→24, 13→24000/1001, 15→96, 16→72, 17→60000/1001, 18→120000/1001이다. 14는 finite positive CustomFrameRate를 요구하며 profile의 rational rate와 tolerance 내 일치해야 한다. 0/default와 알 수 없는 값은 명시적 rate 해석 근거 없으면 unsupported다. drop-frame 표시는 animation 시간축을 29.97 대신 임의 30으로 바꾸는 이유가 아니다. 동일 공식 소스의 `FBX_FRAMERATES` 및 [Autodesk FbxTime](https://help.autodesk.com/cloudhelp/2020/ENU/FBX-API-Reference/cpp_ref/class_fbx_time.html)을 기준으로 한다.

`N=last_frame-first_frame+1`; sample span seconds는 `(N-1)*fps_den/fps_num`이다. `N/fps`와 혼동하지 않는다. expected key tick는 source frame time과 `time_origin`을 Fraction으로 계산한 후 가장 가까운 integer tick로 변환한다. 양수 half-tie는 올림으로 고정하고 결과 비교 허용치는 기본 1 tick이다. 다른 exporter 양자화가 필요하면 profile에 수치와 이유를 미리 기록한다. LocalStart/LocalStop, global TimeSpan, 실제 curve time 범위를 구별해 검사한다.

### 11.3 대상·take·곡선의 연결 관계

- `Objects`를 unique ID map으로 만들고 `Connections`의 object/property edges를 해석한다. duplicate IDs, dangling required connections, hierarchy cycles는 실패다.
- `AnimationStack → AnimationLayer → AnimationCurveNode → AnimationCurve`, `AnimationCurveNode → Model/property`의 연결로 **어떤 take가 어떤 캐릭터의 어떤 채널을 움직이는지** 확인한다. 단순 AnimationStack/action 개수는 근거가 아니다.
- target skeleton은 canonical node path+parent topology+role mapping으로 비교한다. duplicate short names, importer suffix, 여러 armature 중 첫 번째 선택은 금지한다. 허용한 transform helper/extra skeleton node는 profile에 exact 허용 목록을 둔다.
- exact take name과 개수/interval이 profile과 일치해야 한다. 허용하지 않은 source character take나 extra clip이 섞이면 실패다. source root/mesh가 export closure에 남아 있는지 검사한다.
- curve `KeyTime`는 finite integer, strictly increasing이며 value array와 길이가 맞아야 한다. zero-length curve는 invalid이다. transform/skin matrices, positions, key values에는 NaN/Inf를 허용하지 않는다.
- `bake=dense`에서는 **required animated** channels에 expected frame ticks의 coverage를 요구한다. 원래 상수 채널은 property 값 또는 constant curve로 표현할 수 있으며 actual target comparison이 그 상수를 확인하면 허용한다. 모든 curve가 무조건 N keys여야 한다는 규칙은 적용하지 않는다.
- `bake=sparse_equivalent`는 key 개수로 동등성을 판정하지 않고 target evaluator의 전체 요청 time-grid 결과로 판정한다. unsupported interpolation/curve semantics는 target adapter가 검증하지 못하면 실패한다.
- `include_mesh=false`이면 mesh/skin이 없다는 이유로 실패시키지 않는다. true이면 exact expected mesh와 Skin→Cluster→bone/geometry connection, vertex index 범위, finite nonnegative weights, required deformation links를 확인한다. weights normalization policy는 target profile로 명시한다.

### 11.4 축·단위·root

UpAxis/UpAxisSign/FrontAxis/FrontAxisSign/CoordAxis/CoordAxisSign을 모두 읽고 profile의 convention과 비교한다. UpAxis 하나만 같다고 통과하지 않는다. signed basis의 handedness와 orthogonality를 확인한다. 반사 basis를 quaternion 자체로 변환하지 않고 rotation matrix conjugation으로 변환한다.

reflection은 export encode/decode adapter 경계에서만 처리한다. `MotionContext.scene_to_solver_basis`는 품질 명세대로 det=+1을 유지한다. det=-1의 파일 basis는 명시적으로 position/normal/triangle winding을 canonical right-handed representation으로 변환하고 `R_canonical=C*R_file*C^-1` 뒤 proper rotation을 추출한다. normal은 inverse transpose, triangle winding은 handedness가 바뀔 때 한 번 뒤집는 규칙을 기록해 collision sign을 보존한다. importer가 이미 이를 처리했다면 같은 변환을 다시 적용하지 않는다. exact decode mapping을 확인할 수 없으면 `EXPORT_AXIS_DECODE_UNSUPPORTED`로 차단한다.

UnitScaleFactor는 centimetres 기준이므로 `metres_per_file_unit = UnitScaleFactor / 100`이다. 유한한 양수여야 하며 profile unit과 일치해야 한다. geometry 좌표에도 같은 factor가 적용되었는지는 target transform/bind-pose 크기 비교로 확인한다. 단위 tag만 바꾸고 좌표를 그대로 둔 파일을 통과시키지 않는다. [Autodesk FbxSystemUnit](https://help.autodesk.com/cloudhelp/2020/ENU/FBX-API-Reference/cpp_ref/class_fbx_system_unit.html)

source에서 측정한 expected root trajectory, in-place constraints, extract-to-root reconstruction을 각 frame에서 target evaluator 결과와 비교한다. origin/facing/scale의 허용 변환은 ExportProfile에 미리 정해진 것만 적용한다. motion이 조금이라도 있으면 합격하는 기준은 없다.

## 12. Target import/evaluation validator

```python
validate_target_import(
    sealed_fbx: ArtifactRef,
    profile: ExportProfile,
    expected: ExportExpectation,
    timeout: float,
    cancel: CancelToken,
) -> TargetValidationReport
```

Blender adapter는 기존 installed executable을 사용하고 version/adapter source fingerprint/import settings를 기록한다. subprocess는 shell=False의 argument list와 고정된 adapter script에 JSON manifest 경로를 전달한다. 사용자 script/string을 `--python-expr`로 실행하지 않는다. 새 dependency/설치는 자동 수행하지 않는다. target app adapter가 없으면 required target validation은 `blocked: target_validator_unavailable`이며 구조 검사만으로 동일 등급 pass를 내지 않는다.

알고리즘:

1. fresh isolated target scene에 sealed artifact를 import한다. subprocess exit code=0, exact result schema, input SHA256, adapter fingerprint가 모두 일치해야 한다. marker 한 줄 존재만으로 성공시키지 않는다. stdout/stderr와 report file 크기를 제한한다.
2. declared skeleton map에 해당하는 armature와 bone path를 정확히 resolve한다. active action 또는 slot/NLA binding이 expected take를 target armature에 실제 연결하는지 확인한다. `bpy.data.actions` 목록에 아무 action이 있다는 조건은 폐기한다. 설치 Blender 버전별 action slot/import API 차이는 version adapter에 국한하며 미지원 version은 차단한다.
3. bind-pose hierarchy/lengths/mesh binding/root object transforms를 expected profile과 비교한다. names만 일치하고 skeleton proportion이 다른 결과는 실패한다.
4. importer의 알려진 frame origin offset을 명시적으로 적용해 source time→target frame/subframe의 mapping을 고정한다. fps label 변경과 time-resampling을 구별한다. 원래 요청한 모든 integer source frames와 QualityPolicy가 지정한 subframe을 bounded windows로 평가한다.
5. target bone joint head global position을 basis/unit 보정 후 source Joint global position과 metres 단위로 비교한다. armature object matrix도 포함한다. bone axes 표현 차이는 bind-pose 정렬로 제거하며 Euler 값 자체를 직접 비교하지 않는다.
6. orientation은 source/target의 각각 bind-pose 대비 global rotation delta를 같은 basis로 옮긴 뒤 quaternion geodesic angle `2*acos(clamp(abs(dot(q1,q2)),0,1))`로 비교한다. 위치 error, angle error, root trajectory error, scale/finite checks의 max와 quantiles 및 worst joint/frame을 기록한다. 허용치는 profile에 명시된 수치만 사용한다.
7. target adapter는 evaluated motion/geometry를 immutable `exported_capture` manifest로 저장하고 canonical `MotionContext`와 source time-grid에 맞춘다. 품질 명세의 `validate_export_roundtrip(before_export, exported_capture, export_profile, rig_mapping, intent, policy)`를 필수 호출한다. 이 평가기는 joints뿐 아니라 support-local contact drift, keypose/root/prop/timing locks, bone lengths, required non-target scope를 비교한다. mesh가 export 대상이면 실제 reimport skinned surface의 collision도 required다. export 밖의 moving support는 `ReferenceInputs`의 원래 시간별 trace를 같은 source time으로 평가한다.
8. required metrics 각각이 지원된 관측 coverage를 가지고 joints/channels/frames coverage가 100%이며 모든 required tolerance가 통과해야 target validation pass다. missing geometry/support/metric을 조용히 제외하지 않는다. skeleton-only profile은 original render mesh collision을 측정했다고 표시하지 않고 필요한 proxy/unsupported 정책을 정확히 반환한다. static clip은 static expected trajectory와의 동등성으로 판단하므로 “animated bones가 1개 이상” 같은 불필요한 조건을 붙이지 않는다.

### ExportExpectation

quality pass 후 **실제 Cascadeur 결과**를 source로 삼는다. predicted solver output이 아니다. `ExportExpectation`은 expected skeleton topology/rest transforms, exact time grid, unit/basis, joint/global transforms, allowed root conversion, desired take와 함께 `intent_digest`, 원본 ContactSegment/SupportTrack/prop/geometry refs와 hashes, actual postcleanup comparison capture digest, QualityPolicy digest를 고정한다. export에서 다른 rig로 변환하는 계획이면 그 target-space actual capture가 비교 기준이다. source/reference capture가 바뀌면 sealed export와 validator report를 재사용하지 않는다.

## 13. Staging과 원자 publish

```python
create_export_stage(profile, run_id, step_id) -> ExportStage
seal_export(stage, receipt, budget) -> ArtifactRef
publish_verified(artifact, validation_bundle, permit) -> PublishReceipt
reconcile_publish(intent) -> PublishOutcome
```

1. 최종 목적지와 같은 volume/directory의 run-owned unique staging 위치에 exporter raw output을 쓴다. path extension은 `.fbx`로 유지한다. 기존 사용자의 파일을 temporary path로 쓰지 않는다.
2. runtime export가 terminal로 끝나고 raw file의 completion 조건을 만족하면 새 create-exclusive sealed candidate로 복사하면서 SHA256을 계산하고 flush/fsync한다. sealed candidate는 exporter에게 경로를 전달하지 않으며 모든 writable handle을 닫고 runner도 이후 이 경로를 쓰기 모드로 열지 않는다. 이후 exporter가 raw path를 수정해도 sealed candidate는 바뀌지 않는다. 안정된 size/mtime만을 export 품질 증명으로 사용하지 않는다.
3. 모든 구조/target validators는 sealed candidate SHA256을 입력으로 받고 report에 같은 hash를 남긴다. publish 직전에 동일 hash를 다시 확인한다. known runtime success와 actual quality pass가 없으면 artifact bytes가 우연히 존재해도 publish하지 않는다.
4. retained sealed candidate와 별 inode의 `publish_temp`를 같은 destination volume에 create-exclusive byte-copy하고 SHA256 일치와 flush/fsync를 확인한다. publish_temp의 모든 writer를 닫는다. durable publish intent에 `(run_id, step_id, artifact_sha256, publish_temp_identity, destination, overwrite_mode, authorization_digest)`를 먼저 기록한다. final과 retained evidence artifact를 hardlink로 공유하지 않는다.
5. `fail_if_exists`는 같은 filesystem의 atomic no-replace primitive를 사용한다. stdlib `os.link(publish_temp, destination)`으로 완성된 inode를 새 이름에 공개할 수 있는 파일시스템이면 이미 존재할 때 실패하게 한다. hardlink 뒤 publish_temp와 final은 같은 inode이므로 finalize 뒤에도 publish_temp 수정은 절대 금지하며, run-owned publish_temp link만 제거한다. 사용자의 나중 final 수정은 별 inode의 retained sealed artifact에 영향을 주지 않는다. 지원하지 않는 filesystem에서 `exists()` 다음 `os.replace()`로 대체하지 않는다. 별도 확인된 platform no-replace primitive가 없으면 unsupported다.
6. default는 `overwrite_mode=fail_if_exists, overwrite_semantics=none`이다. 일반 `allow_overwrite=True` 또는 기존 파일 한 버전의 교체 승인을 path-unconditional 교체권으로 승격하지 않는다. 예외는 사용자가 exact path와 bounded expiry에 대해 `overwrite_semantics=replace_any_current_content`를 보고 명시적으로 승인한 경우뿐이다. 이 경우만 `replace_path`에서 같은 volume의 `os.replace(publish_temp,destination)`를 허용한다. 특정 기존 hash와 같을 때만 교체하는 filesystem compare-and-swap를 제공한다고 주장하지 않는다. conditional overwrite가 요구되는데 별도 OS 수준 보장이 없으면 unsupported이며, 새 versioned 경로의 별도 승인 plan을 사용한다.
7. final hash 확인과 supported filesystem flush 뒤 durable published receipt를 남긴다. validation report/manifest의 sidecar 기록이 늦었다고 올바르게 게시된 본 파일을 자동 삭제하거나 다시 overwrite하지 않는다. 여러 파일 bundle이 요구되면 immutable version directory를 완성한 뒤 단일 pointer/manifest를 원자 공개하는 별도 profile로 한다. 여러 rename을 하나의 원자 transaction이라고 부르지 않는다.
8. crash가 5와 7 사이에 생기면 intent의 destination/hash와 실제 파일을 비교해 published를 복구한다. bytes가 다르면 blocked하고 사용자의 파일을 복구 명목으로 덮지 않는다.

remote publish, engine project import, 메시지 발송은 이 local publish 권한에 포함되지 않는다. recipe가 그런 목적지를 명시하면 해당 adapter와 exact destination grant를 별도 stage로 요구한다. 이 설계는 network API를 추정해 만들지 않는다.

## 14. 구현 파일과 의존성 순서

| 파일/모듈 | 필요한 최소 변경 |
|---|---|
| `models.py`, protocol/session/auth models | 공용 SceneBinding/SourceBinding/RequestReceipt, v3 HMAC fields, additive job diagnostics |
| `jobs.py`, `service.py:submit_job` | atomic whole update/claim/cancel, exception capture, owner identity; mutation ban 유지 |
| `recipe_models.py` (new) | strict public RecipeSpec/Plan/Permit/Grant/Run/Step/Budget models |
| `recipe_store.py` (new) | seq-CAS, immutable artifact references, idempotent start, cancel intent |
| `recipe_runner.py` (new) | finite transitions/reconcile/resume, approved exact prepare/commit orchestration |
| `recipe_authorization.py` (new) | plan/run/effect/call budget scope validation; UI operation token 우회 없음 |
| `capture.py` (new 또는 quality 담당 명세 파일) | SourceBinding, streamed windows, manifests/valid masks; gated reads |
| `cleanup_workflow.py`, `motion_cleanup.py` | 기존 도구 유지하며 capture/global solve/correction/actual quality 공용 인터페이스 위임 |
| `retargeting.py` (new) | explicit host route의 retarget_pose/controller_targets/world_to_local; 품질 명세의 target-space math와 공용 protected write 경로 연결 |
| PR8 `change_flow.py`, `host_postconditions.py` | receipt-aware commit, unknown recovery 금지, runtime 결과와 host verification 분리 |
| runtime/pump/handler registry | v3 receipt와 fenced UI dispatch; protected checkpoint/export-isolation adapters; 기존 verified save primitive 재사용 |
| `export_workflow.py` (new) | profile→target isolation→raw stage→sealed candidate→validate→atomic publish |
| `fbx_validation.py` (new) | bounded structure/graph/timebase/profile checks |
| `external.py` | legacy validator 보존, strict target adapter와 version-gated action binding/evaluation 추가 |
| `server.py` | 새 recipe tools, alias migration contracts, 기존 tool signature 유지 |

구현 순서: 공용 v3 receipt/binding/lease→legacy job race+exceptions→immutable capture/correction/quality→recipe schema/grant/store→finite runner→generation/rig/retarget step integration→export structural+target validation→atomic publish. 이전 단계의 unknown을 다음 단계의 기본값으로 덮지 않는다. 새 dependency 없이 Python stdlib/Pydantic/기존 NumPy/SciPy/OSQP를 사용한다. 새 공개 API/protocol/schema는 실제 구현 착수 승인 범위에 포함되어야 한다.

## 15. 고정 합격 조건과 최소 직접 확인 항목

이 문서의 설계 합격은 아래 경계가 구체적으로 정의됐는지로 판정한다. 구현 후에는 각 위험에 대응하는 직접 case만 실행하며 전체 회귀/전체 빌드/CI/E2E를 기본 gate에 넣지 않는다. 이번 설계 단계에서는 아무 case도 실행하지 않았다.

- job queued cancel과 worker claim이 경쟁해도 terminal 상태/취소 의도가 유실되지 않음; worker exception이 running으로 남지 않음.
- 동일 start idempotency key와 동일 prepared token 재호출이 새 mutation을 만들지 않음.
- grant와 다른 object/frame/intent/operation/destination/cumulative bounds 또는 소진 budget을 token 단계 전에 거부함.
- claimed timeout→late success→host readback의 경로에서 rollback/retry/중복 commit이 없고 outcome이 해소됨.
- source stale, GUI edit, session/version mismatch에서는 준비·resume·recovery가 잘못된 scene을 수정하지 않음.
- capture 중 missing frame/object/channel을 0으로 취급하지 않으며 clip 전체 requested coverage 없이는 solve/quality pass 없음.
- long clip의 모든 window가 같은 global contact/key model을 사용하고 write chunk resume가 완료 chunk를 건너뜀.
- 실제 correction readback 실패를 predicted improvement로 덮지 않음; bounded variants exhaustion은 실패.
- FBX 잘못된 target/take/timebase/fps/unit/axes/root, truncated curves, partial interval을 각각 직접 reject하고, constant channels·skeleton-only valid profiles는 불필요하게 거부하지 않음.
- published file은 검증한 sealed SHA256과 같고 no-overwrite 경쟁은 existing 파일을 보존함. publish 직후 host crash는 재export 없이 reconciliation함.

남은 실기 불확실성은 숨기지 않는다: native generation의 완료 관측 신호, arbitrary rig/template coverage, exporter 설정 제어성, target app version별 import/action API, scene content 전체 guard의 관측 범위가 실제 지원으로 확인되어야 해당 adapter를 available로 표시할 수 있다. 이 중 하나가 미확인인 recipe는 blocked일 수 있지만, 이를 성공으로 거짓 보고하지 않는 제어 흐름 자체는 위 계약으로 구현 가능하다.
