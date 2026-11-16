# Unbaking의 실제 binding 자료 수집

기준 구현: `7f1565a0ffad1595b9824cba25443bc581997fb6`.

`collect_action_sources.py`는 `.pyi` 선언 수집 뒤에도 남는 **실제 action 등록과
callback source**를 좁혀 읽기 위한 실행 가능한 표준 라이브러리 도구다. 선택한
소스 파일을 import하거나 Cascadeur를 실행하지 않는다. 새로운 production gate,
자격 registry 또는 성공 flag 발급기는 추가하지 않는다.

현재 고정 소스에서 확인한 세 ID는 다음과 같다.

| Step | 실제 handler의 action ID |
|---|---|
| `prepare_keys_by_fulcrums` | `View.AutoInterpolation_Keys` |
| `adjust_keys_and_interpolation` | `View.Animation unbaking` |
| `adjust_autoposing_lock_state` | `AutoPosingTool.AutoUnlock` |

출처는 [handlers/generation.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/handlers/generation.py)의
`unbaking`, 117–119행이다. 이 파일은 action **소비자**다. 이곳에서 ID를 찾았다고
설치 action의 **등록 구현**까지 확인한 것은 아니다.

## 실행

Python 3.11 이상, 추가 의존성 없음. `--python`에는 실제 설치 모듈 이름과 명시적인
파일 경로를 함께 지정한다. 아래 경로는 현재 사용자의 설치 위치를 관측한 값이 아닌
명령 형식 예시다. 설치 디렉터리가 다르면 그 파일의 실제 경로로 바꾼다.

```powershell
python collect_action_sources.py `
  --python 'ml.editable_animation=C:\Program Files\Cascadeur\resources\scripts\python\ml\editable_animation.py' `
  --entry 'ml.editable_animation:run' `
  --output '.\unbaking-source-evidence.json'
```

`ml.editable_animation.run`은 현재 설치 조사 memo에 있는 **검토 후보**다.
이 모듈과 세 action의 실제 등록 관계는 아직 미확인이다. `--entry`도 실행이나 binding
선언이 아니라 해당 정의의 소스를 수집하라는 명시적인 선택이다.

등록 파일을 알고 있다면 다음 입력을 같은 명령에 추가한다.

- Python 등록 파일: `--python '실제.모듈명=실제파일.py'`
- JSON/XML/QML/INI/CFG/TXT/C++ 등록 파일: `--text '실제파일경로'`
- 호출된 별도 Python 함수: 그 파일의 `--python` 입력을 추가한다. 이미 선택한
  파일 사이의 명시 import/지역 함수/`self.method`를 구문상 후보로 연결한다.
- 원래 세 ID 외의 구체적인 등록 키가 확인되면 `--action '정확한ID'`를 지정한다.
  `--action`을 한 번이라도 지정하면 기본 세 ID 대신 지정한 목록을 사용한다.

폴더 재귀 검색, 파일명 추측, 네트워크 접근, native introspection은 하지 않는다.
선택하지 않은 import 대상은 자동으로 열지 않는다. 출력 경로가 이미 있으면 덮어쓰지
않고 종료 코드 2로 실패한다. 기존 결과를 보존하고 다른 새 경로를 사용한다.

## 결과를 읽는 방법

- `files`: 실제로 읽은 파일 경로, SHA256, bytes, Python 모듈 이름.
- `action_occurrences`: Python의 정확한 문자열 literal 또는 명시 text 파일의 문자열
  등장 위치, 줄 번호, 같은 statement, 둘러싼 정의. **등록 완료 판정이 아니다.**
- `candidate_call_graph`: action literal과 같은 statement의 함수 참조 또는 명시 entry에서
  시작하는 구문상 후보. 정의 원문, 호출 줄, 선택 파일 안의 가능한 정의, unresolved
  외부·동적 호출을 함께 반환한다. 다른 함수에 넘긴 직접 함수 참조도 callback 후보로 남긴다.
- `source_indicators`: async/yield, dialog/deferred/current-scene/selection 관련 이름,
  동적 callable, exception handler, return 구문과 원문 위치.
- `graph_cutoffs`: 최대 깊이에 걸린 후보 연결. 비어 있어도 동적 실행 경로가 완전하다는
  뜻은 아니다. 등록 조건·decorator·이름 재바인딩·반환 callable·native C++ dispatch는
  이 수집기가 해석하지 않는다.
- `not_found_in_selected_files`: 선택 파일의 지정된 분석 범위에서 못 찾은 ID.
  전체 설치본에 없다는 뜻이 아니다. Python에서 동적으로 조립한 ID는 해석하지 않는다.

모든 호출 대상은 `syntactic_candidates_only`다. 이름이 일치해도 해당 호출이 그 함수를
실제로 실행한다는 결론을 내리지 않는다. indicator가 없거나 `return`이 보여도 동기
완료를 증명하지 않는다. 결과에는 `binding_proven=false`, `runtime_qualified=false`,
`completion_observed=false`가 고정된다. 이는 제품 기능을 차단하는 새 판단 로직이 아니라
**이 정적 자료가 무엇을 관측하지 않았는지**를 표시한 것이다.

파일 16개·파일당 2 MiB·합계 16 MiB, AST 100,000개, 정의 후보 128개, 호출 2,048개,
깊이 8, 출력 8 MiB로 제한한다. 명시된 깊이 제한 외에는 한도를 넘은 자료를 성공한
부분 보고서로 조용히 잘라내지 않고 입력을 좁히도록 오류를 반환한다.

## 자료가 도착하면 수정할 곳

`INTEGRATION_INPUTS.json`은 세 action과 기존 handler/contract 함수를 고정 source에
연결한다. 다음 사항이 밝혀진 step부터 구현한다.

1. 정확한 action 등록 위치와 설치 파일 hash, 실제 callable/동적 dispatch의 다음 목적지.
2. 그 callable의 명시 object/layer/frame 인자 또는 이를 받을 수 있는 실제 순수 planner.
3. key 추가·삭제·쓰기와 interpolation/lock 변경의 실제 의미 및 상한.
4. 동기 leaf의 반환이 완료되는 경계, 또는 같은 operation ID에 연결된 실제 완료 callback.

이후 `native_unbaking_leaf.execute_qualified_step`에 그 leaf의 구체적인 lowering을 넣고,
`native_unbaking.require_step_contract`의 process-private 실제 등록 조회와
`handlers/generation.unbaking`의 dispatch 연결을 적용한다. 기존 source/topology/비대상
보호는 그대로 소비한다. 현재 공개 인자로 충분하면 새 API를 추가하지 않는다.

Opaque `call_action(...) -> None`만 확인되면 완료를 만들어 반환하지 않는다. callback이
전역 scene/selection 또는 deferred 작업을 쓰면 그 실제 인자와 완료 경계를 먼저 분리해야
한다. source 수집 결과만으로 원 incident를 닫거나 unbaking capability를 열지 않는다.

## 작성 시 실행 범위

이 폴더의 수집기를 설치본에 실행하지 않았다. 설치 binding·native leaf·최종 모션 결과는
미검증이다. 제품 patch를 만들 만큼 실제 leaf 정보가 없으므로 빈 registry/가짜 completion
diff는 추가하지 않았다. 정적 구문 확인은 상위 패킷의 확인 기록에 합산한다.
