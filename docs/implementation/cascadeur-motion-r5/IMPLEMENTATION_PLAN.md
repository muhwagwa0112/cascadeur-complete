# Cascadeur 반복 중단 개선안 — 코드 수준 준비본

기준일: **2026-11-16**  
저장소: `muhwagwa0112/cascadeur-complete`  
기준 브랜치: `feat/cascadeur-motion-r3`  
확인한 HEAD: **`fc0e98eaa30e819f98880a32dce30c6767a5cc64`**  
산출물 상태: **파일·함수별 구현 계약, 참조 코드, 미적용 patch 준비**. 제품 구현 완료·실앱 검증·설치·push를 뜻하지 않는다.

## 1. 결정

첫 구현 묶음은 **원 unknown을 보존하는 별도 incident 처리 + 새 요청 admission + 완료된 실패의 근거 보존**이다. 현재 원장을 삭제하거나 terminal을 다시 쓰는 방식으로 풀지 않는다. 이후 정확한 설치 profile과 qualifier 탭 수명을 정리하고, 실제 mesh 관측·저장 왕복 비교·unbaking 완료 계약을 연결한다.

새로운 전체 protocol 교체는 우선안에 넣지 않았다. 기존 signed `BridgeRequest`에 결합한 **별도 admission sidecar**와 새 native capability handshake로 host/native 양쪽의 실행 조건을 확인한다. journal·sidecar와 새 control API는 제안이므로 실제 적용 시 schema/API 변경 범위를 승인받는다.

완료 기준은 다음으로 고정했다.

- 이번 중단과 직접 연결된 파일/함수, 상태 전이, 데이터 형식, 호출 순서와 오류 처리가 명시되어 있다.
- 로컬 코드만으로 구현할 수 있는 부분과 실제 SDK·기존 private 기록이 있어야 활성화할 부분이 구분되어 있다.
- 코드 초안의 문법과 exact patch 문맥을 확인하고 그 범위를 기록한다. 제품 테스트나 새 CI 절차를 만들어 자동 실행하지 않는다.

## 2. 현재 코드에서 고쳐야 할 연결

| 결함/공백 | 정확한 변경 | 근거 |
|---|---|---|
| terminal unknown 하나가 새 source capture까지 막고 reconcile은 같은 receipt만 재조회 | 원 terminal과 별도 incident journal, 진단·후속 관찰·scoped retirement, 양쪽 admission | [bridge_client](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/bridge_client.py), [request_ledger](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/request_ledger.py) |
| 완료를 관측한 결과 mismatch도 공통 except에서 unknown | native 완료/actual effect closure와 postcondition을 분리하고 원 attempt에 결합 | [native_key_insertion](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/native_key_insertion.py) |
| adapter의 completed 실패 관찰 뒤 wrapper가 unknown을 추가 | private validator가 확인한 같은 요청의 관찰을 유지; terminal 직전 revocation 재검사 | [runtime](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/runtime.py), [independent-position](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/native_independent_position.py) |
| 오류의 `result=None` 때문에 post_source와 effect observation이 응답에 남지 않을 수 있음 | dispatched effect 실패의 result를 dict로 만들고 원 오류+after+근거를 함께 보존 | [runtime의 오류/후속 capture 경로](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/runtime.py) |
| verifier의 2026.1 baseline과 실제 finite 2026.2 profile 혼재 | 명시적인 exact 설치 profile과 catalog/native qualification을 분리 | [verify-install](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/scripts/verify-install.ps1) |
| 일부 qualifier가 종료 시 native 탭을 자동 제거 | 실제 사용하는 잔여 3경로의 owned 탭/파일 보존; 원 활성 탭과 identity 확인 | [native_adapters](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/native_adapters.py), [finite qualification](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/native_interpolation_qualification.py) |
| mesh raw NPZ와 actual quality manifest 사이 근거 없음 | source/evaluation/좌표계/freshness를 연결하는 private capture와 terminal 이후 봉인 | [mesh handler](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/handlers/mesh.py), [actual_mesh_metrics](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/motion_quality.py) |
| 재계산된 derived float의 저장 왕복 차이와 원본 identity를 같은 exact 비교로 처리 | authored/미분류 exact 유지; 증거 있는 derived만 typed comparator, 원본 anchor 고정 | [checkpoint/restore](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/cascadeur_side/cascadeur_complete/native_checkpoint_restore.py) |
| unbaking action의 실제 완료 binding 없음 | prepare 이전 capability 사유 반환; 확인된 sync/terminal binding만 향후 연결 | [현재 관측 기록](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/docs/KNOWN_ISSUES_2026-11-15.md) |

호스트의 `service._supported_build_error()`와 finite operation gate는 exact `2026.2.3.0.16863` 경로를 이미 갖고 있다. 이번 verifier 변경 때문에 catalog 전체나 host 지원 버전을 추가 확대하지 않는다. 원본 `2026.1.3.0.15619` 제품 목록과 실제 native capability의 의미는 다르다. [service.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/service.py)

## 3. 구현 단위와 순서

세부 입력·출력·함수·변경 이유·확인 사례는 `implementation_tasks.json`과 각 하위 문서에 있다.

| ID | 구현 단위 | 선행 | 준비 파일 |
|---|---|---|---|
| R5-01 | 원 receipt를 참조하는 domain별 append-only journal와 진단 | 없음 | `incident/INTEGRATION.md`, `reference_incident_policy.py` |
| R5-02 | authoritative observation과 승인된 retirement prepare/commit | 01 | 같은 문서의 transition/control 계약 |
| R5-03 | signed request+sidecar, host/native/first-write/direct qualifier admission | 01, 02 | incident dispatch·persistence 계약 |
| R5-04 | private 완료 실패의 selector와 wrapper·오류 payload | 없음 | `completion/COMPLETION_IMPLEMENTATION.md`, 참조 classifier, patch 01 |
| R5-05 | insertion 실패 actual after, consumed source, 독립적인 복구 자격 | 04 | 같은 문서의 core/adapter/recovery 연결 |
| R5-06 | exact 설치 profile과 native 관측 상태 분리 | 없음 | `lifecycle/patches/01_exact_installation_profile.proposed.patch` |
| R5-07 | 잔여 qualifier 탭 보존·진단·한정된 자원 사용 | 03 | `lifecycle/patches/02_retain_qualification_fixtures.proposed.patch` |
| R5-08 | 실제 mesh capture·좌표/단위 변환·durable completion 연결 | 03, 04, 07 + 실제 calibration | `motion/MOTION_IMPLEMENTATION.md`, `geometry_policy.py`, `proposed_contracts.pyi` |
| R5-09 | typed 저장 왕복 동등성과 exact 원본 anchor | 03, 04, 07 + field-role 근거 | 같은 문서, `serialization_equivalence.py` |
| R5-10 | unbaking prepare 전 capability 판단과 실제 완료 adapter 계약 | 03 + installed binding 근거 | 같은 문서, `unbaking_requirements.py` |

### 실행 재개를 먼저 여는 묶음

01–07은 서로 맞는 host/bridge 한 묶음으로 통합한다. 열린 unknown 상태에서는 host inspection과 제한된 native diagnostic만 허용한다. setup/새 qualification은 원 완료 closure 또는 승인·증명된 retirement와 자원 분리 이후에만 허용한다. 그 이후의 최초 qualifier는 아직 일반 scene source가 없으므로 별 authenticated setup invocation과 승인된 fixture workspace로 시작한다. 진단이나 새 qualification 자체로 원 barrier를 해제하지 않는다.

설치 transaction·maintenance lease·원 state 이관·같은 process의 기존 model proof 재사용은 이미 있으므로 재구현하지 않는다. 필요한 bridge bytes를 확정한 뒤 기존 installer로 교체하고 새 epoch에서 필요한 operation만 관측하는 순서다. 디스크 fingerprint 일치는 새 process의 loaded fingerprint·native qualification과 별개다.

08–10의 실제 binding을 관측한 뒤 추가 bridge 변경이 필요하면 그 변경은 새 fingerprint를 만든다. “어떤 후속 코드 변경이 생겨도 처음 한 번의 qualification으로 모두 유효하다”는 보장은 하지 않는다. 완성되지 않은 optional unbaking을 필수 mesh/independent motion 경로의 공통 선행조건으로 만들지 않는다.

## 4. 두 기존 unknown에 적용할 흐름

대상은 기록상 다음 두 원 요청이다. 현재 Windows process나 private 파일을 이 환경에서 직접 읽은 것은 아니다.

- global `ffb7fc8e-417c-454c-a669-48625a086eda`: terminal unknown, write phase not_started.
- isolated `fcf3352a-483c-4f9c-bc18-8b61a58822eb`: terminal unknown, write phase completed.

두 기록 모두 [원격 운영 메모](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/docs/KNOWN_ISSUES_2026-11-15.md)에 있다. write phase만으로 미실행이나 완료 실패로 바꾸지 않는다.

1. 각각의 원 인증 도메인에서 원 request/terminal MAC·identity·seq·canonical digest와 raw 파일 digest를 읽는다. root 경로가 다른 두 기록을 한 인증키로 다시 서명하여 합치지 않는다.
2. 원 attempt/epoch/build의 authoritative completion이 남아 있으면 별 observation event로 연결한다. 원 terminal 자체는 바꾸지 않는다. 현재 장면·새 프로세스의 qualification은 과거 증거가 아니다.
3. 근거가 없으면 영향 producer 종료, retained 자원, 독립 baseline, 새 workspace와 겹침 여부를 포함한 구체적인 retirement plan을 만든다. 사용자는 이 자원 선택과 처분에 승인하며, 과거 성공/실패를 대신 인증하지 않는다.
4. 그 승인과 실제 종료/분리 근거가 함께 있을 때만 `retired_unresolved`를 기록하고 새 독립 작업의 admission을 검토한다. 영향 범위·파일 alias·외부 효과가 불명하면 이 경로도 보류한다.
5. 새 run/request/source/plan/grant로 시작한다. 원 unknown run은 계속 보존한다. 이전 요청을 새 ID로 같은 영향 자원에 재전송하지 않는다. 독립 baseline의 새 작업은 과거 실행의 replay로 취급하지 않도록 입력·자원·의도를 명시적으로 새로 결합한다.

이 경로는 실제 제품에 아직 없다. 준비물 안의 `incident_*` 이름은 신규 제안이다. 새 runtime root를 만드는 것만으로 과거 barrier를 없애는 명령은 제공하지 않는다.

## 5. 품질을 낮추지 않고 자동화를 이어가는 조건

### 오류 분류

`native_completion`, `postcondition`, `recovery_eligible`, `quality`를 별도로 유지한다. 완료 증거가 있고 결과만 잘못되면 failed_after_dispatch를 표현하지만, 복구 근거가 없으면 recovery=False다. 원 run의 실패는 유지하고 실패 workspace를 다음 단계나 게시의 입력으로 자동 채택하지 않는다.

오류 payload patch는 원 error code/message와 actual after·native observation을 함께 운반하는 최소 변경이다. wrapper와 삽입 adapter 연결 없이 그 작은 patch 하나만 적용하여 중단이 해결됐다고 판단하면 안 된다.

### Mesh actual capture

`calc_skinned_mesh`의 namespace/shape 수정은 이미 반영되어 있다. 새 작업은 실제 좌표계·평가 신선도·원 source를 관측하고 geometry manifest에 연결하는 것이다. 결과 candidate를 먼저 반환하고 **원 terminal이 durable해진 뒤 private 봉인 → 별 get/verify**를 수행하여 receipt hash가 자기 자신을 포함하는 순환을 피한다.

작은 known-transform fixture 계획은 조건이 맞을 때 평가 2회·계산 5회·guarded driver 변경 1회로 제한한다. 이는 실행된 시험이나 모든 rig의 인증이 아니다. 공개 mesh frame schedule은 기존 정렬 계약을 유지한다. 실제 관측이 없으면 `native_actual`을 발급하지 않는다.

### Serialization equivalence

파일 hash·원 request/source·authored key·구조·설정·미분류 값은 exact다. SDK 소유권/behaviour/property/producer 근거가 확인된 derived 값에만 사전 고정한 float32 ULP+물리 오차/rotation 조건을 적용한다. 허용 오차를 실패값에 맞춰 늘리지 않는다.

모든 reload는 **처음 확정한 P0 anchor**와 직접 비교한다. P0≈P1, P1≈P2를 연결해 P0≈P2라고 간주하지 않는다. 복원된 새 scene은 실제 raw digest를 가진 새로운 source이고, P0와의 동등성은 별 record다. checkpoint·remember_checkpoint·restore·successor와 active/idle 관측을 함께 연결해야 한다.

### Unbaking

현재 API의 action 반환만으로 완료를 만들 수 없다. 설치된 정확한 action binding과 sync leaf/원 요청에 대응하는 terminal continuation이 확인될 때만 adapter를 활성화한다. 그 전에는 prepare·예약·쓰기 전에 구체적인 미지원 사유를 반환한다. 사용자가 요구한 native unbaking stage를 자동 생략하거나 sparse fitting 성공으로 바꾸지 않는다.

## 6. 준비물의 사용 구분

| 종류 | 포함물 | 의미 |
|---|---|---|
| exact patch 초안 | runtime 오류 payload, verifier profile, qualifier retention | 고정 base에 대한 실제 unified diff. 현재 제품에는 미적용이며, 일부는 다른 신규 통합 계약을 선행조건으로 갖는다. |
| 순수 Python 참조 코드 | incident projection/admission, 완료 판정표, typed 수치 비교, geometry 계획/변환 | 상태·수학 로직을 구체화한 코드다. private native 증거·OS 격리·dispatch를 구현한 production adapter가 아니다. |
| `.pyi` 계약 | mesh·serialization·unbaking 신규 내부/외부 연결 | 새 함수의 타입·인자·반환을 고정하는 제안. 설치 SDK의 실제 symbol이라고 주장하지 않는다. |
| 함수별 통합 문서 | 네 영역 문서와 사례 명세 | 신규 함수의 검증 책임, 현행 호출부, 실패 분기, 저장/봉인 순서를 명시한다. |

`proposal_sources/`는 patch 작성 결과의 읽기용 사본이다. 원 checkout으로 복사하거나 import하지 않았다. `.py` 참조 코드의 후보 결과를 그대로 authority로 쓰면 안 된다. 새 native issuer/OS verifier에는 성공하는 대체 stub을 두지 않았다.

## 7. 적용 전에 결정할 공개 변경과 실제 환경 입력

새 dependency/버전 교체는 제안하지 않았다. 실제 적용 승인 범위는 신규 incident control API·journal/sidecar 저장 형식, geometry 봉인/조회 계약, serialization evidence 계약, verifier의 `InstallationProfile` 인수 및 qualifier 동작 변화다. 원 protocol 전체 교체나 제품 목록 전체 변경은 이 준비본의 기본안이 아니다.

실제 활성화에 필요한 환경 입력은 원 private request/receipt/evidence, process 생성 식별자와 종료 근거, 물리 파일 identity/alias, 독립 baseline 및 설치된 SDK의 좌표/derived role/unbaking binding이다. 여기에는 확인되지 않은 값을 넣지 않았다. 이 입력이 없을 때 어떤 capability와 재개 경로가 막히는지는 각 함수의 error code로 명시한다.

검증 명령·결과와 미검증 범위는 `VERIFICATION.md`가 기준이다. 설계의 준비 완료, 제품 구현 완료, native 실행 검증 완료는 각각 구분한다.

## 8. 파일 안내

- `implementation_tasks.json`: R5-01~10의 구현 순서·파일·함수·완료 조건.
- `incident/INTEGRATION.md`, `incident/CASE_SPEC.md`: 원 unknown 보존, two-domain journal, sidecar/admission, 직접 사례.
- `completion/COMPLETION_IMPLEMENTATION.md`: core→wrapper→오류 payload→post_source→recovery/terminal 연결.
- `lifecycle/README.md`: 설치와 실제 qualifier 변경 범위, patch 선행조건.
- `motion/MOTION_IMPLEMENTATION.md`, `motion/VALIDATION_PLAN.md`: actual mesh, P0 기반 typed 비교, unbaking 완료 경계.
- `patches/` 및 `lifecycle/patches/`: 미적용 unified diff.
- `VERIFICATION.md`: 이번에 실제 수행한 준비물 정적 확인과 실행하지 않은 범위.
