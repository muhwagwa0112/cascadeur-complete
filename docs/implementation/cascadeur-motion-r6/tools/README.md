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
`Update.root_group` 및 그 반환 class의 graph/data 접근 부분이다. native dtype getter와
producer/consumer edge getter의 이름은 아직 확정하지 않았다. 알려지지 않은 함수명을
가정하는 대신 확인된 반환 class 선언 전체를 먼저 수집한다. `csc/app`·`csc/model`은 조사
후보 namespace이며 이 문서가 특정 `.pyi` 파일의 현재 존재를 보장하지 않는다.

다른 class/method는 실제 설치에서 확인한 정확한 `.pyi` 경로와 `--symbol`을 추가한다. 최대 8개 파일, 총 16 MiB, 32개 심볼이다. 전체 설치 폴더를 탐색하지 않는다. 출력 파일이 있으면 덮어쓰지 않는다.

`--symbol`은 정확한 선언 이름 또는 class를 포함한 이름이다. `SomeClass.some_method`와 `some_method`를 사용할 수 있다. overload는 각각 남고, class를 선택하면 해당 class 원문을 남긴다. `not_found_in_selected_files`는 선택한 파일에서 찾지 못했다는 뜻이며 SDK 전체에 없다는 뜻이 아니다.

## 결과 사용

1. geometry에서 필요한 좌표/transform/dependency accessor의 실제 타입과 소유 객체를 확인한다.
2. serialization의 Update callback에서 접근 가능한 dtype/producer graph accessor를 확인한다.
3. unbaking의 실제 callable 및 argument lowering을 확인한다.

선언에 반환 타입이 있다고 해서 동기 완료를 증명하지 않는다. action 이름·getter 존재를 작업 실행/완료 API로 간주하지 않는다. 결과 JSON을 기존 native qualification registry나 incident closure 파일로 사용하지 않는다. 설치된 파일의 선언과 실제 loaded bridge fingerprint/epoch는 별개다.

근거: [기준 메모의 설치 SDK 조사](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/docs/KNOWN_ISSUES_2026-11-15.md).
