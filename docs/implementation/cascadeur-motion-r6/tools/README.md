# 설치 SDK 선언 수집

`collect_sdk_declarations.py`는 지정한 설치 `.pyi` 파일만 읽는 standalone 도구다. `csc`를 import하지 않고 앱·scene·queue·incident·키에 접근하지 않는다. 출력은 **읽은 파일의 SHA256, 선언 원문, 행 번호**이며 native 완료·지원 자격을 발급하지 않는다.

Python 3.11 이상과 표준 라이브러리만 사용한다. 새 의존성·설정 변경은 없다. 이번 패킷 작성 환경에서는 사용자의 설치 SDK에 실행하지 않았다.

## 확인된 경로의 예

최신 저장소 메모가 설치 조사에서 인용한 경로는 `resources/scripts/stubs/csc/domain/__init__.pyi`다. 실제 설치 경로를 확인한 후 실행한다. 이 예는 파일이 존재한다는 실시간 확인을 대신하지 않는다.

```powershell
python .\collect_sdk_declarations.py `
  --stub 'C:\Program Files\Cascadeur\resources\scripts\stubs\csc\domain\__init__.pyi' `
  --symbol calc_skinned_mesh `
  --symbol SkinnedMeshCalcResult `
  --output .\sdk-domain-declarations.json
```

같은 설치 조사에서 기록된 `csc/tools/__init__.pyi`에는 `AnimationUnbakingTool`,
`AutoPosingTool` 선언이 있다. 해당 파일이 현재 설치에도 있는지 확인한 후 두 class를
`--symbol`로 선택한다. action ID의 Python binding source는 별도 자료이며 이 수집기의
`.pyi` 출력으로 대체하지 않는다.

추가로 필요한 선언은 실제 `Scene.modify_update`, `SceneUpdater.get_interpolator`,
`Update` 전체와 그 반환 class의 graph/data 접근 부분이다. 공개 API 문서는
[`Update.root()`](https://cascadeur.com/python-api/_generate/csc.update.Update.html)를
선언하지만 저장소의 과거 설치 조사 메모에는 `Update.root_group()`이라는 이름이 있다.
두 이름을 자동 fallback으로 호출하지 않고, 현재 설치 `.pyi`를 받아 정확한 이름·반환형을
결정한다. 선언 수집은 class 단위라 이 차이 때문에 멈추지 않는다. native storage dtype와
producer의 authored/derived 의미는 선언만으로 확정하지 않는다. `csc/update`·`csc/app`·
`csc/model`의 특정 파일이 현재 설치에 존재하는지는 여기서 확인하지 않았다.

다른 class/method는 실제 설치에서 확인한 정확한 `.pyi` 경로와 `--symbol`을 추가한다. 최대 8개 파일, 총 16 MiB, 32개 심볼이다. 전체 설치 폴더를 탐색하지 않는다. 출력 파일이 있으면 덮어쓰지 않는다.

`--symbol`은 정확한 선언 이름 또는 class를 포함한 이름이다. `SomeClass.some_method`와 `some_method`를 사용할 수 있다. overload는 각각 남고, class를 선택하면 해당 class 원문을 남긴다. `not_found_in_selected_files`는 선택한 파일에서 찾지 못했다는 뜻이며 SDK 전체에 없다는 뜻이 아니다.

## 결과 사용

1. geometry에서 필요한 좌표/transform/dependency accessor의 실제 타입과 소유 객체를 확인한다.
2. serialization의 Update callback에서 접근 가능한 dtype/producer graph accessor를 확인한다.
3. unbaking의 실제 callable 및 argument lowering을 확인한다.

선언에 반환 타입이 있다고 해서 동기 완료를 증명하지 않는다. action 이름·getter 존재를 작업 실행/완료 API로 간주하지 않는다. 결과 JSON을 기존 native qualification registry나 incident closure 파일로 사용하지 않는다. 설치된 파일의 선언과 실제 loaded bridge fingerprint/epoch는 별개다.

근거: [기준 메모의 설치 SDK 조사](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/docs/KNOWN_ISSUES_2026-11-15.md).

## 선언과 action source를 한 번에 수집하기

추가된 `collect_native_evidence.py`는 앞 수집기와
`../integration/unbaking/collect_action_sources.py`를 묶는다. 패킷 디렉터리 구조를 유지한
상태에서 Python 3.11 이상으로 다음과 같이 실행한다. 이 명령은 사용자 환경에서 아직 실행하지 않았다.

```powershell
python .\docs\implementation\cascadeur-motion-r6\tools\collect_native_evidence.py `
  --stub-root 'C:\Program Files\Cascadeur\resources\scripts\stubs' `
  --python 'ml.editable_animation=C:\Program Files\Cascadeur\resources\scripts\python\ml\editable_animation.py' `
  --entry 'ml.editable_animation:run' `
  --output .\cascadeur-native-evidence.json
```

설치 경로가 다르면 명시한 경로만 바꾼다. `ml.editable_animation:run`은 저장소가 조사한
후보 entry이며 세 action의 실제 binding이라고 간주하지 않는다. 실제 등록 파일이 발견되면
그 파일만 `--python MODULE=FILE` 또는 `--text FILE`로 추가하고, 해당 callable을 `--entry`로
명시한다. 파일·폴더를 재귀 탐색하지 않는다.

고정된 다섯 후보 `.pyi`는 `csc/{domain,update,model,tools,app}/__init__.pyi`다. 존재하는
파일의 원문 선언을 읽고 없는 후보는 `absent_selected_stub_files`에 남긴다. 선택된 파일이
하나도 없으면 출력하지 않고 종료 코드 2를 반환한다. 일부 파일이 없거나 action literal을
못 찾았다는 결과는 그 설치 전체에 API가 없다는 증거가 아니다. `--build-label`은 선택적인
작업자 메모이며 실행 파일 버전을 관측한 값으로 표시하지 않는다.

출력 JSON 하나에 입력 SHA256/행 번호/선언, 선택한 source의 action literal·호출 관계·미해결
참조, 수집기 자체 SHA256이 담긴다. `material_sha256`은 이 읽기 결과의 digest이며 서명된
실행 증거가 아니다. 기존 출력은 덮어쓰지 않는다. collector source만 import하며 설치 SDK나
설치된 Python source는 import하지 않는다. native 실행·approval·incident 변경·registry 등록은 없다.

공개 선언에서 확인한 graph 접근 후보는 [`Group.nodes()`](https://cascadeur.com/python-api/_generate/csc.update.Group.html),
[`NodeAttribute.connected_attributes()`](https://cascadeur.com/python-api/_generate/csc.update.NodeAttribute.html),
[`RegularFunction.type_name()`](https://cascadeur.com/python-api/_generate/csc.update.RegularFunction.html)다.
이 문서 조회는 2026-11-16에 했으며 설치 build와 동일하다는 판정은 하지 않았다. graph를
열거할 수 있다는 사실과 native producer 전체 closure·data 저장 dtype·비동기 완료 의미는 별개다.
