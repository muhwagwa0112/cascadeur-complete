# R7: 일반 캐릭터의 회전·접촉·컨트롤러 구현안

기준: `feat/cascadeur-motion-r3@99b85163c4125a621ef7e2deeabe22270032c60b`.
이 문서는 **제품에 미적용인 코드 패치와 다음 native 구현 계약**이다. 현재 SDK에서
실행하지 않았고 일반 캐릭터 지원을 등록하지 않는다. 새 의존성, MCP tool, 공개 입력
schema, 설정은 이번 패치에 추가하지 않는다.

## 1. 이번 패치가 실제로 준비한 범위

`product-integration.patch`는 host 4개 파일을 바꾼다.

| 파일 | 구현 |
|---|---|
| `src/cascadeur_complete/skeletal_fk_controller.py` (신규) | 부모 closure와 관측 bind matrix를 가진 FK 후보의 local rotation을 `wxyz` quaternion으로 lowering한다. 부모부터 합성한 world pose를 목표와 비교하고, local translation이 달라지는 후보를 거절한다. |
| `src/cascadeur_complete/retarget_controller.py` | 기존 독립 position lowering을 유지하고, 코드가 소유하는 두 controller만 선택하는 router를 추가한다. |
| `src/cascadeur_complete/cleanup_workflow.py` | `plan_retarget()`의 기존 local rotation 후보 생성·key 확인·native 인코딩·write-scope 경로에 새 FK controller를 연결한다. |
| `src/cascadeur_complete/recipe_native_service.py` | 실제 bridge capability가 새 FK 계약을 발급한 경우에만 해당 preflight를 허용한다. host lowering·native controller observation·재검증은 기존 인증 흐름을 사용한다. |

새 host ID는 `observed-fk-local-rotation-v1`, native capability가 증명해야 할 domain은
`owned_fk_fixed_translation_existing_rotation_v1`이다. **ID 문자열을 profile에 적는 것만으로
실행할 수 없다.** 현재 `native_retarget_inputs.py`는 독립 position만 발급하므로 이 패치만
적용하면 새 FK recipe는 `RETARGET_TARGET_OBSERVATION_UNAVAILABLE`로 남는다.

### 새 FK lowering의 입력과 출력

입력은 기존 `controller_request()`의 네 필드를 그대로 사용한다.

```text
adapter_id: observed-fk-local-rotation-v1
profile: 기존 RigProfile의 canonical dict
targets.local[role]: {position_m: [3] 또는 [N,3], rotation_matrix: [3,3] 또는 [N,3,3]}
targets.world[role]: 동일한 pose 형식
planned_world: targets.world와 같은 계획
```

모든 role은 서로 다른 관측 stable ID에 연결되어야 한다. 부모도 이 role 집합에 포함하고,
하나의 root로 연결된 acyclic hierarchy여야 한다. 별도 dependency joint를 누락한 채 parent를
`None`으로 바꾸거나, 누락 rest를 현재 pose/identity로 채우지 않는다. 이 첫 adapter는
mapped joint 전체가 해당 writer의 writable closure인 경우를 대상으로 한다. mesh는 별도
quality scope로 유지하며 skin vertex를 joint writer 대상으로 취급하지 않는다.

출력은 기존 cleanup 회전 후보 형식이다.

```text
{rotation_wxyz: {native_object_id: [N,4]}, space: "local"}
```

`wxyz` 순서를 명시하고 기존 `hemisphere_continuous()`로 동등 quaternion의 부호 점프를
정리한다. 4×4 rest의 회전 부분은 proper orthogonal matrix여야 한다. scale/shear가 섞인
rest를 회전으로 정규화해서 통과시키지 않는다. root를 포함한 모든 local translation은
시간에 따라 고정되어야 하며, 그 값이 **실제 native translation과 같다**는 최종 확인은
아래 native attestor가 맡는다. host 수학만으로 이 사실을 발급하지 않는다.

local pose를 부모 순서로 `forward_kinematics()`에 전달해 재귀 깊이가 rig 깊이에 따라
늘지 않게 한다. 합성한 world position/rotation과 계획의 일치 허용값 `1e-8`은 host 수학의
정합성 확인에만 사용한다. 최종 모션 품질 허용값이나 native 저장 허용 정책을 대신하지 않는다.
요청 bytes 상한은 기존 native retarget reader와 같은 2 MiB다.

단위와 축은 기존 `MotionContext`를 유지한다. `retarget_pose()`와 이 lowering은 solver의
미터·canonical basis에서 계산한다. bind rest는 관측한 scene-local raw matrix로 보관한다.
`CleanupWorkflow._scene_quaternions()`와 `_eulers_from_solver()`가 쓸 때 한 번만 native
basis로 변환한다. quaternion을 Euler로 표시한 후보에는 `expected_quaternion_wxyz`를
유지하고 native adapter가 실제 SDK 변환 결과를 비교한 뒤에만 쓰기를 허용해야 한다.

## 2. 아직 필요한 native FK leaf — 함수별 구현 명세

아래 이름 중 `native_fk_rotation.py`와 `_read_fk_*`는 **신규 코드 제안**이다. 실제 SDK
callable 이름이 아니며, 존재하는 설치 API인 것처럼 사용하지 않는다. 기존 `NativeSceneAdapter`,
`NativeIndependentPositionAdapter`의 실제 수명주기와 private observation 흐름에 맞춘다.

### C1. 관측 대상과 driver closure

`native_fk_rotation.inspect_fk_domain(scene, source, profile, context)`를 구현한다.

입력: 현재 source binding, 실제 active scene, 위 FK profile, 정확한 frame/time grid.
출력: 호출자가 재작성할 수 없는 process-private record 및 read-only 요약. record에는 다음을
**실제로 읽은 값**으로 보존한다.

- `RigInfo` owner와 ordered joint stable IDs, `Basic.parent`의 완전한 closure.
- `native_bind_rest.read_native_bind_rest()`의 원 inverse-bind matrices, ordered linked
  objects, bind-shape 정보, scene-local rest, mesh 소유 범위. graph에서 부모 역할을 하는
  transform이 skeleton 밖에 있으면 closure를 확장해 정확히 관측하거나 이 domain을 거절한다.
- 각 joint의 `Transform.local_rotation` DataId와 native dtype, layer/key locator,
  원 local translation과 scale의 전체 영향 구간 값, animation/interpolation mode.
- 실제 Update graph의 입력/출력 dependency, 일반 controller/constraint/additive/cycle
  존재 여부, write 뒤에 바뀔 수 있는 derived global transform과 skinning 출력 범위.
- 현재 source digest, build, epoch, loaded fingerprint, observation request/terminal의 연결.

이 첫 domain은 scale writer를 포함하지 않는다. native local/parent scale이 전체 영향 구간에서
실제로 unit scale인지 확인하고, animated scale·비균일 scale·shear가 있으면 이 adapter로
실행하지 않는다. bind matrix만 rigid하다는 이유로 현재 animated scale을 identity로 간주하지 않는다.

`native_recipe_target._read()`는 이미 ownership·Basic parent·native inverse bind와 declared
profile의 일치를 확인한다. 이 구조 증명을 재사용하되 그것을 writer 권한으로 승격하지 않는다.
`native_motion_inputs.read_motion_inputs()`가 읽는 typed behaviour inventory와
`native_update_capture`의 실제 graph를 사용한다. controller/constraint의 부재를 이름 검색이나
property 일부의 부재로 결론 내리지 않는다. 관측이 불완전하면 native leaf가 아직 미지원인 것이다.

### C2. 기존 회전 키 writer와 완료

`NativeFKRotationAdapter(NativeSceneAdapter)`에 기존 adapter와 같은 메서드를 구현한다.

| 메서드 | 구체 동작 |
|---|---|
| `_inspect(scene, operation, arguments)` | `animation.rotation_keys_set`, `space=local`, 실제 기존 layer/frame key만 허용. 실제 rotation encoding과 quaternion roundtrip, writable joint 범위, key mode·tangent·영향 구간을 확인. |
| `required_scope(scene, scope)` / `capture(scene, scope)` | 모든 writable joint와 parent/derived/mesh dependency를 포함하는 실제 scope와 원 projection 발급. 다른 캐릭터·비대상 controller도 변할 수 있다면 모델이 incomplete이므로 거절. |
| `execute(scene, arguments, request)` | 기존 request/confirmation/admission/once-only 경로 안에서 실행. 원본 projection과 checkpoint를 유지하고 실제 native write 전에 시작 경계를 기록. 같은 callback에서 필요한 native Update를 실행하고 반환값과 실제 post-projection을 보관. |
| `validate_failure_observation(...)` / `prepare_recovery_binding(...)` | 실제 쓰기 경계와 post-source를 유지한 실패만 기존 recovery 계약으로 연결. host의 `except`나 현재 pose만으로 partial-write evidence를 만들지 않음. |

SDK에 quaternion setter가 있는지, Euler setter의 축순서·intrinsic/extrinsic·단위가 무엇인지,
DataEditor 쓰기가 해당 rig의 authored rotation channel을 변경하는지는 현재 자료만으로
확정하지 않는다. 설치 source/typed SDK와 실제 동작에서 확인한 **하나의 구체 경로**를 구현한다.
후보 인코딩→실제 SDK quaternion 변환을 비교하고, derived global rotation을 direct write하여
graph를 우회하지 않는다.

완료 record의 필수 연결은 원 request ID → actual write invocation → same-callback Update
반환 → 현재 source/post-source → 원 terminal이다. runtime이 성공 terminal을 보존한 뒤
기존 evaluation/capture를 이어간다. 저장 성공, callback 호출, `ok=True` 같은 하나의 값만으로
전체 동작 완료를 발급하지 않는다. 이미 처리한 request는 원 receipt만 반환한다.

### C3. Native retarget input과 controller attestation

기존 `native_retarget_inputs._read_inputs()`/`_read_controllers()`에서 code-owned adapter ID로
분기해 `_read_fk_inputs()`/`_read_fk_controllers()`를 호출한다. 기존 `_INPUTS`, `_CONTROLLERS`
private ledger와 `verify_observation()` 재관측을 유지한다. 새 MCP operation은 필요 없다.

`_read_fk_inputs()`는 `native_recipe_target`의 구조와 C1의 실제 writer를 모두 확인한 뒤
기존 형식의 `target_rest`, `target_parents`, `axis_alignment`, `root_basis`,
`target_root_anchor_m`, qualification/source/profile/context digests를 발급한다. canonical
rest는 raw native rest에 선언된 basis/length scale을 정확히 한 번 적용한다. semantic mapping과
conversion policy는 선언임을 유지한다. 실제 anatomical role로 관측했다고 표시하지 않는다.

`_read_fk_controllers()`는 같은 private input record를 다시 확인하고 다음을 비교한다.

1. host가 만든 local rotation을 실제 writer의 ordered joint/DataId에 정확히 대응시킨다.
2. 계획의 **모든 local translation과 parent scale이 원 native 채널과 동일**한지 확인한다.
   이 첫 domain은 root 이동도 쓰지 않으므로 다른 root 궤적을 가진 후보를 승인하면 안 된다.
3. 부모를 순서대로 합성한 world pose와 요청의 planned world를 비교한다. host가 보낸
   local/world 한 쌍만 서로 일치한다고 판단하는 것으로 끝내지 않는다.
4. 실제 key closure, writer dtype/encoding와 변경되지 않을 channel의 범위를 다시 확인한다.
5. 기존 `controller_targets` 형식으로 exact output digest를 보존하고 process-private ledger에
   저장한다. 호출자가 넘긴 digest나 성공 주장으로 이 record를 생성하지 않는다.

`qualified_capability()`는 C1–C3가 현재 build/epoch에서 확인된 **실제 instance**에 대해서만
아래 read-only descriptor를 반환한다. 이 descriptor는 권한이 아니고 실제 target은 다시 관측한다.

```json
{
  "adapter_id": "observed-fk-local-rotation-v1",
  "rig_contract": "owned_fk_fixed_translation_existing_rotation_v1",
  "channels": ["rotation"],
  "space": "local",
  "existing_keys_only": true,
  "private_target_observation_required": true,
  "target_scope": "observed",
  "object_ids": ["실제 관측한 대상 ID"]
}
```

실제 qualification 기록·operation 등록·재시작 수명은 기존 framework를 이용한다.
추가 승인 시스템이나 반복 quality gate를 신설하지 않는다.

## 3. FK 이후 남은 목표 — 실제 함수와 데이터 연결

### C4. Root translation과 skeleton rotation의 결합

현재 recipe의 `host_channel`과 cleanup은 position/rotation 중 하나만 허용한다. 따라서
두 별도 commit을 하나의 atomic 작업이라고 부를 수 없다. mixed pose를 지원하려면 다음
**공개 schema/효과 변경을 별도 구현 변경으로 제안하고 승인받아야 한다**. 이 패치에는 적용하지 않았다.

- `recipe_models`의 motion channel에 coupled pose를 명시하고, plan에 exact per-channel
  write scope·같은 checkpoint·영향 구간을 선언한다. 기존 rotation-only/position-only 입력은 유지한다.
- `NativeCharacterPoseAdapter.prepare`의 입력은 `root_position_writes`,
  `joint_rotation_writes`, 실제 channel/DataId/layer/frame locator, 원 source/intent/checkpoint.
  출력은 같은 native transaction의 전체 expected scope와 one-use 준비 record다.
- `execute`는 root와 회전을 같은 native transaction에서 적용한다. 설치 SDK에 그런 보장이
  없으면 성공 시퀀스를 둘로 나누고 두 번째 실패를 **partial-write**로 유지한다. atomic이라고
  보고하거나 실패한 부분을 다시 호출하지 않는다.
- `CleanupWorkflow.plan_retarget()`는 기존 `retarget_pose()`의 `local/world`를 사용한다.
  FK 회전과 root position 후보를 같은 계획에 넣고, native 평가 후 전체 world pose를 비교한다.
  위치는 `positions_to_scene()`, 회전은 `_scene_quaternions()`로 각각 한 번만 변환한다.
- `RecipeRunner`의 actual readback은 두 channel 모두 확인해야 한다. 한 channel이 성공하고
  다른 channel이 미확정이면 단계 전체를 성공 처리하지 않는다. 기존 recovery가 실제 실패
  attestation과 post-source를 소비하도록 연결한다.

### C5. 발 접촉·무릎·팔의 실제 controller lowering

`motion_solvers.solve_contacts_v2(batch, rig, supports, contacts, intent, limits)`는 이미
전체 시간 구간을 함께 풀고 ankle/knee 및 heel/ball/toe의 **world position 목표**를 반환한다.
`solve_arm_clearance_v2()`도 목표를 계산한다. 이를 일반 rig의 joint position에 그대로 쓰면
bone rest와 controller 관계를 바꿀 수 있다. 현재 feet 경로의 `fit_keys(position goals, ...)`
직결은 실제 해당 position driver가 자격을 가진 경우에만 유지한다.

신규 `lower_contact_controllers(goals, original_capture, observed_rig, writer_observation)`의
입력과 처리 순서를 다음처럼 고정한다.

1. role은 기존 solver의 `left.hip`, `left.knee`, `left.ankle`, `right.*`, contact role을
   정확한 관측 ID에 대응시킨다. support pose와 anchor는 같은 time grid의 실제 관측이다.
2. FK skeleton이면 실제 bind 길이와 parent rotation으로 hip/knee/end 목표를 local rotation에
   변환한다. 기존 `solve_two_bone()`의 pole/reach 결과를 사용하고 bone translation을 바꾸지 않는다.
   180도/축이 정해지지 않는 경우 pole 또는 관측된 joint axis가 없으면 거절한다.
3. baseline rotation의 twist를 보존하면서 필요한 swing을 적용하고, 적용한 FK로 world joint
   목표를 다시 계산한다. joint limit/수정 envelope/lock를 넘으면 후보를 채택하지 않는다.
4. 컨트롤러 rig이면 actual TechnicalLinks/constraint graph가 증명한 control channel로 변환한다.
   native IK가 담당하는 output joint를 직접 쓰지 않는다. coupled output closure를 C4의 같은
   pose 계획에 넣는다. 알려지지 않은 solver node와 cyclic controller는 별도 native adapter가 필요하다.
5. output은 `local rotation` 또는 **실제 writable control position/rotation**과 predicted world,
   변환에 사용한 native observation digest다. solver의 `host_model_pass`는 실제 품질 결과가 아니다.

feet correction은 `IntentConstraints.action=repair`, `root_policy=preserve`와 기존 contact schedule을
그대로 따른다. retarget가 만든 새 motion을 baseline으로 삼아 원본 보존 오차를 0으로 만들면 안 된다.
원 입력 motion, retarget의 명시 목표, 수정 전 capture를 서로 구분한 채 기존 quality 계산에 전달한다.

### C6. 키 사이의 회전과 장시간 클립

첫 FK 단계는 이미 존재하는 키만 사용한다. `plan_retarget()`의 rotation 경로는 변경된 sample이
실제 key가 아니면 `KEY_LAYOUT_INSUFFICIENT`로 끝난다. 이것을 없애려고 새 키를 몰래 만들지 않는다.

후속 `build_rotation_key_model(observed_layout, evaluated_capture, native_rotation_probe)`는
그 build의 실제 quaternion interpolation과 tangent/mode 영향 구간을 관측해야 한다.
`fit_rotation_keys(goal_wxyz, original, model, locks, limits)`는 SO(3) log tangent의 오차를 풀고
현재 key values를 함께 보존한다. insertion이 필요하면 기존 `plan_key_insertion()` 계약을
**회전 채널의 실제 locator/예측/완료 관측**으로 확장해야 하며 position insertion의 자격을 복사하지 않는다.

긴 clip은 시간창마다 독립적으로 수정해 경계를 끊지 않는다. 기존 sparse resource 추정과
key influence 범위를 이용하고, window 경계에는 고정 공유 key와 실제 interpolation 영향 범위를
포함한다. 한정된 key/행렬 예산 안에서 계획을 분할하되 원 request를 재실행하지 않는다.
구현 전 전체 benchmark나 새 성능 gate를 요구하지 않는다.

### C7. 실제 모션·mesh 품질과 납품 연결

호출 순서는 기존 경로를 유지한다.

```text
original authenticated capture
→ solve / controller lowering / intent envelope
→ one-use prepare / commit / original terminal
→ actual evaluation
→ full required local/global motion + general-rig skin geometry capture
→ evaluate_actual_quality(original, actual, rig, intent, policy, ...)
→ delivery artifact seal / consumer roundtrip
```

`motion_quality.required_motion_metrics()`가 이미 요구하는 root 보존, bone 길이, 회전 수정,
비대상 위치·회전, key-pose lock, contact gap/drift를 유지한다. mesh가 필수이면 실제 skinning
geometry에서 penetration/intersection을 읽어야 한다. 두 mesh·세 frame fixture의 calibration을
일반 skin rig에 적용하지 않는다. native graph/ordered skin weights·inverse binds·bind shape·실제
evaluation origin에 결합한 general-rig geometry adapter가 별도로 필요하다.

`evaluate_actual_quality()`에는 원 capture와 실제 post-evaluation capture를 전달하고,
support tracks와 geometry manifest를 동일한 context/motion capture digest에 결합한다.
변경한 joint만 읽고 다른 joint/controller/mesh의 변화를 누락하지 않는다. 샘플 frame pass를
프레임 사이 전체 충돌 자유로 보고하지 않는다. 새 허용 수치나 필수 metric 생략은 이 문서가
정하지 않으며 사용자의 실제 clip intent와 기존 품질 정책을 사용한다.

## 4. 완료 조건과 현재 미구현 경계

이번 패치의 완료 조건은 host FK 후보 생성과 현재 authenticated controller 호출부 연결이다.
원격 문서에 실앱 PASS를 새로 쓰거나 general rig 지원으로 표시하지 않는다.

native 구현을 적용할 때 필요한 직접 확인은 **실제로 변경한 동작**으로 제한한다. 해당 rig에서
기존 회전 키 변경→현재 Update/evaluation→local/global 및 비대상 readback→checkpoint를
한 번 연결해 확인한다. 이후 contact나 coupled writer를 구현하는 변경에서는 그 추가 동작만
직접 확인한다. 전체 테스트·CI·반복 감사는 이 계획의 요구사항이 아니다.

아직 구현되지 않은 native leaf는 C1–C3이며, 일반 root motion·접촉·controller·회전 보간의
추가 구현은 C4–C6이다. 일반 geometry와 최종 consumer의 연결은 C7 및 delivery 문서와 함께
완성해야 한다. 기존 R6의 실제 fixture 성공은 그대로 인정하며 다시 시험하지 않는다.

## 근거 코드

- [기준 retarget 입력/증명](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_retarget_inputs.py)
- [실제 ownership·parent·inverse-bind 관측](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_recipe_target.py)
- [기존 host retarget 계획](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/cleanup_workflow.py)
- [기존 접촉·팔 solver](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/motion_solvers.py)
- [실제 motion·mesh 품질 계약](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/motion_quality.py)
