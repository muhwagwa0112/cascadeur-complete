# R6 motion: 실제 등록 경로를 만드는 준비 코드

## 범위와 현재 완료선

기준은 `muhwagwa0112/cascadeur-complete@7f1565a0ffad1595b9824cba25443bc581997fb6`이다. 이 디렉터리는 문서 branch에 보관할 준비 패킷이다. 제품 모듈에 적용하거나 native 기능 자격을 발급하지 않았다. SDK 호출 코드가 들어 있지만 실행하지 않았다. 기존 incident admission/producer retirement/설치 identity의 선행 차단도 그대로다.

| 파일 | 이번에 구체화한 실행 경로 | 아직 실제 설치에서 확인할 부분 |
|---|---|---|
| `reference_geometry.py` | 실제 source 기반 두 Transform/두 self-bound cube 생성, 10회의 계산을 이용한 coordinate/negative-control 관측, private finite-profile 등록, 정렬된 pair capture, mutation→evaluation→capture private chain | 새 두 객체 구성, typed graph extractor, Update 안 calc의 허용/완료 semantics, 실제 geometry/motion adapter 통합 |
| `reference_serialization.py` | guarded Update callback에서 dtype/graph와 raw projection을 함께 고정, 코드 소유 역할 규칙으로 policy 등록, 매 사용 graph 재관측, 불변 P0 비교, private checkpoint의 실제 copy-load→새 scene 결합 | 실제 native dtype/producer getter 및 역할 의미, graph-only 변경을 누락하지 않는 열거, 이 profile의 no-yield/관측 비변경 semantics |
| `serialization_equivalence.py` | 기준 HEAD의 기존 comparator 고정 사본, 변경 없음 | 수학적 비교 후보일 뿐 SDK 역할/완료 증거가 아님 |
| `UNBAKING_NATIVE_WORKITEM.md` | 세 step의 typed lowering 가능 조건, 필요한 source/선언/한 native leaf 작업 | 실제 action binding과 완료 leaf; 현 자료만으로 동등한 lowering을 발명할 수 없음 |

모든 Python은 `motion` namespace package의 참조 코드다. `from motion.reference_serialization import ...`처럼 패킷 상위 디렉터리를 import root로 쓰는 구성이다. 실제 Cascadeur binding 함수는 호출 시에만 `cascadeur_complete`/`csc`를 import한다. reference 객체/JSON을 production proof로 받아들이는 경로는 없다. 이번에 import, 테스트, native 실행을 하지 않았다.

## 직접 확인한 source와 metadata

아래 blob SHA는 GitHub의 해당 고정 HEAD에서 읽은 file identity다. 설치 파일 hash나 loaded fingerprint를 대신하지 않는다.

| Source | Git blob SHA | 이번 설계에서 쓰는 실제 함수 |
|---|---|---|
| [native_fixture.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_fixture.py) | `0689e41b9963cf5db2a2bcac27ca5e36477345a6` | `_owned`, `_modify`, `create_disposable_scene`; `add_transform_mod`/Section/set_data_value의 실제 호출 형태 |
| [native_geometry_qualification.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_geometry_qualification.py#L59-L161) | `e556365feadddcddcd9d10cab5fe2da87c45152e` | `_fixture_inputs(scene, fixture)`는 5-tuple, `_calculate(scene, fixture, frames, retained)`는 `(inputs,trials)` 반환 |
| [native_geometry_capture.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_geometry_capture.py#L63-L136) | `9c61878e51cda3348ceab46d91a4d00487c63938` | `_CONTRACTS`, `_origin`, `_inputs`, `NativeGeometryCaptureAdapter` |
| [native_scene_adapter.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_scene_adapter.py#L104-L127) | `45821dd297b400523113ead072a3b3ef8177d498` | `NativeSceneAdapter.execute`, `finalize_evaluation` |
| [native_serialization.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_serialization.py) | `cc9e0acee20af393fbc64938ad7d5356d9ec9ea3` | `pin_reference`, `compare_with_private_policy`, `_POLICIES` |
| [serialization_equivalence.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/serialization_equivalence.py#L266-L353) | `3a5df24f542fc894737845fb0db39e941b7b2495` | 기존 comparator 그대로 재사용 |
| [native_checkpoint_restore.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_checkpoint_restore.py#L326-L385) | `ce6d491e217fd1667a9bdf406415045a459485ac` | `_CHECKPOINTS`, `remember_checkpoint`, `_restore_native`, `_original_terminal` |
| [native_project_io.py](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_project_io.py#L129-L245) | `633fd626dd08622150e4d4a9e31e86ccbb0a7225` | `load_project_copy`의 실제 return `(target, observation)` |

dtype/producer graph가 Update callback에서만 보인다는 내용은 [현재 memo](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/docs/KNOWN_ISSUES_2026-11-15.md)의 설치 조사 보고다. 과거 memo는 `Update.root_group()`을 적었지만 2026-11-16에 조회한 [공개 API 선언](https://cascadeur.com/python-api/_generate/csc.update.Update.html)은 `Update.root()`이다. 현재 설치 선언을 수집하여 이름·반환형을 결정하며 자동 fallback getter를 만들지 않는다. 이번에는 설치를 열거나 SDK를 실행하지 않았다. `Scene.modify_update` → `updater.get_interpolator().reload()/interpolate()` 호출은 위 현재 source에서 직접 확인했다. 공개 node/edge accessor의 존재만으로 설치 graph의 완전성·native storage dtype를 확정하지 않는다.

## 1. 두 mesh를 실제 pair 경로에 연결하기

### 별도 유한 setup

기존 single-cube helper는 일반 contract를 발급하지 않고, `_fixture_inputs`는 정확히 한 객체만 허용한다. `create_independent_transform`도 빈 장면의 한 객체 전용이다. 이를 두 번 부르거나 viewer를 속이지 않는다. 새 `native_create_owned_pair`는 확인된 기초 명령을 새 소유 장면에서 고정 두 번 사용한다.

- `commands.add.add_transform.add_transform_mod(model, update, callback_scene, session, True)`로 두 객체를 만들고 실제 object/layer ID를 받는다. 두 독립 layer가 아니면 거절한다.
- 실제 Section/Interpolation/Key API로 각 layer의 `0,1,2` keys를 만들고 typed `model.data_editor().set_data_value`로 local/global 위치를 쓴다. 초기 위치들은 source에 고정된 dyadic 값이다.
- `csc.domain.assets.AssetsManager.get_cube_mesh(2.0)`, `MeshDependency(mesh)`, `common.mesh.set_mesh_object_data(...,[obj],create_default_material=False)`로 각각 자기 객체 하나에만 묶는다.
- 새 `native_read_pair_inputs`가 기존 `_fixture_inputs`의 typed asset/link/parent/weight/matrix 검사를 두 객체 closure로 특수화한다. 일반 reader의 one-object 제한을 전역 완화하지 않는다.
- `csc.domain.calc_skinned_mesh(domain,obj,frame)`의 실제 `positions`를 즉시 소유 배열로 복사한다. 허용 shape는 float32 `(N,3)` 또는 정확한 `(N,3,1)`이다.

신규 setup ID는 **제안** `setup.qualify_owned_pair_geometry`, retention kind는 **제안** `owned_pair_geometry`다. 기존 `setup.qualify_geometry_calculation`의 `5 calc / 2 eval / 1 driver` 상한을 바꾸지 않는다.

| 항목 | 새 pair setup의 명시 상한 |
|---|---:|
| 새 탭 / `.casc` 파일 | 1 / 2 |
| 새 객체 / 독립 layer | 2 / 2 |
| frames / mesh당 vertices | 3 / 64 |
| mesh 계산 | 10: 각 mesh `0,2,1,0` 8회 + driver 변경 후 두 mesh의 frame1 2회 |
| 명시 interpolation evaluation | 2 |
| 기존 driver key 변이 | 첫 mesh의 local position frame1 1회 |
| graph-aware capture Update callback | 2: 위 8회/2회 계산을 각각 묶음 |
| setup 내 model 생성 transaction | modify_with_session 1, initial author/attach modify 1, driver modify 1 |
| projection / typed graph JSON | 각각 2 MiB |

graph callback 2개도 effect다. `2 eval`이라는 숫자로 이를 숨기지 않는다. 실제 Update entry가 암묵적 interpolation/scene mutation을 추가하면 이 예산/완료 계약은 실패하며, 기존 상한으로 실행을 계속하지 않는다. 네 번의 modify_update 진입(명시 evaluation2 + capture2)은 알려진 호출 수이며 native 내부 연산/heap의 hard bound를 주장하지 않는다. original-tab 복귀/retention bookkeeping은 기존 RetainedProbe 계약을 따른다. 파일/탭 실패 잔여물은 보존하고 자동 재시도하지 않는다.

새 helper를 연결할 정확한 곳은 `incident_setup._HELPERS/_SEMANTIC_LIMITS`(host/native mirrored source), `incident_admission.SETUP_IDS`, `SetupAdmission`의 graph-callback 상한 필드, `intent_for`의 setup 분류, `dispatch_setup`의 명시 branch, `native_probe_retention._LIMITS/_SETUP_OPERATIONS/_FILENAMES`다. `maximum_update_graph_captures=2`, 고정 object/layer/frame 상한을 signed setup plan의 semantic_limits에 포함시키는 **승인·schema 변경 제안**이다. 기존 setup 승인으로 새 helper를 호출하지 않는다.

### 생성부터 등록까지의 실제 조립

새 native helper `native_owned_pair_geometry.qualify_owned_pair_geometry`의 조립 순서는 다음으로 고정한다. 아래 이름 중 신규 프로젝트 함수는 SDK 함수가 아니다.

```python
# Proposed product integration, not executed or applied.
admission = assert_setup_admission("setup.qualify_owned_pair_geometry")
# Compare every signed semantic limit to the fixed pair limits BEFORE new tab.
retained = RetainedProbe("owned_pair_geometry")
retained.before_new_tab()
scene = create_disposable_scene(retain_on_failure=True)
retained.track(scene, "owned-pair-geometry")
runner = bind_native_update_runner(
    scene, extract_installed_update_facts, retained.before_effect)
kernel = PairGeometryPositivePath(scene=scene, retained=retained, runner=runner)
# Callback finishes retention/records the completed actual setup, then returns.
# Any exception runs retained.finish(error); it does not install anything.
contract = kernel.initialize(complete_retained_setup)
native_owned_pair_geometry._KERNELS[private_context_key] = kernel
native_geometry_capture._CONTRACTS[build_fingerprint_epoch_key] = native_contract
guards.register_adapter("system.observe_geometry_capture", native_adapter)
```

`native_contract/native_adapter`는 위 실제 `kernel/contract`를 private identity로 보유하는 신규 native wrapper다. wire dict/hash를 받는 생성자가 아니다. 실제 완료 전에는 마지막 세 줄을 실행하지 않는다. wrapper는 `verification/evidence_bytes/observed_build/operations`를 실제 보존된 qualification bytes에서 만들며, host flag로 `identity_stable`나 동기 완료를 채우지 않는다. `geometry_contract_status()`는 이 실제 registry와 현재 build/epoch/scene를 조회한다. “등록됨”과 “이번 실행의 graph를 재확인함”을 구분한다.

**아직 없는 native wrapper의 정확한 책임:** `required_scope/capture`는 아래 historical source 경로를 사용하고, `execute`는 새 request의 runner/guard를 만들어 `kernel.capture`를 호출한다. `NativeGeometryCaptureAdapter.execute`의 `_sample_mesh_positions` 루프는 그 결과의 raw/canonical rows를 쓰도록 교체한다. 다른 루프에서 계산을 다시 호출하지 않는다. `mesh_to_world`는 같은 callback에서 읽은 matrix에서만 나온다. coordinate 계약에는 실제 observed raw space와 explicit context basis/scale을 함께 넣는다. 현재 `stage/finalize/get/verify`와 NPZ/candidate/completion sidecar 검증은 유지한다. reference JSON 자체를 `native_actual`로 봉인하지 않는다.

이 wrapper/dispatch 변경은 아직 적용 코드가 아니다. 현행 `_CONTRACTS`에 참조 객체를 넣기만 해서는 product가 작동하지 않는다. 아래 source gate, current request lifetime, motion ownership까지 함께 구현해야 한다.

### source/현재성/effect 경계 — 기존 readonly 경로에 숨기지 않기

현재 `_execute_admitted_request`는 dispatch 전에 `guards.assert_source`를 부르고 현재 geometry는 `file` effect다. Update callback이 필요한 이 profile은 **mixed effect**로 분류해야 한다. `src/cascadeur_complete/effects.py::classify_effect`와 `runtime._request_effect`에서 해당 geometry route를 동일하게 변경한다. 기존 effect enum의 `mixed`를 사용하며 별 효과명을 발명하지 않는다. `system.capture_source`나 `system.validate_source`가 몰래 modify_update를 호출하면 안 된다.

구현할 내부 경로는 다음이다.

1. 이미 허가된 native evaluation/capture callback에서 실제 graph+raw projection을 읽어 private `UpdateSnapshot`을 발급한다. `UpdateCaptureRunner.transition`은 한 callback의 실제 before/after를 그 callback이 끝난 뒤에만 봉인한다. readonly accessor가 없는 상태에서 캐시 graph를 “지금 읽었다”고 표시하지 않는다.
2. 신규 내부 `issue_operation_source_from_closed_snapshot(scene, scope, inputs_digest, snapshot_handle)`는 실제 private snapshot에서 operation-scope source를 만든다. 이는 **과거에 실제 관측한 상태에 대한 source**이며 현재 상태라는 별도 주장을 하지 않는다. scope에 `expected_graph_dtype_digest`와 `validation_mode="qualified_update_boundary"`를 서명된 조건으로 포함한다. 임의 snapshot JSON을 입력받지 않는다.
3. 이 mode가 등록된 정확한 adapter에만 `runtime._execute_admitted_request`의 일반 readonly assert/capture와 다른 명시 gate를 둔다. 사전에는 원 issued-source identity·scope/args·raw projection·epoch를 검사한다. 실제 graph/current source 검사는 허가된 modify_update callback 첫 부분에서 수행하며, 일치하기 전에는 calc/파일/명시 data write를 하지 않는다. raw-only 검사를 full-source 검증 완료로 반환하지 않는다. 일반 adapter의 `guards.assert_source`는 완화하지 않는다.
4. 이 callback에 들어가는 것 자체가 원 mixed request가 허가한 bounded graph-observation effect다. entry/return이 예상 밖 scene 변경을 일으키면 unknown/실패 관측을 보존한다. graph를 보기 위해 현 permission을 우회하거나 read-only 요청을 action으로 바꾸지 않는다. 이것이 현재 설치에서 qualify할 수 없는 경우 이 adapter는 등록하지 않는다.
5. callback 후 같은 native no-yield dispatch 안에서 실제 raw projection을 다시 읽고, private snapshot/파일 effect의 `before_write`를 연결한다. terminal 뒤의 finalizer는 memory-only로 receipt를 붙인다. 새로운 파일을 쓰거나 calc를 재dispatch하지 않는다.

위는 **새 내부 source validation 계약 제안**이다. 공개 source의 serialized shape가 바뀌면 schema/version 및 host/native validator 변경 승인이 필요하다. 현재 코드의 unobserved graph revision을 있는 것처럼 사용하지 않는다.

setup와 capture의 request lifetime도 분리한다. `PairGeometryPositivePath.initialize`만 setup용 retained/runner를 쓴다. 완료 뒤 두 binding을 버리며, `capture(..., runner=current_request_runner, before_calculation=current_request_guard)`는 새 요청의 admission/source/effect guard를 반드시 받는다. setup의 permit으로 후속 capture를 실행하지 않는다.

### scope와 기존 pair 품질 소비자

두 mesh를 같은 scene에서 잡으므로 현행 nonempty `pairs` schema를 바꿀 필요가 없다. production schedule은 mesh별 정렬 ID 및 오름차순 frame이며 calibration의 `0,2,1,0` 순서를 재사용하지 않는다. 이 최초 profile은 exact owned scene instance, 두 actual mesh ID, 부모 없음, identity rotation/scale, self weight1, graph closure, 3 frames, 변하지 않은 topology/asset에 한정된다. 일반 skinned character/blendshape/parented mesh를 qualify하지 않는다.

`native_motion_capture._ownership`는 현재 single-independent 또는 unique RigInfo 경로다. 소유 pair의 motion baseline도 통과하도록 **private pair contract와 정확한 두 ID가 확인된 경우만** identity ownership을 발급하는 branch가 필요하다. 임의의 두 Transform이나 `{root:None}` 입력으로 이 branch를 열지 않는다. evaluation/source/canonical batch의 기존 validation은 유지한다. 이는 최초 pair fixture→motion baseline→geometry manifest→`actual_mesh_metrics`를 실제로 열기 위한 필수 연결이며 생략하면 여전히 막힌다.

`actual_mesh_metrics`에는 origin source/successor, motion capture, 같은 evaluation receipt, actual full projection/graph closure, topology/skin, sorted frame/time/context, canonical positions, windows/triangles/hash를 기존 field로 공급한다. sampling 숫자나 파일 존재만으로 native geometry 품질을 통과시키지 않는다.

## 2. Mutation successor → evaluation → capture의 인증된 연결

`MutationEvaluationRebind`는 기존 [무조건 거절 branch](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/cascadeur_side/cascadeur_complete/native_geometry_capture.py#L87-L114)를 대체할 실제 내부 기록 알고리즘이다.

1. 실제 mutation callback의 완료 상태를 graph-aware snapshot으로 잡고 successor가 발급된 뒤 `stage_mutation(original_signed_request, actual_successor, actual_snapshot)`한다. 현재 full-reader adapter만 허용한다. sample_digest뿐 아니라 scope에 결합된 content_revision을 실제 projection으로 재계산한다.
2. native terminal receipt 기록 뒤 `seal_mutation`이 `_original_terminal`로 원 request/receipt를 다시 인증한다. 원 signed request의 `mac`을 포함한 전체 canonical digest를 사용한다. 현재 `_original_terminal` lines220–242도 이 방식을 쓴다. failure/unknown은 성공으로 봉인되지 않는다.
3. `NativeSceneAdapter.execute`의 기존 refresh callback을 `runner.transition` 안에 넣어 실제 interpolation 직전/직후 graph와 raw projection을 얻는다. 이전 full successor 상태와 evaluation의 실제 pre-state가 exact하게 같아야 한다. operation scope가 달라진 것은 full-state equality와 각 source의 독립 scope digest로 연결한다. historical origin source를 current assert_source에 넣지 않는다.
4. `finalize_evaluation`의 기존 terminal 완료 뒤 `seal_evaluation`을 memory-only로 부른다. 해당 evaluation post source/receipt를 정확히 보존한다.
5. `native_geometry_capture._origin`의 mutation 분기는 `require_capture`를 호출한다. `native_motion_capture.lookup_capture`에서 받은 private record만 전달하며 현재 graph-aware snapshot, 실제 full projection, motion source, evaluation receipt를 모두 일치시킨다. origin ID를 evaluation ID로 바꾸어 거절을 피하지 않는다.

새 기록은 runtime epoch 안에서만 존재한다. 재시작 후 disk 후보/JSON으로 private proof를 재구성하거나 원 SDK 쓰기를 재실행하지 않는다. mutation adapter가 실제 graph-aware post snapshot을 낼 수 없으면 그 adapter의 rebind는 아직 미지원이다. 이번 코드가 일반 writer의 불완전 projection을 full-reader로 승격하지 않는다.

## 3. Update 관측에서 serialization policy를 발급하기

### 미확인 SDK leaf의 정확한 경계

`extract_installed_update_facts(model, update, updater) -> UpdateFacts` 하나를 실제 설치에 맞춰 구현해야 한다. 이 이름은 신규 프로젝트 함수이며 SDK getter 이름이 아니다. 필요한 반환 내용은 다음과 같다.

- 현재 전체 graph의 typed node/port/edge, 실제 producer 구현 identity, 모든 data/setting dependencies, external links. outer scene 전체 closure를 빠뜨리지 않는 열거가 필요하다. 임의 `complete=True`는 입력 field가 아니다.
- 모든 projection data ID의 actual owner, native dtype, sample shape, producer ID와 정확한 native kind, upstream data ID, consumer ID.
- authored storage 여부의 실제 의미. getter가 이 사실을 제공하지 않으면 `None`이며 exact 유지. 이름/Animation 모드만으로 `False`를 쓰지 않는다.
- graph-only 변경이 같은 raw projection에 숨어도 digest가 바뀌어야 한다. 일회 graph 캐시/role-layout digest를 현재성 증거로 쓰지 않는다. transient pointer를 임의로 제거해 동일 graph라고 만드는 canonicalization도 금지한다.

root의 host-only declaration collector에 줄 우선 파일은 설치 `resources/scripts/stubs/csc/domain/__init__.pyi`, `.../csc/tools/__init__.pyi`다. `.../csc/update/__init__.pyi`, `.../csc/model/__init__.pyi`, `.../csc/app/__init__.pyi`도 경로 존재를 확인할 후보다. 필요한 class는 Scene/SceneUpdater/Update/Data와 Update 반환 타입 및 그 도달 가능한 typed graph/port 타입이다. `../tools/collect_native_evidence.py`는 이 다섯 후보와 관련 class 선언을 한 번에 모으며, 없는 후보를 별도로 기록한다. 공개 문서의 함수명을 설치 코드에 추정 적용하지 않고 실제 선언과 반환형을 따라간다.

### Issuer와 consumer

`bind_native_update_runner`는 확인된 `handler_registry.transact(domain.modify_update,...,before_write=...)`에 연결한다. 한 callback 전후의 raw projection, graph와 dtype가 같아야 관측 snapshot을 발급한다. 밖으로 반환한 뒤 projection/context도 exact하게 같아야 한다. 관측용 Update가 save drift를 수정해서 통과시키면 `UPDATE_OBSERVATION_CHANGED_RAW_STATE`로 거절한다. save/load를 Update 안에 중첩하는 코드는 없다.

`SerializationPositivePath.initialize_anchor`는 실제 P0와 actual producer/type 관측으로 `DerivedRule`을 만들고 private policy registry에 등록한다. 역할 규칙 `RoleSpec`은 **설치 producer 의미를 검토한 코드 소유 rule**이며, 각 비교에서 caller가 주는 policy가 아니다. numeric budget은 P0 비교를 보기 전에 정한다. 현재 실패한 Cascy 1 ULP에 맞춰 숫자를 고르지 않는다. native type이 float32이고 authored_storage가 False이며 정확한 producer/behaviour/property/shape가 모두 맞는 규칙만 numeric rule이 된다. 다른 필드는 exact다. 이 최초 issuer는 quaternion 규칙을 추가하지 않는다.

`observe_phase(anchor,phase,runner=current_request_runner)`는 매번 fresh Update 관측을 얻고 원 P0의 dtype/graph와 exact 비교한 후 기존 comparator를 호출한다. 현재 guard는 **그 phase의 dispatch**에서 얻는다. `bind_current_request_runner`가 이미 private하게 결합된 실제 native scene에 새 request guard를 붙인다. anchor 생성 request의 만료된 permit을 working_save/restore에 재사용하지 않는다. observation 직전 save/load로 합법적으로 바뀐 raw state는 해당 phase의 실제 native 결과에서 pin하며 원 mutation source를 억지로 current assert하지 않는다.

### 새 탭으로 restore되는 경로

현행 `_restore_native`는 line342에서 새 target을 load하고, line347/355에서 비교한 뒤, **line368에서야** `guards.link_clone`를 한다. 그러므로 P0의 scene identity와 restore target의 provisional identity를 무조건 같게 검사하면 정상 restore도 막힌다.

`load_checkpoint_copy`는 기존 load 호출을 대체하는 내부 bridge다. `_CHECKPOINTS`의 실제 private record → `require_anchor`의 실제 immutable anchor → 정확한 원 P0 bytes/hash → 원 file path/hash/length → **실제 `load_project_copy`가 반환한 target/관측**의 순서로 새 runner를 결합한다. caller-provided load dict/scene ID를 받지 않는다. 기존 restore permit/source/owned-path checks를 보존한다. 같은 load를 두 번 실행하지 않는다.

새 target의 provisional identity로 `project_load/restored_save`를 비교하고, 기존 `guards.link_clone`가 완료된 뒤 `bind_completed_clone_identity`가 실제 native identity를 확인해 future binding을 memory-only로 갱신한다. P0나 이전 observation을 고쳐 쓰지 않는다. project-load 관측과 최종 lineage는 서로 다른 시점의 기록이다.

적용 위치는 다음으로 한정한다.

| 기존 함수 | 제안 변경 |
|---|---|
| `native_serialization.pin_reference` | 새 issuer가 잡은 동일 P0 bytes/actual typed observation을 private anchor에 연결. 별도 사후 projection을 P0로 교체하지 않음 |
| `native_adapters.checkpoint` lines272–281 | 첫 save 전 P0 issuer 초기화. checkpoint_save/working_save는 각 실제 결과 + 현재 request runner로 원 P0에 직접 비교 |
| `native_serialization.compare_with_private_policy` | empty global policy lookup 대신 anchor-bound issuer policy + fresh current Update 관측 사용 |
| `remember_checkpoint` | 기존 fixed file/hash/P0 identity 보존; private issued observation과 actual raw projection을 검증 |
| `_restore_native` lines342–355 | 한 번의 private load bridge를 사용하고 provisional target runner로 두 phase 비교 |
| `_restore_native` line368 이후 | 실제 link_clone 후 private identity binding 갱신, 기존 successor manifest의 actual raw digest 유지 |
| native terminal/source 생성 | 비교 후보 hash가 아니라 실제 restore raw projection에 successor binding; serializer 관측을 native completion 대신 쓰지 않음 |

## 최소 검증 명세 — 여기서는 실행하지 않음

root는 준비물의 Python 3.11 AST와 실제 patch가 있는 경우 apply 가능성만 한 번 확인한다. 이 motion 디렉터리에는 자동 적용 patch가 없다. 미확인 SDK leaf를 포함한 변경을 적용 가능한 제품 patch라고 포장하지 않았다.

추후 구현 단계의 L2는 다음 직접 사례로 제한한다. 새 프레임워크/전체 suite/CI는 요구하지 않는다.

| 대응 함수 | 한정 사례 |
|---|---|
| `PairGeometryPositivePath.initialize/capture` | 실제 retained pair의 10 trials가 local/global 중 정확히 하나를 결정하고 changed-driver/unchanged-control을 맞춘 경우 등록; shape/graph/asset/frame/다른 scene 또는 context mismatch는 calc 전에 거절. 새 capture는 setup grant가 아닌 새 request guard로 실행 |
| `MutationEvaluationRebind` | authenticated mutation full successor와 evaluation prestate exact 일치 + 실제 terminal + private capture이면 연결; 다른 origin/graph-only 변경/unknown terminal/unsigned request 사본이면 거절 |
| `SerializationPositivePath` | predeclared derived float32 규칙 범위의 차이는 허용, authored/unclassified 1 ULP도 거절; P0→P1→P2 누적 drift는 P0와 직접 비교해 거절; graph-only 변경과 Update 자체의 raw 변경 거절 |
| `load_checkpoint_copy` | 실제 private checkpoint file의 한 load가 만든 다른 scene instance를 provisional→linked identity로 이어 허용; 외부 scene dict/다른 file hash/다른 P0/옛 request permit은 거절 |

예정 명령 형식은 구현 시 해당 사례를 기존 관련 테스트 파일에 추가한 뒤 `pytest <해당_파일> -k '<새_사례_정확한_이름>' -q`다. 현재 존재하지 않는 test ID를 실행 명령처럼 확정하지 않는다. SDK 작업은 승인된 finite helper 한 번으로 제한하며, 성공 뒤 재확인 실행이나 일반 rig 확대 검증을 자동으로 추가하지 않는다.
