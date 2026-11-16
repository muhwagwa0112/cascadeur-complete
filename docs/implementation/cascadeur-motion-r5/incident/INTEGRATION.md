# Incident 원장과 admission — 구현 직전 계약

## 범위와 승인 경계

기준 HEAD: `fc0e98eaa30e819f98880a32dce30c6767a5cc64`, branch `feat/cascadeur-motion-r3`.

이 문서와 `reference_incident_policy.py`는 **설계 참조**다. 제품 소스를 변경하지 않았고 제품 import·테스트·SDK·설치·push를 실행하지 않았다. packet의 정적 확인 결과는 상위 `VERIFICATION.md`에 별도로 기록한다. 아래 신규 journal/sidecar schema, control API, native admission 변경은 **적용 및 실행 승인 대상**이다. `BridgeRequest`, `RequestReceipt`의 기존 wire shape와 `succeeded`/`failed_after_dispatch`/`outcome_unknown` enum은 유지한다.

선택한 안은 **원 signed request에 결합한 별도 admission sidecar**다. protocol 전체 교체는 필요하지 않다. 새 host는 loaded fingerprint 일치와 `incident_admission_v1` capability를 확인한 runtime에만 보호 대상 요청을 발행하고, 새 runtime은 유효한 sidecar가 없는 보호 대상 요청을 첫 effect 전에 거절한다. sidecar는 기존 source/confirmation/grant를 대신하지 않는다.

## 1. 변경 위치와 호출 연결

| 대상 | 기존 지점 | 제안 변경 |
|---|---|---|
| `src/cascadeur_complete/bridge_client.py` | `BridgeClient.execute():65–69` | `unresolved_effects()` 전역 판정 부분을 incident admission 조회로 교체한다. 기존 request ID의 observation-only 분기는 그대로 먼저 실행한다. 새 source/evaluation/effect는 승인된 incident disposition과 자원 격리를 함께 평가한다. |
| 같은 파일 | `_execute_once():120–140` | 이미 있는 request는 계속 `reconcile_request()`만 호출한다. 새 요청에만 code-owned admission reservation을 넘겨 `queue.submit()`한다. |
| 같은 파일 | `request_status():285`, `reconcile_request():317` | 변경 없이 재사용한다. 신규 `incident_inspect()` 응답에서 원 terminal과 후속 observation/disposition을 별도 필드로 제공한다. |
| `src/cascadeur_complete/atomic_queue.py` | `AtomicQueue.submit():57–68` | session/nonce/MAC가 결정된 payload를 immutable outbox에 쓴 다음 sidecar를 durable 생성하고, 마지막에 queue 파일을 publish한다. 기존 request에는 새 sidecar를 발급하지 않는다. |
| `src/cascadeur_complete/request_ledger.py` | `read_receipt():54–79`, `unresolved_effects():90–110` | 원 MAC/sequence/result digest/terminal 불변성 검사를 유지한다. raw unresolved 목록의 의미도 유지한다. 신규 `incident_store`가 원 ledger를 입력으로 projection을 만들며 raw unknown을 삭제하지 않는다. |
| 신규 `src/cascadeur_complete/incident_store.py` | 없음 | 원장 읽기/append/CAS/head, 원 요청·terminal bytes 결합, 각 인증 domain의 projection을 담당한다. 순수 policy 코드와 IO를 분리한다. |
| 신규 `src/cascadeur_complete/incident_control.py` | 없음 | inspect/observe/retirement prepare·commit·새 작업 admissibility API. SDK mutation을 직접 수행하지 않는다. 종료·격리는 구체적 승인에 묶인 별도 executor 계약을 호출한다. |
| 신규 host/native `incident_admission.py` | 없음 | 같은 canonical schema·domain hash·MAC purpose·검증 규칙을 구현한다. native Python 3.11 범위에서 동작해야 하며 host 코드 import를 native에 가정하지 않는다. |
| `cascadeur_side/cascadeur_complete/runtime.py` | `_drain_once():1897`, 그 안의 `1943–1971` | 원 message/nonce/terminal 처리 유지. 신규 sidecar 검사 실패는 authenticated `rejected_pre_dispatch`, `dispatched=false`로 종결한다. 원 terminal이 있으면 sidecar와 관계없이 원 결과를 그대로 재조회한다. |
| 같은 파일 | `execute_request():1510–1549` | source/confirmation을 소비하기 **전** admission을 재검증한다. `dispatch_started` 전에 native admission claim을 durable 기록한다. claim 또는 sidecar 오류가 있으면 SDK effect에 들어가지 않는다. |
| `guarded_runtime.py` | `before_write():170–184` | 별도 admission guard를 기존 source guard와 모두 실행한 뒤에만 `write_phase=started`로 바꾼다. 인자로 전달된 `source_guard`가 admission guard를 대체할 수 없게 한다. |
| `guarded_runtime.py` | `begin_request():140`, `capabilities():76` | invocation마다 admission context를 올바르게 설치·정리하고, `incident_admission_v1`의 schema version·code fingerprint·registry binding을 code-owned capability로 알린다. client 입력으로 capability를 만들지 않는다. |
| `runtime.py` | `_run_operation_legacy():1010`의 `system.status` branch | 기존 guarded_capabilities 반환 경로를 재사용한다. 별도 native diagnostic은 `scene_state()` 앞의 신규 `execute_incident_diagnostic()`으로 분리한다. |
| `src/cascadeur_complete/server.py` | `service():28`, 기존 `@mcp.tool()` 구조 | 신규 wrappers `incident_inspect`, `incident_observe`, `incident_retirement_prepare`, `incident_retirement_commit`을 명시적으로 추가한다. |
| `src/cascadeur_complete/service.py` | `CascadeurService.__init__():80` | 신규 controller를 연결하고 같은 이름의 얇은 service methods를 추가한다. controller의 missing evidence/registry를 정상 허용으로 바꾸지 않는다. |

기존 `host_dispatch.lock`은 host가 응답을 기다리는 동안에도 잡혀 있으므로 native가 이 lock을 획득하게 하면 안 된다. 신규 admission lock은 **발행/판정의 짧은 구간**에만 잡는다. runtime은 해당 lock을 별도로 획득하고 SDK 호출 동안 잡지 않는다.

### 제안 시그니처

```python
# Host local control APIs. All identifiers below refer to exact immutable bytes.
def incident_inspect(request_ref: OriginalRequestRef) -> IncidentInspection: ...
def incident_observe(request_ref: OriginalRequestRef,
                     expected_incident_head: JournalHead,
                     evidence_ref: EvidenceRef) -> IncidentStatus: ...
def incident_retirement_prepare(request_refs: tuple[OriginalRequestRef, ...],
                                baseline_ref: ImmutableBaselineRef,
                                new_workspace: ProposedWorkspace) -> RetirementPlan: ...
def incident_retirement_commit(plan_digest: str,
                               operator_authorization: AuthorizationRef) -> RetirementStatus: ...

# Internal only; no JSON -> VerifiedEvidence automatic conversion.
def read_verified_domain(domain: RegisteredDomainRef,
                          expected_head: JournalHead) -> VerifiedDomainSnapshot: ...
def append_event(event: NewIncidentEvent,
                  expected_head: JournalHead) -> JournalHead: ...
def project_incidents(locked_ledger: AuthenticatedLedgerSnapshot,
                      journal: VerifiedJournal,
                      evidence: VerifiedEvidenceSource) -> IncidentProjection: ...
def reserve_admission(intent: NormalizedRequestIntent,
                      registry: VerifiedDomainRegistry) -> AdmissionReservation: ...
def issue_for_signed_request(payload: dict, reservation: AdmissionReservation) -> AdmissionSidecar: ...
def prepare_setup_invocation(plan: ApprovedSetupPlan) -> AuthenticatedSetupInvocationRef: ...
def verify_admission(request: dict, *, phase: Literal["dispatch", "first_write"]
                     ) -> VerifiedAdmission: ...
def claim_admission(request: dict, verified: VerifiedAdmission) -> NativeAdmissionClaim: ...
def assert_current_admission() -> None: ...
def claim_setup_invocation(setup_invocation_ref: AuthenticatedSetupInvocationRef) -> NativeAdmissionClaim: ...
def assert_setup_admission(operation_name: str,
                            setup_invocation_ref: AuthenticatedSetupInvocationRef) -> VerifiedSetupStepGrant: ...
```

`AtomicQueue.submit()`에 넣을 새 인자는 code-owned issuer 또는 reservation 객체다. arbitrary caller callback/`allow_unknown=true` 옵션을 공개하지 않는다. sidecar 발급과 queue publish 사이 예외는 원 outbox를 지우지 않는다.

### 메뉴 qualifier의 별도 진입점

현재 explicit qualifier 메뉴는 host queue를 거치지 않는다. `assert_setup_admission()`을 lifecycle packet의 `RetainedProbe` 생성 및 첫 create/save/fixture read-write **앞**에 연결한다. sidecar 없는 직접 메뉴 effect는 거절하고 진단만 제공한다. setup도 global/isolated incident admission을 먼저 통과해야 하며 새 qualification은 기존 unknown을 해결하는 증거가 아니다.

`setup_invocation_ref`는 새 immutable authenticated setup request를 가리킨다. code-owned setup registry에 등록한 정확한 helper 이름/bytes, runtime epoch, 새 owned fixture namespace, input/output closure, fixture budget, 명시적 operator 승인에 묶는다. host는 signed outbox와 setup sidecar를 staging하고 ref만 UI에 전달한다. queue와 메뉴 양쪽에 같은 실행을 publish하지 않는다. 승인된 native setup dispatcher의 `claim_setup_invocation()`이 원 request/sidecar를 검증하고 single-use claim을 **정확히 한 번** durable 소비한 뒤 private `_LOCAL.setup_invocation_ref/context`를 설치한다. `assert_setup_admission()`은 그 context·thread·operation·epoch·resource revision을 검사만 하고 token/ticket을 다시 소비하지 않는다. 이 구분으로 과거의 이중 소비 결함을 반복하지 않는다. 원 terminal이 있거나 이미 claim된 ref는 관찰만 한다. dispatcher는 `try/finally`로 context를 제거/복구하고 중첩·다른 thread·반환 후 callback을 거절한다. 첫 SDK effect 및 첫 파일 write 앞에서도 current admission을 확인해야 한다. 실제 helper에 이 연결이 없는 상태를 안전한 setup 구현으로 표시하지 않는다.

현재 lifecycle packet의 code-owned setup ID는 `setup.qualify_native_adapter`, `setup.qualify_independent_models`, `setup.qualify_independent_position_writer`다. `RetainedProbe(kind)`는 이 고정 mapping을 사용해 `getattr(guards._LOCAL, "setup_invocation_ref", None)`을 assertion에 전달할 수 있다. 메뉴의 기존 `run(scene)` signature를 바꾸거나 사용자의 bool/path를 권한으로 받지 않는다. 다른 qualifier를 이 계약으로 실행하려면 해당 정확한 helper mapping과 효과 범위를 먼저 연결해야 하며 이름 prefix만으로 허용하지 않는다.

`assert_setup_admission()`의 반환은 검증된 내부 `VerifiedSetupStepGrant`이며 필드는 `workspace_path`, `maximum_new_tabs`, `maximum_casc_files`다. 내부 read-only mapping으로 표현할 수 있지만 wire에서 같은 모양의 dict를 받는 것은 허용하지 않는다. 기존 private claim·허용 step·승인된 parent physical identity/resource manifest를 재확인한 뒤 반환한다. `RetainedProbe`는 이 승인 경로만 `mkdir(exist_ok=False)`하고 helper의 고정 상한과 grant 예산 중 작은 값을 지킨다. 경로 충돌 시 새 UUID/root로 fallback하지 않는다. 현재 finite 상한은 native base 2 tabs/5 `.casc`, model 1/2, writer 1/2이며 실제 helper와 승인된 plan이 함께 같은 값을 사용해야 한다.

한 explicit command가 models→writer 등 여러 helper를 호출하는 현재 경로는 sidecar의 code-owned `helper_sequence`와 step별 budget/resource closure에 미리 고정한다. invocation ticket을 helper마다 다시 소비하지 않는다. 각 assertion은 원 claim 아래 **현재 허용된 step**인지 확인한다. 같은 epoch/loaded bytes의 private model proof가 이미 있으면 해당 step은 read-only 확인으로 건너뛸 수 있지만 새 권한을 만들지 않는다. 한 helper가 unknown/pending/미완료이면 후속 helper로 진행하지 않고 원 setup invocation을 unknown으로 보존한다. generic `include_scene_adapter=True`는 이번 finite 승인 sequence에서 제외한다.

setup은 source를 만들기 전의 code-owned fixture 절차이므로 일반 scene source를 가짜로 발급해 선행조건을 충족시키지 않는다. 기존 explicit setup 허가/범위 제약을 유지하고 incident admission을 추가한다. 이 신규 control API/sidecar도 적용 승인이 필요하며 참조 policy는 effect 종류를 `explicit_setup`으로 판단할 뿐 fixture executor를 구현하지 않는다.

## 2. 원 기록과 새 상태를 분리하는 타입

`OriginalRequestRef`는 `(auth_domain_id, store_instance_id, request_id, request_digest, operation_digest, terminal_payload_digest, terminal_bytes_digest, original_runtime_epoch, original_run_id)`다. 원 `RequestLedger.read_request/read_receipt` 검사에 성공한 뒤에만 생성한다. canonical payload digest와 실제 receipt bytes hash를 모두 보존한다. 원 key/request/token/terminal/소비 budget을 재서명·덮어쓰기·환급하지 않는다.

incident는 다음 두 축을 가진다.

| 축 | 상태/전이 | 허용 근거 |
|---|---|---|
| 실행 관찰 | 없음 → `proved_no_effect` / `proved_completed_success` / `proved_completed_failure` | 원 native attempt의 권위 있는 완료·실제 effect closure 증거 |
| 격리 | 없음 → `retirement_started` → `retirement_committed` | exact plan에 대한 operator 승인 → producer 종료·영향 자원 격리 증거 |

원 terminal outcome은 모든 전이에서 `outcome_unknown` 그대로다. operator 승인은 두 번째 축의 작업 권한만 부여하며 첫 번째 축의 진실을 증명하지 않는다. 뒤늦은 원 완료 증거를 추가해도 이미 retire한 자원을 자동 재활성화하지 않는다. 원 run의 resume/replay 권한도 자동으로 생기지 않는다.

등록되지 않은 legacy terminal unknown도 raw ledger에서 발견하면 열린 incident로 취급한다. journal이 없다고 unknown이 없는 것으로 처리하지 않는다. terminal이 아직 없는 다른 claimed/pending effect는 별도 unresolved blocker로 유지한다. 이번 terminal-unknown retirement 계약으로 그 기록을 임의 종결하지 않는다.

### Journal schema 1 — 제안

domain별 `state/incidents/events/<seq>-<event_digest>.json`에 append-only envelope를 둔다. 필드는 `schema_version`, `domain`, `seq`, `previous_event_digest`, `kind`, `original`, `evidence_digest`, `plan_digest`, `mac`다. `kind`는 등록·원 완료 관찰·retirement 시작·retirement 완료만 허용한다.

- `auth_domain_id = HMAC-SHA256(original_bridge_key, "cascadeur-complete/incident-auth-domain/v1\\0")`.
- journal key는 원 key에서 purpose와 domain/store를 결합해 도출한다. admission, operator authorization, original queue와 purpose를 구분한다. 원 `bridge.key`를 교체하지 않는다.
- canonical JSON은 UTF-8, 정렬 key, compact separators, NaN/Infinity 금지이며 decoder는 중복 key·미지원 schema·예상 밖 필드를 거절한다.
- entry MAC은 body를, 다음 entry의 predecessor는 **직전 MAC을 포함한 envelope 전체**를 결합한다.
- signature가 맞는다는 사실은 SDK 의미가 맞다는 증거가 아니다. `VerifiedEvidenceSource`가 원 attempt/완료/영향 범위를 별도로 검증해야 한다.

`reference_incident_policy.py`는 이 인증 encoding/chain 확인, 상태 축적, 허용 후보 판정을 순수 함수로 제공한다. 실앱의 evidence verifier와 sidecar writer는 구현하지 않는다. `_CANDIDATE` 결과를 native permit으로 직접 쓰면 안 된다.

## 3. Global과 isolated 인증 domain

두 root는 별도 인증 domain으로 검사한다. root path 문자열이나 UUID만으로 domain을 합치지 않는다. 같은 key를 복사한 root는 같은 auth domain의 복제본이며 독립 실행 허가가 아니다. `store_instance_id`와 물리 root identity/active-store binding으로 중복 writer를 거절한다.

control registry는 지원하는 기존 global/isolated root의 domain ID, store ID, 물리 root identity, key locator, active writer binding을 포함한다. registry는 `CASCADEUR_MCP_ROOT`로 임의 선택한 root 목록이 아니라 설치/control authority의 검증된 기록이다. 최초 도입 시 현재 두 root를 원 키와 원 immutable records로 등록한다. 이름을 모르는 root를 찾아내려고 전체 디스크를 스캔하지 않는다. 등록되지 않은 producer나 공유 자원 때문에 영향 범위를 닫을 수 없으면 해당 새 작업을 보류한다.

각 root의 원 receipt와 journal은 **각 root의 원 key**로 검증한다. global record를 isolated key로 재서명해서 승계하지 않는다. aggregate admission에는 각 domain의 `(store, journal head, unresolved-set digest)`와 registry digest를 넣는다. target native verifier가 peer domain의 원 인증 자료를 안전하게 읽어 검증할 권한이 없으면 closed한다. key를 sidecar·로그·응답에 넣지 않는다. 여러 domain을 검증하는 내부 resolver는 검증 전용 API이며 peer journal 쓰기 권한을 요청에 제공하지 않는다.

두 domain에 걸친 retirement plan은 동일 plan digest 아래 **각 domain에서 별도로** 승인·기록한다. distributed all-or-nothing commit을 꾸미지 않는다. 한 domain만 완료됐거나 다른 domain 접근이 끊기면 aggregate admission이 계속 거절된다. 완료된 domain의 원 기록을 되돌리지 않는다.

## 4. 보호 대상별 admission

| 경로 | 열린 unknown에서도 가능한가 | 결과의 권한 |
|---|---|---|
| host ledger/status/manifest/process inspection | 가능. 읽기 오류는 진단에 표시 | 실행/source 권한 없음 |
| 원 request status/reconcile | 가능. 원 signed request identity 그대로 조회 | 재dispatch 없음 |
| 제한된 native incident diagnostic | 무변경 reader와 원 request/epoch/bytes 결합이 입증될 때만 | 진단 DTO만; source/token/grant 없음 |
| 일반 scene read | unknown 동안 일반 경로는 차단. 필요하면 검증된 diagnostic reader로 한정 | evaluation을 포함하지 않음 |
| `system.capture_source`/rebind/prepare | authoritative closure 또는 retirement+새 workspace 분리 이후 | 기존 source/qualification 계약도 통과해야 함 |
| evaluation/scene/file/mixed effect | 모든 domain의 admission과 기존 보호 조건을 모두 통과해야 함 | 기존 confirmation·source·예산 계약 유지 |

현재 `runtime.execute_request()`는 시작부터 `scene_state()`를 읽는다. 따라서 새 diagnostic 이름을 whitelist에만 추가하면 무변경/저비용 진단 계약이 되지 않는다. `execute_incident_diagnostic()`을 **그 읽기보다 앞선 별도 분기**로 두고 원 ledger/retained private record만 제한해서 반환한다. SDK read가 필요한 확장은 해당 reader의 자격을 별도로 확인한 범위에만 허용한다. 기존 `system.status`도 scene 상태를 읽으므로 host-local process inspection과 같다고 주장하지 않는다.

`WorkKind`는 code-owned operation registry와 인자 정규화 결과로 결정한다. client가 diagnostic 이름/flag를 지정해 평가·setters를 숨길 수 없다. `system.capture_source`는 `_ISSUED_SOURCES`에 권한 자료를 생성하므로 diagnostic 분기로 옮기지 않는다. `animation.interpolation_refresh`와 `transform_get(refresh=True)`는 evaluation이다.

## 5. Sidecar와 두 번의 native 검사

위치 제안: `state/request_records/<request_id>/admission-v1.json`. 신규 파일이며 원 `request.json`이나 `runtime_events`를 변경하지 않는다.

필수 binding은 `schema_version/purpose`, target `domain/store`, registry digest, 원 **signed request 전체** digest, request/operation ID·digest, runtime epoch, loaded fingerprint, source-binding digest(없으면 명시 null), safety-context digest, incident heads, 각 domain의 unresolved-set digest, resource manifest digest, workspace generation, baseline digest, evidence refs, ticket ID, MAC다. 유효시간은 원 request 범위를 넘지 않는다. 만료는 과거 effect가 없었다는 근거가 아니다.

현재 요청 자체가 outbox에 기록되면 raw unresolved 목록에 나타날 수 있다. admission snapshot은 **같은 domain/request ID와 signed digest가 모두 같은 현재 요청 하나만** 계산에서 제외한다. 다른 pending/unknown 요청은 제외하지 않는다. source capture처럼 effect=none인 요청도 보호 대상 분류를 유지한다.

native 검사 순서:

1. 원 request MAC/shape 및 기존 terminal 검사. 기존 terminal이 있으면 그대로 조회하고 끝낸다.
2. sidecar purpose/MAC/original digest/epoch/loaded bytes/registry·peer heads/resource proof를 검사한다. 미지원·누락·변조·stale는 `rejected_pre_dispatch`다.
3. 새 native admission claim을 append-only로 기록한다. 동일 ticket/request의 이미 소비된 claim이 있으면 원 요청을 재조회하고 executor를 다시 호출하지 않는다.
4. 기존 source/confirmation 검증 뒤 `dispatch_started`와 원 native executor로 진행한다.
5. `guards.before_write()`에서 admission guard와 source guard를 **둘 다** 실행한다. retired epoch, retirement pending, peer head 변경, alias/handle 변경은 write 전에 거절한다. 원 scope에 승인된 effect 중복 집행을 허용하지 않는다.

`verify_admission()`/`assert_current_admission()`은 재검증이며 재소비가 아니다. durable single-use consumption은 `claim_admission()` 한 번에만 있다. `_LOCAL`에는 그 claim을 설치하고 call 종료 시 제거한다. source guard 인자를 전달하거나 `begin_request()`를 호출해 admission context를 덮어쓰는 경로는 허용하지 않는다.

first-write 검사와 retire-start가 경합해도 retire 완료는 producer 종료 증거 전에는 기록할 수 없다. 이미 시작된 native call이 있을 수 있는 동안 새 workspace effect는 허용되지 않는다. admission lock을 SDK 호출 전체에 걸어 UI callback 교착을 만들지 않는다.

## 6. Authoritative observation의 정확한 입력

`incident_observe()`는 원 request/terminal bytes digest, 원 epoch/build/loaded fingerprint, 원 attempt identity, code-owned completion record, producer closure, actual after/effect-closure digest를 받는 **검증된 evidence locator**만 받는다. 원 실행과의 결합이 없는 새 qualification 성공은 인정하지 않는다. native proof가 process-private였다면 원 process 유실 후 현재 장면으로 재생성할 수 없다.

`write_phase=not_started`, setter 반환, `native_true=True`, 현재 projection·파일 존재/부재, operator 확인 중 하나만으로 완료를 인정하지 않는다. 완료된 실패와 recovery eligibility도 분리한다. incident observation은 기존 conditional recovery가 요구하는 원 `failed_after_dispatch` terminal을 조작하여 만들어 주지 않는다. 이번 범위에서 원 unknown run은 재개하지 않는다. 지원되는 새 작업을 새 plan/grant로 시작한다.

새 코드에서 발생한 `failed_after_dispatch/recovery=false`는 root가 준비하는 failure contract를 따른다. 그 원 run을 자동 continue/publish하거나 실패 workspace를 자동 baseline으로 삼지 않는다. 이 incident 모듈도 그런 자동 승계를 허용하는 권한을 발급하지 않는다. 사용자가 독립된 새 작업을 명시 승인한 경우까지 전역 금지를 추가하지 않는다.

## 7. Retirement, aliases, producer 종료

`retirement_prepare()`는 읽기 전용으로 exact plan을 만든다. plan은 원 incident refs, registry digest와 domain별 expected heads, 만료시각, 실행 주체/PID+creation time/epoch, 관련 native child·external consumer, 포함하는 원 input/output 경로와 물리 identity, 보존할 증거 hash, 선택한 확정 baseline, 새 workspace, 종료·격리 조작 목록을 결합한다. 승인 전 process 종료·파일 이동·권한 변경을 수행하지 않는다. commit 시작 때 registry/head/plan/승인 만료를 다시 대조하고 달라졌으면 같은 승인으로 범위를 확장하지 않는다. 일단 승인된 exact plan이 시작된 뒤 crash 복구는 새 범위의 재승인이 아니라 그 plan의 durable 상태·원 허용 조작만 재관측한다.

`retirement_commit()`은 먼저 모든 관련 domain에 `retirement_started`를 CAS append해 새 dispatch를 막는다. operator가 승인한 종료·격리 executor가 실제 완료 증거를 반환한 뒤에만 `retirement_committed`를 각 domain에 기록한다. PID 값/TTL/lock 파일 존재만으로 종료를 증명하지 않는다. PID+creation time의 동일 실행 주체와 실제 OS 종료, 관련 child/consumer의 종결, late callback producer가 더 이상 존재하지 않음을 확인해야 한다. 원 process identity·producer 집합이 복원되지 않는 legacy 사건은 이 사실을 숨기지 않는다. 완전한 실행 영역 종료를 증명할 별도 authoritative evidence가 없는 한 해당 retirement를 완료하지 않는다.

파일 독립성은 `Path.resolve()`나 문자열 prefix만으로 증명하지 않는다. existing file/directory의 volume/file ID, hard link, reparse/symlink 대상, 대소문자·짧은 이름 alias, 공유 publication target을 handle 기반으로 확인해야 한다. 새 output은 실제 parent directory identity와 새 파일 생성 조건까지 묶는다. 검사 뒤 parent/target이 바뀌면 admission을 무효화한다. 이 Windows-specific verifier는 참조 코드에 구현하지 않았다.

unknown 영향 output은 삭제하지 않고 보존·격리 manifest에 묶는다. 새 baseline은 unknown **이전**에 확정된 immutable source/checkpoint여야 하고 그 출처·bytes hash를 검증한다. 우연히 같은 현재 파일 hash라는 이유로 전후 이력을 지우지 않는다. 새 scene instance/workspace generation/request/run/plan/grant를 사용한다. alias로 old target을 가리키거나 unknown output에서 입력을 파생하면 별개 작업으로 인정하지 않는다.

위 source/checkpoint 조건은 원 애니메이션 작업을 이어 만드는 새 run에 적용한다. 완전히 독립된 code-owned qualification fixture는 승인된 immutable generator bytes/parameters를 baseline으로 삼을 수 있다. 이 예외는 helper가 unknown scene/출력을 입력으로 읽지 않고 명시된 새 fixture 자원만 사용하는 것이 확인된 경우에 한정한다. fixture 성공을 원본 작업의 복원·완료 증거로 재사용하지 않는다.

effect footprint가 unknown/global, 외부 consumer 미종결, 공유 경로의 영향 범위 불명, baseline provenance 부재이면 verifier는 `EvidenceUnavailable`을 반환하고 admission은 거절한다. operator 위험 수락을 증거 타입으로 변환하지 않는다. 모든 사건을 영구 freeze시키는 정책 대신 **증명된 containment의 범위에서만** 새 작업을 허용한다.

## 8. Concurrency·crash·업그레이드 경계

lock 순서는 maintenance shared lease → domain들을 `(auth_domain_id, store_instance_id)` 정렬한 admission lock → 해당 domain journal append lock이다. 기존 host_dispatch lock을 잡는 곳은 host뿐이며 native에서는 획득하지 않는다. IO 중 연결한 모든 peer domain의 read snapshot도 설치 교체와 경합하지 않게 기존 shared maintenance lease에 묶는다. SDK 호출·승인 대기 중에는 새 journal/admission lock을 유지하지 않는다.

| 중단 지점 | durable 사실 | 재시작 처리 |
|---|---|---|
| retirement 승인 전 | 읽기 전용 plan | 새 권한 없음. 원 unknown 유지 |
| retire-start 기록 후, 종료/격리 전·도중 | fence가 durable | 원 process 종료를 추정하지 않음. 동일 plan 상태를 관찰하고 이미 승인된 idempotent 단계만 별도 executor가 계속할 수 있음 |
| producer 종료 후 retire-commit 전 | 종료 evidence가 있거나 없음 | 실제 evidence를 재검증해 append; 없으면 pending 유지 |
| 한 domain만 retire-commit 완료 | 부분적으로 완료된 containment | aggregate admission은 거절. 완료 기록을 되돌리지 않음 |
| outbox 전/후 sidecar 미완성 | 원 outbox가 없거나 staged 상태 | queue publish 금지. absent 파일만 보고 no-effect 판정하지 않음. admission 소비 ledger·supported runtime binding을 함께 확인하는 predispatch-cancel 경로만 사용 |
| sidecar·queue publish 후 응답 없음 | claim/원 receipt에 따라 다름 | 기존 원 request 조회만. 새 sidecar·nonce로 같은 요청을 재발행하지 않음 |
| native admission claim 후 effect/terminal 전 | 원 실행 완료 불명 가능 | 원 unknown 경로로 유지; claim 소거·ticket 환급 금지 |
| event durable, head 갱신 전 | 유효한 완전 event suffix | 독점 writer가 연속 seq/MAC/predecessor를 검증한 suffix만 head에 반영. 임시/부분 파일은 허용 상태로 보지 않음 |
| sidecar 발급 후 incident/resource head 변화 | old snapshot | native 거절. 첫 write 이후라면 기존 completed/unknown 분류 규칙이 적용되며 predispatch로 거짓 반환하지 않음 |

append는 기존 `atomic_write_json()`의 overwrite 사용을 그대로 복사하지 않는다. journal target은 exclusive create/no-overwrite, temp flush/fsync, 원자적 publish, head 갱신 순서를 보장하는 전용 writer가 필요하다. 원장과 sidecar의 fsync/rename crash durability는 실제 Windows 구현에서 직접 확인해야 한다. 이 참조에는 그 결과를 가정한 IO stub이 없다.

MAC hash chain은 무결성과 순서를 검사하지만 동일 권한으로 key와 전체 state/head를 함께 과거로 되돌리는 공격까지 독자적으로 막지는 못한다. 이 범위는 기존 local state 접근제어와 같은 trust boundary다. 외부 anti-rollback 서비스를 새로 도입하지 않는다. reader는 설치/control authority가 고정한 head/active-store binding과 다른 snapshot을 임의 수용하지 않는다. 손상·알 수 없는 버전·중복 active store는 diagnostics 외 closed한다.

upgrade-state의 기존 state/snapshots/logs/policy 전체 bytes 보존을 사용하되 새 incidents/admission/claim/registry binding도 보존 대상에 포함한다. 기존 key/receipt를 재서명하지 않는다. 이전 host가 새 journal을 이해하지 못하면 원 unknown 전역 barrier로 계속 차단된다. 이전 runtime에는 새 host가 guarded 요청을 publish하지 않는다. 새 runtime은 이전 host의 sidecar 없는 protected request를 거절한다. 설치/재시작으로 retired resource와 old source의 자격을 되살리지 않는다.

## 9. 두 기존 unknown의 실제 처리 분기

| 원 사건 | A: 원 완료 관찰 | B: retirement 후 새 작업 |
|---|---|---|
| global `ffb7fc8e-417c-454c-a669-48625a086eda` | 원 global key로만 읽는다. double-token 결함과 `write_phase=not_started`만으로 no-effect를 발급하지 않는다. 원 attempt의 code-owned no-invocation/종료 근거가 남아 있을 때만 별도 관찰을 append한다. 현재 확보된 자료로는 그 증거가 확인되지 않았다. | 원 request/source arguments에서 effect footprint를 닫고 원 producer/consumer 종료·output 격리가 입증될 때만 retire한다. 범위를 복원할 수 없으면 isolated의 성공으로 global barrier를 해제하지 않는다. |
| isolated `fcf3352a-483c-4f9c-bc18-8b61a58822eb` | `completed` write와 LINEAR→STEP 불일치는 원 완료 봉인을 대신하지 않는다. 새 wrapper 수정/새 qualification으로 과거 receipt를 failure/success로 바꾸지 않는다. | `unknown-after-insertion.casc` 등 사건 output을 보존·격리하고, 원 삽입 이전의 확정 checkpoint에서 새 workspace를 만든다. 원 epoch/PID+creation time/producer closure가 확인돼야 한다. global domain의 미해결 영향도 aggregate admission에서 함께 확인한다. |

새 workspace가 열렸다고 기존 두 요청이 해결되었다고 보고하지 않는다. 상태 응답은 `original_outcome=outcome_unknown`, 실제 observation 유무, retirement disposition, 새 run identity를 각각 표시한다.

## 남은 경계

현재 설계에서 native/OS proof를 생성하는 가짜 구현은 없다. 구현 전후 실제로 확보해야 하는 것은 code-owned original completion verifier, Windows producer/alias/resource verifier, 안전한 journal/sidecar IO, 두 root의 원 인증자료 접근이다. 증거가 끝내 없으면 해당 A/B 경로는 불가능하다는 결과를 그대로 반환한다. 순수 정책 코드 작성만으로 실앱 recovery·SDK 안정성·Windows crash durability가 검증됐다고 주장하지 않는다.
