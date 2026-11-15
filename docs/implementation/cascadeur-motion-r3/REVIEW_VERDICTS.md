# 최종 검수 판정 — r3

기준일: 2026-11-15

## 판정 대상

대상은 **구현 전 설계 r3**다. 제품 코드 수정 완료, 실제 Cascadeur/Blender 실행 통과, 임의 모션의 완벽한 품질을 판정한 기록이 아니다.

세 검수역은 `REVIEW_SCOPE.json`에 기록된 동일한 다섯 파일을 검수했다. 각 검수역이 manifest와 파일 SHA-256의 일치를 확인했다.

검수 범위 manifest SHA-256:

`edf27fc9c8ba510191349a11ce01bad34620f16d9aa459c0d2af94bf97f7d668`

| 검수역 | 담당 agent | 최종 판정 | 미해결 차단 지적 |
|---|---|---|---:|
| 모션 품질 | `/root/quality_design_review` | PASS — 구현 설계 범위 | 0 |
| 자동화 | `/root/automation_design_review` | PASS — 구현 설계 범위 | 0 |
| 안정성 | `/root/stability_design_review` | PASS — 구현 설계 범위 | 0 |

## 기존 차단 지적의 해결

### 모션 품질

- 회전·손·보행 보존 작업이 완료 의존 경로에서 빠지는 문제를 수정했다. T32의 prerequisite closure는 32/32이며 누락 참조·순환이 없다. host retarget의 quaternion/IK/key fitting 의존성도 연결했다.
- IK 도달 불가능 시 기본 실패와 명시적 목표 투영을 구분했다. 긴 clip은 전역 key 변수·D1/D2·접촉 anchor를 유지하는 문제 하나로 고정했다. percentile ground는 진단에만 사용한다.
- `RecipeSpec.intent`와 support/contact/prop/geometry 참조를 연결했다. 의미 제약·품질 문턱·후보 variant·실행 예산은 각각 한 계약이 소유한다.
- 실제 target capture를 `validate_export_roundtrip`으로 연결했다. 접촉·root·keypose·prop·timing과 mesh 포함 시 실제 skinned collision이 최종 평가에 남는다.
- native/host retarget route와 새 host 구현 파일·함수를 확정했다. 승인 범위 밖 route fallback은 없다. full weights만으로 실제 skinning이 정확하다고 주장하지 않는다.

### 자동화

- 공개 API는 `recipe_*`, 모델은 `WorkflowPlan`, 실행기는 `RecipeRunner`로 통일했다. 저장형 RunState/StepState와 공개 요약 상태의 mapping을 고정했다.
- 기존 ErrorCode를 유지하며 세부 이유는 `result.error_details.code`로 전달한다. migration alias는 prepare/snapshot/selection도 호출하지 않는다.
- 최초 승인한 scope 안의 단계는 자동 진행하며 exact prepare token·단일 사용 commit은 유지한다. 제한된 contact detection·key insertion·candidate variant는 초기 grant에 포함할 수 있다.
- argument-aware effect classification을 execute/batch/job/runner가 공유한다. 평가 갱신은 순수 read나 unknown 중 reconciliation으로 우회하지 않는다.
- 입력부터 native/host motion 작업, 실제 품질 확인, checkpoint, export/target 검증, publish까지 단계가 연결된다. 취소·재시작·late response에서 완료 mutation을 재실행하지 않는다.
- sealed artifact와 public file을 분리하고 기본 no-clobber를 적용한다. 임의의 overwrite bool을 무조건 교체권으로 확대하지 않는다.

### 안정성

- SceneBinding과 SourceBinding을 유지하고 scope descriptor/authored content/evaluated sample의 hash projection을 구분한다. complete는 runtime/adapter가 required dependency와 coverage를 검증한 뒤 발급한다.
- scene identity를 path/name과 분리하고 runtime epoch·실제 instance·snapshot lineage로 관리한다.
- durable request ID/nonce/receipt, 최대 한 번 dispatch, outcome_unknown, stale claim 재queue 금지, 관측 기반 reconciliation을 확정했다.
- dispatch 뒤 첫 write 전 guard 거절과 실제 write 실패를 구분한다. write_phase/failure_kind/recovery_eligible 및 callback permit을 추가하고 write0 guard 거절에는 rollback을 금지한다.
- rollback은 종료·정확한 target·현재 guard·snapshot integrity·lineage를 확인한 별 recovery 요청으로 제한한다. 원 failure와 recovery failure를 합치지 않는다.
- runtime `_error`와 host wrapping에서 실제 before/after와 request identity를 보존한다. 관측 불가를 성공이나 no-effect로 바꾸지 않는다.
- protocol/token/evidence의 위험한 자동 승격을 막고 실제 관련 코드·fixture·profile bytes와 loaded runtime fingerprint에 증거를 결합한다.

## 수행한 확인과 미실행 항목

수행: 관련 main/PR8 함수의 정적 대조, 세부 명세 간 계약과 기존 지적의 교차 확인, 고정 문서 hash 확인, 작업 JSON 파싱과 32개 작업의 의존 경로 확인.

미실행: 제품 코드 수정, dependency 설치·버전 변경, 컴파일·lint·저장소 테스트(L1~L4), CI, Cascadeur/Blender 실행, 실제 모션 변경·export, commit/PR 변경/push.

실기기에서 확인하지 않은 조건은 명세의 활성화 조건으로 남았다. csc scene wrapper identity, native callback/yield/후속 write, 필요한 dependency reader, AutoPosing/BEZIER/mesh 평가, native generation/retarget/physics 설정·완료 관측, exporter/importer 동작, Windows 파일 공개·잠금의 실제 동작이 여기에 해당한다. 확인되지 않은 adapter는 `unsupported`, `blocked`, `unverified`로 처리하며 이를 runtime PASS로 표시하지 않는다.

검수 완료 후 새 기준·전수검사·전체 테스트를 추가하지 않았다. 이번 PASS는 지정한 구현 설계 범위의 기존 차단 지적이 모두 해소되었다는 뜻이다.
