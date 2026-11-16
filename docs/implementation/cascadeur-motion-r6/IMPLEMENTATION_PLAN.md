# Cascadeur R6 — 재개 경로와 실제 기능 연결 준비안

기준: `muhwagwa0112/cascadeur-complete`, `feat/cascadeur-motion-r3`의
`7f1565a0ffad1595b9824cba25443bc581997fb6`.

이 디렉터리는 **적용 패치·참조 구현·native 연결 작업을 준비한 자료**다. 이 자료를
commit한 것과 제품에 패치를 적용한 것, 사용자 Windows에서 실행한 것은 구분한다.
제품 코드 직접 적용, 앱 종료/설치/재시작, incident 상태 전환은 이번 배포에 포함하지 않는다.
원 두 요청의 terminal과 키를 변경하지 않는다.

## R6 후속 추가: 참조 구현에서 제품 호출부로

`integration/`에 실제 host/native 호출부의 적용 제안과 통합 patch를 추가했다.
적용 대상의 기준은 위 `7f1565a`이며, docs branch에 push된 자료를 자동으로 제품에
적용한 상태는 아니다. `integration/README.md`에서 최종 통합 소스와 적용 순서를 확인한다.

수동 재개의 metadata draft→로컬 승인→signed outbox→native admission, 소유 pair의
setup/ownership과 현재 요청 runner, mutation terminal→evaluation→geometry capture,
동일 P0 기반 serialization 호출을 연결하는 코드가 포함된다. 설치 SDK의 실제 graph/data
추출과 unbaking binding·완료 경계는 검증되지 않은 SDK 함수를 만들어 채우지 않는다.
해당 입력은 `tools/collect_native_evidence.py`의 단일 수집 명령으로 얻을 수 있도록 했다.

최초 23개 파일의 참조 상태와 후속 통합 상태를 혼동하지 않도록, 아래 원 설계와
`integration/`의 제품 대상 소스를 함께 보되 실제 적용에는 최종 통합 patch를 사용한다.

## 이번에 고치는 설계 공백

R5에서 admission·보존·비교·거절 경로가 구현됐다. 현재 중단을 해결하려면 그 경로가
요구하는 사실을 **어디서 얻고, 어느 함수가 등록하고, 다음 요청이 어떻게 사용되는지**가
이어져야 한다. 같은 빈 registry나 실패 조건을 하나 더 만드는 것으로 완료 처리하지 않는다.

1. **설치:** 이미 인증한 runtime 디렉터리를 새 폴더로 교체하면 signed physical ID와
   실제 디렉터리가 달라진다. 설치와 실패 복구 모두 runtime/persistent 디렉터리를 유지한다.
2. **과거 incident:** 없는 과거 producer/consumer 기록은 새 code로 소급 생성할 수 없다.
   원 결과는 unknown으로 남긴다. 두 건에 한정한 명시적 위험 수용과, 독립 실행 환경의
   비간섭 관측을 서로 다른 재개 경로로 설계한다. 어느 경로도 원 작업의 성공·실패·복구
   판정으로 사용하지 않는다.
3. **미래 incident:** 실행 시작 전에 관리 범위를 확보하고 기록해야 한다. 추후 장애에서
   재사용할 수 있는 원 process identity·작업 범위·완료/종료 관측을 실제 생산 경로에 연결한다.
4. **모션:** 유한한 실제 지원 범위에 대해 private contract/policy를 발급하고 소비한다.
   선언이나 cube 관측 하나를 일반 rig/완전 자동화의 근거로 확대하지 않는다.

## 적용 순서와 병렬로 가능한 작업

### 1. 설치 patch를 먼저 적용할 준비

`installer/`의 기준 source와 patch 설명을 따른다. source 설치뿐 아니라 동일 runtime의
실패 복구가 root 전체를 교체하는 경로도 함께 수정한다. 기존 유지보수 lease와 busy 검사를
유지하고, hook이 변경하는 설치 ownership/ACL만 해당 transaction의 이전 상태로 되돌린다.
incident marker·registry·키·journal을 수동 재서명하거나 삭제하지 않는다.

이 작업의 목적은 기존 state를 유지한 새 host/bridge 설치 경로를 만드는 것이다.
Windows에서 실제 설치를 수행하기 전까지 물리 ID 보존을 실행 검증했다고 표시하지 않는다.

### 2. 앱을 실행하지 않고 SDK 근거를 수집

`tools/collect_sdk_declarations.py`는 선택한 `.pyi`만 읽는다. 준비 패치와 함께 독립적으로
진행할 수 있고 legacy admission을 풀 필요가 없다. API 선언은 실제 SDK 호출 완료를
증명하지 않지만, 존재하지 않는 getter/callable를 가정하는 반복을 줄인다.

현재 확인된 경로/심볼과 미확인 후보는 `tools/README.md` 및 `motion/`을 따른다.
미확인 심볼의 결과가 비어 있으면 선택 파일을 확인한다. 전체 SDK에 없다고 결론내리지 않는다.

### 3. legacy의 원 기록과 새 대상의 재개 권한을 분리

`incident/`에서 원 outcome을 바꾸지 않는 두 진행 경로를 제안한다.

**운영 경로 — 두 legacy 건의 명시적 수용:** 기존 환경을 사용할 때, 로컬 operator가 원래
두 사건의 정확한 original digest와 새 run/workspace/baseline/loaded epoch, 남은 불확실성을
검토해 한정된 시작을 승인할 수 있도록 한다. `manual_legacy_disposition_v1`는 과거 완료나
OS 비간섭의 증거가 아니다. 원 terminal/open 기록, 원 run 자동 resume 금지, 신규 unknown에
대한 차단은 유지한다. 실제 발급·정책 적용은 이번에 하지 않으며 자동 fallback으로 두지 않는다.
원 결과 확인 또는 확인된 격리가 필수인 운영에서는 이 경로를 선택할 수 없다.

**격리 근거가 필요한 경로 — 독립 target coverage:** 원 실행 권한과 독립된 환경이 실제로
있는 경우에만 현재의 비간섭 관측을 사용한다. 새 root·current PID·앱 재시작·사용자 제공
`closed=true`는 그 근거로 쓰지 않는다.

새 환경의 OS 경계, 독립된 baseline, 입력 반입 경로, 출력/IPC/네트워크/공유 디렉터리 범위를
구체적으로 관측할 수 있어야 한다. 원 환경과 같은 권한이 새 VM 설정·디스크를 바꿀 수 있다면
그 신뢰 경계를 숨기지 않는다. GPU/라이선스 때문에 해당 환경에서 Cascadeur가 실행되지
않는다면 그 backend를 운영 가능한 해법으로 판정하지 않는다.

현재 canonical registry는 원 stores를 직접 여는 구조다. 원 키/registry를 단순 복사하거나
등록 목록에서 원 사건을 빼서 새 환경을 통과시키지 않는다. 필요한 연결은 독립 supervisor가
확인한 원 head/terminal digest와 새 target domain을 묶는 제한된 증거 반입 및 그 소비 경로다.
이 변경은 새 정책/자료 형식을 포함하므로 실제 적용 시 구체적 설계 승인이 필요하다.

두 경로의 결과는 각각 **위험 수용**과 **대상별 격리 관측**으로 구분해 기록한다. 수용 서명만
있는데 격리가 확인됐다고 표시하지 않는다. 단순 `ignore_unknown` 옵션은 추가하지 않는다.

최초 legacy 이전은 경로와 baseline 선택이 필요한 운영 작업이다. 이후 관리되는 새
실행의 정상 작업·관측·재시도는 해당 승인 범위 안에서 자동화하는 것이 목표다. 예전 run을
자동으로 이어 실행하거나 그 산출물을 새 baseline으로 승인하지 않는다.

### 4. native positive path를 각각 연결

`motion/`은 geometry, serialization, unbaking을 분리한다.

- Geometry는 code가 소유하고 검증한 유한 profile에서 contract 생성→등록→상태 조회→실제
  capture 소비까지 연결한다. 원 mutation successor와 현재 evaluation/capture의 관계를
  인증하며 원 request ID를 evaluation ID로 바꿔 관계를 생략하지 않는다.
- Serialization은 Update callback에서 실제 역할/graph를 관측할 경로를 사용한다.
  graph revision이 없다면 매 사용 시 확인해야 하며 과거 snapshot만으로 현재성을 주장하지
  않는다. authored/unclassified 값은 exact로 유지하고, derived 허용은 확인한 field에만 적용한다.
  저장의 각 단계는 동일한 원 P0와 비교한다.
- Unbaking은 세 action의 실제 callable·인자 lowering·완료 관측을 확보한 뒤 연결한다.
  현재 `call_action()` 반환이나 getter 존재만으로 완료를 표시하지 않는다. 정확한 leaf가
  확인되지 않은 부분은 필요한 설치 자료와 구현 위치를 지정한 native work item으로 남긴다.
  sparse 처리로 원래 기능을 대체했다는 판정을 하지 않는다.

## 상태 표현

| 상태 | 의미 |
|---|---|
| 적용 준비 patch | 고정된 기준 source에 대한 diff. 제품 적용/Windows 실행과 구분한다. |
| 참조 코드 | 순수 로직과 연결 형태를 구현한 파일. production package에 import되지 않는다. |
| SDK/OS 연결 대기 | 필요한 실제 경계와 입력이 문서화됐지만 이 환경에서 실동작 확인하지 못했다. |
| native 실행 확인 | 사용자 환경에서 해당 유한 경로를 실제 실행하고 근거를 확보한 경우에만 사용한다. |

이 패킷만으로 일반 rig, 최종 모션 품질, 완전 자동화 또는 legacy incident 해결을 완료로
표시하지 않는다. 한 기능의 자격으로 다른 기능의 검증을 대신하지 않는다.

## 검증 범위

이번 작성 시에는 변경 준비 파일의 Python 구문과 기준 source에 대한 patch 적용 가능성만
확인한다. 실제 명령·결과는 `VERIFICATION.md`에 기록한다. PowerShell/Windows/SDK 실행,
전체 테스트·빌드·E2E·coverage·CI는 수행하지 않는다.

제품 적용 시에는 해당 수정의 직접 위험을 겨냥한 L2 케이스만 먼저 확인한다. installer의
물리 ID 및 rollback, incident의 원 terminal 보존 및 새 대상 한정, motion의 해당 profile과
source 연결을 확인하면 된다. 전체 suite나 반복 감사 절차를 이 계획에 추가하지 않는다.

## 기준 코드

- [현재 설치 교체](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/scripts/install.ps1)
- [store 물리 ID](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_store.py)
- [현재 retirement prepare](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_control.py)
- [현재 admission 정책](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_policy.py)
- [최신 구현/실행 범위 기록](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/docs/KNOWN_ISSUES_2026-11-15.md)
