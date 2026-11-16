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

## 후속 제품 호출부 통합 확인 — 2026-11-16

앞 절은 최초 23개 준비물의 확인 기록이다. 이번 후속 확인은 추가·변경 파일과 새 통합
patch만 대상으로 했다. 최초 설치 patch나 이미 통과한 변경 없는 Python 파일은 다시 검사하지 않았다.

| 확인 | 명령·방법 | 결과 |
|---|---|---|
| 추가·변경 Python | `ast.parse(..., feature_version=(3, 11))` 후 `compile(tree, path, "exec", dont_inherit=True)` | **39개 파일 통과**. 동일 bytes는 한 번만 컴파일하여 실제 서로 다른 내용은 **28개**. 코드를 실행하거나 제품 모듈을 import하지 않음. |
| 추가·변경 JSON | `json.loads(...)` | **5개 통과**. task 7개의 ID·의존 관계·추가 artifact 경로도 일치. |
| 통합 patch 문맥 | `git apply --check /workspace/scratch/fc42dd265c37/cascadeur-r6-code-ready/integration/product-integration.patch` | pinned source 임시 사본에서 **exit 0**, 출력 없음. 실제 제품 적용은 하지 않음. |
| 기준 source | 원 Git tree blob과 통합 대상 원본 bytes 비교 | 기존 제품 source **20개 일치**. 추가 제품 target 9개는 기준 tree에 없음. |
| 최종 proposed source | `integration/source-metadata.json`의 SHA256/Git blob과 최종 bytes 비교 | **29개 target 일치**. recovery/motion 중복 4개는 3-way 병합. |
| host/native mirror | 최종 target bytes 비교 | admission, effects, manual_setup, pair_continuation, policy, setup **6종 일치**. |

위 Python 환경은 **3.12.14**, 구문 대상은 **3.11**이다. 통합 patch의 SHA256은 다음과 같다.

```text
3fcb36db838969fec171b69cc84a54c7a026b0064e58e4663a034584c8a25453
```

두 코드 영역의 연결 검토는 새 manual setup의 승인/잠금/원 요청 재사용과 새 finite
continuation의 실제 선행 receipt·source·confirmation 전달, native activation과 mutation
terminal 연결에 한정했다. 새 SDK leaf가 없을 때 setup dispatcher가 먼저 디렉터리를
만들고 unknown을 남길 수 있는 호출 순서를 확인해, 인증된 setup의 정적 dependency
거절을 claim/dispatch 이전으로 옮겼다. 이 검토는 실행 테스트 결과가 아니다.

**미실행:** 제품 patch 적용, 제품 import, pytest, 전체 테스트·빌드·E2E·CI(**L4 미실행**),
수집기의 실제 설치 SDK 실행, 로컬 승인 발급, Windows 설치/복구, native pair setup과
10/12단계 continuation, serialization save/load, unbaking, 일반 rig 품질·consumer 납품.
필수 `native_installed_update_facts.py`의 실제 구현은 이번 packet에 포함되지 않으며,
구문/patch 통과가 그 native 동작을 대신하지 않는다.
