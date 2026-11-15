# Cascadeur 변경 설계: 상태 결합·실행 영수증·복구 안정성

설계 기준: main `82b350cad4deda2ff5df288f46764a899115252d`, PR8 `1bb447898e8ced16b6931b72cfeb0f563127f746`. PR8 변경 파일은 `cascadeur-pr8-review`, 변경 없는 파일은 `cascadeur-review`의 동일 경로를 읽었다. 이 문서는 구현 명세이며 제품 수정, 실행, 테스트, 설치, commit/push는 수행하지 않았다.

## 1. 근거와 변경 경계

확인한 흐름은 다음과 같다.

| 근거 파일·함수 | 현재 동작 | 변경 이유 |
|---|---|---|
| PR8 `cleanup_workflow.py::_read` | 첫 응답의 `scene_id`만 보관하고 다음 응답과 비교 | 다른 frame/key 값 변경, 동일 path의 별도 탭, sample 이후 변경을 놓친다. |
| PR8 `change_flow.py::prepare_change` | 현 상태를 새로 조회하고 snapshot 이후 새 상태로 token 발급 | 오래된 sample로 계산한 writes를 새 revision에 승인하는 문제를 막아야 한다. |
| PR8 `runtime.py::scene_state` | path/name hash identity, current frame transforms와 key index 등으로 revision 계산 | 이 값은 전체 content revision이나 탭 instance ID가 아니다. |
| main의 PR8 미변경 `bridge_client.py::_execute_once` | claim 이후 timeout을 `UI_LOCKED`로 반환하고 일부 경로에서 request ID 누락 | 실제 실패와 결과 불명을 나누고 재조회할 identity를 유지해야 한다. |
| PR8 `change_flow.py::_restore_failed_change`, `_rollback_internal` | backup이 있는 모든 failure에 rollback, 내부 rollback의 대상 guard 없음 | predispatch 거절·unknown·다른 탭의 변경에 복구를 실행하면 안 된다. |
| PR8 `runtime.py` rollback handler | 새 working copy를 열며 `close_previous=False` | 이 보존 동작은 유지한다. PR8에서 이미 있는 해결을 새 변경으로 세지 않는다. |
| main의 PR8 미변경 `atomic_queue.py::recover_stale_claims` | 오래된 `.processing`을 `.json`으로 되돌림 | age는 실행되지 않았다는 증거가 아니다. mutation 재전송 금지. |
| PR8 `handlers/animation.py`에 해당하는 main 파일 | position/rotation key writer는 `transact(domain.modify_update, ..., edit)` 사용 | 실제 write callback 앞에서도 source guard가 필요하다. |
| PR8 `handler_registry.py::transact` | callback 예외를 수집해 호출자에게 다시 올림 | native atomicity·no-yield·callback completion을 증명하지 않는다. |
| `animation.transform_get(refresh=True)` | 내부에서 `refresh_interpolation` → `modify_update` 실행 | unknown 중 허용할 무부작용 읽기로 분류하면 안 된다. |
| main `product_catalog.py::binding_material` | URL/id/test id/fixture id 중심의 hash | 구현·fixture bytes가 달라져도 과거 live evidence가 살아남을 수 있다. |

PR8의 temp JSON nonce, runtime root, malformed request 처리, `snapshot_required` 정리, `*_prepare` API 및 change-flow 분리는 유지한다. 새 dependency와 전면 구조 개편은 필요 없다. public API/schema 변경은 후속 구현 승인 범위에 포함하며 이 설계만으로 적용하지 않는다.

## 2. 공용 wire 모델과 불변식

`SceneBinding`, `SourceBinding`, `RequestReceipt` 명칭은 자동화·품질 담당과 공용으로 사용한다. 다음은 타입 계약이며 실제 Pydantic 코드는 후속 구현 대상이다.

```python
class SceneBinding:
    schema_version: Literal[1]
    runtime_epoch: str             # Cascadeur 실행 session UUID, host PID 아님
    scene_instance_id: str         # 경로/이름/탭 index가 아닌 live instance UUID
    document_lineage_id: str       # 승인된 clone/checkpoint 계보
    revision_kind: Literal["scope_digest"]
    scope_digest: str              # canonical scope descriptor만의 SHA-256
    content_revision: str          # scope_digest + 실제 authored content SHA-256
    selection_digest: str | None  # 선택 의존 operation만 필수

class SourceBinding:
    schema_version: Literal[1]
    binding: SceneBinding
    scope: dict                   # canonical read/write dependency manifest
    sample_digest: str
    inputs_digest: str             # MotionContext/RigProfile/params/manifest bytes
    adapter_fingerprint: str
    complete: bool

class RequestReceipt:
    schema_version: Literal[1]
    request_id: str
    request_digest: str
    operation_digest: str
    session_id: str                # 기존 queue key-derived session 유지
    runtime_epoch: str
    host_instance_id: str
    run_id: str | None
    step_id: str | None
    attempt_id: str | None
    lease_epoch: int | None
    phase: Literal["created", "queued", "claimed", "dispatch_started",
                   "applied_observed", "terminal"]
    outcome: Literal["pending", "rejected_pre_dispatch",
                     "canceled_pre_dispatch", "succeeded",
                     "failed_after_dispatch", "outcome_unknown"]
    dispatched: bool | None        # None은 증거 없음, False는 긍정적 비실행 증거
    scene_before: SceneBinding | None
    scene_after: SceneBinding | None
    effect_class: Literal["none", "evaluation", "scene", "file", "mixed"]
    write_phase: Literal["not_started", "started", "completed", "unknown"]
    failure_kind: str | None       # guard_rejected_before_first_write 등
    recovery_eligible: bool        # False는 복구 금지; True도 현재 guard 재검증 필요
    mutation_observed: bool | None
    terminal_result: dict | None
    result_digest: str | None
    recovery: dict | None
    seq: int
    mac: str
```

`content_revision`은 문서 전체의 변경 counter가 아니다. 검증된 native generation API는 현재 근거가 없으므로 만들지 않는다. `scope_digest`는 IDs/channels/ranges/dependency 목록의 canonical descriptor hash이고, `content_revision`은 그 scope digest와 실제 authored key 값·보간·constraint·rig 데이터를 함께 hash한 것이다. `sample_digest`는 evaluated sample artifact의 별 projection이므로 두 값을 같은 hash처럼 비교하지 않는다. `inputs_digest`는 MotionContext/RigProfile/params 등 외부 입력의 canonical bytes다. 전체 문서 복구/내보내기의 guard로 쓰려면 그 operation에 필요한 전체 범위를 scope에 포함해야 한다.

기존 `scene_id`, `scene_revision`, `expected_revision`은 표시·구 API용으로 남길 수 있지만 v3 자동 mutation의 권한·freshness 근거로 사용하지 않는다. `SourceBinding.complete=False` 또는 알 수 없는 dependency는 준비 성공이 아니라 `BINDING_UNAVAILABLE`/unsupported 결과다.

`RequestReceipt.terminal_result`는 runtime dispatch 및 runtime postcondition의 결과다. host readback, 품질 평가, checkpoint, export 검증은 별도 host/run 기록이다. runtime terminal receipt를 host 성공/실패로 덮어쓰지 않는다. recipe step의 `succeeded`는 runtime success와 필요한 host 관측·checkpoint가 모두 성립했을 때만 쓴다.

## 3. scene instance와 content/source 결합

### 3.1 instance identity

`runtime.py`에 `_scene_instance(view_scene) -> SceneInstance`와 registry를 둔다. registry는 실제 view object에 강한 참조를 유지하고 같은 Python object (`is`)에 같은 UUID를 배정한다. 현재 소스가 사용하는 `get_scene_manager().current_scene()/scenes()/set_current_scene()` 외 새 csc 메서드는 가정하지 않는다.

경로, 탭 이름, tab index, object/rig ID 목록만으로 instance를 합치지 않는다. 동일 파일 두 번 열기, unsaved 동명 탭, Save As는 서로 구분한다. Python wrapper가 재생성돼 identity를 유지할 수 없으면 같은 장면이라고 추측하지 않고 instance를 새로 배정해 기존 binding을 만료시킨다. 이 경우 자동화 capability는 `identity_unstable`로 비활성화된다. 검증된 adapter에서 실제 native instance ID가 확인된 뒤에만 해당 adapter를 바꾼다.

`runtime_epoch`는 앱 session마다 새 UUID이며 bridge hot reload가 상태를 잃으면 새 epoch를 발급한다. 이전 epoch의 모든 token/queued mutation/recovery permit은 실행 거절한다. 단순 PID 및 PID 재사용은 epoch가 아니다. host instance는 별 UUID다.

### 3.2 source scope와 digest

scope에는 write drivers, 부모/rig descendants, read-only collision/support geometry, 기존 keys 및 interpolation metadata, 필요한 rig/Autoposing state, frame/time/unit/basis profile을 포함한다. quality 명세의 MotionContext/RigProfile과 같은 ID를 쓴다. 누락 frame/channel을 zero로 대체하지 않는다. ordering은 frame, stable object id, channel을 정해 global key grid와 chunk 경계와 무관하게 동일한 digest를 만든다. `allow_nan=False`, finite-only, 정확한 수치 serialization을 사용하며 guard에 metric tolerance나 rounding을 적용하지 않는다.

`complete=True`는 사용자가 자기 선언하는 값이 아니다. adapter가 exact operation과 검증된 RigProfile로 required dependency closure를 재도출하고 요청 scope·실제 수집 coverage와 비교한 뒤 발급한다. 외부 plan이 parent/constraint/collision dependency를 빼거나 예상 row 수를 작게 제출하면 complete로 승격하지 않는다. caller 제공 Scope를 그대로 해시하는 것만으로 required scope 검증을 대신하지 않는다.

host chunk reads는 sample 후보를 만든다. 각 chunk의 before/after hash 비교만으로는 A→B→A 편집에 의한 혼합 sample을 배제할 수 없다. 최종 runtime source validation은 선언된 전체 scope를 한 UI-thread 작업 안에서 streaming 재독해한다. authored projection으로 `content_revision`을, evaluated projection으로 `sample_digest`를 각각 다시 계산해 각각 원 binding과 비교한다. 동일 projection이 아닌 두 digest를 서로 비교하지 않는다. 전체 project가 아니라 실제 dependency scope만 읽는다.

snapshot의 파일 hash는 파일 integrity를 증명할 뿐 live scene memory가 여전히 같은 상태라는 증거가 아니다. 따라서 snapshot hash만으로 최종 전체 scope 재독해를 생략하지 않는다. native content generation 또는 immutable scene-reader가 실제 adapter에 확인되기 전까지, 읽기 work budget를 넘는 long clip은 `source_validation_budget_exceeded`로 bounded refusal한다. sample interval을 몰래 줄이거나 current-frame hash로 대체하지 않는다. 사용자가 명시적으로 범위를 줄여 새 plan을 만들면 별 요청이다.

### 3.3 prepare와 snapshot lineage

```python
CleanupWorkflow._read(..., *, source_session=None) -> BoundRead
CleanupWorkflow.sample(...) -> BoundSample
CleanupWorkflow._finish_source(scope, inputs) -> SourceBinding

ChangeFlowMixin.prepare_change(
    feature_id, operation_name, arguments, ttl=300.0, *,
    source_binding: SourceBinding | None = None,
    execution_context: ExecutionContext | None = None,
) -> dict

ChangeManager.prepare(..., source_binding, scene_binding,
                      mutation_request_id, execution_context, snapshot_manifest_id)
```

cleanup `prepare_*`는 실제 sample부터 얻은 `SourceBinding`을 반드시 전달한다. 기존 직접 edit API에서 `source_binding=None`이면 준비 시점에 operation dependency scope를 읽어 binding을 생성한다. 이미 계산된 writes를 받는 cleanup route에서 현재 scene을 읽어 새 binding을 붙이는 fallback은 금지한다.

prepare 순서는 policy/feature/argument/path/범위 검증 → original source guard → journaled `safety.snapshot` → 새 working instance/파일 검증 → 같은 scope의 content 보존 확인 → token 발급이다. snapshot과 working branch 만들기도 효과가 있는 요청이므로 request ID/receipt가 있다. snapshot timeout이 unknown이면 token을 발급하지 않는다.

`SnapshotManifest`는 `schema_version=1`, snapshot/working UUID, parent scene binding, clone scene binding, content scope+digest, source binding digest, file sha256/length, created request ID, recipe lineage, adapter fingerprint를 기록하고 HMAC으로 묶는다. 원본 source digest와 working content digest가 같을 때만 lineage edge를 확정하고 source binding의 instance를 새 working instance로 재결합한다. 경로 변경이나 새 revision 조회만으로 재결합하지 않는다. scope 밖의 content 보존을 검증하지 않았다면 문서 전체 동일성을 주장하지 않는다.

원본 scene과 snapshot bytes는 보존한다. 중간 snapshot 실패는 원 mutation 실패와 구분하고, 생성된 파일을 삭제해 원인을 숨기거나 새 token을 자동 발급하지 않는다.

### 3.4 write callback과 native 비동기 경계

`runtime.execute_request`의 target/source 검사에 더해 `handlers/animation.py::{position_keys_set,rotation_keys_set}`의 실제 `edit` callback 첫 write 앞에서 `context["assert_source_binding"](...)`를 호출한다. 호출자가 callback 진입 전에 기다리는 동안 scene이 바뀌면 write 0으로 거절해야 한다. primitive update loop는 대상 domain을 captured reference로 고정하며 loop에서 새로운 active scene을 선택하지 않는다.

`handler_registry.transact`에 선택적 `before_write` 및 callback entered/completed 관측을 추가한다. request-local callback permit은 native method 호출 stack이 활성인 동안만 유효하며 예상 UI thread·한 번의 callback 진입·exact request/target을 검사한다. native method가 callback completion 전에 반환하면 permit을 revoke하고 native completion unproven으로 기록한다. 나중 callback 또는 두 번째 callback은 first write 전에 거절한다. 현재 wrapper와 공식 signature의 `callable -> bool`만으로 원자성이나 no-yield를 보장하지 않는다. adapter manifest에는 `dispatch_semantics`와 actual evidence fingerprint를 둔다. cleanup 자동화는 `synchronous_no_yield`와 callback 종료/settled readback이 확인된 adapter에서만 허용한다. native call이 UI reentry/후속 비동기 write를 일으키는 adapter는 자동 mutation capability를 disabled로 둔다. 단 한 번의 정상 실행을 no-yield의 수학적 증명으로 쓰지 않는다. 이 제약을 만족하는 근거가 없으면 unsupported가 정확한 제품 동작이다.

handler dispatch 후 callback source guard에서 stale을 발견한 경우 dispatch 기록은 유지한다. 이때 `write_phase=not_started`, `failure_kind=guard_rejected_before_first_write`, `recovery_eligible=False`가 입증되면 원 feature write는 0이고 rollback을 금지한다. `failed_after_dispatch` 하나만 보고 복구해서 그 사이 사용자 편집을 버려서는 안 된다. instrument하지 못한 native 호출은 write가 없었다고 추정하지 말고 `write_phase=unknown`으로 둔다. `recovery_eligible=True`는 해당 failure가 recovery의 후보가 될 수 있다는 필요조건일 뿐이다. actual recovery는 terminal/idle, current target, complete source guard, lineage와 snapshot integrity를 다시 검사한다.

export/UI action의 단순 dispatch 성공은 native 작업 완료가 아니다. 그 adapter는 `dispatched_pending_observation` 상태를 유지하고, native 완료 신호가 확인된 경우 또는 해당 adapter에 검증된 안정 readback 절차가 끝난 경우에만 이후 단계로 간다. marker 없이 현재 값이 예상과 같다는 것만으로 아직 실행 중인 작업을 완료 처리하지 않는다. clone을 열거나 snapshot을 생성하는 작업 역시 native 비동기 경계를 통과하면 같은 규칙을 적용한다.

## 4. durable request와 at-most-once dispatch

### 4.1 API와 저장 구조

```python
BridgeClient.execute(..., request_id=None, source_binding=None,
                     execution_context=None) -> ResultEnvelope
BridgeClient.request_status(request_id: str) -> RequestReceipt
BridgeClient.cancel_request(request_id: str) -> RequestReceipt
BridgeClient.reconcile_request(request_id: str, *, observation=None) -> Reconciliation

RequestLedger.create(request) -> immutable request record
RequestLedger.read_receipt(request_id) -> RequestReceipt | None
RequestLedger.write_cancel_intent(request_id, expected_digest) -> None
```

단건 `change_prepare`도 mutation request UUID를 미리 배정한다. v3 token HMAC에는 이 ID와 exact operation digest, scene/source binding, snapshot manifest, adapter fingerprint, run/step/attempt/lease 및 expiry가 포함된다. `change_commit` 재호출은 이 ID의 상태/결과를 조회하고 이미 소비된 token을 새 request로 재전송하지 않는다.

기존 random nonce/HMAC/session과 runtime token verification을 유지한다. host request record는 enqueue 전에 원 nonce·MAC까지 기록한다. host restart 후 같은 request ID의 응답을 인증할 때 RAM의 `_outstanding`만 요구하지 않고 이 signed durable record에서 기대 nonce를 읽는다. 같은 ID+같은 digest는 상태 조회만 가능하고 같은 ID+다른 digest/nonce는 conflict다.

저장 layout 예:

```text
state/request_records/<request_id>/request.json
state/request_records/<request_id>/cancel_intent.json
state/request_records/<request_id>/runtime_events/0001-claimed.json
state/request_records/<request_id>/runtime_events/0002-dispatch_started.json
state/request_records/<request_id>/runtime_events/0003-applied_observed.json
state/request_records/<request_id>/runtime_events/0004-terminal.json
state/request_records/<request_id>/host_verification.json
state/request_records/<request_id>/reconciliation.json
```

runtime event는 runtime만 작성한다. host가 runtime terminal receipt를 합성하지 않는다. immutable event와 request-ID 단위 exclusive claim을 사용하며 canonical SHA/HMAC을 검사한다. existing atomic JSON의 unique temporary+flush+fsync를 재사용한다. incomplete/corrupt event는 absence/success로 해석하지 않고 unknown으로 보존한다. runtime epoch가 바뀐 queue 파일은 receipt 손실 여부와 무관하게 dispatch 거절한다. 이 때문에 process/power restart 뒤 오래된 queue가 재실행되는 경로를 차단한다.

정확히 한 번 실행을 보장한다고 쓰지 않는다. dispatch marker를 fsync한 뒤에만 native handler에 들어가며 marker가 있으면 같은 request는 다시 들어가지 않는다. marker를 쓴 뒤 실제 호출 전에 crash한 경우 실제 effect는 없을 수 있으나 unknown으로 남길 수 있다. 요청마다 **최대 한 번 dispatch**와 나중의 **관측에 의한 결과 확인**을 제공한다.

### 4.2 dispatch 순서

1. authenticated immutable request ID/digest 확인; 같은 ID의 terminal receipt가 있으면 반환만 한다.
2. queue `.json`을 claim; claim receipt를 저장한다. protocol/shape/TTL/epoch/lease/권한 검사는 native side effect 전에 한다.
3. scene instance와 source scope, staging files, snapshot manifest를 확인한다. 취소 intent를 다시 확인한다.
4. v3 consumed token의 exact operation/request/scope binding을 확인한다. 기존 일회용 marker를 유지한다.
5. `dispatch_started` event를 durable하게 저장한다. 저장 실패 시 native call 금지.
6. handler를 한 번 호출한다. native write callback 자체에도 source guard가 있다.
7. 완료 및 실제 결과/후조건을 관측하면 `applied_observed`, 이어 runtime terminal을 기록한다. handler exception 후 effect 없음이 증명되지 않으면 `failed_after_dispatch`/mutation unknown으로 보수적으로 기록한다.
8. signed response는 receipt에 대한 전달물이며 receipt보다 먼저 성공을 공개하지 않는다. host는 terminal receipt 뒤에 host postconditions를 적용한다.

`safety.snapshot`, checkpoint-save, rollback, export도 side effect 요청이다. 이들에 대한 내부 경로를 arbitrary user operation 실행 우회로로 만들지 않는다. recipe인 경우 exact step authorization/lease와 목적 경로까지 bind한다. mutation context 없는 plain read job은 기존 정책대로 mutation을 제출하지 못한다.

### 4.3 timeout, cancel, authentication failure

successful unlink로 여전히 unclaimed인 unique queue 파일을 취소했거나 runtime가 predispatch 취소 receipt를 발행한 경우에만 `canceled_pre_dispatch`이다. claim된 뒤 wait budget이 끝나면 `ok=False`, `status="outcome_unknown"`, `outcome="outcome_unknown"`, 기존 top-level `error_code="TIMEOUT"`, `result.error_details.code="OUTCOME_UNKNOWN"`, request ID/nonce reference/receipt location을 보존한다. 기존 ErrorCode enum은 유지하고 상세 사유는 구조화 detail에 둔다. 응답 인증 failure이면 top-level `INVALID_REQUEST`를 유지하되 outcome은 여전히 unknown일 수 있다. `UI_LOCKED`는 dispatch 실패가 확인된 UI 문제 설명으로만 남긴다.

사용자 취소는 durable intent다. dispatch 이후에는 native 동작이 취소됐다고 보고하지 않는다. 결과가 늦게 오면 보존하고 run의 취소 의도와 분리한다. modal license gate나 응답 MAC 실패도 단독으로 no-effect 증거가 아니다. UI gate를 닫았는데 runtime 결과가 없으면 unknown이며 자동 rollback/retry 금지다.

`ResultEnvelope`에 `request_id`, `receipt_id`, `phase`, `outcome`, `dispatched`, `recovery_state`를 추가한다. `change_flow.py`와 `host_postconditions.py`에서 exception을 새 envelope로 감쌀 때 이 필드와 before/after scene binding, runtime evidence를 그대로 보존한다. 마지막에 무조건 `status = 'failed'`로 덮어쓰는 코드를 없앤다. `ok=True`는 필요한 postconditions 통과 결과에만 사용한다.

runtime `_error`도 `_error(..., before_state, after_state=None, phase, write_phase, request_identity)` 계약으로 바꾼다. 현재 예외 시점 state를 before와 after 양쪽에 복사하는 동작은 제거한다. before는 dispatch 전 실제 관측, after는 실패 후 별 관측이며 실패로 after를 읽지 못하면 null/unknown이다. 부분 write가 있었는데 revision 변화가 없었다고 합성하거나 host wrapping이 원 request ID를 지우지 않는다.

### 4.4 stale claim와 lease

`AtomicQueue.recover_stale_claims`는 mutation `.processing`을 `.json`으로 바꾸지 않는다. receipt를 조회하고 미해결을 격리·표시한다. API 이름을 당장 남겨도 의미는 discovery/reconciliation이며 dispatch 재시작은 하지 않는다. read-only job도 refresh/evaluation effects를 정확히 분류한 뒤에만 retry할 수 있다.

host간 exclusive OS lease와 `lease_epoch` fencing을 사용하되 lease가 GUI 편집을 막는다고 주장하지 않는다. runtime은 dispatch 직전 owner/epoch를 검사한다. TTL 경과나 host PID 죽음은 아직 살아 있는 Cascadeur native 작업이 끝났다는 증거가 아니다. unresolved runtime dispatch가 있으면 successor host의 mutation, snapshot, rollback, export, publish를 차단한다. observation 순서는 receipt 읽기 → 원 runtime 완료/종료 증거 → 안전한 scene readback이다.

`animation.transform_get(refresh=True)`와 `animation.interpolation_refresh`는 무부작용 reconciliation 허용목록에서 제외한다. outcome unknown 중에는 disk receipt/status 같이 부작용이 없는 관측만 허용한다. evaluation refresh는 원 작업이 끝난 뒤 별도 journaled evaluation 또는 guarded adapter 안에서 수행한다.

## 5. 실패와 rollback 계약

```python
ChangeFlowMixin._restore_failed_change(
    record, failed, *, receipt: RequestReceipt, recovery_guard: SceneBinding
) -> ResultEnvelope

ChangeFlowMixin._rollback_internal(
    snapshot_id, *, failed_request_id, expected_target: SceneBinding,
    expected_source_digest, recovery_context
) -> ResultEnvelope
```

| 원 요청 상태 | 자동 복구 |
|---|---|
| host validation/source stale/권한/scene mismatch/TTL 등 predispatch rejection | rollback 없음; 이미 존재하는 working tab와 snapshot을 유지 |
| canceled before dispatch | rollback 없음 |
| native handler는 dispatch됐으나 callback first-write guard가 거절됨 | dispatch 기록 유지; `write_phase=not_started` proof를 보존하고 rollback 없음 |
| claimed/dispatch timeout, invalid response, native completion 미확인 | outcome unknown; 재dispatch/rollback/export/publish 없음 |
| runtime terminal failure와 정확한 대상·lineage·현재 guard 확인 | 정책이 승인한 recovery를 별 request로 제출 가능 |
| runtime success 후 host quality/readback 실패 | 원 runtime receipt를 보존; 종료 확인 및 현재 guard 뒤 별 recovery 요청 |
| 다른 탭/epoch/후속 편집 때문에 guard 불일치 | 자동 복구 거절; 실패 branch·snapshot·관측 결과 보존 |
| rollback 자체의 실패/unknown | 원 failure와 recovery failure를 별도 기록; 재귀 rollback 금지 |

runtime `safety.rollback_internal`은 더 이상 target 없는 예외가 아니다. failed request ID, failed working instance, snapshot ancestor, current source/recovery digest, exact manifest/file sha, runtime epoch와 lease를 검사한다. recovery request 자체가 일회용이고 receipts를 가진다. automatic recovery는 lineage 내 ancestor만 허용한다.

복구는 검증된 immutable snapshot에서 새 writable copy를 만들고 기존 실패 tab를 그대로 두는 PR8 방식을 유지한다. 무관한 tab를 닫거나 기존 파일을 덮어쓰지 않는다. source digest가 제한 scope면 전체 문서 restore로 덮을 수 없으므로 copy를 열더라도 다른 branch를 보존하고 결과를 `restored_to_new_working_copy`로 설명한다. 원 작업은 여전히 실패이며 rollback 성공을 원 feature success로 바꾸지 않는다.

manual `prepare_rollback(snapshot_id)`는 현재 target와 source snapshot manifest를 impact에 보이고 새 exact token으로 승인한다. unrelated lineage snapshot을 명시적으로 열려는 수동 작업은 auto rollback과 구분하는 `open_snapshot_copy` 의미를 사용한다. 과거 source path 문자열만 보고 활성 문서를 지정하지 않는다.

## 6. source/path/file integrity와 export publish

input file/mesh/profile/write blob는 이름·mtime·length만으로 식별하지 않고 실제 bytes SHA-256과 schema/length를 manifest에 넣는다. prepare 후 commit 사이 source가 바뀌면 stale이다. 파일을 사용하는 adapter는 run 전용 UUID staging copy와 고정 hash를 사용하고 existing local/UNC/device/overwrite policy를 그대로 적용한다. 경로를 `resolve()`하고 허용 root와 exact manifest item을 확인한다. unknown state인 원본 파일에 자동 덮어쓰기를 하지 않는다.

Windows native loader가 path를 다시 여는 gap에서는 가능한 adapter가 읽기 handle을 유지해 write/delete sharing을 금지하도록 구현한다. loader의 file-sharing behavior가 확인되지 않은 경우 guarded input staging을 unsupported로 두며 `hash를 한 번 읽었다`는 것을 atomic integrity 보장으로 과장하지 않는다. 새 패키지는 필요 없고 기존 stdlib/ctypes 범위다. 이 제한은 전체 보안 감사가 아니라 실제 native path handoff의 데이터 일관성 조건이다.

export는 `staging/<run>/<step>/<attempt>`의 새 이름으로만 쓰고 terminal native completion, structural/target roundtrip 검증, bound source/expected output 관측이 끝나야 artifact manifest를 seal한다. 파일 존재/크기 안정만으로 export 성공을 증명하지 않는다. async export가 입력 scene을 언제 capture하는지 확인되지 않으면 expected output과 artifact를 직접 대조하는 adapter 검증이 필요하며, 그것도 불가능하면 자동 publish는 지원하지 않는다.

publish는 승인된 exact output path와 manifest hash를 가진 별 step이다. 기본은 기존 final 파일 overwrite 금지다. `exists()` 검사 후 `os.replace()`는 중간에 생성된 타 파일을 덮으므로 사용하지 않는다. automation 공용 구현의 `publish_no_clobber`는 같은 filesystem의 `os.link(publish_temp, final)`로 destination 생성권을 원자 획득한다. 보존할 sealed staging과 `publish_temp`는 별 bytes copy+hash 검증으로 분리한다. final을 사용자나 외부 프로그램이 나중에 수정해도 sealed staging이 같은 inode를 통해 변하면 안 된다. `publish_temp`와 final에는 게시 전 native writer가 없음을 확인한다. 지원하지 않는 filesystem은 명시 거절하고 check+replace로 fallback하지 않는다.

Windows 전용으로 `os.rename()`를 사용하는 구현을 택한다면 같은 volume의 no-clobber adapter로만 사용하고 copy/delete fallback을 하지 않는다. [Python 3.12 공식 os 문서](https://docs.python.org/3.12/library/os.html#os.rename)는 Windows에서 destination이 이미 존재하면 `FileExistsError`이며, `os.replace()`는 허용되는 기존 파일을 대체한다고 명시한다.

overwrite 승인만으로 조건부 원자 치환이 생기지는 않는다. 승인 당시 destination identity/hash를 실제로 조건부 교환하는 primitive/lock이 확인되지 않은 adapter는 conditional overwrite mode를 unsupported로 둔다. legacy `allow_overwrite=True`를 그 사이 수정된 임의의 내용까지 대체할 권한으로 승격하지 않는다. 예외적으로 사용자가 구체적인 review에서 `overwrite_semantics=replace_any_current_content`, exact path, bounded expiry를 명시 승인하면 그 경로 내용의 무조건 교체를 별 mode로 제공할 수 있다. 이 mode를 hash-CAS라고 부르지 않고 default에는 활성화하지 않는다. 새 이름을 임의로 선택하지 말고 승인된 versioned 경로 범위 안에서만 별 output을 만든다. crash 후 final 파일 hash가 seal된 manifest와 같으면 관측으로 publish 완료를 확정할 수 있고, 다르면 conflict로 멈춘다. 반복 `os.replace`로 이를 해결하지 않는다.

## 7. crash window와 유한 복구

| 중단 지점 | 영속 증거 | 다음 실행의 행동 | 금지 |
|---|---|---|---|
| enqueue 이전 | request ID/token 및 created outbox, runtime claim 없음 | 동일 request identity를 조회; enqueue 여부 불명확하면 상태 확인. predispatch임을 확정한 경우만 같은 durable request를 최초 publish | 새 UUID로 보이지 않는 재시도 |
| enqueue 후 claim 이전 | unique queued file, immutable request | atomic cancel 성공이면 canceled_pre_dispatch; 아니면 receipt 조회 | exists 검사만으로 cancel 성공 주장 |
| claim 직후, dispatch marker 이전 | claimed receipt | 살아 있는 runtime은 취소 intent 처리 가능. runtime 종료가 확정되고 native 진입 전임이 ledger ordering으로 확인된 경우만 rejected/canceled로 finalize | age만 보고 `.processing` 재queue |
| dispatch marker 뒤 실제 apply 이전 | dispatch_started | 실행 여부를 단정할 수 없으므로 unknown; native dispatch 재진입 없음 | exactly-once 성공 또는 미실행 단정 |
| apply 뒤 receipt 이전 | dispatch_started, scene 효과 가능 | 원 native 완료/종료 확인 뒤 read-only 관측; 원 요청 historical result와 reconciliation을 분리 | 자동 rollback/reapply |
| runtime terminal 뒤 ack 이전 | immutable terminal receipt | host restart가 원 nonce로 인증해 결과 수신; host checks/checkpoint를 이어감 | handler 재호출 |
| export 뒤 seal 이전 | staged file + export receipt | export 재실행 없이 해당 staged artifact의 manifest/target 검증 | 존재만으로 성공/publish |
| seal 뒤 publish 이전 | sealed artifact manifest | authorization·destination 조건이 유효할 때만 publish step 수행 | 원 mutation 재실행 |
| publish 뒤 publish receipt 이전 | sealed hash, final artifact 가능 | final hash/path/identity 관측으로 reconcile; 다르면 blocked | 무조건 overwrite 재시도 |
| apply 관측 뒤 checkpoint 이전 앱 crash | runtime receipt 있으나 지속 결과 없음 | checkpoint 없음으로 blocked; 관측된 파일이 정확한 checkpoint임을 증명할 때만 이어감 | 성공했던 step을 암묵적 replay |

unknown 자동 처리는 deadline/횟수 budget 내 bounded polling 후 `blocked`로 종료한다. 영원한 백그라운드 retry를 만들지 않는다. 결과에는 request/run/step ID, 마지막 검증된 phase, snapshot/checkpoint/staging 경로, 가능한 상태 확인·명시 recovery 동작만 남긴다. 새 수동 recovery가 필요할 때 기존 unknown을 실패나 성공으로 덮어쓰지 않는다.

재시작 뒤 observation이 요구 결과·후조건·checkpoint를 모두 증명하면 별 `Reconciliation`에 `reconciled_applied`와 proof를 기록할 수 있다. 원 terminal receipt가 없었다는 사실은 유지한다. 아직 원 runtime가 동작 중이거나 target/lineage를 식별하지 못하면 observation이 비슷해도 재개하지 않는다.

## 8. 함수별 최소 변경 위치

| 파일 | 수정 |
|---|---|
| `models.py` | binding/receipt 모델, v3 fields/errors/status; legacy 표시 fields 유지 |
| `cleanup_workflow.py` | `_read`/`sample` exact coverage·bound reads; 각 `prepare_*`가 SourceBinding 전달; current-state rebind 금지 |
| PR8 `change_flow.py` | prepare source guard→journaled snapshot→lineage; request-bound token; commit receipt 기반 분기; conditional recovery |
| `safety.py` | v3 HMAC payload/domain; token/request/operation/source/snapshot binding; used token을 status 조회할 수 있는 안전한 record 읽기 |
| `bridge_client.py` | durable ID/nonce, request_status/cancel/reconcile, timeout unknown, request metadata 보존 |
| `atomic_queue.py` | durable request identity, non-destructive receipt reads, stale claim requeue 금지 |
| PR8 `runtime.py` | runtime epoch/instance registry, source reader/guard, immutable receipts, request dedup, predispatch vs effect failure, guarded snapshot/rollback |
| PR8 `handler_registry.py` | callback entered/completed + before_write hook; 기존 예외 전파 유지, no-yield는 검증되지 않으면 capability false |
| `handlers/animation.py` | actual write callback의 source guard, target captured ref, exact write readback; evaluation refresh 분류 |
| PR8 `host_postconditions.py` | result identity/receipt 보존; 대상 binding을 붙인 settled readback; runtime completion과 host verification 분리 |
| PR8 `ui_file_flow.py` | action dispatch를 request receipt에 연결; dialog/timeout/MAC failure를 no-effect로 변환하지 않음; staged output manifest |
| `jobs.py`, PR8 `service.py::submit_job/retry_job` | 기존 read job API 유지, mutation job 허용으로 우회하지 않음; unknown/불완전 재시작은 failed 자동 retry와 구분; recipe record는 별도 |
| `verification.py`, `product_catalog.py` | 실제 implementation/fixture/profile bytes hash, loaded runtime fingerprint, evidence schema v3 |
| `paths.py`/설치 manifest | receipt/manifest dirs 및 새 stdlib-only helper 포함; root policy는 PR8 유지 |

## 9. version/evidence 및 migration 계약

runtime handshake는 supported protocol/schema/capability와 실제 loaded adapter fingerprint를 반환한다. v3 host가 v2 bridge와 연결되면 read-only diagnostics는 가능한 범위에서 제공하되 source-bound mutation/recipe는 `UNSUPPORTED_VERSION`으로 명시 거절한다. 위험한 v2 mutation downgrade는 없다.

ChangeToken v3는 signed field를 추가하며 HMAC domain을 `cascadeur-complete-change-v3`로 바꾼다. pending v2 token은 자동 변환/재서명하지 않고 reprepare를 요구한다. `.used`/seen marker는 보존한다. v2 `.processing`/running jobs는 결과가 없으면 legacy_unknown으로 읽고 자동 재시도하지 않는다. legacy snapshot은 automatic ancestor로 채택하지 않으며 수동 import/검증·새 manifest가 필요하다. 기존 `change_prepare/change_commit/change_rollback`, read job tool명은 유지하고 선택 keyword와 상태조회 tool을 추가한다.

실제 code fingerprint는 해당 feature가 사용하는 host adapter, runtime handler/helper, catalog schema, solver, policy-relevant logic의 bytes SHA와 버전, actual fixture bytes, profile, verification implementation hash를 포함한다. 명칭/id만 hash하지 않는다. runtime은 loaded manifest를 보고하고 디스크 파일이 바뀌어도 reload 확인 전 새 loaded fingerprint라 하지 않는다. host/runtime fingerprint 불일치는 mutation 차단이다.

live evidence v3는 application exact build, adapter fingerprint, fixture SHA, inputs/profile, protocol/schema, platform 및 실제 필요한 dependency version, request ID, verified postconditions, final checkpoint/artifact hash에 결합한다. v2 evidence는 기록으로 보존하되 v3 `verified_live` 근거로 자동 승격하지 않는다. 설계 검수 PASS는 어떤 capability도 live verified로 만들지 않는다.

## 10. 후속 구현 시 필요한 최소 직접 검증

현재 수행한 검증은 위 관련 source 정적 읽기뿐이다. 아래는 구현 후 변경 지점만을 대상으로 할 직접 검증 명세이며 지금 실행하지 않았다. 전체 suite/CI/benchmark는 요구하지 않는다.

1. 같은 path/name의 두 live scene object에 서로 다른 instance; wrapper identity 불안정/epoch 변경은 거절. Save As/clone은 검증된 lineage edge만 허용.
2. sample 후 current frame 밖 key 값·interpolation·부모/rig/profile 중 실제 dependency 하나를 바꾸면 dispatch 0. chunk A/B/A 혼합 데이터는 최종 scope 검증에서 거절. content 불일치 source를 새 token으로 승격하지 않음.
3. claimed 뒤 timeout/late ack/host restart에서 request ID와 원 nonce 보존; 같은 request duplicate는 handler count 1 이하. dispatch marker 뒤 crash는 unknown이며 requeue 없음.
4. predispatch SCENE_CHANGED, MAC failure, claimed timeout, terminal partial write 실패를 구분. 첫 세 경우 rollback 0; 마지막은 exact guard/lineage 일치 시 한 번만 recovery. rollback 실패에 재귀 없음.
5. 원 failed branch 대신 다른 탭이 활성화되거나 후속 edit이 있으면 rollback guard 거절. snapshot bytes 변경은 reject. PR8의 실패 tab 보존 확인.
6. token에 포함된 request/source/operation/file/step/lease 중 하나를 바꾸면 consume/runtime execution 거절. 기존 policy·일회용 replay 보호 유지.
7. runtime terminal 성공 뒤 host readback 실패·cancel 요청·checkpoint missing을 원 feature success로 보고하지 않음. result wrapping에 request metadata 유지.
8. export 완료 후 ack loss, seal 후 publish 직전, publish 후 ack loss에서 export 반복/원 mutation 반복이 없고 final hash로만 reconcile. destination 바뀜은 overwrite 금지.

callback/no-yield/scene-wrapper stability/native serializer completion은 실제 Cascadeur adapter evidence가 필요하다. 이는 설계상 미확인 영역을 명시한 것이며 추측으로 통과 처리하지 않는다. 구현 후 해당 adapter의 좁은 live 확인 전에는 자동화 capability가 disabled인 것이 올바른 동작이다. 설계 판정과 실제 제품 동작 검증은 별도로 보고한다.
