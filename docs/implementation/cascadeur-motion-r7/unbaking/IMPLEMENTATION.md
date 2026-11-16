# R7 — unbaking 실제 실행 연결 준비

기준: `muhwagwa0112/cascadeur-complete@99b85163c4125a621ef7e2deeabe22270032c60b`.
이 디렉터리는 **미적용 제품 diff와 설치 leaf 구현 명세**다. native unbaking 완료나
설치 SDK의 미발견 API를 구현했다고 주장하지 않는다. 현재 알려진 세 action의 이름은
아래와 같지만 실제 함수·명시 인수·완료 수명은 아직 근거가 없다.

| step | 기준 제품에 있는 action ID | 필요한 실제 근거 |
|---|---|---|
| `prepare_keys_by_fulcrums` | `View.AutoInterpolation_Keys` | 호출 대상, fulcrum 입력·대상 closure, 실제 작성 key와 완료 |
| `adjust_keys_and_interpolation` | `View.Animation unbaking` | algorithm 인수·구간·보간 쓰기 범위, 완료 및 보존 postcondition |
| `adjust_autoposing_lock_state` | `AutoPosingTool.AutoUnlock` | 실제 lock 소유자·인수, fixation 변경 범위, 완료 |

## 이번 diff에 들어 있는 코드

`product-integration.patch`는 기준 source에 다음 세 파일을 변경/추가한다.

| 제품 target | 구체적 변경 |
|---|---|
| `cascadeur_side/cascadeur_complete/native_unbaking.py` | `step_contract_status()`가 현재 등록된 전용 adapter의 살아 있는 private 계약만 읽는다. 없으면 기존 `qualified=False`를 유지한다. `require_step_contract()`는 source를 확인한 뒤 같은 executor를 반환한다. 기존 topology 비교는 재사용한다. |
| `cascadeur_side/cascadeur_complete/native_unbaking_binding.py` | 새 private adapter 연결 계층. qualification bytes/실행 build/epoch/코드 fingerprint, exact step 계약, source와 원 attempt, 일회 실행, 실제 completion handle, 전체 projection의 허용 범위를 연결한다. |
| `cascadeur_side/cascadeur_complete/handlers/generation.py` | `generation.unbaking`의 `call_action()` fallback을 없애고 같은 등록 executor를 호출한다. 등록되지 않은 leaf는 선택이나 native effect 전에 거절된다. |

현재 `runtime._run_operation()`은 등록된 mutation이면 handler를 거치지 않고
`adapter.execute()`를 직접 부른다. 그래서 handler에 SDK 함수를 붙이는 것만으로는
실제 guarded 경로에 연결되지 않는다. 새 연결 계층은 이 실제 dispatcher를 사용한다.
`src/cascadeur_complete/unbaking_contract.py::require_unbaking_step()`는 이미 step별
proof를 요구하므로 그대로 사용한다. 공개 요청 schema·권한·토큰·receipt 형식을 바꾸지 않는다.

`generation.state.ready_for_unbaking`은 기존 레이어/구간의 기초 상태다. 이 값은
실행 capability가 아니며, enable 여부는 계속 `unbaking_steps[step].qualified`로 판단한다.

## 실제 요청 흐름

1. 설치 native leaf의 **소유 fixture qualification**이 실제 인수·완료·postcondition을
   관측하고 process-private `QualifiedBundle`을 만든다. 이 leaf/helper는 아직 미구현이다.
2. 그 helper가 `install_after_native_qualification(handle)`을 직접 호출한다. 이 함수는
   고정된 코드 모듈 `cascadeur_complete.native_installed_unbaking`만 import한다.
   startup, MCP JSON, 환경변수, 임의 모듈명에서 qualification을 만들지 않는다.
3. 기존 `guards.register_adapter("generation.unbaking", adapter)`가 원 evidence bytes와
   build/fingerprint, `synchronous_no_yield` 계약을 확인한다. 관측을 만들지 않은 선언은
   native leaf가 bundle로 발급할 수 없어야 한다.
4. host의 기존 step preflight, source capture, prepare/commit/confirmation을 거친다.
   `required_scope()`는 native leaf가 관측한 전체 의존 closure를 반환한다.
5. 기존 runtime이 원 요청을 claim하고 `begin_adapter_attempt()` 뒤에 실행한다.
   새 executor는 같은 TLS 요청·operation·source·callback generation을 확인한다.
6. effect 없는 인수 lowering을 마친 `PreparedStep`을 만든다. 최초 effect 직전에 원 source와
   admission을 재확인하고 원 attempt를 소비한다. leaf는 선택 및 각 native write 경계에서
   기존 `guards.before_write()`를 적용한다.
7. 실제 실행이 같은 native 호출 수명 안에서 완료됐을 때만 leaf가 `CompletedStep`을 반환한다.
   원 요청에 연결된 실제 trace 및 postcondition을 검사하고, 새 full projection에 기존
   `compare_projections()`의 key budget·대상 밖 변경 검사를 적용한다.
8. 모두 맞을 때만 `guards.observe_effect(..., "completed")`를 기록한다. durable terminal과
   post-source는 기존 runtime이 발급한다. 이 코드에서 synthetic receipt를 만들지 않는다.

중복 방지용 `_consumed`는 adapter가 속한 현재 runtime epoch 동안 원 request digest를
보존한다. 횟수 상한이나 성공 후 삭제를 추가하지 않으며, 사용한 요청을 다시 실행 가능하게
만들지 않는다. 재시작 뒤의 원 요청 처리는 기존 durable receipt/reconcile 경로가 담당한다.

이 첫 연결은 기존 full-projection source 방식에 한정한다. `qualified_update_boundary`
source를 받으려면 SDK leaf가 실제 Update callback 안에서 현재 source를 확인하는 추가
구현이 필요하므로 이번 adapter는 그 mode를 명시적으로 거절한다. 일반 rig나 대규모 frame
범위를 현재 fixture의 qualification에서 자동 확장하지 않는다.

## 미구현 설치 leaf의 정확한 내부 인터페이스

다음은 **새로 구현할 제품 내부 Python 인터페이스**다. Cascadeur SDK에 이 이름의 함수가
있다는 뜻이 아니다. 이 파일의 empty stub나 성공을 반환하는 대체 구현을 포함하지 않는다.

대상 파일: `cascadeur_side/cascadeur_complete/native_installed_unbaking.py`.
`QualifiedBundle`, `PreparedStep`, `CompletedStep`은 그 모듈이 직접 소유하는 타입이어야 한다.
JSON/dict/digest는 이 객체를 대신할 수 없다. 발급·소비는 원 private registry에서 확인한다.

| 함수 | 인수와 반환/책임 |
|---|---|
| `take_qualified_bundle(qualification_handle)` | 실제 owned fixture helper의 원 private handle → retained `QualifiedBundle`. 이전 epoch·다른 build·실패한 probe·caller dict를 거절한다. |
| `qualification_bytes(bundle)` | 실제 qualification의 원 bytes. 이후 변경하지 않는다. |
| `adapter_verification(bundle)` | 기존 `guards.register_adapter` 계약의 dict. `operations`는 정확히 `["generation.unbaking"]`. `identity_stable`, dispatch semantics는 probe의 실제 관측이어야 한다. |
| `step_contracts(bundle)` | 성공한 step만 키로 가진 dict. 각 항목은 아래 identity와 5개 digest를 가진다. 미확인 step을 포함하지 않는다. |
| `bundle_is_current(bundle)` | retained callable/SDK code identity, 원 source pins, build/epoch/loaded fingerprint, 관측의 revoke 여부를 읽어 현재 유효할 때만 `True`. native 작업이나 fixture를 실행하지 않는다. |
| `required_scope(bundle, scene, scope)` | 실제 controller/rig/layer/parameter/dependency closure를 확인하고 기존 scope dict 반환. object 이름이나 호출자의 complete flag로 추정하지 않는다. |
| `capture(bundle, scene, scope)` | 기존 `coverage_complete`/`sample_projection`/`authored_projection` 계약. `coverage_complete=True`는 qualified reader가 확인한 closure에만 사용한다. |
| `prepare_step(bundle, scene, arguments, request, identity)` | effect 없는 explicit lowering → `PreparedStep`. 실제 callable·인수·target·원 projection·정책·요청을 private하게 보관한다. |
| `prepared_step_matches(bundle, prepared, scene, arguments, request, identity)` | 바로 그 prepared handle과 원 요청·scope가 같을 때만 `True`. |
| `execute_step(bundle, prepared, attempt)` | 관측된 SDK 함수로 한 번 실행. 각 effect 경계에서 admission/source/target을 확인한다. 실제 선택을 사용한다면 exact selection을 확인하고 원 선택 복원도 허용 효과와 completion 범위에 포함한다. 성공 시 `CompletedStep`; 미확정이면 예외로 남긴다. |
| `consume_completed_step(bundle, completed, identity)` | 실제 native callback/return 수명과 semantic postcondition을 확인한 원 완료 handle을 일회 소비하고 아래 완료 dict를 반환한다. 소비 후에도 trace는 폐기하지 않는다. |
| `completed_step_is_current(bundle, completed, identity)` | 소비한 원 trace가 유지되며 callback 수명이 닫혔고 변경·revocation이 없을 때만 `True`. digest 문자열만 비교하는 함수로 구현하지 않는다. |
| `validate_failure_observation(bundle, scene, request, ref)` | 기존 `native_completion._checked_record()`가 요구하는 원 private failure record를 검증한다. 완료가 입증되지 않으면 record를 발급하지 않는다. |
| `failure_observation_revoked(bundle, ref)` | 원 실패 trace의 생존·revoke 상태를 반환한다. 늦은 callback/범위 이탈을 기존 native completion quarantine에 전달한다. |

Step 계약의 identity는 `step`, `action_id`, 실제 `installed_build`, `runtime_epoch`,
`runtime_fingerprint`, `dispatch_semantics="synchronous_no_yield"`다. digest는 다음 다섯 개다.

- `installed_callable_digest`: 실제 설치 callable과 관련 source/loaded code identity의 결합.
- `lowering_digest`: 검증한 명시 인수 변환 및 허용 domain.
- `completion_contract_digest`: 해당 invocation에 상관된 완료와 닫힌 native 효과 수명.
- `postcondition_contract_digest`: 해당 step의 의미 있는 결과 검증식과 비교 domain.
- `qualification_digest`: 실제 소유 fixture의 원 관측. caller가 제출한 문자열을 인증하지 않는다.

완료 dict는 `step`, `request_digest`, `operation_digest`, `original_source_digest`,
`runtime_epoch`, `runtime_fingerprint`, `installed_build`, `callback_generation`,
`scene_before`, `scene_after`, `completion="completed"`, `postcondition="matched"`,
`before_projection_digest`, `after_projection_digest`, `completion_contract_digest`,
`postcondition_contract_digest`, `native_trace_digest`를 반환한다. 새 executor가 원 request와
독립 readback에 대조한다. 반환 dict는 외부 입력이 아니라 원 `CompletedStep`의 private 조회다.

실제 SDK leaf는 원 request/attempt에 묶인 trace observer를 terminal 뒤에도 유지해야 한다.
닫혔다고 관측한 수명 뒤에 callback이나 효과가 발견되면 보관한 원 request 객체로
`guards.revoke_adapter_observation(request, reason)`을 호출한다. 기존 native completion이
sealed success의 revoke를 epoch quarantine으로 처리한다. 성공 반환 뒤 observer를 끊거나
현재 scene을 다시 읽어 과거 완료를 재발급하는 구현은 이 계약에 맞지 않는다.

`compare_projections()`의 `native_completion="unverified"`는 projection 비교만의 상태로
그대로 남긴다. 실제 native 완료는 별도 private trace에서 입증한다. 그 필드를 `observed`로
바꿔 topology 비교를 완료 증거로 승격하지 않는다.

## 설치 환경에서 먼저 확보해야 하는 입력

R6 기록은 선택한 SDK 선언 29개를 찾았지만 세 action의 실제 등록을 찾지 못했다고 명시한다.
새 수집기를 반복 실행하는 것만으로 이 공백이 없어지지 않는다. 필요한 입력은 다음과 같다.

1. 위 세 exact action ID 각각의 실제 등록 소유 source/compiled entry와 callback 대상.
   이미 식별한 파일만 지정하고 source bytes/hash·배포 build를 함께 보관한다.
2. callback이 읽는 실제 인수, selection·frame·rig·fulcrum·tool state, 추가 controller/child-layer
   확장 규칙. 글로벌 UI 상태를 암묵 입력으로 남기지 않는다.
3. 동일 invocation에 연결되는 실제 종료 신호와 효과가 더 이상 발생하지 않는 시점.
   `call_action()` 반환, scene revision 변화, 동일 projection 반복 관측, 고정 sleep은 제외한다.
4. step별 실제 의미 결과: fulcrum에 따른 key 위치·개수/보존, 키와 보간 변경·보호 구간,
   대상 AutoPosing fixation 상태 및 비대상 보존. native completion과 품질은 별개로 확인한다.

설치 소스가 opaque UI action만 노출하고 완료 수명을 관측할 수 없으면 현 guarded runtime의
동기 계약에 연결할 수 없다. 실제 공개된 lower-level 동기 API가 있으면 그것을 사용하는
별도 leaf를 구현한다. 비동기 경로만 가능하면 native claim을 보존하는 별도 pending/terminal
상태 설계가 선행돼야 한다. 이 문서의 동기 adapter에 event-loop 재진입·sleep·자동 클릭으로
완료를 끼워 맞추지 않는다. 기존 sparse fitting 결과를 native unbaking 성공으로 표시하지 않는다.

## 나머지 구현 순서와 완료 조건

1. 세 action 중 실제 source/arguments/completion이 확인된 step부터 위 leaf를 구현한다.
   미확인 step은 `qualified=False`다. 이 단계에서 SDK 함수명이나 버전 fallback을 추측하지 않는다.
2. 기존 `incident_setup.py`의 코드 소유 helper 패턴에 **명시적으로 승인된 유한 unbaking
   qualification helper**를 추가한다. 실제 native 알고리즘의 효과 상한이 확인된 뒤에만
   필요한 tab/file/frame/key 최대치를 작성한다. 이번 diff는 미확인 상한이나 helper ID를 등록하지 않는다.
3. 해당 helper가 원 fixture/source·전후 projection·세부 target·native trace를 보관하고 private
   bundle을 발급한 뒤 `install_after_native_qualification()`에 넘긴다. probe 실행과 제품 요청을
   섞지 않는다. 새 공개 도구를 만들지 않고 기존 setup/prepare/commit 흐름에 연결한다.
4. 실제 제품 요청 한 건에서 preflight → original source → native attempt → step 결과 →
   원 terminal → fresh evaluation/capture로 이어지는 연결을 확인한다. 실제 key/보간/lock 결과와
   non-target 보존을 확인해야 완료이며, native 성공 자체를 최종 모션 품질 pass로 사용하지 않는다.
5. native 예외·불명확 완료는 원 요청을 보존한다. leaf가 실제 completed failure를 관측한 경우에만
   기존 `guards.bind_failure_observation(attempt, ref)`를 호출한다. 이때 R7 recovery 경계로 넘어간다.
   exception이나 timeout만으로 rollback permit을 만들지 않는다.

구현 후 필요한 직접 사례는 각 구현 step의 실제 target 실행, 보호 범위 위반 거절, 원 요청 재실행
거절, 완료가 없는 native 결과의 unknown 보존이다. 전체 회귀·반복 qualification·CI 실행을
완료 절차로 추가하지 않는다. 이번 packet에서는 실행하지 않았다.

## 기준 코드

- [현재 unconditional step 차단](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_unbaking.py)
- [원 action/selection handler](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/handlers/generation.py)
- [실제 registered adapter dispatch/terminal 분류](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/runtime.py)
- [원 native attempt·private failure 검증](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_completion.py)
- [host의 기존 step preflight](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/unbaking_contract.py)
