# Cascadeur motion r3 구현 상태와 남은 문제

작성일: 2026-11-15  
대상 브랜치: `feat/cascadeur-motion-r3`  
개선 명세: `docs/cascadeur-motion-plan-r3`의 `fb6310499d37c21c08fb38040be4fe496be1c3a2`  
구현 기반: PR #8 브랜치의 `1bb447898e8ced16b6931b72cfeb0f563127f746` 변경을 로컬에 squash 적용한 뒤 r3 개선 반영

## 현재 상태

프로토콜 3, 원본 바인딩, durable receipt, 결과 불명 시 재실행 금지, 조건부 복구, SI 기반 모션 계산, finite recipe runner, FBX 검증·게시 코드를 연결했다. r3의 32개 작업 전체가 실앱에서 검증되었다는 의미는 아니다. 특히 이 체크아웃은 검증된 Cascadeur native 어댑터를 설치하거나 등록하지 않는다. 따라서 실제 장면 변경과 전체 제작 파이프라인은 아직 사용할 수 없다.

계획 문서의 `implementation_spec_r3_not_executed` 및 설계 리뷰 통과 기록은 당시 설계 산출물의 상태다. 현재 구현·실행 검증 결과로 읽으면 안 된다. 이 메모는 남은 문제를 기록하며, 최신 지원 판단은 실제 capability와 해당 실행의 receipt·측정 결과를 따른다.

## P0: 실앱 사용을 막는 문제

### 1. 검증된 native guard와 source/identity 어댑터 부재

- 위치: `cascadeur_side/cascadeur_complete/guarded_runtime.py`, `runtime.py`, host의 `bridge_client.py`, `change_flow.py`.
- `_ADAPTERS`는 비어 있으며 production 등록 구현이 없다. 실제 scene instance와 lineage, authored dependency closure, 읽은 원본과 쓰기 직전 원본의 일치, UI callback의 동기 완료를 해당 SDK에서 검증하지 않았다.
- 영향: 정상적인 완전한 SourceBinding을 발급할 수 없고 guarded mutation은 사전 차단된다. 호출자가 `complete=true`나 capability를 넣어 이 제한을 해제할 수 없다.
- 다음 작업: 고정 대상 build `2026.1.3.0.15619`에서 실제 SDK reader와 operation별 어댑터를 구현하고, 동일한 loaded fingerprint·관찰된 build·scene 식별·no-yield 완료 근거를 확보해야 한다. 체크를 우회하거나 임의 증거 해시를 넣는 방식으로 활성화하면 안 된다.

### 2. 실제 checkpoint와 recipe 단계 어댑터 부재

- 위치: `src/cascadeur_complete/recipe_runner.py`, `recipe_planning.py`, `service.py`, `recovery.py`.
- 실제 `recipe_checkpoint` 훅이 없으므로 현재 live recipe는 preflight에서 막힌다. 파일 입력, rig 생성, retarget/generation/unbaking, export 등 추가 단계에도 해당 native 훅이 필요하다.
- 영향: plan과 blocker 조회는 가능하지만 차단된 plan은 승인·실행할 수 없다. 실패 후 복구 역시 검증된 runtime rollback 어댑터가 없어 지원되지 않는다.
- 다음 작업: 원본 backup과 별도 working scene, 실제 파일 hash·lineage·현재 scene 식별, 저장 완료 및 successor checkpoint를 관찰하는 어댑터를 연결한다. 복구는 원 요청의 인증된 terminal failure와 별도 permit으로 한 번만 수행하며 unknown 요청은 재실행하지 않는다.

### 3. Cascadeur native export와 소비자 왕복 검증 미완료

- 위치: `src/cascadeur_complete/export_workflow.py`, `fbx_validation.py`, `external.py`, `blender_export_adapter.py`, `export_publisher.py`.
- Cascadeur에서 export 설정 적용과 실제 완료를 관찰하는 어댑터가 없다. 파일 존재나 dispatch 성공만으로 native export 완료를 판정하지 않는다.
- FBX parser, 별도 sealed artifact, 구조 검증, Blender importer 실행 경로, 검증 후 원자 게시 코드는 구현되어 있다. 실제 Cascadeur export 또는 Blender import 실행은 하지 않았다. 설치된 Blender 4.5 importer 소스 확인은 실제 import 성공의 증거가 아니다.
- 영향: 실제 최종 FBX 납품은 검증되지 않았다. 대상 실행 파일·importer·설정의 정확한 지문과 원본 의도에 대한 실제 target capture 없이는 export 품질 pass를 만들 수 없다.
- 다음 작업: native 설정/완료 어댑터를 연결하고 명시적 ExportProfile로 별도 작업 경로에 export한 다음, 실제 소비자의 측정 결과와 원본 의도를 비교한 후 게시한다.

## P1: 모션 품질과 호환성 제한

### 4. Host 예측과 실제 변형 결과의 차이

- quaternion, two-bone IK, contact QP, 보간 기반 key fitting, triangle/capsule 충돌, 양팔 결합 solver 및 retarget 계산은 host 구현이다.
- 실제 rig controller의 반응, native Euler↔quaternion 변환, reskin 후 mesh와 연속 시간 충돌 자유는 검증하지 않았다. 양팔 solver 결과도 실제 skin 변형 검증 결과가 아니다.
- 필요한 측정값이 없으면 `unverified`를 유지한다. 사용자 policy에서 쉬운 지표만 선택해 root·lock·접촉·충돌·원본 보정 한도를 생략할 수 없다. 원본 역할별 envelope 위반도 품질 지표에 포함한다.
- 다음 작업: 실제 읽기/쓰기 및 reskin adapter로 solver 예측과 readback을 비교하고, 필요한 경우 연속 시간 평가기를 추가한다. sampled frame 통과를 연속 구간 전체 통과로 확대하지 않는다.

### 5. 기존 키와 보간 접근이 부족한 클립

- sparse rotation styling에 필요한 기존 키가 없으면 `KEY_LAYOUT_INSUFFICIENT`로 차단한다. key insertion adapter는 없다.
- contact key fitting은 실제 driver별 보간 모델을 확인해야 한다. repair는 새로운 걸음이나 접촉 스케줄을 추정·생성하지 않는다.
- recipe에서 검증된 controller 경로가 없는 styling/arm 단계는 차단된다. 단건 canonical prepare 경로와 recipe에서 승인 가능한 단계의 범위는 동일하지 않다.
- 다음 작업: 실제 layer/key ownership과 보간 접근을 검증하고, 키 추가가 필요하면 원본 의도와 승인 범위에 포함된 별도 adapter를 구현한다.

### 6. Protocol 3 전환과 설치 상태

- 변경 준비에는 명시적인 rig profile, FPS·단위·좌표계, 원본 intent와 runtime 발급 SourceBinding이 필요하다. 종전 직접 mutation 도구 이름은 부작용 없는 prepare 이행 안내를 반환한다.
- protocol 2는 읽기 전용 호환 경로다. 변경 요청은 downgrade하지 않는다. host와 loaded bridge의 지문이 다르면 새 변경을 거부한다. 이미 제출한 요청의 원 receipt 조회는 계속 가능하다.
- 이 작업에서는 로컬 `.venv` 의존성을 구성했으며, 설치 스크립트·frozen bundle·installer를 실행하거나 전역 MCP 등록을 변경하지 않았다. 실제 설치 시 host와 bridge를 함께 갱신하고 Cascadeur를 재시작해야 한다.

## 수행한 확인과 확인하지 않은 범위

아래는 구현 중 해당 변경 시점에 수행한 대상 확인이다. 한 번의 최종 전체 suite 실행 결과가 아니며, 실앱 지원을 인증하지 않는다.

| 대상 | 관찰된 결과 |
|---|---|
| Protocol/queue/receipt 경계 | 기존·추가 case 통과. legacy 읽기 fallback과 패키지 변경 후 원 receipt 관찰 case는 개별 확인 |
| 실제 in-process MCP 계약 | `tests/test_guarded_surface.py`: 2 passed |
| Service 변경 거부·원 native 결과 보존 | `tests/test_guarded_service.py`: 2 passed |
| 모션 수학·기하·solver·chunk | `tests/test_motion_contracts.py`: 8 passed |
| Recipe 실행·job claim | 해당 시점의 두 대상 파일에서 12 passed |
| 추가 필수 품질 지표 경계 | `-k mandatory_quality`: 2 passed, 10 deselected |
| 실제 bridge/executable bytes 변경 시 plan 지문 변경 | `-k implementation_digest_tracks`: 1 passed, 12 deselected |
| 조건부 복구·stale/unknown/중복 방지 | `tests/test_recovery_boundary.py`: 5 passed |
| Export 파일 무결성 | `tests/test_export_integrity.py`: 10 passed |
| Evidence binding | `tests/test_verification.py`: 6 passed |
| Legacy FBX CLI fixture | 대상 case 1 passed |
| Canonical 품질 helper 직접 확인 | duration-only policy 거부, 실제 target provenance 없는 equal-pose export는 unverified |
| Host 진입점 import | server/service/recipe/recovery/export import 성공 |

이후 raw quaternion 원본 hash 보존과 write 정렬은 코드 검토로 수정했으며 모션 검사를 반복하지 않았다. 공개 MCP golden snapshot은 실제 도구 스키마로 갱신한 산출물이며 그 갱신 자체는 독립 검증이 아니다. 마지막 의존 파일 목록·문서 갱신을 포함한 최종 전체 tree에 대해 모든 검사를 재실행하지 않았다.

실행하지 않은 범위: 전체 pytest, broad lint/format, CI, installer/release build, 실제 Cascadeur 장면 변경·복구, 실제 Blender import, 최종 FBX 납품, 장시간·대규모 실제 클립 실행. 이 범위에는 미발견 결함이나 기존 fixture/mock의 protocol 3 전환 누락이 있을 수 있으며 현재 실패로 확정한 것은 아니다.

## 다음 작업 순서

1. 실제 고정 SDK의 source/identity/no-yield guard를 최소 한 operation에 연결한다.
2. 별도 working scene과 checkpoint·rollback 완료 관찰을 구현한다.
3. 작은 명시적 rig/clip에서 capture → prepare → commit → actual readback과 원본 intent를 확인한다.
4. actual reskin·접촉·key interpolation 평가를 연결한다.
5. native FBX export → 고정 소비자 import → 원본 기준 품질 평가 → 게시 경로를 확인한다.
6. 필요한 범위의 기존 계약·설치·CI 호환성을 확인한 뒤 지원 상태를 갱신한다.

관련 문서: [README](../README.md), [현재 workflow와 과거 예시의 구분](MOCAP_CLEANUP_WORKFLOW.md), [r3 구현 명세](implementation/cascadeur-motion-r3/IMPLEMENTATION_PLAN.md).
