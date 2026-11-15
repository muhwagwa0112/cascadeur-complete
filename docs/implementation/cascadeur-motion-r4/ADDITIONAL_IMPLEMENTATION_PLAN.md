# Cascadeur r4 추가 구현 계획

**확인 기준: 2026-11-15 · `feat/cascadeur-motion-r3` · `c55981152f40afee24221d70aa972235754a105e`**

새 푸시에는 r3 명세를 반영한 host·bridge 기반 코드가 들어 있다. 그러나 현재 실앱 변경을 여는 검증된 native adapter가 없고, recipe·checkpoint·export 연결도 남아 있다. 추가 작업은 기존 수학·receipt·검증 helper를 재작성하는 대신, 이 기반을 실제 SDK·원본 보존·완료 관측·actual 품질·최종 파일에 연결하는 16개 작업이다.

이 문서와 JSON은 **추가 설계 산출물**이다. 제품 코드 수정, 설치, 테스트, 실제 Cascadeur/Blender 실행, 새 push를 수행하지 않았다. 아래 신규 타입·함수명은 프로젝트 내부 구현 제안이며 존재가 확인된 Cascadeur SDK API 이름이 아니다.

## 1. 다시 확인한 푸시

| 항목 | 확인 내용 |
|---|---|
| 새 구현 | [`c5598115`](https://github.com/muhwagwa0112/cascadeur-complete/commit/c55981152f40afee24221d70aa972235754a105e), `feat/cascadeur-motion-r3` |
| 기반 | 문서 commit `fb631049…`의 자식. 구현 메모는 PR #8 기반 변경을 squash 적용했다고 명시한다. 다음 구현은 `c559…`에서 이어가며 PR #8 변경을 다시 적용하지 않는다. |
| 비교 refs | 확인 시 main `82b350ca…`, r3 문서 브랜치 `fb631049…`, PR #8 `1bb44789…`; 새 구현 브랜치 PR은 검색 결과에서 확인되지 않았다. |
| 개발자가 남긴 요청 | 고정 build `2026.1.3.0.15619`의 실제 reader/guard/완료 어댑터, checkpoint/rollback, 실제 motion/reskin/key 모델, native export/소비자 capture, protocol 3 동시 설치·재시작 |
| 기존 설계 판정 | r3의 PASS는 당시 설계에 한정한다. 현재 구현·runtime 성공 판정으로 재사용하지 않는다. |

직접 근거: [새 구현 메모](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/docs/KNOWN_ISSUES_2026-11-15.md#L8-L58). 메모에 기록된 과거 선택 테스트 통과는 구현자의 기록이며 이번 검토에서 재실행하지 않았다.

## 2. 여기서 요구하는 것

| 구분 | 필요한 내용 | 처리 방침 |
|---|---|---|
| 사용자가 정할 의도 | 대상 캐릭터·clip/범위, repair/styling/새 모션 생성 목적, 허용 보정·lock/contact/prop 정책, 최종 경로·소비자·overwrite 여부 | 의미가 모호한 선택만 받는다. 원시 JSON·키 배열 작성은 요구하지 않는다. |
| 장면에서 자동 취득할 데이터 | stable IDs·ownership·hierarchy·rest axes·skin·layer/key/interpolation, 읽을 수 있는 FPS·단위·basis·root 회전·support | 읽기 builder가 출처와 함께 수집한다. 못 읽는 값만 확인한다. 이름·기본값을 관측 사실로 간주하지 않는다. |
| runtime이 발급할 증거 | 실제 build/loaded fingerprint, complete SourceBinding, native 완료·successor·checkpoint receipt, target capture provenance | 사용자 입력으로 받지 않는다. 임의 complete/verified/hash로 차단을 해제하지 않는다. |
| 이후 실제 지원 활성화에 필요한 환경 | 고정 Cascadeur build의 SDK/schema와 실행 접근, 작은 기존-key rig/clip, 해당 설치의 Blender 경로/bytes | 계획과 host 연결 구현은 먼저 진행할 수 있다. native 지원은 실제 관측이 확보된 조합만 켠다. |

**설정값만 채워 해결할 수 있는 상태가 아니다.** 메모의 요청 중 큰 부분은 실제 adapter 개발과 완료·품질 증거 연결이다. 잘못된 입력을 보충하는 일과 아직 구현되지 않은 작업을 capability에 구분해 표시한다.

## 3. 추가로 확인한 직접 연결 결함

| 발견 | 코드 수준 원인 | 반영 작업 |
|---|---|---|
| 첫 checkpoint 순환 의존 | 일반 scene/mixed prepare는 이미 snapshot_manifest를 요구한다. 초기 source/파일을 보호 복제하는 별 bootstrap 권한이 필요하다. | R4-03/04 |
| 정상 successor의 재개 차단 | 재개 preflight가 최초 spec.input을 현재 active scene과 다시 비교한다. initial과 continuation 검사를 나눠야 한다. | R4-03/06 |
| 해소된 unknown 뒤 worker 정지 가능 | resume이 reconcile 후 즉시 반환하여 running/verifying 상태를 다시 예약하지 않는다. start scheduler 자체는 이미 있다. | R4-06 |
| native 인자/ID로의 번역 공백 | plan의 rig/motion 선언 dict와 실제 handler payload가 다르며 import/new rig의 후속 ID 계약이 없다. | R4-03/10 |
| export의 무조건 차단 | export hook이 있어도 runner가 항상 EXPORT_STAGE_REQUIRES_PERSISTED_NATIVE_PREPARATION을 발생시킨다. | R4-12/14 |
| 소비자 품질 연결 공백 | Blender report → canonical SampleBatch 변환, 원본 의도 문맥, trusted capture verifier가 필요하다. | R4-13 |
| source 설치 후 상태 연속성 누락 | backup으로 이동한 request_records/keys/one-attempt 상태를 active root에 이어주는 코드가 없다. frozen installer까지 동일 손실로 일반화하지 않는다. | R4-16 |
| sparse 구조와 자원 추정 불일치 | contact solver는 sparse인데 preflight가 n*n*128을 사용한다. dense n×n 할당 결함으로 확인한 것은 아니다. | R4-15 |
| AutoPhysics 실측 계약 잔여 | enable은 toggle, snap은 revision 변화로 완료를 추정한다. 실제 상태·완료가 없는 무인 실행은 열 수 없다. | R4-11 |

각 발견의 고정 commit 소스 링크는 해당 작업에 둔다. 기존 cleanup의 operation별 `_bind_source`와 start supervisor는 이미 구현되어 있으므로 새로 만드는 대상으로 오인하지 않는다.

## 4. 공통 계약과 실행 순서

| 제안 내부 계약 | 핵심 입력·출력 | 불변 조건 |
|---|---|---|
| NativeAdapter / NativeEffectObservation | 실제 runtime 관측 + exact operation/arguments → 읽기 scope·actual effect·완료/unknown·successor | reader 등록만으로 mutation 지원을 표시하지 않는다. |
| MotionInputDraft | character/범위/의도 → 관측 metadata·provenance·누락/모호 항목 | draft는 승인이나 SourceBinding을 발급하지 않는다. |
| BootstrapGrant | initial complete source(선행 snapshot은 없음) 또는 FileManifest + owned path·허용 effect | 초기 입력·보호 복제 전용이며 일반 snapshot 규칙을 해제하지 않는다. |
| StageEffect | 승인 선언 + 검증된 predecessor/현재 source → exact payload·effect bounds·expected successor | declaration digest와 concrete arguments digest를 모두 보존한다. |
| DerivedTargetRef | producer receipt + 유일 selector·ownership/topology → actual ID/layer mapping | 생성 전 wildcard 권한이나 이름 첫 항목 선택을 허용하지 않는다. |
| CheckpointObservation | 원 request/receipt + 실제 save 완료 → immutable file manifest·source before/after·lineage | bool/파일 존재만으로 성공하지 않는다. |
| TargetCaptureEvidence | sealed SHA + 실제 importer/nonce/report → raw/canonical capture digest | 다른 capture나 임의 verified 값으로 재사용하지 않는다. |

원본 artifact·baseline·intent·support는 고정하고 current binding만 인증된 successor로 이동한다. 각 새 operation은 최종 concrete payload에 결합한 source를 발급한다. 기존 cleanup 재발급 경로는 재사용한다. 최초 파일 입력은 scene binding이 없는 상태를 별 BootstrapGrant로 다루며, 생성된 실제 장면부터 일반 source 규칙을 적용한다.

### 구현 순서와 납품 단위

1. **기존 rig·기존 clip의 실제 보정:** R4-01/02/03/05 → R4-04/06/07/15 → R4-08. 기존 key의 한 writer에서 원본 보호, 실제 완료, actual 품질, successor checkpoint까지 연결한다.
2. **최종 FBX 납품:** R4-12 → R4-13 → R4-14. 실제 export·sealed 구조·고정 소비자 capture·원본 품질·게시 상태를 연결한다. standalone 보정이 된다는 이유로 최종 파일 품질을 생략하지 않는다.
3. **자동화 입력/기능 확장:** R4-09/10/11. sparse 삽입, 파일 입력/새 rig, native/host retarget, generation/unbaking, 검증된 styling/arm·AutoPhysics를 같은 계약으로 확장한다.
4. **배포 전 상태 보존:** R4-16은 앞 단계와 병행하되 실제 기존 설치를 교체하기 전에 완료한다. 신규 설치와 upgrade를 구분하며 이전 unknown/receipt를 잃지 않는다.

이 순서는 제품의 동작 범위를 정의한다. 실제 앱 전체 왕복 실행을 이번 계획 검수의 자동 gate로 추가하지 않는다. 구현 완료와 실앱 지원 인증을 분리하고, 실제 왕복 실행은 아래 검증·승인 범위에 따른다.

## 5. 코드 수준 작업 명세

| ID | 우선순위 | 작업 | 선행 |
|---|---|---|---|
| R4-01 | P0 | 실제 SDK 관측과 native adapter 실행 연결 | 없음 |
| R4-02 | P0 | 리그·시간·좌표·접촉 입력 자동 수집 | R4-01 |
| R4-03 | P0 | 선언 계획을 실제 operation·파생 ID 권한으로 연결 | R4-01 |
| R4-04 | P0 | 초기 backup·working scene·checkpoint·조건부 rollback 구현 | R4-01, R4-03, R4-05 |
| R4-05 | P0 | native 완료 불명·successor를 durable receipt에 반영 | R4-01, R4-03 |
| R4-06 | P0 | checkpoint와 resume을 실제 worker 진행에 연결 | R4-03, R4-04, R4-05 |
| R4-07 | P0 | 실제 layer/key·보간 모델과 fitting 한도 연결 | R4-01, R4-02 |
| R4-08 | P0 | 실제 motion·reskin 결과로 필수 품질 판정 | R4-01, R4-02, R4-04, R4-05, R4-06, R4-07, R4-15 |
| R4-09 | P1 | 승인된 범위의 sparse key 삽입 | R4-03, R4-06, R4-07, R4-08 |
| R4-10 | P1 | 파일·리그·retarget·generation·unbaking stage 구현 | R4-02, R4-03, R4-04, R4-05, R4-06, R4-07, R4-08 |
| R4-11 | P1 | AutoPhysics의 상태·완료 관측을 무인 실행에 연결 | R4-01, R4-03, R4-04, R4-05, R4-06, R4-08 |
| R4-12 | P0 | native FBX export와 sealed artifact까지 runner 연결 | R4-03, R4-04, R4-05, R4-06, R4-08 |
| R4-13 | P0 | 실제 소비자 capture를 원본 기준 품질 평가에 연결 | R4-02, R4-08, R4-12 |
| R4-14 | P0 | 검증 후 게시와 run 결과·취소·crash 복구 연결 | R4-03, R4-06, R4-12, R4-13 |
| R4-15 | P1 | sparse solver·실제 peak에 맞는 자원 예산 | R4-02, R4-07 |
| R4-16 | P0 | 설치 교체 시 receipt·키·재개 상태와 지원 표기 보존 | R4-01, R4-03, R4-05, R4-06 |
### R4-01 — 실제 SDK 관측과 native adapter 실행 연결

**우선순위:** P0 · **기존 매핑:** T02, T03, T04, T08, T31 · **선행:** 없음

**변경 파일:** `cascadeur_side/cascadeur_complete/guarded_runtime.py`, `cascadeur_side/cascadeur_complete/runtime.py`, `cascadeur_side/cascadeur_complete/handler_registry.py`, `신규 제안: native_adapters/sdk_2026_1.py`.

**연결 함수·타입:** `register_adapter/capabilities/capture_source/assert_source`, `_run_operation/execute_request`, `제안: observe_runtime/bootstrap_verified_adapters/execute_native`.

**현재 문제:** 현재 _ADAPTERS가 비어 있고 production 등록이 없다. register_adapter는 reader 객체와 proof 필드를 검사하지만 실제 build·증거 bytes를 인증하지 않으며, _run_operation은 등록 reader의 executor가 아니라 기존 handler/inline 경로로 dispatch한다.

**구현 내용**

1. 프로세스에서 관측한 build, loaded bridge/SDK manifest, epoch, operation, rig/profile 범위를 묶는 NativeAdapter 계약을 추가한다. required_scope/capture와 execute_native/완료 관찰을 동일 등록 항목에 연결한다. 실제 SDK signature는 설치된 2026.1.3.0.15619의 소스·stub·관측으로 확인한 뒤 구현한다.
2. required_scope가 실제 driver·parent·constraint·layer/key/interpolation·mesh/support 의존성을 재도출하도록 한다. authored projection과 sampled projection을 분리하고 host와 runtime의 canonical sample DTO를 일치시킨다. 사용자가 제공한 scope를 그대로 해시하거나 누락값을 0으로 채우지 않는다.
3. scene instance는 강한 참조, epoch, 실제 확인된 lineage로 식별한다. selection 의존 작업은 실제 selection digest를 읽는다. 첫 write 직전 같은 dependency closure를 동기 UI 임계 구역에서 확인하며 coverage/budget을 확보하지 못하면 차단한다.
4. 첫 writer는 기존 rig·기존 key의 position 또는 rotation 한 종류로 제한해 actual readback까지 연결한다. SDK 관측에 따라 구체 operation을 선택하며 reader만 등록된 항목을 mutation 지원으로 표시하지 않는다.
5. 활성화 증거는 소스 밖의 immutable record로 두고 bytes/hash/build/fingerprint/operation을 검증한다. 검증 전 adapter는 production disabled 상태로 유지한다. 좁은 native 증거 수집은 별도 disposable scene에서 명시적으로 승인된 관측으로 수행하고 production capability를 먼저 켜서 자기 인증하지 않는다.
6. 부분 hot reload의 디스크 hash를 실제 loaded bytes 증거로 간주하지 않는다. source/bridge를 함께 설치하고 깨끗한 재시작 뒤 bootstrap한다. 새로운 작업 지원 여부는 operation별 blocker로 반환한다.

**완료 조건**

- build·증거·의존 데이터 불일치에서 새 write 0회. 동일 파일의 다른 tab을 혼동하지 않는다.
- 검증된 한 operation에서 source→guarded write→actual readback→원 request receipt가 연결된다. 지원 범위는 실제 관측한 build/rig/operation으로 한정한다.

**최소 직접 확인(계획, 미실행):** L1: 변경 bridge 파일 정적 확인. L2: 잘못된 evidence/build 및 source 이후 key/interpolation 변경 거절에 대응하는 최소 직접 case.

**실제 환경에서 필요한 근거:** 고정 build의 SDK/schema, scene identity와 callback scheduling, 읽기 closure, 실제 writer/readback.

**소스:** [guarded_runtime.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/guarded_runtime.py#L16-L112) · [runtime dispatch](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/runtime.py#L988-L1027).

### R4-02 — 리그·시간·좌표·접촉 입력 자동 수집

**우선순위:** P0 · **기존 매핑:** T09, T10, T14, T15, T21, T32 · **선행:** R4-01

**변경 파일:** `src/cascadeur_complete/motion_context.py`, `src/cascadeur_complete/cleanup_workflow.py`, `src/cascadeur_complete/service.py`, `src/cascadeur_complete/server.py`, `신규 제안: src/cascadeur_complete/motion_profile_builder.py`.

**연결 함수·타입:** `제안: inspect_motion_inputs/resolve_motion_inputs/build_required_capture_scope`, `기존 service.capture_source/source_capture`.

**현재 문제:** 현재 cleanup과 공개 호출은 profile/context/intent/support를 호출자가 공급해야 한다. 구조 검증은 있으나 실제 장면에서 이를 조립하는 경로가 없다.

**구현 내용**

1. inspect_motion_inputs(character_ref, frame_range, support_refs, purpose) → MotionInputDraft, resolve_motion_inputs(draft_ref, overrides, intent_policy) → ResolvedMotionInputs를 제안한다. draft에는 값, 출처, 모호한 항목, 누락 항목과 원본 지문을 함께 둔다.
2. stable ID·ownership·hierarchy·rest/local axes·bone lengths·skin/mesh·key/layer·읽을 수 있는 FPS/단위/좌표계를 native reader에서 얻는다. 이름 매칭은 후보만 제안하고 중복/다른 캐릭터 소유권을 검증한다. 재사용 profile도 rig 구조 지문에 대조한다.
3. root 위치와 회전을 각각 관측한다. 위치 전용 Point에서 root 회전을 0 오차로 만들지 않는다. 유리수 FPS와 정확한 time grid·basis·단위 provenance를 보존한다.
4. contact는 원본의 support-local plane 또는 triangle/barycentric anchor와 시간별 support transform을 사용한다. 자동 탐지를 쓰면 사전에 승인한 정책에서 원본 한 번을 분석해 interval/mode/anchor를 고정한다. candidate에 유리하게 contact를 다시 정의하지 않는다.
5. 사용자에게는 캐릭터·범위·repair/styling 목적·수정 한도·모호한 support/prop만 받는다. 관측 불가 값만 확인 요청한다. runtime이 source를 독립 발급하며 사용자가 complete/hash/receipt를 작성하지 않는다.

**완료 조건**

- 원시 profile JSON 없이 작은 실제 캐릭터의 입력 draft를 만들 수 있다.
- 누락·소유권 모호성·stale draft는 구체적 blocker를 반환한다. 기본값을 관측 사실로 승격하지 않는다.

**최소 직접 확인(계획, 미실행):** L1/L2: builder의 중복 role/누락 root rotation/stale draft 직접 case.

**실제 환경에서 필요한 근거:** 실제 hierarchy/rest/ownership/FPS·unit·basis/key/support reader.

**소스:** [필수 입력](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/cleanup_workflow.py#L44-L74) · [profile/context](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/motion_context.py#L24-L241) · [공개 호출](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/server.py#L960-L1107).

### R4-03 — 선언 계획을 실제 operation·파생 ID 권한으로 연결

**우선순위:** P0 · **기존 매핑:** T22, T24, T25 · **선행:** R4-01

**변경 파일:** `src/cascadeur_complete/recipe_models.py`, `src/cascadeur_complete/recipe_planning.py`, `src/cascadeur_complete/recipe_authorization.py`, `src/cascadeur_complete/recipe_runner.py`, `src/cascadeur_complete/service.py`.

**연결 함수·타입:** `compile_steps/validate_step_authorization/_prepare`, `제안: resolve_stage_effect/BootstrapGrant/StageEffect/DerivedTargetRef`.

**현재 문제:** 파일 input은 source capture 전에 실행되지만 complete binding이 요구된다. rig/motion 선언 dict와 실제 handler 인자의 digest가 다르고, import/새 rig가 생성할 ID를 후속 exact target으로 연결할 모델이 없다.

**구현 내용**

1. BootstrapGrant를 initial source 또는 exact FileManifest, operation/신규 경로, plan/step/run/lease, build/epoch에 결합한다. snapshot이 없는 최초 보호 복제·입력 단계에만 사용하고 일반 mutation의 snapshot 요구를 유지한다.
2. StageEffect에 operation/effect class, canonical arguments와 digest, declaration digest, exact source, input/output artifact, effect bounds, 예상 successor, derivation 증거를 둔다. 선언→실제 인자 lowering 규칙 자체를 승인한다.
3. literal effect는 기존 exact 인자 검사, derived effect는 승인된 변환과 결과 exact 인자 검사를 모두 한다. 단순히 digest 검사를 제거하지 않는다.
4. DerivedTargetRef는 producer step/terminal receipt, role/path selector, topology·ownership, cardinality를 승인에 묶는다. 실제 생성 ID/layer/instance를 immutable mapping으로 저장하고 dispatch 전에 재검증한다. 모호한 이름 첫 항목이나 wildcard로 확대하지 않는다.
5. 기존 CleanupWorkflow._bind_source의 operation별 재발급을 유지한다. 새 generic input/rig/motion/checkpoint/export에 최종 payload가 정해진 뒤 같은 trusted rebind를 적용한다. 원본 baseline/intent는 바꾸지 않는다.
6. initial preflight와 continuation preflight를 분리한다. continuation은 immutable 원본 artifact와 terminal predecessor가 증명한 current binding·lineage를 검사하며 최초 active scene으로 되돌리라고 요구하지 않는다.

**완료 조건**

- 파일 bootstrap→실제 생성 ID→일반 보호된 후속 변경을 하나의 승인된 계획으로 연결한다.
- payload/producer/target/path 바꿔치기는 token 발급 전에 차단하고, 정상 successor의 resume은 허용한다.

**최소 직접 확인(계획, 미실행):** L2: 선언 lowering, producer ID/경로 변조 거절, initial/continuation 구분 직접 case. 공개 공유 모델 변경 시 해당 모듈 L3까지만.

**실제 환경에서 필요한 근거:** 새 scene/rig 실제 생성 identity와 ownership은 R4-04/R4-10에서 공급.

**소스:** [현재 compile](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_planning.py#L48-L123) · [현재 권한](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_authorization.py#L59-L117) · [기존 rebind](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/cleanup_workflow.py#L76-L123) · [preflight](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/service.py#L119-L153).

### R4-04 — 초기 backup·working scene·checkpoint·조건부 rollback 구현

**우선순위:** P0 · **기존 매핑:** T05, T06, T26 · **선행:** R4-01, R4-03, R4-05

**변경 파일:** `src/cascadeur_complete/change_flow.py`, `src/cascadeur_complete/recovery.py`, `cascadeur_side/cascadeur_complete/runtime.py`, `cascadeur_side/cascadeur_complete/guarded_runtime.py`, `신규 제안: native checkpoint/rollback adapter`.

**연결 함수·타입:** `prepare_change 주변의 별 bootstrap prepare`, `_save_snapshot/_run_operation/_verified_rollback_adapter`, `제안: prepare_initial_checkpoint/execute_initial_checkpoint/capture_successor`.

**현재 문제:** 일반 scene/mixed prepare가 이미 snapshot_manifest를 요구하여 첫 checkpoint 생성에 순환 의존이 있다. 기존 save/copy/load 경로만으로 native 완료·새 instance·lineage·write phase를 증명하지 못한다.

**구현 내용**

1. 초기 source 또는 FileManifest와 BootstrapGrant를 먼저 영속화하고 기존 request ledger/mutation lane에 진입한다. first effect 직전 원본을 재검사한 뒤 immutable backup과 별 working scene을 만든다.
2. Save As로 live object의 파일명만 바뀐 상태를 새 clone이라고 처리하지 않는다. 실제 별 instance의 authored/sample 동등성, parent→child 관계를 관측한 경우에만 lineage를 연결한다.
3. 원본/working/backup/checkpoint 경로, SHA256/length, scene instance/epoch/lineage, source digest, request/receipt, plan/profile을 manifest에 결합한다. 저장 완료는 native 신호·관측을 사용하며 파일 존재·크기 안정만으로 판정하지 않는다. 기존 파일 덮어쓰기는 하지 않는다.
4. 후속 성공 변경의 actual readback 뒤 successor checkpoint를 별 request로 저장한다. 첫 checkpoint와 후속 checkpoint 모두 같은 강도의 receipt/manifest 검사를 적용한다.
5. 복구는 인증된 원 terminal partial failure와 현재 post-source, 조상 snapshot, 일회용 RecoveryPermit에만 허용한다. copy/open 실제 경계에 before_write/finish_write를 연결하고 새 경로·새 working instance로 복구한다.
6. snapshot 검증→복사→native load 사이 파일 변경을 막는 조건을 실제 Windows/SDK loader 동작에 맞춰 확보한다. 실패한 working scene과 원 실패 receipt는 보존한다. unknown·prewrite 거절·다른 scene·변조 snapshot·이미 claim한 복구에서는 복구 0회, 재귀 복구도 0회다.

**완료 조건**

- 선행 snapshot 없는 최초 protected bootstrap이 정확한 별 권한으로 실행되고 일반 변경은 여전히 snapshot을 요구한다.
- 복구 성공은 실제 파일·새 instance·동일 lineage·완료 phase를 만족하며 원 실패 기록과 분리된다.

**최소 직접 확인(계획, 미실행):** L2: bootstrap 권한의 다른 작업 재사용 거절, checkpoint 완료 불명, terminal partial failure의 one-attempt 복구 직접 case.

**실제 환경에서 필요한 근거:** clone/save/load 완료, 다른 tab 보존, 파일 hash·loader sharing, 실제 successor identity.

**소스:** [snapshot 선행 요구](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/change_flow.py#L111-L141) · [기존 snapshot](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/runtime.py#L918-L974) · [기존 rollback](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/runtime.py#L1349-L1368) · [복구 판정](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recovery.py#L199-L226).

### R4-05 — native 완료 불명·successor를 durable receipt에 반영

**우선순위:** P0 · **기존 매핑:** T05, T06, T26 · **선행:** R4-01, R4-03

**변경 파일:** `cascadeur_side/cascadeur_complete/runtime.py`, `cascadeur_side/cascadeur_complete/guarded_runtime.py`, `src/cascadeur_complete/bridge_client.py`.

**연결 함수·타입:** `execute_request/_drain_once/receipt_event`, `제안: NativeEffectObservation/capture_successor`.

**현재 문제:** 현재 dispatch 결과를 terminal success/failure로 마무리하고 old scope로 post capture한다. 향후 완료 불명 또는 scene 교체 adapter를 넣을 때 이 분기를 그대로 쓰면 unknown·successor 계약과 충돌한다.

**구현 내용**

1. NativeEffectObservation은 완료 관측, 효과 없음이 증명됨, 완료 불명을 구분한다. Python 함수 반환·예외만으로 native 완료 또는 terminal failure를 확정하지 않는다.
2. 실제 synchronous_no_yield 완료가 확인된 범위만 활성화한다. 비동기 작업은 지원되는 operation-correlated completion protocol이 별도로 있을 때만 추가하고, 미관측 API는 disabled로 둔다.
3. dispatch 이후 unknown은 원 request/claim/nonce를 보존한다. _drain_once가 이를 rejected_pre_dispatch로 바꾸지 않도록 분기한다. 새 ID 재실행·rollback·후속 evaluation/export를 막고 원 receipt만 reconcile한다.
4. post capture를 same-instance와 승인된 successor로 분리한다. successor는 원 source, effect/receipt, 실제 새 identity·scope·lineage를 결합해야 한다.
5. 여러 transaction이 있는 operation은 request 전체의 write phase를 누적한다. 앞에서 이미 쓴 뒤 guard 실패를 before-first-write로 오표시하지 않는다. host quality 실패가 원 native terminal outcome을 덮지 않는다.

**완료 조건**

- unknown 이후 새 dispatch/복구 0회. late receipt가 오면 원 request의 결과만 갱신한다.
- scene 교체 뒤 실제 successor binding이 나오며 old scope를 다른 scene에 임의 재사용하지 않는다.

**최소 직접 확인(계획, 미실행):** L2: dispatch 후 unknown 보존, late receipt, 누적 write phase, successor 관측에 대응하는 직접 case.

**실제 환경에서 필요한 근거:** 지원 operation의 실제 완료 신호, no-yield 범위, successor 관측.

**소스:** [runtime terminal 처리](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/runtime.py#L1440-L1542) · [queue 정리](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/runtime.py#L1851-L1857).

### R4-06 — checkpoint와 resume을 실제 worker 진행에 연결

**우선순위:** P0 · **기존 매핑:** T06, T07, T25, T26 · **선행:** R4-03, R4-04, R4-05

**변경 파일:** `src/cascadeur_complete/recipe_runner.py`, `src/cascadeur_complete/recipe_store.py`, `src/cascadeur_complete/recipe_models.py`, `src/cascadeur_complete/service.py`.

**연결 함수·타입:** `resume/_schedule/_supervise/advance_once/_finish_native/reconcile`, `recipe_checkpoint/compare_and_update/adopt`.

**현재 문제:** start의 supervisor는 이미 있다. 문제는 resume이 reconcile 후 바로 반환해 running/verifying로 풀린 run을 다시 예약하지 않는 분기와, checkpoint 결과를 verified/sha256 dict로만 받는 연결이다.

**구현 내용**

1. reconcile이 실행 가능한 상태로 풀면 per-run worker를 깨운다. worker가 종료 중일 때 들어온 wakeup도 잃지 않도록 작은 wakeup/종료 처리를 둔다. 취소·만료·현재 native unknown 상태에서는 새 effect를 시작하지 않는다.
2. 최초 bootstrap checkpoint를 첫 보호 변경보다 앞에 두고 후속·최종 checkpoint도 독립 StepRecord/request/receipt/artifact로 저장한다. typed CheckpointObservation을 소비하고 임의 verified bool을 완료로 인정하지 않는다.
3. checkpoint 저장 후 host 중단 시 원 receipt와 저장된 manifest를 조회해 다음 단계로 이어간다. 같은 save/import/clone을 새 ID로 반복하지 않는다.
4. initial/continuation preflight를 R4-03 계약에 맞춰 호출한다. 원본 baseline/intent는 immutable, run.current_binding은 인증된 successor로 갱신한다.
5. finite variant/iteration/time/call/key 예산은 기존 계획에 고정한다. 품질 미달 시 승인된 후보만 시도하고 한도 소진은 명시적 실패로 끝낸다. 실행 중 품질 기준을 낮추거나 과거 결과를 새 원본으로 바꾸지 않는다.

**완료 조건**

- unknown→late success→한 번의 resume으로 후속 verification/checkpoint/host 단계가 진행한다.
- checkpoint 중단·취소·만료에서 native 재dispatch나 권한 밖 후속 실행이 없다.

**최소 직접 확인(계획, 미실행):** L2: resume early-return 재현 case, checkpoint 완료와 manifest 기록 사이 중단, worker exit/wakeup 경합의 직접 case.

**실제 환경에서 필요한 근거:** checkpoint 실제 완료 증거는 R4-04가 공급.

**소스:** [resume/scheduler](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L158-L241) · [checkpoint/export 분기](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L297-L313) · [reconcile](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L598-L654).

### R4-07 — 실제 layer/key·보간 모델과 fitting 한도 연결

**우선순위:** P0 · **기존 매핑:** T08, T19, T21, T24, T25 · **선행:** R4-01, R4-02

**변경 파일:** `src/cascadeur_complete/motion_solvers.py`, `src/cascadeur_complete/cleanup_workflow.py`, `src/cascadeur_complete/recipe_runner.py`, `cascadeur_side/cascadeur_complete/handlers/animation.py`.

**연결 함수·타입:** `build_key_model/fit_keys/plan_pass`, `제안: capture_key_model/evaluate_key_candidate`, `recipe_verify_interpolation 대체 내부 descriptor`.

**현재 문제:** 현재 LINEAR/STEP 문자열 기반 verified와 선형 fitting은 native curve를 관측한 증거가 아니다. plan_pass에서 허용한 fitting limit 일부도 fit_keys 호출에 전달되지 않는다.

**구현 내용**

1. KeyLayoutObservation에 driver/channel/space, owning layer/key ID/frame, 구간 mode/tangent/ease, blend/cycle/controller 영향, 영향구간 앞뒤 key, evaluator/build/source 지문을 담는다.
2. 실제로 확인된 LINEAR/STEP은 sparse model을 사용한다. BEZIER/AutoPosing/unknown은 검증된 evaluator 또는 승인된 dense-key 방식의 명시적 coverage를 사용하고, 모델을 모르면 INTERPOLATION_MODEL_UNVERIFIED를 유지한다.
3. fit_error_m, velocity/acceleration weight, iteration/resource budget 등 허용된 값을 fit_keys에 명시 전달한다. residual, sample schedule, model/source digest, unchanged interval·lock 보존 결과를 반환한다.
4. preflight·solver·permit이 같은 descriptor digest를 사용하게 한다. recipe_verify_interpolation의 bool이나 호출자 interpolation_capabilities만으로 지원을 인증하지 않는다.
5. native Euler↔quaternion 변환과 per-driver key grid를 실제 writer에 연결한다. 서로 다른 layer의 key grid를 임의 합집합/교집합으로 강제하지 않는다. interpolation 변경은 명시적으로 승인한 범위에만 허용한다.

**완료 조건**

- 키 위치는 맞지만 중간에 overshoot하는 작은 사례를 actual evaluator가 검출하거나 unverified로 표시한다.
- 사용자가 지정한 fitting 한도가 실제 solver에 전달되고 모델/source가 달라지면 stale로 막힌다.

**최소 직접 확인(계획, 미실행):** L2: 해당 fitting 한도 전달, 서로 다른 key grid, descriptor stale/unknown mode 직접 case.

**실제 환경에서 필요한 근거:** 실제 curve/tangent/controller evaluation 및 native 회전 convention. 연속 coverage는 별 근거 없으면 제공하지 않는다.

**소스:** [key model/fit](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/motion_solvers.py#L45-L123) · [fitting 호출](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/cleanup_workflow.py#L316-L377) · [recipe 차단](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L88-L107).

### R4-08 — 실제 motion·reskin 결과로 필수 품질 판정

**우선순위:** P0 · **기존 매핑:** T11, T12, T13, T14, T15, T16, T17, T18, T19, T21 · **선행:** R4-01, R4-02, R4-04, R4-05, R4-06, R4-07, R4-15

**변경 파일:** `src/cascadeur_complete/cleanup_workflow.py`, `src/cascadeur_complete/motion_quality.py`, `src/cascadeur_complete/motion_geometry.py`, `src/cascadeur_complete/recipe_runner.py`, `cascadeur_side/cascadeur_complete/handlers/animation.py`, `cascadeur_side/cascadeur_complete/handlers/mesh.py`.

**연결 함수·타입:** `제안: capture_actual_motion/capture_actual_geometry/measure_actual_quality`, `기존 evaluate_quality/recipe quality stage`.

**현재 문제:** 기존 writer는 쓴 key를 readback하지만 key 사이와 전체 영향구간·reskin까지 입증하지 않는다. recipe quality에 actual mesh penetration/intersection producer가 연결되지 않았다.

**구현 내용**

1. 실제 write 완료 뒤 원본과 같은 시간·공간·역할 기준으로 parent/local/global·root·dependency를 다시 샘플한다. authored data를 바꾸는 interpolation refresh는 evaluation effect로 취급한다.
2. 실제 reskin 완료 후 body/garment/prop/support geometry를 제한된 window로 캡처하고 source/successor, completion receipt, topology/skin digest, 단위·공간·time schedule·coverage·각 window hash를 기록한다.
3. 원본 baseline, solver prediction, native actual, 최종 target capture를 서로 다른 digest로 보존한다. prediction-actual residual과 original-actual 품질을 모두 측정하며, 누적 수정 한도는 항상 처음 원본에 비교한다.
4. root 위치/회전, 역할별 envelope, lock/key pose, non-target, bone/IK, 승인 contact/support, 요청한 mesh metric을 필수 closure로 계산한다. 누락·NaN·stale source·reskin 미관측은 pass가 아니다.
5. 실제 손·발·소품 접촉은 승인된 영역/시간/tolerance로만 제외한다. open mesh의 unknown sign이나 baseline 표면을 candidate 실제 표면으로 간주하지 않는다. 양팔/몸/옷은 변경 후 함께 측정한다.
6. sampled_frames와 연속 시간 coverage를 분리한다. 연속 구간 무충돌이 요구되면 실제 subframe 평가와 시간구간 상한 근거가 있는 evaluator를 추가하고, 그 전에는 sampled 통과로 연속 품질을 주장하지 않는다.

**완료 조건**

- host 예측과 실제 controller/skin 결과가 다르면 차이를 반환하며 native 완료만으로 품질 pass를 만들지 않는다.
- 필수 metric 전체가 실제 capture에 근거하고 누락 하나라도 품질은 failed 또는 unverified다.

**최소 직접 확인(계획, 미실행):** L2: actual/source 불일치, root rotation 누락, required mesh metric 누락, 원본 누적 envelope 위반에 대응하는 작은 case.

**실제 환경에서 필요한 근거:** actual readback·reskin 완료와 시간별 mesh. 연속 coverage가 필요하면 별 실제 evaluator 근거.

**소스:** [현재 actual quality](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L434-L447) · [필수 품질](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/motion_quality.py#L56-L307) · [mesh producer](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/handlers/mesh.py#L62-L137).

### R4-09 — 승인된 범위의 sparse key 삽입

**우선순위:** P1 · **기존 매핑:** T18, T19, T24, T25 · **선행:** R4-03, R4-06, R4-07, R4-08

**변경 파일:** `src/cascadeur_complete/cleanup_workflow.py`, `src/cascadeur_complete/recipe_runner.py`, `src/cascadeur_complete/recipe_authorization.py`, `cascadeur_side/cascadeur_complete/handlers/animation.py`.

**연결 함수·타입:** `제안: plan_key_insertions/apply_key_topology_delta`, `plan_pass/_measured_effect`.

**현재 문제:** 필요한 기존 key가 없는 sparse styling은 KEY_LAYOUT_INSUFFICIENT로 차단된다. allow_key_insertion을 켜도 실제 삽입 adapter가 없다.

**구현 내용**

1. KeyTopologyDelta에 object/channel/layer, 기존 topology digest, 추가 frame/value/tangent/mode, 추가 수·영향구간·비대상 영향을 담는다.
2. allow_key_insertion, generated_keys budget, editable frames, lock/contact/event key 및 interpolation-change 권한을 모두 검사한다. layer 공유 효과도 원본 scope와 승인에 넣고 관측 불가하면 차단한다.
3. working scene에서만 승인된 delta를 적용하고 topology readback과 R4-08 품질을 확인한다. 기존 키 삭제·리타이밍·새 걸음 합성을 이 작업에 섞지 않는다.
4. 초기 recipe가 정책·최대 개수·범위를 승인했다면 키마다 재승인을 요구하지 않는다. 완료 unknown은 재삽입하지 않는다.

**완료 조건**

- 허용된 최소 key만 추가되며 실제 count/ownership/tangent/영향구간이 계획과 일치한다.
- opt-in이 없거나 SDK 미지원이면 기존 차단을 유지한다.

**최소 직접 확인(계획, 미실행):** L2: opt-in 없는 삽입 거절, shared layer 범위 및 key 예산 초과, 실제 topology 차이 직접 case.

**실제 환경에서 필요한 근거:** 대상 build의 key 생성·layer ownership·실제 보간 영향.

**소스:** [sparse 차단](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/cleanup_workflow.py#L390-L442) · [recipe key 제한](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L99-L107).

### R4-10 — 파일·리그·retarget·generation·unbaking stage 구현

**우선순위:** P1 · **기존 매핑:** T09, T22, T24, T25 · **선행:** R4-02, R4-03, R4-04, R4-05, R4-06, R4-07, R4-08

**변경 파일:** `src/cascadeur_complete/recipe_models.py`, `src/cascadeur_complete/recipe_planning.py`, `src/cascadeur_complete/recipe_runner.py`, `src/cascadeur_complete/service.py`, `src/cascadeur_complete/retargeting.py`, `cascadeur_side/cascadeur_complete/handlers/generation.py`.

**연결 함수·타입:** `compile_steps/_prepare/_host_step`, `recipe_input_arguments/recipe_rig_arguments/recipe_motion_arguments 또는 typed 대체`, `retarget_pose/controller_targets/generation.unbaking`.

**현재 문제:** 선언을 concrete SDK 인자로 낮추는 hook이 없고 host retarget은 실제 controller writer로 연결되지 않는다. 기존 단건 unbaking operation은 recipe mode/compile에 없다.

**구현 내용**

1. casc_file/fbx_file은 exact FileManifest→owned working 입력 effect→terminal load/import→실제 identity/ownership/파생 ID→source 순으로 컴파일한다. merge_into_working은 기존 working의 binding도 요구한다.
2. rig template/explicit mapping을 실제 등록 operation과 검증된 rig construction profile로 변환한다. 현재 compile의 rig.quick_rig라는 이름만으로 지원을 선언하지 않고 실제 registry/payload/completion을 확인한다.
3. native retarget은 현재 handler의 source_point_id/target_point_id/first_frame/last_frame과 source·target 소유권을 연결한다. source asset 로딩이 필요하면 effect를 계획에 명시한다.
4. host retarget은 host_compute로 retarget_pose를 실행하고 검증된 controller_targets adapter가 exact writer payload를 생성한 뒤 별 보호 write를 수행한다. motion.retarget이라는 이름으로 native dispatch하지 않는다. route는 승인 후 고정하며 native↔host 임의 fallback은 없다.
5. native root motion/inbetweening/keyposes/external asset은 실제 selection/layer/range/key·완료·결과를 관측한다. generation.unbaking은 기존 세 step enum만 허용하여 recipe mode와 topology bounds를 연결한다.
6. import/retarget의 원본 artifact와 원본 의도는 계속 보존한다. 새 모션 생성이 목적이면 승인된 생성 요구와 생성 직후 관측 baseline을 구분해 고정하고, 이를 기존 모션 repair의 원본 보존 증거로 오표시하지 않는다.
7. finger/wrist/hand/arm styling recipe는 각 canonical planner→verified controller adapter→동일 actual quality 경로로 연결한다. 지원되는 기존-key route와 key 삽입이 필요한 route를 구분하며 후자는 R4-09 완료 후 연다.

**완료 조건**

- 지원 대상으로 명시한 route가 실제 입력→리그→모션→actual capture까지 정확한 승인 범위에서 연결된다.
- 원본/대상 mapping·key topology·비대상 결과를 관측하며 revision/count 변화만으로 성공 처리하지 않는다.

**최소 직접 확인(계획, 미실행):** L2: native retarget payload lowering, host solve/write 분리, producer ID 오류, unbaking enum/scope의 직접 case.

**실제 환경에서 필요한 근거:** 각 선택 route의 SDK payload·완료·실제 rig/controller 결과. 전체 rig 지원으로 일반화하지 않는다.

**소스:** [motion declaration](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_models.py#L156-L174) · [compile](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_planning.py#L78-L99) · [기존 native motion](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/handlers/generation.py#L102-L179) · [host retarget](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/retargeting.py#L62-L138).

### R4-11 — AutoPhysics의 상태·완료 관측을 무인 실행에 연결

**우선순위:** P1 · **기존 매핑:** T08, T21, T23, T25 · **선행:** R4-01, R4-03, R4-04, R4-05, R4-06, R4-08

**변경 파일:** `cascadeur_side/cascadeur_complete/handlers/physics.py`, `src/cascadeur_complete/recipe_models.py`, `src/cascadeur_complete/recipe_planning.py`, `src/cascadeur_complete/recipe_runner.py`.

**연결 함수·타입:** `auto_physics_enable/auto_physics_snap/_auto_physics_state`, `제안: verified physics stage adapter`.

**현재 문제:** 현재 enable은 Switch Auto Physics toggle을 호출하며 내부 on/off를 못 읽는다고 명시한다. snap은 revision 변화로 completed_synchronously를 판단한다. r3 T23의 실제 상태·완료 연결은 아직 남아 있다.

**구현 내용**

1. 실제 enabled/working/failed 상태 reader와 확인 가능한 setter 또는 상태 기반 전이를 확보한다. 이를 못 읽으면 toggle을 ensure-on으로 바꾸거나 무인 recipe에 켜지 않는다.
2. physics 설정·target/center of mass·선택 layer/range·실제 지원 operation을 StageEffect에 묶고 key·시간·호출 한도를 승인한다. 반복 호출로 상태를 반전시키지 않는다.
3. snap 완료는 실제 완료 신호·confirmation state와 requested target motion 관측을 결합한다. revision/selection/playhead 변화만으로 완료·품질을 인증하지 않는다.
4. 관측 가능한 불가능/실패 상태, 완료 불명, 설정 미관측을 구분한다. native unknown에서는 새 snap/복구를 실행하지 않고 완료 후 R4-08 필수 품질을 적용한다.

**완료 조건**

- 상태를 알 수 없는 toggle은 자동 실행 불가로 남고, 검증된 route만 정확히 한 번 진행한다.
- 실제 완료되지 않은 snap이나 물리 실패가 성공·품질 pass로 보고되지 않는다.

**최소 직접 확인(계획, 미실행):** L2: 이미 on/상태 불명/중복 요청과 revision-only snap 판정에 대응하는 직접 case.

**실제 환경에서 필요한 근거:** 실제 physics state/setter·완료/confirmation·실패 상태. SDK 접근 전 함수명을 만들지 않는다.

**소스:** [현재 toggle/snap](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/handlers/physics.py#L570-L619).

### R4-12 — native FBX export와 sealed artifact까지 runner 연결

**우선순위:** P0 · **기존 매핑:** T24, T25, T27, T28 · **선행:** R4-03, R4-04, R4-05, R4-06, R4-08

**변경 파일:** `src/cascadeur_complete/recipe_runner.py`, `src/cascadeur_complete/recipe_planning.py`, `src/cascadeur_complete/export_workflow.py`, `src/cascadeur_complete/export_models.py`, `cascadeur_side/cascadeur_complete/runtime.py`.

**연결 함수·타입:** `advance_once/_preflight/reconcile`, `create_export_stage/seal_export`, `제안: native export settings/scope/completion adapter`.

**현재 문제:** 현재 export_stage/export_validate/publish는 hook 유무와 관계없이 항상 EXPORT_STAGE_REQUIRES_PERSISTED_NATIVE_PREPARATION으로 막힌다. 기존 inline exporter도 exists_on_return만으로 완료를 증명하지 못한다.

**구현 내용**

1. preflight와 실행 hook 이름/계약을 일치시키고 unconditional raise를 native stage→seal→validate→publish의 영속 상태 전이로 바꾼다.
2. 최종 destination과 raw staging을 구분하여 승인된 staging 생성 규칙·owned 경로·run/step을 concrete StageEffect에 고정한다. plan의 output_paths 검사와 같은 권한 범위에 넣는다.
3. 선택 skeleton/mesh closure를 격리하고 take/range/FPS/axes/unit/root/bake 설정을 실제 적용·readback하여 ExportProfile에 결합한다. export_all_objects를 대상 격리 증거로 쓰지 않는다.
4. export 직전 actual postcleanup capture에서 ExportExpectation을 생성한다. 정확한 time grid·topology·rest-relative rotation, 원본 baseline/intent/support/policy와 actual before-export refs를 별도로 고정한다.
5. 원 request/run/step/attempt/lease/operation/profile/raw path와 실제 완료가 일치하는 terminal receipt에만 seal_export를 호출한다. recipe에서는 null run/step을 허용하지 않는다.
6. 파일 존재/크기 안정/dispatch 성공은 완료가 아니다. unknown은 원 request를 유지하며, terminal 후 sealing 중 중단은 기존 native 결과에서 이어간다.

**완료 조건**

- actual source/profile에 결합된 native 완료 receipt와 sealed SHA256를 만들고 staged까지만 갱신한다.
- 다른 receipt/profile/path 또는 dispatch-only 결과는 seal 전에 거절된다.

**최소 직접 확인(계획, 미실행):** L2: 현재 unconditional branch 수정 확인, receipt/profile/path 불일치, native 완료 뒤 seal 중단의 직접 case.

**실제 환경에서 필요한 근거:** 실제 exporter 설정·대상 격리·완료 관측·export 파일.

**소스:** [export 항상 차단](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L307-L313) · [기존 stage/seal](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/export_workflow.py#L25-L94) · [inline export](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/cascadeur_side/cascadeur_complete/runtime.py#L1339-L1348).

### R4-13 — 실제 소비자 capture를 원본 기준 품질 평가에 연결

**우선순위:** P0 · **기존 매핑:** T21, T29 · **선행:** R4-02, R4-08, R4-12

**변경 파일:** `src/cascadeur_complete/external.py`, `src/cascadeur_complete/blender_export_adapter.py`, `src/cascadeur_complete/export_workflow.py`, `src/cascadeur_complete/motion_quality.py`, `src/cascadeur_complete/recipe_runner.py`.

**연결 함수·타입:** `validate_target_import/_compare_target_capture/validate_export_roundtrip`, `제안: decode_target_capture/capture_verifier/roundtrip_validator closure`.

**현재 문제:** roundtrip_validator가 없으면 import report가 있어도 품질은 미확인이다. Blender의 position_m/rotation_delta_wxyz dict와 공용 SampleBatch 사이 변환·출처 인증·원본 문맥 연결이 없다.

**구현 내용**

1. 실제 target executable/importer/adapter/settings bytes 지문을 고정하고 sealed artifact와 ExportExpectation, before-export actual, original reference, rig mapping, intent/policy/support/geometry refs를 공급한다.
2. 실제 imported report를 canonical SampleBatch로 변환한다. units/basis/time origin/rest·bind alignment를 명시하고 delta quaternion을 absolute quaternion으로 그대로 복사하지 않는다. 필요한 rest 정보는 실제 관측 또는 검증된 원본 profile에서 얻는다.
3. subprocess 종료·nonce·input SHA·설치 bytes·report schema를 검사한 뒤 raw→canonical capture의 digest 관계를 immutable record로 남긴다. 내부 capture_verifier는 그 exact capture만 인증하며 caller의 verified/ok 선언은 받지 않는다.
4. roundtrip_validator가 공용 validate_export_roundtrip에 original reference와 before-export actual을 모두 넘긴다. 원본 intent뿐 아니라 export 변환 오차도 검사한다.
5. mesh가 있으면 실제 reimport evaluated geometry를 공급하고 support/prop은 원본 timeline으로 평가한다. required metric·joint/frame/channel coverage가 빠지면 unverified를 유지한다.
6. 첫 소비자는 실제 설치 bytes가 확인된 Blender 한 profile로 제한한다. 지원하지 않는 action/container/rest layout은 명확히 차단한다. 버전 이름만 같은 설치나 다른 DCC로 통과를 확대하지 않는다.

**완료 조건**

- 실제 target capture로 원본 의도와 export 직전 실제 결과를 모두 비교한 ValidationBundle이 같은 sealed SHA256에 결합된다.
- 출처·rest/time 변환·required geometry가 없으면 품질 pass가 나오지 않는다.

**최소 직접 확인(계획, 미실행):** L2: basis/time/rest 변환의 직접 case와 잘못된 capture SHA/nonce/필수 metric 누락 거절.

**실제 환경에서 필요한 근거:** 고정 소비자의 실제 import·pose/mesh capture. 현재 미실행.

**소스:** [validator 공백](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/external.py#L121-L203) · [공용 roundtrip](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/motion_quality.py#L320-L369) · [target producer](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/blender_export_adapter.py).

### R4-14 — 검증 후 게시와 run 결과·취소·crash 복구 연결

**우선순위:** P0 · **기존 매핑:** T26, T30 · **선행:** R4-03, R4-06, R4-12, R4-13

**변경 파일:** `src/cascadeur_complete/recipe_runner.py`, `src/cascadeur_complete/recipe_authorization.py`, `src/cascadeur_complete/recipe_store.py`, `src/cascadeur_complete/export_publisher.py`.

**연결 함수·타입:** `advance_once/resume/cancel/publish_verified/reconcile_publish`.

**현재 문제:** 원자 게시 helper는 있으나 runner의 publish 분기가 막혀 실제 승인·상태·재개와 연결되지 않는다.

**구현 내용**

1. 승인된 run/profile/destination/overwrite, ValidationBundle, sealed SHA256에서만 내부 PublishPermit를 발급한다. 새 publish 직전에 cancel/expiry를 확인한다.
2. publish intent와 결과를 durable StepRecord에 연결하고 실제 published일 때만 run.export를 갱신한다. final과 sealed는 별 inode를 유지한다.
3. 기존 publish intent가 있으면 만료 여부에 앞서 reconcile_publish로 이미 일어난 결과를 조회한다. 만료 후 결과 관찰은 가능하지만 새 overwrite/re-export는 하지 않는다.
4. rename/link 후 host 중단 또는 sidecar 오류가 있어도 이미 게시된 파일을 취소 명목으로 삭제하지 않는다. no-clobber와 content/identity conflict를 보존한다.
5. run succeeded는 actual motion quality pass와, export 요청이 있으면 해당 artifact의 validated+published를 모두 요구한다. dispatch accepted나 구조 검사만으로 성공하지 않는다.

**완료 조건**

- 같은 artifact가 한 번 게시되고 중단·취소·만료 후 재개가 기존 final을 다시 쓰지 않는다.
- 권한 밖 destination/overwrite 또는 품질 미통과 artifact는 게시되지 않는다.

**최소 직접 확인(계획, 미실행):** L2: runner의 publish 직전 cancel, 권한 밖 destination, 게시 후 기록 전 중단 복구 직접 case.

**실제 환경에서 필요한 근거:** R4-12/13의 실제 완료와 품질 증거를 소비한다.

**소스:** [현재 publish helper](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/export_publisher.py#L113-L194) · [현재 runner 분기](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_runner.py#L307-L313).

### R4-15 — sparse solver·실제 peak에 맞는 자원 예산

**우선순위:** P1 · **기존 매핑:** T13, T19, T20, T25 · **선행:** R4-02, R4-07

**변경 파일:** `src/cascadeur_complete/recipe_planning.py`, `src/cascadeur_complete/motion_solvers.py`, `src/cascadeur_complete/motion_geometry.py`, `cascadeur_side/cascadeur_complete/handlers/mesh.py`.

**연결 함수·타입:** `input_preflight/solve_contacts_v2/fit_keys/WindowedSurfaceTrack`, `제안: estimate_motion_resources/validate_resource_budget`.

**현재 문제:** contact solver는 sparse 구조인데 recipe preflight는 n*n*128 bytes로 추정한다. contact에는 arm과 같은 nnz 예산 제한도 없다. dense n×n 할당 결함이 확인된 것은 아니다.

**구현 내용**

1. 실제 per-driver key 수·변수·D1/D2/fit/constraint nnz와 index/data 폭, solver workspace/factorization의 확인된 상한, 활성 geometry window를 계산한다.
2. float32→float64·정규화/geometry 생성 임시 복사, retained original/candidate/actual, payload·disk peak를 함께 센다. nnz만으로 factorization peak를 정확히 보장한다고 표기하지 않는다.
3. contact에 max_variables/max_nonzeros/메모리 한도를 allocation/factorization 전에 적용하고 fitting에도 실제 모델·예산을 전달한다. n*n*128은 sparse 기반 추정으로 바꾸되 한도 자체는 제거하지 않는다.
4. transport/geometry는 나눠도 global source·D1/D2·contact anchor를 독립 solve로 분할하지 않는다. 겹친 결과는 동일성을 확인하고 평균으로 차이를 숨기지 않는다.
5. 큰 hash/artifact 입력은 전체 read_bytes 복사 대신 bounded reader를 관련 경로에만 적용한다. 예산 초과는 필요한 양/허용량을 반환하고 clip 범위를 몰래 줄이지 않는다.

**완료 조건**

- 작은 sparse case의 변수/nnz/배열 예측이 실제 구성과 맞고 낮은 예산은 큰 allocation 전에 막는다.
- 긴 clip을 제곱 추정으로 무조건 차단하거나 실제 메모리 제한 없이 무조건 허용하지 않는다.

**최소 직접 확인(계획, 미실행):** L2: 작은 행렬의 예산 산정과 의도적으로 작은 budget 차단 직접 case. 장시간 benchmark는 기본 gate가 아니다.

**실제 환경에서 필요한 근거:** 큰 규모 지원을 선언하려면 해당 backend/workspace 상한 또는 별 실측이 필요하다.

**소스:** [현재 메모리 추정](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/recipe_planning.py#L145-L152) · [sparse contact](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/motion_solvers.py#L344-L523) · [기존 arm budget](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/motion_solvers.py#L191-L205).

### R4-16 — 설치 교체 시 receipt·키·재개 상태와 지원 표기 보존

**우선순위:** P0 · **기존 매핑:** T02, T05, T06, T26, T31, T32 · **선행:** R4-01, R4-03, R4-05, R4-06

**변경 파일:** `scripts/install.ps1`, `packaging/install-hooks.ps1`, `scripts/build-release.ps1`, `src/cascadeur_complete/paths.py`, `src/cascadeur_complete/package_fingerprint.py`, `README.md`, `docs/KNOWN_ISSUES_2026-11-15.md`.

**연결 함수·타입:** `source runtime 교체·state 이관`, `manifest 생성·runtime handshake·operation capability`.

**현재 문제:** source install은 old runtime을 backup으로 옮긴 뒤 ownership/snapshots/live_evidence만 새 root로 가져온다. request_records·인증키·one-attempt 상태를 이어가는 코드가 없다. frozen installer까지 같은 손실로 일반화하지 않는다.

**구현 내용**

1. 기존 store path 정의를 사용해 bridge/confirmation keys, request/response/receipt, seen/consumed marker, recovery claim/permit/result, recipe/job/checkpoint/staged 참조를 인증 가능한 상태 집합으로 staging에 보존한다. 키 내용은 로그에 쓰지 않는다.
2. 새 import가 새 키를 만들기 전에 기존 상태를 이어야 한다. 실행 중인 이전 bridge와 state 교체가 경합하지 않게 한다. 이전 프로세스 종료만으로 unknown을 실패·미실행으로 바꾸지 않는다.
3. 구 queued/running과 source는 보존하되 자동 실행하지 않는다. 기존 token을 재서명하거나 replay marker를 지우지 않는다. 새 epoch에서는 새 source로만 새 mutation을 허용한다.
4. source/frozen의 기존 manifest 생성 체계를 재사용하고 신규 adapter 모듈·detached evidence를 필요한 패키지에 포함한다. host/bridge를 함께 갱신하고 재시작한 실제 loaded fingerprint를 대조한다.
5. 원 request receipt 조회는 fingerprint 변경 후에도 가능하게 유지한다. 과거 live evidence는 보존하지만 새 build/adapter에서 현재 지원 증거로 자동 재사용하지 않는다.
6. capability와 문서는 operation/rig/consumer/coverage별 실제 지원 및 blocker를 표시한다. 원래 r3 설계 PASS는 역사 기록으로 유지하며 구현·실행 완료 증거로 덮어쓰지 않는다.

**완료 조건**

- upgrade 뒤 원 request의 terminal/unknown과 recovery claim을 원 인증 근거로 조회할 수 있다.
- 새 runtime에서 이전 source/token이 새 실행 권한이 되지 않으며 지원 범위는 실제 검증 조합만 표시된다.

**최소 직접 확인(계획, 미실행):** L2: 임시 root의 최소 receipt/key/unknown/recovery claim 이관 case. installer 전체 실행·release build·CI는 별도 승인 없이 실행하지 않는다.

**실제 환경에서 필요한 근거:** 실제 Windows source upgrade·재시작 후 receipt 조회와 loaded manifest 확인은 이후 실행 항목.

**소스:** [source install](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/scripts/install.ps1#L74-L155) · [install hooks](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/packaging/install-hooks.ps1#L16-L105) · [state 경로](https://github.com/muhwagwa0112/cascadeur-complete/blob/c55981152f40afee24221d70aa972235754a105e/src/cascadeur_complete/paths.py#L46-L61).
## 6. 검증 범위와 현재 판정

이번에 수행한 것은 고정 commit의 관련 제어 흐름·입력 계약·차단 이유 정적 확인과 이 추가 계획의 작성·세 담당 검수다. 새 구현 메모가 적은 과거 테스트 결과를 이번 실행 결과로 세지 않는다.

향후 구현 검증은 충분한 가장 낮은 단계에서 멈춘다. 변경 파일의 L1 또는 해당 결함의 최소 L2를 기본으로 하며, 공유 모델·공개 인터페이스가 실제 바뀌는 경우에만 해당 모듈 L3를 고려한다. 새 테스트는 버그 재현·수정 확인에 가장 저렴한 경우만 기존 파일에 최소 추가한다. 전체 suite·전체 build·CI·광범위 E2E·장시간 benchmark는 기본 완료 gate가 아니다.

실제 SDK 동작을 인증해야 하는 좁은 확인도 실행 전에 실제 환경과 승인 범위를 맞춘다. 전체 앱 왕복처럼 L4에 해당하는 확인은 구체적인 위험과 예상 실행 범위를 제시하고 승인받은 뒤 수행한다. API·schema·설치 설정·새 의존성/버전 변경 등 사전 승인 대상은 실제 구현 변경안을 구체화한 시점에 승인 범위를 확정한다. 현재는 그 실행을 요청하거나 수행하지 않았다.

검수 완료 조건은 시작 때 정한 세 범위로 고정한다: 품질은 실제 관측과 원본 보존, 자동화는 bootstrap→continuation→최종 파일 연결, 안정성은 권한·unknown·복구·upgrade 연속성이다. 새 전수감사나 통과한 항목의 재감사를 완료 직전 조건으로 추가하지 않는다.

**검수 상태:** 세 담당 모두 PASS. 아래 판정은 새 잔여 연결에 관한 계획 검수이며 제품 코드·실앱·최종 FBX의 실행 인증이 아니다.

| 담당 | 지정 검수 범위 | 판정 | 잔여 설계 차단 |
|---|---|---|---|
| 모션 품질 | 관측 입력·key/보간·actual reskin·원본 보호·key 삽입·sparse 예산·target 품질 문맥 | PASS | 0 |
| 자동화·export | bootstrap/파생 ID·continuation·resume/checkpoint·stage lowering·export/consumer/publish | PASS | 0 |
| native·안정성 | adapter 실제 실행·증거·초기 snapshot·unknown/successor·one-attempt recovery·upgrade 상태 | PASS | 0 |

산출물 정합성은 16개 고유 ID, 선행관계 비순환, 작업별 Markdown 절, 미실행 상태 표기를 직접 확인했다. 검수자는 지정된 연결의 반영 여부만 확인했으며 기존 32개 작업 전수 재감사나 제품 테스트를 수행하지 않았다.

## 7. 파일 및 실행 상태

- `ADDITIONAL_IMPLEMENTATION_PLAN.md`: 본 문서, 변경 파일·함수·계약·선행관계·완료 조건·소스.
- `implementation_tasks.json`: 동일 16개 작업의 기계 판독 가능한 목록과 수행 정책. 모든 작업은 planned_not_implemented / planned_not_run.
- 제품 코드 수정: 없음. 의존성/버전 변경: 없음. 테스트/설치/CI/실앱 실행: 없음. 추가 push: 없음.
- 실제 build/rig/operation/consumer/coverage 관측이 없는 부분은 지원 불가 또는 unverified를 유지한다. 설계 PASS를 완벽한 runtime 품질로 표현하지 않는다.

