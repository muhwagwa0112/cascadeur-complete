# R7 복구: 저장된 승인으로 최초 dispatch 이어가기

기준: `muhwagwa0112/cascadeur-complete@99b85163c4125a621ef7e2deeabe22270032c60b`.
이 디렉터리는 **미적용 제품 diff**와 남은 실제 복구 작업의 구현 명세다.
새 public API·wire schema·설정·의존성은 추가하지 않는다.

## 현재 구현과 이번에 확인한 빈 구간

기존 `NativeIndependentPositionAdapter._observe_failed_write()`는 실제로 반환한
native transaction, 정확히 완료한 setter prefix, 전체 projection과 현재 source를
관측한다. 이 경로가 존재하는데도 partial-write attestation 전체가 미구현이라고
기록하면 잘못이다. 현재 미확인은 **실제 실패 → 인증된 실패 terminal → 별도 recovery
permit → 실제 복원 → host의 복원 결과 확인**을 한 실행으로 통과한 기록이다.

기존 `NativeCheckpointRestoreAdapter.execute()`와 `recovery_succeeded()`는 실제
새 탭 복원·P0 비교·파일 bytes·원 receipt·permit·후속 source를 이미 연결한다.
이번에는 이 로직을 다시 작성하지 않는다.

`ChangeFlowMixin._restore_failed_change()`는 `attempt.claim` 뒤 승인 준비를 한다.
`prepare_rollback()`이 signed `prepared.json`과 실제 confirmation token을 저장한 뒤,
`dispatch.json`을 쓰기 전에 호스트가 종료되면 다음 호출은 존재하지 않는 recovery
request를 조회만 한다. 따라서 **아직 최초 dispatch를 하지 않은 유효한 승인**이 있어도
계속 막힌다. `product-integration.patch`는 이 한 구간을 연결한다.

## 실제 코드 변경

제품 대상은 `src/cascadeur_complete/change_flow.py` 하나다.

1. `_rollback_internal()`은 기존 `prepare_rollback()` 성공 뒤 새 private 함수
   `_dispatch_prepared_recovery(journal, permit)`를 호출한다.
2. `_restore_failed_change()`의 이미 claim된 owner 경로는 `prepared.json`이 있을 때만
   같은 private 함수를 호출한다. 새 승인·permit·request ID를 만들지 않는다.
3. private 함수는 signed permit/prepared의 원 실패 ID, recovery ID와 permit digest를
   대조한다. dispatch 기록이 있거나 원 request가 이미 ledger에 있으면 기존
   `client.reconcile_request()`로만 이동한다.
4. 미사용 token을 `ChangeManager.load()`로 읽어 schema 3, rollback operation,
   source, arguments, request ID, execution context를 원 permit과 대조한다.
   consumed token이면 조회만 한다. 만료되거나 사라진 token은 다시 발급하지 않는다.
5. 원 실패 request와 authenticated terminal을 다시 읽고 기존
   `recovery_candidate()`, 현재 source 검사와 `verify_snapshot()`을 재사용한다.
   원 epoch/scene/projection/checkpoint가 달라지면 최초 dispatch도 거절한다.
6. 기존 immutable `dispatch.json`을 exclusive하게 생성한 한 호출만 기존
   `commit_change()`로 진행한다. 경합에서 늦은 호출은 원 recovery ID를 조회한다.
   token 소비와 native `native-restore.claim`은 기존 구현을 그대로 사용한다.

`request_status`와 `request_reconcile`은 계속 읽기 전용이다. 이번 최초 dispatch
이어가기는 원 실패에 결합된 **effectful** `reconcile_consumed_change()` / conditional
recovery 경로에서만 가능하다. 기존 recipe의 취소 처리와 실행 grant 검사를 우회하지 않는다.

## 중단 시점별 동작

| 보존된 상태 | 이어갈 동작 | 생성하지 않는 것 |
|---|---|---|
| claim만 있고 permit/prepared 없음 | `blocked_recovery_owner_unresolved` 보존 | 새 owner·새 permit |
| permit만 있고 prepared 없음 | 같은 recovery ID 조회, 미확정 보존 | 새 token·새 request |
| prepared 있음, token 미사용, dispatch 없음, 현재 원 source와 permit 유효 | 그 token의 최초 dispatch 한 번 | 재승인·추가 ID |
| prepared 있음, token 만료·현재 source 변경 | 거절, 원 기록 보존 | TTL 연장·다른 scene으로 전환 |
| dispatch 있음 또는 token 소비됨 | 같은 recovery ID의 원 receipt 조회 | native 재호출 |
| 복구 request의 terminal이 실제 실패 | `recovery_failed` | 재귀 복구 |
| 복구 request pending/unknown | `blocked_recovery_outcome_unknown` | 추정 성공·추정 실패 |
| 복구 성공과 실제 복원 검증 통과 | 원 작업의 실패 outcome 유지, `recovery_state=recovered` | 원 실패를 성공으로 변경 |

처음 `dispatch.json`을 쓴 뒤 실제 queue enqueue 전에 호스트가 종료되는 경우는 이번에
열지 않는다. 이 구간은 이미 dispatch intent가 있으므로 조회만 한다. claim·dispatch
파일 부재만으로 native effect가 없다고 추정하거나 기존 unknown을 replay하지 않는다.

## 남은 native 복구 구현·실행

### 일반 캐릭터 writer의 failure observer

캐릭터 writer와 unbaking writer가 추가되면 각각 다음 private contract를 자신이 실제
관측한 setter/transaction에 결합해야 한다. 기존 independent-position observer를
그대로 범용 등록하거나 `recovery_eligible=True`를 임의로 넣지 않는다.

- `begin_adapter_attempt()`의 실제 request identity와 invocation에 관측을 결합한다.
- 실제 native callback 진입/종료 횟수, 실행 thread, native 반환값, 완료된 write prefix를
  기록한다. 예외가 난 setter 또는 반환 후 callback 가능성이 있으면 `unknown`이다.
- 새 character projection reader로 원 immutable baseline과 실제 write prefix의 결과를
  비교한다. controller/constraint의 파생 변화도 관측된 closure에 포함해야 한다.
- `validate_failure_observation()`은 원 request object, epoch, loaded bytes, 전체
  after projection과 현재 source를 다시 확인한다. 이후 callback이 관측되면 폐기한다.
- 원 실패 terminal을 seal하기 전 `prepare_recovery_binding()`이 실제 checkpoint를
  확인해 rollback source를 발급한다. 원 terminal이 durable해진 뒤에만 host permit을 쓴다.
- 현재 native transaction이나 callback이 진행 중이면 복원을 시작하지 않는다.

### 실제 실패 사례를 연결할 실행 지점

기존 `native_independent_position.py`의 성공 qualification은 실패 증거를 만들지 않는다.
동일 원칙으로 새 캐릭터 경로도 성공한 write에 가짜 오류를 붙여 recovery 자격을 주지 않는다.
실제 허용된 disposable workspace에서 발생한 반환 완료 후 오류가 있다면 그 원 request와
private trace를 사용한다. native가 진행 중이거나 완료 여부가 불명인 오류는 이 경로의
성공 사례가 될 수 없다.

필요한 원자료는 원 signed request/terminal, 정확한 post-source, checkpoint manifest와
파일, 원 실패 adapter trace, 실제 recovery request/terminal, restored source·P0 관측과
파일 hash다. 기존 열한 legacy unknown은 이 자료로 소급 변경하지 않는다. 현재 producer
관측의 `observed_partial_v1` / `closure_authority:none`도 producer 종료 증거로 승격하지 않는다.

## 적용 뒤 이 변경에 직접 필요한 확인

신규 전체 테스트나 반복 gate를 만들지 않는다. 실제 적용 시에는 변경 구간의 두 상태만
대상으로 한다: 저장된 미사용 승인 뒤 종료한 host의 **최초 dispatch가 정확히 한 번**
이어지는 경우, dispatch 기록이 이미 있거나 token이 소비된 경우 **native를 재호출하지 않고
원 request만 조회**하는 경우. 원 실패 후 native 복원 관찰은 별도 실앱 사례이며 이번
정적 코드 준비와 구분한다.

## 소스 근거

- [기존 host 복구 경로](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/change_flow.py)
- [기존 native failure observer](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_independent_position.py)
- [기존 native 복원](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_checkpoint_restore.py)
- [기존 host 복원 판정](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/recovery.py)
