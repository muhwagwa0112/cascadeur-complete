# 실행 완료·결과 오류·복구 자격을 연결하는 변경안

기준: `fc0e98eaa30e819f98880a32dce30c6767a5cc64`. 상태: **코드 수준 설계와 미적용 패치**. 아래 신규 함수는 제안이다. 현재 SDK에 존재하는 함수라는 뜻이 아니며, 아직 저장소·앱에 적용하지 않았다.

## 1. 이번에 고칠 정확한 연결

현재 세 문제가 연속된다.

1. `native_key_insertion.insert_positions()`는 `domain.modify` 반환·callback 완료를 검사한 뒤에도 projection mismatch를 공통 `except`에서 `unknown`으로 만든다.
2. `runtime._run_operation()`는 adapter가 실제로 발급한 `completed` 실패 관찰이 있어도 뒤에 `unknown`을 추가한다. `execute_request()`는 마지막 관찰을 사용한다. 삽입뿐 아니라 `native_independent_position._observe_failed_write()`가 이미 발급하는 private 실패 관찰도 영향을 받는다.
3. `_execute_request_impl()`가 오류를 `_error()`로 바꾸면 `result=None`이다. 이후 `execute_request()`는 `result`가 dict인 경우에만 `post_source_binding`과 native 관찰을 넣는다. 알려진 실패의 after를 읽어도 recovery 함수가 그 근거를 받지 못한다.

근거: [삽입 코어](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/native_key_insertion.py), [runtime](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/runtime.py), [기존 position 실패 attestation](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/native_independent_position.py).

수정은 **미래 요청**에 적용한다. 두 원 terminal unknown을 이 새 판정기로 다시 분류하지 않는다. 원 receipt의 hash·MAC·token·budget은 그대로다.

## 2. 내부 데이터 계약

wire의 `succeeded / failed_after_dispatch / outcome_unknown / rejected_pre_dispatch`를 유지한다. 새 private 관찰 record는 native 패키지 안에만 존재한다.

```python
# Proposed private record. Canonical bytes are stored once; no wire constructor.
FailureObservation = {
    "contract": "completed_native_failure_v1",
    "request_digest": ...,       # original signed request, including its identity
    "operation_digest": ...,
    "original_source_digest": ...,
    "runtime_epoch": ...,
    "runtime_fingerprint": ...,
    "installed_build": ...,
    "scene_before": ...,
    "scene_after": ...,
    "callback_generation": ...,
    "completion": "completed",  # or privately proven no_effect; never phase inference
    "postcondition": "mismatched",
    "before_projection_digest": ...,
    "expected_projection_digest": ...,
    "actual_after_digest": ...,
    "actual_effect_scope_digest": ...,
    "native_contract_evidence_digest": ...,
    "native_transaction": ...,
    "post_source_digest": None,  # optional; unknown scope cannot issue a normal SourceBinding
    "recovery_contract_digest": None,
    "primary_error": {"type": ..., "message": ...},
}
```

`completed`를 발급하려면 같은 build·loaded bytes·operation에 대해 다음을 모두 검증한다.

- 호출·callback·setter 수명과 지연 효과가 닫혔다. `modify=True`, callback 한 번, `finish_write()`만으로 일반적인 native 완료를 증명하지 않는다. 확인된 finite sync 계약과 해당 요청의 실제 trace가 함께 필요하다.
- 원 request/source와 현재 scene identity/epoch가 맞는다. callback 재진입·다른 thread·late callback은 관찰을 무효화한다.
- actual after를 complete reader로 읽고 실제 변경 closure를 판별할 수 있다. `after != expected`는 오류이며, 충분한 완료 증거가 있을 때만 known failure가 된다.
- 원 projection 범위를 벗어난 객체·외부 파일·지연 효과의 가능성을 닫지 못하면 `unknown`이다. 비대상 section 변경이 관측 가능한 전체 closure 안에 있으면 known failure일 수 있으나 복구 자격은 별개다.

`write_phase=not_started`는 `no_effect` 증거가 아니다. pre-native validation failure를 무변경으로 판단하려면 adapter의 검증된 경로에서 native 진입이 없었고 어떤 효과도 시작되지 않았다는 private record가 필요하다. 예외 객체의 사용자 추가 attribute, public `verified=True`, 같은 hash 모양의 문자열을 증거로 쓰지 않는다.

## 3. `guarded_runtime.py`의 신규 내부 함수

| 제안 시그니처 | 구현 책임 |
|---|---|
| `begin_adapter_attempt(request, operation, adapter, scene) -> AttemptHandle` | 현재 TLS request와 등록 adapter identity 확인. 원 request/op/source digest, epoch/fingerprint, scene identity, 시작 effect index를 고정. handle은 process-private registry에서만 생성. |
| `bind_failure_observation(handle, adapter_record_ref) -> ObservationHandle` | 정확한 등록 adapter의 private validator를 호출. 실제 trace·scope·after·현재 callback generation을 확인한 관찰만 연결. public dict를 승격하지 않음. |
| `lookup_failure_observation(handle, scene, request) -> dict | None` | private record lookup, canonical bytes·원 request·adapter·generation·live trace 검증. 사후 변경/무효화/다른 attempt면 None. 기존 관찰 원본을 참조하므로 late callback 무효화를 감추지 않음. |
| `selected_effect_for_request(request, scene) -> dict | None` | 해당 요청에 결합된 관찰만 선택. 같은 요청의 unknown/revocation은 completed보다 우선. 상충하는 복수 관찰은 unknown. 단순 `effects[-1]` 또는 operation name 일치만으로 선택하지 않음. |

`observe_effect()`의 기존 반환 dict는 진단용으로 유지할 수 있다. private provenance는 별 registry/TLS에 둔다. 일반 dict를 복사하여 새 완료 근거로 받아들이지 않는다. `begin_request()`는 요청별 선택 상태를 초기화하되 이미 발급한 private record와 revocation 연계를 없애지 않는다. operation이 끝나면 이후 요청에서 재사용할 수 없도록 handle을 소비한다.

현재 성공 adapter 전부를 새 인터페이스로 재작성하지 않는다. 먼저 변경 대상인 insertion·independent-position의 **오류 경로**에 새 contract를 적용한다. 다른 adapter가 private validator를 제공하지 않으면 이 경로에서 completed 실패로 승격하지 않는다. 기존 성공·완료 관찰 계약은 유지한다.

## 4. `runtime._run_operation()` 변경 본문 설계

아래는 새 내부 함수를 추가한 뒤 연결할 본문이다. 현재 코드에 그대로 붙여 실행할 수 있는 단독 패치가 아니다.

```python
def _run_operation(scene, operation, request):
    name = operation.get("name")
    adapter = guards._ADAPTERS.get(name)
    if not (_operation_is_mutating(operation) and adapter is not None):
        return _run_operation_legacy(scene, operation, request)

    before = dict(guards.scene_instance(scene))
    handle = guards.begin_adapter_attempt(request, operation, adapter, scene)
    try:
        return adapter.execute(scene, operation.get("arguments") or {}, request)
    except Exception as exc:
        # A lookup failure must retain the primary executor exception.
        observation = guards.lookup_failure_observation(handle, scene, request)
        if observation is None:
            guards.observe_effect(
                name, "unknown", scene_before=before, scene_after=None,
                detail={"error": str(exc)[:500],
                        "reason": "PRIVATE_FAILURE_COMPLETION_UNAVAILABLE"},
            )
        # A valid existing observation stays selected; no second fallback is
        # appended. The final classifier rechecks revocation before sealing.
        raise
```

`lookup_failure_observation()` 자체의 검증 오류는 내부에서 `None`과 별 diagnostic으로 반환한다. SDK를 재실행하거나 본래 예외를 덮어쓰지 않는다. source/scene 재읽기가 실패해도 그 오류는 추가 진단으로 남기고 원 오류를 유지한다. 원 writer가 private `no_effect` 관찰을 발급한 경우도 동일한 검증 경계를 통과해야 한다.

기존 position writer에서는 `_observe_failed_write()`가 만드는 `_failure_evidence_bytes`, `_failure_trace`, request/after digest 검사 로직을 **하나의 private validator**로 분리하여 wrapper lookup과 `prepare_recovery_binding()`에서 재사용한다. 복구 adapter 유무를 완료 판정의 선행 조건으로 만들지 않는다. 복구가 미지원이어도 실행 완료가 알려진 실패는 표현할 수 있어야 한다.

## 5. 삽입 코어와 adapter의 변경

### `native_key_insertion.insert_positions()`

`domain.modify()` 완료 검사 직후 native completion 후보와 trace snapshot을 보관한다. `after`를 한 번 완전히 읽어 actual digest/실제 변경 closure를 기록한다. 기대 projection mismatch가 발생하면 primary error와 actual after를 함께 보관한다.

private validator가 위 2절 조건을 만족시키면 `_SOURCES[source_id].state="completed_failure"`와 `after`, `failure_observation_ref`를 기록한다. 나머지는 기존 `state="unknown"`이다. 성공은 기존 `"completed"`를 유지하여 success proof 소비자를 불필요하게 바꾸지 않는다.

공통 `except`는 무조건 unknown으로 덮지 않는다. 같은 source/attempt에 이미 발급된 valid completed-failure record를 조회하여 해당 관찰을 유지한다. 불완전한 callback·setter exception·수명 불명·read failure는 unknown으로 남긴다. late callback은 현재처럼 callback generation을 올리고 qualification/관찰을 무효화한다. 새 qualifier의 성공 사례만으로 실패 수명 계약을 만들어서는 안 된다.

### `NativeKeyInsertionAdapter`

신규 내부 메서드 제안:

```python
def validate_failure_observation(self, scene, request, record_ref): ...
def capture_known_failed_after(self, scene, request, record_ref): ...
```

두 메서드는 core의 private `_SOURCES` record를 lookup하고 request/source/scope/epoch/fingerprint/trace/after를 검증한다. `record_ref`는 index일 뿐 권한이 아니다. `execute()`는 `try/except`에서 이 lookup을 호출하여 현재 attempt에 실패 record를 연결한 후 **원 예외를 다시 던진다**.

`_completed`를 성공·known-failure 두 종류의 consumed observation으로 확장하되 두 권한을 분리한다.

- 성공 record: 기존 정확한 successor capture·topology proof를 유지한다.
- known-failure record: actual after가 **원 closure 안에 완전히 포함되고 원 snapshot/scope와 같다는 검증**을 통과할 때만 원 scope의 post_source를 발급한다. 삽입 전의 absent-key 검사를 다시 적용하지 않는다. `execute()`는 consumed record가 있는 source를 성공/실패 여부와 관계없이 재실행 거절한다.
- 원 closure 밖 변경: ordinary SourceBinding을 발급하지 않고 별 `failed_after_observation`에 actual digest/비대상 변경을 남긴다. 완료가 알려졌다면 failed_after_dispatch는 유지하지만 `recovery_eligible=False`이고 자동 continuation은 중단한다.

`prepare_recovery_binding()`은 이미 `NativeSceneAdapter`에 상속되어 있다. 없는 메서드를 새로 채우는 문제가 아니다. 삽입용 private 실패 attestation과 같은 원 scope의 post_source가 준비되면 기존 상속 위임을 재사용한다. 현재 position writer의 `synchronous_returned_write_prefix_exact_projection_v1` 증거는 LINEAR→STEP section rewrite에 재사용하지 않는다.

`native_key_insertion_evidence.finalize_insertion()`/`verify_key_topology()`는 기존대로 **원 succeeded terminal**만 인정한다. known failure·retirement·후속 observation으로 성공 topology proof를 발급하지 않는다.

## 6. 오류 결과 보존과 terminal 순서

적용 가능한 작은 초안은 `patches/01-runtime-error-observation-payload.patch`에 있다. changed code는 effectful dispatch 이후의 오류 `result=None`만 dict로 정규화한다. 성공 응답·pre-dispatch 오류는 바꾸지 않는다. 이 패치만으로 unknown이 해소되지는 않는다.

전체 통합 순서:

1. `_execute_request_impl()`의 원 오류 code/message/trace를 보존한다.
2. effectful dispatched 실패에서 `result=None`이면 `error_details` dict를 만든다.
3. selected private failure의 actual after와 가능한 post_source를 붙인다. source capture 실패는 `post_source_error`와 warnings로 기록한다. 이미 있는 원 executor 오류를 capture 오류 한 줄로 지우지 않는다.
4. 현재 request와 연결된 private 관찰을 다시 검증하여 outcome을 정한다. `write_phase`나 `result.ok`만으로 completed를 만들지 않는다.
5. 원 code-owned 실패 attestation·같은 scope의 post_source·immutable checkpoint·qualified restore를 모두 만족할 때만 recovery binding 후보를 만든다. 실패 시 False를 유지하고 이유를 남긴다.
6. 최종 result를 원 terminal receipt에 한 번 봉인한다. result에 **그 receipt 자신의 digest**를 넣지 않는다. 실패 record digest/reference까지만 포함한다.
7. durable terminal 이후 private 실패 record에 receipt digest를 연결한다. 실제 rollback 실행은 기존과 같이 원 terminal MAC/request/result digest를 다시 검사한다. terminal 쓰기 실패는 미해결 상태이며 재dispatch하지 않는다.

중간 crash에는 기존 queue의 원 요청 조회만 허용한다. partial finalization 때문에 새 요청으로 원 효과를 다시 실행하지 않는다. callback revocation이 terminal 직전에 발생하면 unknown으로 봉인한다. 이미 발행한 terminal 뒤에 계약 위반 callback이 발견되면 원 terminal을 수정하지 않고 별 incident로 runtime epoch를 차단한다.

## 7. 판정표와 자동화 동작

| 검증된 관찰 | 결과 | 다음 동작 |
|---|---|---|
| dispatch 전 거절 | rejected_pre_dispatch | 원 요청은 미실행. 새 입력/계획은 별 승인·식별자로 처리 |
| dispatch됐으나 private no-effect 증명 | failed_after_dispatch, recovery=False | 실패 원인을 반환. 자동 환급/재시도 정책을 새로 만들지 않음 |
| native 완료·closure 관측, 결과 mismatch | failed_after_dispatch | 복구 자격 별도 계산. 원 run은 실패/차단이며 성공 continuation 금지 |
| 완료·closure·수명 중 하나 불명 | outcome_unknown | incident 경로만. 같은 효과 replay 금지 |
| native 완료+postcondition 만족 | succeeded | actual motion quality·export 판정은 기존 별도 단계 |

known failure를 얻어도 실패한 workspace를 다음 recipe의 입력/게시물로 자동 채택하지 않는다. 복구 후에도 원본 intent/quality anchor를 유지한다. 복구 미지원이면 명시적인 새 작업 계획에서 검증된 baseline을 선택한다. 별 incident의 scoped admission 조건과 연결하며, unknown을 다른 이름으로 바꿔 우회하지 않는다.

`reference_completion_policy.py`는 이 표의 **순수 결정 로직**이다. hash 형식과 입력 일관성을 확인할 뿐 실제 MAC·SDK·private evidence를 인증하지 않는다. 반환 `authority=False`는 의도적이다. 제품이 이 결과를 그대로 dispatch 허가로 읽는 통합은 금지한다.

## 8. 최소 직접 검증 명세 — 아직 실행하지 않음

| 사례 | 변경 후 기대값 |
|---|---|
| 실제 로직을 호출하는 adapter-bound 완료 실패 + wrapper exception | private 관찰 뒤 fallback unknown을 추가하지 않음; failed_after_dispatch |
| 오류 envelope의 `result=None` + valid post_source | error_details와 post_source/native_effect_observations가 같이 보존 |
| 같은 phase=completed, private 완료 proof 없음 | outcome_unknown |
| cross-request/source/epoch/adapter record, 임의 exception attribute | record 거절; unknown; 복구 False |
| lookup 후 terminal 전에 callback generation 변경 | unknown; 기존 success/failure proof 재사용 불가 |
| insertion after가 성공 예상과 다르지만 finite complete closure 안 | known failure 가능; topology success proof는 없음 |
| 비대상 section 변경에 position-prefix attestation 제공 | 복구 거절; 원 오류·actual delta 유지 |
| 실패 after source 발급 후 같은 insertion 재호출 | consumed source 거절; setter 호출 증가 0 |
| failed result + matching failure attestation + qualified restore | recovery 후보만 발급; 실제 restore는 원 durable terminal 확인 후 별 요청 |

제안 테스트 파일은 구현 시 `tests/test_native_failure_observation.py`를 최소 사례로 추가하거나 기존 관련 fixture를 재사용한다. 아직 이 파일/테스트가 저장소에 존재하지 않는다는 점을 명시한다. 실행 시 예시 범위는 `pytest tests/test_native_failure_observation.py -q --tb=short` 한 파일이며, 해당 구현에 실제 생성된 case 이름만 사용한다. host 복구 연결을 바꾸었을 때만 기존 `tests/test_recovery_boundary.py`의 직접 관련 case를 필터한다. 이 준비 작업에서 pytest·전체 suite·CI·실앱은 실행하지 않았다.

## 9. 구현과 native 증거의 구분

코드로 지금 준비 가능한 것은 private 타입/selector, 오류 payload, core/adapter 상태 분기, 후속 source와 복구 연결이다. **삽입의 특정 실패가 no-pending-effect와 완전한 actual closure를 갖는다는 native 사실은 코드 작성으로 대신할 수 없다.** 현재 실제 LINEAR→STEP 사건에 새 증거가 있다고 선언하지 않는다. 증거 없는 경로는 unknown을 유지하면서 incident에서 독립 작업 재개를 처리한다.

host는 `pyproject.toml`상 Python `>=3.12,<3.13`, bridge는 기존 Python 3.11 호환 스타일을 유지한다. 새 의존성을 추가하지 않는다. 신규 내부 record/journal 또는 공개 반환 계약을 실제 제품에 적용할 때는 구체적인 diff와 함께 해당 schema/API 변경 범위를 승인받는다.
