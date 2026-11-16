# R6 후속 제품 호출부 통합

기준 제품 commit은 `7f1565a0ffad1595b9824cba25443bc581997fb6`이다. 이 디렉터리에는
R6 참조 코드의 host/native 호출부를 연결하는 **미적용 제품 패치**와 제안 소스가 있다.
이 자료의 push와 제품 적용·Windows 실행·실제 모션 납품은 서로 다른 상태다.

## 통합 파일 선택

동시에 적용할 때의 기준 파일은 `product-integration.patch`다. recovery와 motion이
함께 수정하는 host/native admission·setup 파일을 같은 고정 원본에서 병합했다.
그 최종 소스는 `merged_sources/`에 있고, 나머지 대상의 최종 소스 위치와 원본/제안
SHA256·Git blob SHA는 `source-metadata.json`에 있다.

통합 patch의 제품 대상은 **29개 파일(기존 20개 변경, 신규 9개)**이다. 중복 수정한
host/native admission·setup 4개 파일은 같은 기준에서 병합했으며, host/native mirror
6종은 최종 bytes가 일치한다.

`recovery/`와 `motion/`의 개별 patch는 각 변경을 읽기 위한 독립 제안이다. 통합 patch를
적용한 뒤 같은 개별 patch를 중복 적용하지 않는다. 설치 보존 수정은 별도
`../installer/installer-runtime-identity.patch`를 사용한다. 그 patch는 이번 통합 diff에
중복 포함하지 않았으며 제품 코드 경로가 겹치지 않는다.

## 연결한 범위

- **수동 재개:** 실행 판단을 요구하지 않는 metadata draft, 실제 로컬 검토·승인,
  signed outbox, host/native admission 소비, exact setup 요청 제출까지 연결한다.
  원 unknown을 닫거나 삭제하지 않고 새 대상의 명시적 운영 판단을 기록한다.
- **미구현 입력의 처리:** pair setup의 필수 설치 leaf가 없으면 인증된 계획을 대상으로
  비실행 정적 선언 확인에서 거절한다. 위치는 native claim·실행 시작 기록·workspace
  생성 전이다. 따라서 이 누락을 새 dispatched unknown으로 만들지 않는다. 이미 시작한
  native 작업의 오류 분류는 바꾸지 않는다.
- **후속 동작:** setup 성공 결과와 실제 retained fixture identity를 사용하는 유한한
  후속 경로의 범위·호출부는 `recovery/README.md`와 `motion/INTEGRATION.md`를 따른다.
  일반 recipe나 원 프로젝트 재개를 이 fixture 경로로 확대하지 않는다.
- **모션:** 소유 pair의 setup/registry/ownership, 현재 요청의 Update runner,
  실제 mutation successor·terminal·evaluation·capture 관계를 제품 호출부에 연결한다.
- **직렬화:** checkpoint/save/load가 같은 P0를 사용하고, 각 사용 시 현재 요청의 guard와
  새 graph 관측을 받도록 연결한다. 미확인 field에 허용 오차를 주지 않는다.
- **unbaking 입력:** 명시한 source에서 action literal·정의·호출 후보를 모으는 도구와
  각 step의 제품 연결 위치를 제공한다. 실제 binding·완료 신호는 source 후보 수집만으로
  확인된 것으로 표시하지 않는다.

각 proposed module은 해당 `proposed_sources/`의 product 경로로 들어가는 파일이다.
문서 디렉터리의 Python 파일을 현재 설치에 import해서 capability를 활성화하지 않는다.
기존 R6의 `reference_*.py`는 당시 참조 구현으로 남으며 통합 patch가 지정한 제품 모듈을
대체하지 않는다.

## 설치 SDK 입력을 받는 한 명령

`../tools/collect_native_evidence.py`가 현재 설치의 선언과 명시한 action source를 JSON
하나로 수집한다. 정확한 예시는 `../tools/README.md`에 있다. 파일 열기·AST 해석만 하며
Cascadeur SDK와 설치 Python source를 import하지 않는다. 대상 파일과 실행 결과를
지정하지 않은 일반적인 "SDK 확인" 작업으로 남기지 않고, 필요한 class·action·제품
함수와 입력 형식을 고정했다.

공개 문서와 설치 조사 기록에 Update 진입 함수 이름 차이가 있어 `Update` class 전체를
수집한다. 빠진 파일·심볼과 미해결 native/external call은 결과에 남긴다. 이 수집 결과는
source 근거이며 native 완료 영수증·approval·registry 등록 값이 아니다.

## 실제 완료에 필요한 환경 의존 부분

제품 통합 diff를 적용하더라도 다음 근거는 사용자 환경에서 확보해야 한다.

1. 기존 runtime 디렉터리/원 기록을 보존한 Windows 설치와 새 loaded package.
2. 현재 설치에 맞는 실제 Update graph/data extractor. 새 파일 이름만 만들거나
   caller dict를 받아 qualifier로 등록하지 않는다. derived storage 의미를 모르면
   수치 tolerance는 활성화하지 않는다.
3. 해당 유한 helper와 후속 요청의 실제 native 실행 결과. 일반 rig의 품질이나 긴 클립의
   정확성을 두 mesh·세 frame 결과로 판정하지 않는다.
4. unbaking 세 step의 정확한 action binding·argument lowering·동기 또는 상관된 완료
   경계. `call_action()` 반환이나 sparse fitting으로 기능을 대체하지 않는다.

일반 controller/rotation/retarget/AutoPhysics, 원 프로젝트 복구, 최종 consumer 왕복과
납품의 미확인 사항은 그대로 남는다. 이번 코드 연결은 그 목표를 삭제하거나 통과 기준을
낮추지 않는다. 실제 사용자 장비에서 실행하지 못한 부분을 성공으로 표시하지 않는다.

## 확인 기록

이번 추가 파일의 정적 확인과 통합 patch 문맥 확인은 `../VERIFICATION.md`의 후속 절에
기록한다. 전체 테스트·E2E·CI·새 반복 감사 절차는 추가하지 않는다.
