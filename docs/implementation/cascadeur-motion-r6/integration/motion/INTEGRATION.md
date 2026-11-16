# R6 native 모션 호출부 연결 — 적용 제안

기준 구현은 `7f1565a0ffad1595b9824cba25443bc581997fb6`이다. 이 디렉터리는 제품 경로별
변경 소스와 unified diff를 제공한다. 제품에 적용하거나 Cascadeur에서 실행한 결과가 아니다.
기존 R6 reference 파일을 수정하지 않고 그 호출부를 별도의 proposed source로 구체화했다.

## 실제로 연결한 범위

1. `setup.qualify_owned_pair_geometry`를 host/native setup 목록과 명시적인 semantic limits에
   넣었다. 두 객체·두 레이어·세 프레임·10회 mesh 계산·2회 evaluation·1회 driver mutation·
   2회 graph capture를 사용하는 별도 helper이며 기존 single cube helper를 변경하지 않는다.
   `RetainedProbe`가 원 탭과 두 저장 파일을 보존한 뒤 성공해야 private pair binding과
   geometry/evaluation/position/activation 어댑터가 등록된다.
2. helper가 실제 만든 scene 객체와 실제 original scene 객체, tab ID, object/layer ID,
   setup request ID, 초기 fixture projection digest를 결과에 담는다. 나중의 source/read/effect는
   해당 setup의 authenticated terminal receipt와 현재 승인된 finite continuation context를
   대조한다. 파일의 `qualified=true`나 wire hash로 native binding을 생성할 수 없다.
3. `scene.activate`는 원 탭과 해당 fixture 탭 사이에서만 동작한다. 최초 활성화 전에는 setup의
   초기 projection과 현재 fixture가 같아야 한다. native source는 두 문서와 탭 목록을 함께
   읽는다. 실제 tab 전환 뒤 원·대상 문서와 탭 목록이 유지되는지 읽고, 같은 request의 private
   activation record에 한해서만 runtime의 scene successor 검사를 통과시킨다. 다른 scene
   전환에 적용되는 예외를 만들지 않는다. 종료 시 원 탭 복원도 별도 명시된 effect다.
4. 한 owned mesh의 기존 키에 대한 명시적인 local position write를 Update callback으로
   수행한다. 실제 전후 snapshot을 보관하고 runtime이 실제 successor source와 terminal을
   만든 뒤 `stage_mutation`/`seal_mutation`을 호출한다. 다음 evaluation은 실제 callback의
   전후 상태를 `stage_evaluation`에 연결하며 terminal 뒤 `seal_evaluation`을 호출한다.
   기존 다른 scene의 어댑터는 code-owned router가 그대로 선택한다.
5. pair motion capture에는 두 객체 각각의 identity ownership을 발급한다. 공유 RigInfo나
   humanoid 의미를 만들어 넣지 않는다. geometry의 origin request를 evaluation request로
   바꾸지 않고 실제 mutation receipt → successor → evaluation 전후 → evaluation receipt →
   private motion capture → 현재 Update snapshot 순서로 `MutationEvaluationRebind`를 소비한다.
6. 기존 geometry exporter의 NPZ/window/manifest/terminal sealing을 유지하고 sample 부분을
   current request runner의 `capture_window`에 연결했다. source capture/preflight는 raw
   projection만 읽으며 Update를 숨기지 않는다. 실제 effect에서 현재 전체 graph와 dtype가
   setup contract에 맞는지 확인한 뒤 raw positions를 발급한다. effect를 `mixed`로 표현하고
   host effects, mirrored incident effects, native runtime, recipe channels/StageEffect/authorization
   역시 같은 분류를 사용하도록 맞췄다.
7. 기존 checkpoint의 P0, checkpoint save, working save, 실제 load, restored save를
   `native_serialization_binding`에 연결했다. 매 phase마다 현재 request에 한정한 guard와 새
   Update runner를 사용한다. 이미 save/load를 거친 장면에 과거 P0 source guard를 반복 적용하는
   대신, 실제 phase의 raw state를 고정해 관측 중 변경을 막고 원래 private P0와 비교한다.
   원 문서 보호·incident admission·실제 request·현재 scene identity를 계속 검사한다.
   restore는 `load_project_copy`를 한 번만 호출하고 그 반환 scene에 private lineage를 연결한다.

## 파일 연결

| 대상 | 구현 |
|---|---|
| 새 `native_update_capture.py` | R6 Update runner·immutable P0·private numeric policy 본문. transition의 두 snapshot 저장 공간을 effect 전에 예약한다. |
| 새 `native_owned_pair_geometry.py` | 실제 pair fixture, bounded sampling, authenticated mutation/evaluation rebind 본문. |
| 새 `native_owned_pair_binding.py` | setup issuer, 실제 private adapters, exact activation, source/continuation 결합, terminal finalizer. |
| 새 `native_serialization_binding.py` | current phase guard, fresh runner, private anchor 등록, 실제 load/clone 연결. |
| 새 `native_setup_dependencies.py` | authenticated setup sidecar의 pair dependency 선언을 claim/dispatch 전에 파일 bytes와 AST로만 확인. 설치 leaf를 import/실행하지 않음. |
| setup/admission/retention | 새 helper와 해당 상한만 추가한다. mirrored host/native 소스는 동일하다. |
| geometry/motion capture | native pair contract 조회, current-request sampling, private ownership, mutation-origin 소비. |
| native runtime | geometry mixed effect, exact private activation successor 승인, terminal 후 memory-only pair finalizer. |
| checkpoint/serialization | 기존 실제 save/load 위치에 phase observer를 넣는다. 원 P0를 사후 값으로 덮어쓰지 않는다. |
| recipe planning/authorization | geometry의 file+evaluation channels와 shared effect classifier를 맞춘다. 전체 recipe의 legacy continuation을 새로 구현한 것은 아니다. |

## Recovery continuation과 공유하는 정확한 계약

helper 결과는 다음 실제 값들을 포함한다. UUID나 hash 예시는 발명하지 않는다.

```text
profile, limits, mesh_ids[2], layer_ids[2], frames[0,1,2], retention,
fixture_scene{scene_instance_id,document_lineage_id}, fixture_tab_id,
original_scene{scene_instance_id,document_lineage_id}, original_tab_id,
setup_request_id, fixture_projection_digest, geometry_evidence_digest,
general_rig_supported=false
```

각 후속 request는 approved finite plan에 결합된 다음 context를 사용한다.

```text
execution_context.finite_continuation = {
  setup_request_id, setup_receipt_digest, fixture_scene, original_scene, plan_digest
}
```

위 context는 legacy incident 예외를 사용하는 경로에 필요하다. incident 예외가 없는 정상
domain에서는 기존 `assert_request_admission`이 모든 domain을 통과한 뒤 원 setup terminal을
private binding의 실제 setup ID로 조회하고, 기존 source/effect/confirmation 승인으로 진행한다.
정상 경로를 사용할 때 legacy plan 발급을 새로 요구하지 않는다. `incident_route`가 들어간
요청에는 정상 경로의 이 조건을 적용하지 않으며 exact finite context를 계속 검사한다.

모듈은 actual setup receipt와 위 field들을 다시 대조한다. 첫 activation dispatch에서 해당
private fixture를 정확한 `plan_digest`에 예약한다. 다른 plan은 같은 fixture의 초기 상태를
재사용할 수 없다. host의 원 incident 보존·manual 승인·request MAC·step 순서·mutation confirmation
경로는 recovery 통합 패치가 담당하며 이 모듈이 대신 발급하지 않는다.

Native operation 인자는 기존 형태를 유지한다.

- activation: `scene.activate`, `{"tab_id": 실제 fixture 또는 original tab ID}`.
- mutation: `animation.transform_set`, `{"ids":[실제 ID 하나],"position":[x,y,z],"frame":0|1|2,"space":"local"}`.
- evaluation: `animation.interpolation_refresh`, `{}`.
- motion capture: 기존 `system.observe_motion_capture` 인자와 실제 두 ID, 실제 evaluation successor source.
- geometry: 기존 `system.observe_geometry_capture` 인자. `origin_request_id`는 실제 원 mutation request로 유지한다.

## 실제 설치 자료가 없어서 구현하지 않은 하나의 SDK leaf

필수 제품 모듈 `cascadeur_side/cascadeur_complete/native_installed_update_facts.py`는 이 패치에
존재하지 않는다. 존재하지 않는 getter를 채우거나 진단용 graph 관측을 production contract로
승격하지 않았다. 이 파일의 구현에는 설치 build의 정확한 선언과 실제 bounded native 관측이
필요하다. 내부 project 함수의 계약은 다음과 같다.

```python
extract_installed_update_facts(model, update, updater) -> native_update_capture.UpdateFacts
```

결과에는 모든 projection data의 실제 owner/dtype/shape 및 닫힌 graph의 node/typed port/edge,
external link, producer와 data/setting dependency가 포함되어야 한다. 역할이 미확정인 data의
`authored_storage`는 `None`으로 남겨야 한다. 일반 이름이나 Animation mode로 derived 역할을
추정해서는 안 된다. `UpdateFacts` 객체의 형식 검사 자체가 이 설치 leaf의 completeness나
native 완료 의미를 증명하지 않는다.

선택적인 내부 project 함수 `serialization_role_specs(scene)`는 실제 producer 의미를 확인한
field에만 `RoleSpec`을 반환한다. 이 함수가 없으면 **exact-only** 비교다. installed leaf 자체가
없으면 serialization은 기존 exact comparator를 유지한다. 이미 typed path를 시작한 뒤 오류가
발생한 경우 exact fallback으로 오류를 숨기지 않는다. pair setup은 leaf import를 먼저 하므로
leaf가 없을 때 native `execute_request`가 먼저 `validate_unclaimed`로 확인한 exact setup
sidecar를 사용해 `native_setup_dependencies`의 정적 선언 확인을 실행한다. 이 확인은 설치 leaf를
import하지 않고, 계획에 고정된 SHA256·현재 loaded fingerprint·동기 함수 선언의 형태만
확인한다. admission claim, `dispatch_started`, setup workspace mkdir보다 앞에서 실패하므로
기존 `rejected_pre_dispatch` 경로로 끝난다. 이미 dispatch한 후의 SDK/import/실행 오류를
이 경로로 바꾸지 않는다. 실제 qualification은 이후 명시 setup에서 그대로 수행한다.

따라서 이 패치만 적용해도 Cascy float drift가 허용되거나 pair native 실행이 보장되는 것은
아니다. 설치 leaf와 실제 동작 확인을 다음 실행자가 충족해야 하는 구체적인 경계로 남겼다.
일반 rig, arbitrary mesh deformation, unbaking, 최종 animation 품질은 이 finite profile의
완료 범위에 포함되지 않는다.

## 적용·검증 범위

`motion-native-integration.patch`는 exact 7f 기준 독립 patch다. recovery patch와
`incident_setup.py`/`incident_admission.py`/`runtime.py` 등의 변경이 겹칠 수 있으므로 이 둘을
순서대로 무작정 적용하지 않는다. 상위 통합 patch에서 동일 기준의 변경을 합성한다.
원문·변경 bytes와 target path는 `source-metadata.json`에 기록했다.

이 작성 작업은 source 생성만 수행했다. Python import, SDK, PowerShell, pytest, E2E,
전체 build/CI는 실행하지 않았다. root가 최종 합성된 변경에 한해 AST와 `git apply --check`를
수행하고 실제 결과를 상위 verification 문서에 남긴다.
