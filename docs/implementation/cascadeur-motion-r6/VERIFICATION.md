# R6 준비물 확인 결과

기준 commit: `7f1565a0ffad1595b9824cba25443bc581997fb6`  
작성·확인일: 2026-11-16  
환경: Linux, Python **3.12.14**, Git **2.52.0**. Python 구문 대상은 **3.11**이다.

## 수행한 확인

| 확인 | 명령·방법 | 결과 |
|---|---|---|
| Python 준비 코드 6개 | `ast.parse(source, filename=path, feature_version=(3, 11))` | 모두 통과. 모듈 import 또는 함수 실행은 하지 않음. |
| JSON 3개 | `json.loads(...)` | BASELINE, implementation_tasks, installer/source-metadata 통과. |
| 작업 목록 | task ID 중복·의존 ID·산출물 디렉터리 확인 | 7개 항목의 참조 일치. |
| Installer patch | 고정 기준 파일의 임시 사본에서 `git apply --check installer/installer-runtime-identity.patch` | exit **0**, 오류·경고 출력 없음. 대상 5개 파일. 실제 제품에는 적용하지 않음. |
| Installer 원문·제안 identity | metadata의 SHA256 및 Git blob SHA1을 실제 bytes와 비교 | 기준 source 10개, 변경 제안 5개 및 patch digest 일치. |
| 기존 comparator 사본 | 원 Git blob SHA1과 실제 사본 bytes 비교 | `3a5df24f542fc894737845fb0db39e941b7b2495` 일치. |

Python 6개는 `tools/collect_sdk_declarations.py`, motion의 참조 코드 2개와 comparator,
incident의 참조 코드 2개다. 처음 comparator 사본 비교에서 말미 newline 1바이트가 추가된
차이를 발견했고 그 1바이트만 제거했다. 변경된 사본만 다시 구문 확인했으며, 이미 통과한
나머지 파일은 구문 검사를 반복하지 않았다. comparator 로직·주석 변경은 없다.

설치 patch의 SHA256:

```text
384cce183e48840ba2a885212a92f34a8b5f87cb4df33e32fed973786b48248d
```

## 미실행·미검증

- 제품 Python import, pytest, 전체 테스트·빌드·E2E·benchmark·coverage·CI: **미실행(L4 미실행)**.
- PowerShell parser/실행, Windows file ID·DACL 보존, source/frozen installer 및 Inno rollback: 미검증.
- 독립 Hyper-V host·VM·인증서·PowerShell Direct·OS 종료/격리: 미실행. 사용자 환경의 가용성도 미확인.
- Manual legacy disposition의 발급·소비 및 실제 정책 전환: 미실행. 제안 코드를 승인 토큰으로 사용하지 않음.
- Cascadeur 설치 SDK 수집기 실행, 신규 pair helper, dtype/graph extractor, 실제 geometry/serialization/unbaking: 미실행.
- 일반 rig의 최종 모션 품질, 기존 프로젝트의 복구, 실제 consumer 납품, 완전 자동화: 완료 판정 없음.

`git apply --check`는 patch 문맥을 확인한다. AST는 Python 구문을 확인한다. 어느 결과도
PowerShell·Windows·SDK의 실동작이나 native completion을 대신하지 않는다.

각 하위 문서에는 제품 적용 뒤 필요한 직접 사례만 기재했다. 새 테스트 프레임워크나 전체
회귀·반복 감사·CI 실행 절차를 추가하지 않았다.

## 공개 범위

이번 commit의 산출물은 `docs/implementation/cascadeur-motion-r6/` 아래의 준비 파일이다.
제품 경로에 patch를 적용하거나 기존 원 request/receipt/key/incident를 변경한 commit이 아니다.
실제 원격 commit·branch 및 파일 일치 확인은 푸시 완료 응답에 기록한다. 이 문서 작성 시점에
아직 없는 commit SHA나 실앱 실행 결과를 미리 기입하지 않는다.
