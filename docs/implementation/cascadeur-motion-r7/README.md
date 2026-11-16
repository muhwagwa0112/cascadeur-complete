# Cascadeur motion R7 구현 준비

기준 제품: [`99b8516`](https://github.com/muhwagwa0112/cascadeur-complete/commit/99b85163c4125a621ef7e2deeabe22270032c60b)
(`feat/cascadeur-motion-r3`). 작성일: 2026-11-17, Asia/Seoul.

R6의 실제 SDK reader, 소유 pair continuation, immutable-P0 roundtrip 이후 남은
**unbaking / 캐릭터 회전·접촉 / 최종 FBX·mesh 품질 / 실패 복구**를 구체화한 packet이다.
제품 코드에 적용하지 않은 diff이며 native 지원 등록이나 실앱 성공을 발급하지 않는다.

통합 diff의 제품 대상은 **12개 파일: 기존 9개 수정, 3개 추가**다.
신규 모듈은 unbaking 연결, FK quaternion lowering, native/consumer mesh 형상 비교다.

## 파일

| 파일 | 용도 |
|---|---|
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | 남은 전체 구현의 실제 코드 위치, 의존 관계, 현재 준비한 코드와 native 구현 경계 |
| [product-integration.patch](product-integration.patch) | 네 영역의 제품 변경을 함께 적용할 때 사용하는 통합 diff |
| [integration-source-metadata.json](integration-source-metadata.json) | 기준 source와 최종 source의 Git blob/SHA256, component 연결 |
| [unbaking/IMPLEMENTATION.md](unbaking/IMPLEMENTATION.md) | runtime adapter 연결, 실제 설치 leaf의 정확한 함수·인수·완료 계약 |
| [character/IMPLEMENTATION.md](character/IMPLEMENTATION.md) | FK 회전 lowering 코드와 native writer, root·IK/contact·회전 보간의 다음 구현 |
| [delivery/IMPLEMENTATION.md](delivery/IMPLEMENTATION.md) | 최종 native/consumer mesh 동작 비교 코드와 실제 character exporter 계약 |
| [recovery/IMPLEMENTATION.md](recovery/IMPLEMENTATION.md) | 저장된 승인 뒤 최초 dispatch 이어가기, 원 실패/복구 증거 연결 |
| [implementation_tasks.json](implementation_tasks.json) | 네 영역의 구현 상태·필요 native 입력·산출물 연결 |
| [VERIFICATION.md](VERIFICATION.md) | 이번 packet에 실제 수행한 정적 확인과 미실행 범위 |

각 영역에도 `product-integration.patch`와 `source-metadata.json`이 있다.
**통합 diff와 개별 diff 중 하나를 사용한다.** 통합 diff를 적용한 뒤 개별 diff를 중복 적용하지 않는다.

## 적용 대상과 공개 변경 제안

기준 commit에서 이미 반영된 R6 patch를 다시 적용할 필요는 없다. R7는 그 이후의 diff다.
현재 다른 commit에서 작업 중이면 관련 target source 차이를 먼저 병합해야 한다.

이번 packet의 delivery 영역에는 `TargetImportSettings`의 `native_mesh_mapping` 및
`max_mesh_distance_checks`를 제안한다. 이는 **미적용 public schema 변경안**이다. 실제 제품
적용 전에 해당 호환성 변경 범위를 검토해야 한다. 다른 영역의 이번 diff는 신규 공개 도구나
설정·의존성을 추가하지 않는다. 이후 root+rotation 결합 channel 제안도 아직 schema에 적용하지 않았다.

현재 clone에서 검토할 명령은 다음과 같다. 이 packet에서 실제 제품 적용을 실행한 명령이 아니다.

```bash
git apply --check docs/implementation/cascadeur-motion-r7/product-integration.patch
```

실제 제품 반영 시 host/native 코드를 함께 배포하고 기존 방식으로 새 runtime의 실제 지원
범위를 관측해야 한다. R7 code가 있다는 이유로 native capability를 활성화하지 않는다.

## 완료라고 표시하지 않은 부분

- 실제 설치된 unbaking 세 action의 callable·인수·완료 신호와 해당 native leaf.
- 일반 캐릭터의 실제 회전 writer, controller/constraint closure, root·회전·접촉 결합 실행.
- character/skin을 포함한 실제 native FBX exporter와 전체 소비자 왕복·최종 납품 성공.
- 실제 실패 요청부터 restore까지의 native 관찰 및 legacy producer 종료 증거.

위 항목은 단순한 테스트 숫자 부족이 아니다. 각 문서에 실제 구현 함수와 필요한 입력을 적었다.
완료 판정은 준비 코드, native 구현, 실제 최종 품질을 구분한다.
