# Unbaking: 실제 lowering을 결정하는 작은 native 작업

기준 source는 `7f1565a0ffad1595b9824cba25443bc581997fb6`이다. 이 문서는 준비 패킷이며 제품 적용, SDK 실행, action dispatch, 테스트를 수행하지 않았다.

## 현재 결론

확인된 typed data/Section API만으로 세 UI action과 같은 의미의 finite lowering을 아직 정의할 수 없다. `set_data_value`, `set_sections`, `Interpolation.LINEAR/STEP`는 쓰기 수단이다. fulcrum의 선택 기준, key 제거/추가 정책, interpolation 오차 기준, AutoPosing lock의 의미를 제공하지 않는다. 임의의 sparse fitting이나 명시 key 삽입으로 대체하고 unbaking 성공이라고 보고하지 않는다.

현재 [native_unbaking.step_contract_status/require_step_contract](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_unbaking.py#L19-L40)는 모든 step을 미자격으로 반환한다. 이 준비 패킷에서 같은 always-false 함수를 다시 구현하지 않는다. 아래 한 leaf가 완성돼야 성공 분기가 생긴다.

| Step | 확인된 수단 | 아직 없는 의미 입력 | 조건부 구현 경로 |
|---|---|---|---|
| `prepare_keys_by_fulcrums` | 실제 key/section reader 및 typed section writer | 실제 fulcrum/contact 필드의 owner/property/type, 원 action의 frame 선택 규칙, key 생성·삭제 규칙 | 설치 action binding의 순수 planner를 명시 객체/레이어/구간 인자로 분리할 수 있을 때만 finite plan으로 낮춘다. |
| `adjust_keys_and_interpolation` | 기존 key position writer, Section/Interpolation API; AnimationUnbakingTool의 difference getter 보고 | getter의 정확한 signature와 단위, 선택/삭제 규칙, 실제 action 구현, 허용 오차와 종료 조건 | 동기 계산 leaf가 반환한 구체적 edit 목록을 현재 typed writer로 적용하고 전체 scope 결과를 비교한다. |
| `adjust_autoposing_lock_state` | 설치 AutoPosingTool에 add/update가 있다는 memo | 정확한 lock data/setting ID와 bool/enum 의미, per-frame/static 범위, 원 action과 같은 정책 | 실제 lock field와 의미가 확인된 경우에만 제한된 값 목록으로 내린다. 이름에 `lock`이 있다는 이유로 bool을 바꾸지 않는다. |

[native_fixture.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_fixture.py#L111-L184)의 Section/set_data_value 경로는 현재 source에서 직접 확인했다. `ActionManager.call_action -> None`, 설치 `ml/editable_animation.py`의 dialog/deferred callback/전역 current scene/범위 확대는 [현재 memo](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/docs/KNOWN_ISSUES_2026-11-15.md)에 기록된 설치 조사 결과다. 이번 패킷 작성에서 설치 파일을 다시 실행하거나 조사하지 않았다.

## 다음 실행자에게 필요한 유한 입력

1. **선언 자료:** 설치 build, 파일 SHA-256, source path/line과 함께 `csc.app.ActionManager`, `csc.tools.AnimationUnbakingTool`, `csc.tools.AutoPosingTool` 선언을 제공한다. 이름은 기록된 설치 타입이며 새 completion 함수를 가정하지 않는다. `.pyi`에 return type이 있어도 완료 semantics 증거가 되지 않는다.
2. **실제 binding 자료:** `View.AutoInterpolation_Keys`, `View.Animation unbaking`, `AutoPosingTool.AutoUnlock` 세 ID가 등록되는 정확한 Python/C++ binding의 파일/line/source hash. `ml/editable_animation.py`가 비슷해 보인다는 이유로 binding으로 간주하지 않는다. 제공된 Python source에서 전역 scene/selection, dialog, deferred scheduling, worker/consumer 호출의 실제 reachable branch만 좁혀 읽는다.
3. **한 step의 작은 native 결과:** 먼저 발견된 가장 작은 동기 leaf 한 개만 대상으로 명시 object/layer/range와 predeclared 추가·삭제·쓰기 상한, 실제 callback 반환/terminal correlation, 전후 key topology·비대상 필드의 관측을 받는다. opaque action만 존재하면 token/continuation이 실제 어디에서 종료되는지의 owner/operation ID를 받아야 한다. quiet period나 연속 동일 projection을 종료 증거로 대신하지 않는다.

선언 수집은 host-only AST/source 수집으로 가능하다. 3번은 별도의 native 실행 단계이며 이번 push나 AST 확인으로 충족되지 않는다. 위 입력이 나오기 전에는 completion leaf 이름이나 setter property를 만들어 넣지 않는다.

## 정확한 구현 단위

신규 **프로젝트 함수**(SDK 함수가 아님) `native_unbaking_leaf.py::execute_qualified_step(scene, step, source, arguments, request)` 한 모듈을 구현 대상으로 둔다. 요구 출력은 다음과 같다.

```python
# Proposed internal project type. No code in this packet instantiates it as proof.
NativeUnbakingStepCompletion(
    request_id=..., installed_binding_sha256=..., step=...,
    before_source_digest=..., exact_scope_digest=...,
    added_key_locators=..., removed_key_locators=..., written_key_locators=...,
    changed_data_or_setting_ids=..., actual_after_projection_digest=...,
    completion_observation=...,  # actual synchronous leaf or actual correlated terminal
)
```

등록 순서는 `정확한 설치 binding 발견 → 해당 step의 native bounded 관측 → private QualifiedStep 객체 발급 → step별 private registry 등록 → prepare/preflight에서 해당 scope 지원 여부 확인 → current request source guard → 명시 lowering 실행 → 실제 완료 및 topology readback → native terminal 후 memory-only 봉인`이다. caller가 `qualified=True`, source hash 또는 completion dict를 주어 등록시키는 경로는 만들지 않는다.

동기 leaf가 실제로 있다면 `handler_registry.transact` 안에서 명시 인자를 전달한다. 설치 함수가 그 callback 안에서 호출 가능한지와 callback 밖 작업을 예약하지 않는지는 해당 native 관측으로 확인해야 한다. 현재 opaque `call_action`을 transact로 감싸는 것만으로 동기 함수가 되지는 않는다.

변경 대상은 다음으로 제한한다.

- `native_unbaking.py::step_contract_status/require_step_contract`: private 실제 등록 객체 조회와 exact step/scope/current build 확인. 등록되지 않은 step은 구체적인 미확인 입력을 반환한다.
- `handlers/generation.py::unbaking`: 기존 action dispatch 분기 전에 qualified leaf로 라우팅한다. 현재 source/topology/selection 상한은 유지한다. 선택 효과가 필요한 설치 leaf이면 명시 scope와 선택 복구 완료까지 같은 관측 범위에 포함한다.
- `server.py::animation_unbaking_prepare`, `recipe_native_service.py::recipe_preflight`: 요구 step 중 하나라도 binding/완료/상한 자격이 없으면 prepare 전에 정확한 reason으로 거절한다. stage 자동 삭제나 sparse mode 변환을 하지 않는다.

공개 API 확장은 현재 요구하지 않는다. 실제 설치 leaf에 현 public arguments로 표현할 수 없는 필수 인자가 있으면 그 인자와 의미를 확인한 뒤에만 별도 API 변경안으로 올린다.

## 최소 직접 사례 명세 — 실행 안 함

추후 해당 leaf가 실제 생겼을 때 기존 `tests/test_unbaking_bounds.py`의 다음 두 경우만 직접 검증 대상으로 삼는다: (a) qualified exact binding/step이 원 added/removed/written 상한과 비대상 projection을 지키며 실제 terminal로 끝남, (b) `None`만 반환하거나 dialog/deferred path로 들어간 경우 completed를 발급하지 않고 기존 unknown/reconciliation 정책을 보존함. 예상 명령은 새 사례를 기존 파일에 추가한 뒤 `pytest tests/test_unbaking_bounds.py -k 'qualified_leaf or deferred_leaf' -q`이다. 이는 향후 명령 명세이며 현재 존재하는 test name이나 실행 결과를 주장하지 않는다.
