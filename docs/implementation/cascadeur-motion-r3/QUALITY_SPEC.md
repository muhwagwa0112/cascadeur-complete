# 모션 품질 수정 명세 — 구현 전 설계

기준: `muhwagwa0112/cascadeur-complete` main `82b350cad4deda2ff5df288f46764a899115252d`; PR 8 head `1bb447898e8ced16b6931b72cfeb0f563127f746`. 읽은 snapshot: `/workspace/scratch/fc42dd265c37/cascadeur-review`. 이 문서의 줄 번호는 main snapshot 기준이다. PR 8의 cleanup `_read` 변경은 통신 경로 변경이며 아래 수학적 결함의 해결로 계산하지 않는다.

이 문서는 제품 코드 변경·실행 검증이 아닌 구현 명세다. 함수/데이터 계약 중 새 항목은 **제안하는 host 코드**이며, 같은 이름의 Cascadeur API가 존재한다는 뜻이 아니다. 실제 앱에서 확인하지 못한 기능은 지원 조건과 실패 결과를 명시한다. 최종 설계 PASS는 실제 애니메이션의 완벽함을 보증하지 않는다.

## 1. 변경이 필요한 코드 근거

| ID | 현재 근거 | 수정해야 할 동작 |
|---|---|---|
| Q01 | `cleanup_workflow.py:_points` 146–156, `prepare_feet` 191–195; `motion_cleanup.py:apply_offsets` 356–375 | 선택 캐릭터 밖 이름이 다른 Point까지 body offset을 받음. 이름 패턴은 소유권 근거가 아님. |
| Q02 | `motion_cleanup.py:solve_arm_offsets` 849–859, 937–948; `cleanup_workflow.py:prepare_arm_clearance` 463–465 | QP 실패·정체·제약 미발견이 zero offset으로 끝나고 `ok=True`가 될 수 있음. |
| Q03 | `motion_cleanup.py` 7–8, `ContactParams` 56–65, `_foot_motion` 144–156, `WristParams.sigma` 994, `pulse_envelope` 1497–1514 | cm/Y-up/프레임 간격 가정. 속도·평활·펄스가 FPS나 비균일 키 간격에 따라 달라짐. |
| Q04 | `cleanup_workflow.py:prepare_feet` 176, 185–187; `motion_cleanup.py:step_pass` 379–411 | 기본 `steps=True`가 드래그를 보행으로 바꾸고 root 누적 이동을 취소함. 원래 안무·의도 보존 조건이 없음. |
| Q05 | `motion_cleanup.py:floors` 72–74, `contact_weights` 196–208, `solve_contacts` 226–230, 287–298 | percentile 높이는 계단·경사·이동 지지면을 표현하지 못함. 원본 hip–ankle 최대 거리는 실제 다리 길이/관절 한계가 아님. |
| Q06 | `cleanup_workflow.py:prepare_feet` 188–207, `prepare_arm_clearance` 428–441, `prepare_fingers` 327–345; `motion_cleanup.py:linear_interpolation` 967–979 | dense 수정 목표를 기존 키에만 기록하고 선형 예측을 실제 보간 결과처럼 보고함. 팔은 모든 컨트롤러 키의 교집합만 사용함. |
| Q07 | `cleanup_workflow.py` 227, 470, 628; `handlers/animation.py:position_keys_set` 395–401, 465–470 | 10 cm 허용오차 및 helper 전면 면제로 실제 접촉/충돌 실패를 가릴 수 있음. |
| Q08 | `motion_cleanup.py:finger_cleanup` 469–503, `finger_stats` 521–532, `_median_rotation` 1019–1025, `_align` 1028–1036, `wrist_summary` 1225; `cleanup_workflow.py:sample` 113–142 | 반회전 부근 quaternion 부호/중앙값, 단일 프레임 빈 diff, 정반대 벡터, 누락 샘플의 0 초기화 처리 결함. |
| Q09 | `motion_cleanup.py:two_bone_elbow` 1433–1443, `settle_resting_hand` 1479–1489 | 목표 거리만 clamp하고 실제 wrist는 그대로 두어 두 뼈 길이 동시 만족 불가. 퇴화 bend plane도 처리하지 않음. |
| Q10 | `handlers/mesh.py` 67–74; `motion_cleanup.py:MeshSurface.__init__` 717, `hand_body_clearance` 1373 | unweighted vertex의 dominant=-1이 마지막 joint로 해석됨. |
| Q11 | `motion_cleanup.py:MeshSurface` 703–775, `hand_body_clearance` 1393–1405 | nearest vertex+normal은 실제 triangle surface 거리/내외 판정이 아니며 깊은 침투가 `reach` 때문에 clear가 됨. |
| Q12 | `cleanup_workflow.py:prepare_arm_clearance` 433–442; `motion_cleanup.py:MeshSurface` 706–710 | 두 팔을 각각 원본 상대 팔에 대해 풀어 이동 후 양팔 상호충돌을 놓침. vertex 이동 모델도 실제 skinning과 동일하다는 근거 없음. |
| Q13 | `motion_cleanup.py:pose_hand` 1293–1355, `_solve_thumb` 1235–1288, `settle_resting_hand` 1449–1478 | 전 손가락을 open/fist 한 값으로 대체해 제스처 의미 손실. thumb 최적화의 성공·예산·잔여 침투 판정 없음. 근접한 손을 의도된 접촉으로 단정. |
| Q14 | `FootRig` 23–34, `finger_parts` 425, `cleanup_workflow.py:_arm_points` 361–365, `_hand_track` 481–502 | QRT 이름/양손 존재/단일 mesh를 강제. 리깅 매핑과 제어기 의미가 명시되지 않음. |
| Q15 | `handlers/mesh.py:MAX_MESH_FRAMES` 7, 48–49; `handlers/animation.py` 257, 280–281, 404–405; `cleanup_workflow.py:_arm_mesh` 383–388 | 2000 frame/60000 write를 넘는 클립 처리 없음. 구간별 독립 solve로 단순 해소하면 경계가 달라짐. |
| Q16 | `handlers/animation.py:_section_row` 10–29, `rotation_from_euler_xyz` 240–254; `runtime.py:_read_transforms` 485–513, `timeline.get` 1066–1076 | 현재 read는 local/global 및 보간 모드만 제공. FPS/unit/up, 실제 Bezier 계수, target-space 리타겟 evaluator는 이 경로에서 확인되지 않음. Euler converter가 없을 때 다른 convention으로 fallback함. |

현재 테스트는 정상 synthetic 장면의 개선을 확인한다. 예: `tests/test_motion_cleanup.py` 54–66은 원본 최대 reach를 올바른 기준으로 가정하고, 175–187은 sparse 키의 실제 앱 보간을 재평가하지 않으며, 406–412는 reachable wrist 한 사례뿐이다. 아래 수정 확인은 이 구체적 누락을 겨냥한다.

## 2. 공통 계약: 좌표, 시간, 소유권, 결과

### 2.1 Host 데이터형

`motion_cleanup.py`에 순수 dataclass/helper로 둔다. 공개 MCP schema·기존 prepared envelope 변경은 root 통합 명세의 승인·호환 계획을 따른다.

```python
@dataclass(frozen=True)
class MotionContext:
    frames: np.ndarray              # int64[N], 원래 frame ids, strictly increasing
    time_s: np.ndarray              # float64[N], strictly increasing (N=1 허용)
    time_source: str                # fps | explicit
    fps_num: int                    # 양수, time_s와 일치
    fps_den: int                    # 양수
    metres_per_scene_unit: float    # 유한, >0
    scene_to_solver_basis: np.ndarray  # (3,3), C.T@C=I, det(C)=+1
    metadata_provenance: dict       # actual adapter read 또는 명시적 rig/profile 입력

@dataclass(frozen=True)
class RigProfile:
    profile_id: str
    character_id: str
    role_ids: dict[str, str]         # semantic role -> stable object id; 이름은 진단용
    writable_ids: frozenset[str]
    derived_ids: frozenset[str]
    dependency_ids: frozenset[str]
    parent_ids: dict[str, str | None]
    rest_local_transforms: dict
    joint_axes: dict                # declared local hinge / swing-twist axes
    joint_limits_rad: dict          # optional; 미제공 제한을 보편 해부학으로 추측하지 않음
    bone_lengths_m: dict
    mesh_ids: tuple[str, ...]
    controller_adapter_id: str

@dataclass(frozen=True)
class SampleBatch:
    context: MotionContext
    object_ids: tuple[str, ...]
    space: str                       # local | global; host target-space goal은 별도 타입
    position_m: dict[str, np.ndarray]    # 요청 N행만 저장
    rotation_wxyz: dict[str, np.ndarray]
    channel_valid: dict[str, np.ndarray]
    source_binding: SourceBinding      # 안정성 명세의 authoritative binding

@dataclass
class SolverResult:
    status: str  # no_change | candidate | failed | unsupported | cancelled
    reason_codes: list[str]
    values: dict
    report: dict

@dataclass(frozen=True)
class IntentConstraints:
    action: str                    # repair | declared styling | retarget
    editable_frames: tuple[int, int]
    root_policy: str               # preserve | explicit mapped trajectory
    contacts: tuple[ContactSegment, ...]
    locked_roles_frames: dict
    key_pose_locks: dict
    preserve_timing: bool          # default True
    allow_key_insertion: bool      # default False
    allow_interpolation_change: bool  # default False
    correction_envelope: dict     # roles/channels별 최대 변경량과 승인된 재시도 범위

@dataclass(frozen=True)
class QualityPolicy:
    profile_id: str
    profile_revision: str
    calibration_status: str        # proposed | host_checked | runtime_calibrated
    required_metrics: tuple[str, ...]
    limits_si: dict
    coverage: str                  # sampled_frames | verified_continuous
    collision_semantics: str       # volume | oriented_patch | unsigned_surface
    permitted_contact_allowances: dict
    required_export_roundtrip: bool
```


`SourceBinding`은 안정성 명세의 객체를 사용한다. `CaptureManifest`에는 context/profile digest, requested/received id×frame×channel coverage, sample digest를 넣는다. 독자적 scene freshness 체계를 추가하지 않는다. content generation API를 추측하지 않고 scope digest 검증이 필요하면 안정성 명세의 한 UI-thread dispatch 비교 절차를 사용한다.

### 2.2 단위와 시간

- 모든 host 계산은 m, s, rad, float64. bridge 경계에서만 scene length와 Euler XYZ radians로 변환한다. 사람용 cm/deg 표시는 마지막 단계에서만 반올림한다. 판정은 반올림 전 값으로 한다.
- 모든 world/local 벡터를 같은 기저로 표현하는 좌표 **표현 변경**으로 정의한다: `p_solver = s*C*p_scene`, `R_solver = C*R_scene*C.T`. local bone vector/rest transform에도 같은 C를 적용한다. 단순히 물체를 회전시키는 연산과 혼용하지 않는다. 역변환은 `p_scene=C.T*p_solver/s`, `R_scene=C.T*R_solver*C`.
- solver 입력 `det(C)=-1`, shear, 미확인 handedness는 `UNSUPPORTED_COORDINATE_SYSTEM`. 비균일 ancestor scale은 translation/rotation 리타겟을 혼합하지 않고 `UNSUPPORTED_NONRIGID_PARENT`로 막는다. 미러링은 별도 명시 profile 없이는 실행하지 않는다. export/import의 **좌표 표현**이 반사 기저인 경우에는 명시 ExportProfile의 verified decode adapter가 position과 normal의 signed basis 변환, det<0일 때 triangle winding 반전, `R'=M*R*M.T`를 수행해 canonical right-handed geometry로 먼저 변환한다. 그 후 MotionContext에는 det=+1 basis만 들어간다. 이 표현 변경에서 semantic Left/Right를 바꾸거나 캐릭터 동작을 미러링하지 않는다. exact mapping 미확인시 unsupported다.
- `time_s[i]=(frames[i]-frames[0])*fps_den/fps_num`. 별도 timestamp를 지원할 때는 위 식을 강제하지 않는 별도 `time_source=explicit` 계약을 사용하고 timestamp coverage를 fingerprint에 포함한다. frame 번호를 재배치하거나 자동 retime하지 않는다.
- `timeline.get` 현재 반환값에는 FPS가 없다. 확인된 앱 accessor가 생기기 전에는 명시적 MotionContext/검증된 scene profile에서 공급한다. 30/60 FPS, cm, Y-up을 조용히 추정하지 않는다. 필요한 metadata 미확인시 분석은 raw-unit로 한정하고 prepare는 `MISSING_CLIP_METADATA`.
- 비균일 시간의 1차 미분: `v_i=(x[i+1]-x[i])/dt_i`; 2차 미분: `a_i=2*(v_i-v[i-1])/(dt_i+dt[i-1])`. least squares 적분 가중은 각각 `sqrt(dt_i)`, `sqrt((dt_i+dt[i-1])/2)`. 이를 sparse D1/D2로 만들어 모든 평활·속도 비용에 재사용한다. 기존 `spacing=median(diff(keys))` 근사는 제거한다.
- gaussian은 `sigma_s`와 `exp(-0.5*((t_j-t_i)/sigma_s)^2)`를 사용하고 4σ 밖은 제외한다. 실제 간격이 균일할 때만 `sigma_frames=sigma_s/dt` 최적화를 허용한다. window·minimum span·gap·ramp·attack·release도 초로 정의한다.
- default tuning은 물리 단위와 profile scale에서 한 번 확정한다. 기존 `*_cm` 인수는 `/100`, `*_per_frame` 인수는 해당 입력 FPS를 곱해 변환한 **legacy tuning**으로 표시한다. 생산 workflow의 새 기본값은 seconds 기반이며 frame 기본값을 FPS마다 재해석하지 않는다.

### 2.3 Scope와 샘플 유효성

```python
resolve_rig_profile(objects, requested_ids, profile) -> RigProfile
validate_samples(batch, required_channels) -> None
```

`requested_ids=None`일 때에도 전체 Point가 write scope가 되지 않는다. 기존 QRT 자동 탐지는 role 이름을 유일하게 찾는 데만 사용한다. parent/rig membership을 실제로 확인할 수 있으면 단일 character 소유권을 확인하고, 현재 read 경로로 확인할 수 없으면 명시적 profile의 stable ids가 필요하다. 부분 object_ids로 캐릭터를 지정한 경우 누락 driver를 자동으로 write scope에 추가하지 않는다. dependency 확대는 읽기만 가능하며 write set은 `writable_ids`의 부분집합이어야 한다.

샘플은 compact requested frame array를 갖는다. 누락 위치/회전 행을 0 또는 identity로 대체하지 않는다. frame마다 정확히 한 번의 id/space/frame 응답을 확인하고 missing/duplicate/unexpected/nonfinite/channel mismatch를 `INCOMPLETE_CAPTURE`로 반환한다. Point의 rotation null은 position-only 요청이면 정상이며 finger Box rotation 요구에는 오류다. topology/weights의 row 수와 vertex 수도 일치해야 한다.

N=0은 invalid. N=1의 정적 거리·각도 분석은 가능하며 velocity/acceleration은 `not_applicable`이다. 단일 프레임의 quaternion cleanup은 원본 반환 또는 명시한 static constraint만 적용한다. N=1/2에 shape가 음수인 sparse D2나 빈 `.max()`를 만들지 않는다. `linear_interpolation`은 key 0개 오류, key 1개 상수, key 중복 오류, 범위 밖은 명시적 boundary policy를 사용한다.

### 2.4 성공/실패 상태

- `no_change`: 요청한 metric의 baseline capture가 완전하고 모든 required constraint가 이미 만족되며 intent가 변경을 요구하지 않을 때만. `writes=[]` 자체는 근거가 아니다.
- `candidate`: 유한 solver 결과, declared scope/intent/host constraints를 만족한 후보. `host_model_pass=true`와 `runtime_quality=unverified`를 함께 표시한다.
- `failed`: QP/optimizer failure, nonfinite solution, infeasible constraint, budget exhausted, residual 불합격. 쓰기를 준비하지 않으며 `ok=False`.
- `unsupported`: metadata/rig/evaluator/geometry 등 필수 의미를 관측할 수 없음. 0 침투·성공으로 대체하지 않는다.
- `cancelled`: 취소 플래그/예산 만료. 부분 결과를 성공으로 내지 않는다.

OSQP `solved`와 `solved inaccurate`는 그대로 성공이 아니다. primal/dual residual, 원래 비선형 뼈 길이/충돌/접촉 제약, 유한성을 직접 계산해 문턱 통과시만 candidate. status 문자열과 위반 metric을 보존한다. 정체는 `SOLVE_STALLED`; iteration 소진은 `SOLVE_BUDGET_EXHAUSTED`. 마지막보다 나은 feasible iterate가 있으면 그 iterate만 사용하고 검증치도 그 값에서 다시 산출한다. all-required-pass 이전에 `ok=True`로 승격하지 않는다.

공통 `validate_policy`는 모든 수치의 finite, sigma/duration ≥0, attack/release >0, trust region/물리 scale >0, iteration 및 per-frame constraint budget 양의 정수, `soft_limit`의 `0≤knee<limit`, normalized `fixed_closure∈[0,1]`, frame interval의 범위/순서/유일성을 확인한다. 잘못된 입력을 clip해서 다른 요청으로 수행하지 않는다. 이 오류는 `INVALID_POLICY`이며 쓰기 준비 이전에 종료한다. 시간 예산과 취소는 자동화 worker 계약으로 집행하며 확인되지 않은 OSQP callback API를 발명하지 않는다.

## 3. 접촉 보존과 이동 지지면

```python
@dataclass(frozen=True)
class SupportTrack:
    support_id: str
    origin_m: np.ndarray          # [N,3]
    rotation_wxyz: np.ndarray     # [N,4], support-local -> canonical world
    geometry: object             # plane 또는 verified triangle surface
    deforming_vertices_m: object | None

@dataclass(frozen=True)
class ContactSegment:
    role: str                    # heel/ball/toe/palm 등 개별 contact role
    support_id: str
    first_frame: int
    last_frame: int
    mode: str                    # planted | rolling | sliding | free
    anchor_local_m: np.ndarray | None
    triangle_id: int | None
    barycentric: np.ndarray | None
    provenance: str              # explicit / imported / approved_detection

detect_contact_candidates(batch, rig, supports, params) -> dict
solve_contacts_v2(batch, rig, supports, contacts, intent, limits) -> SolverResult
```

### 3.1 접촉 판정과 의미

`floors()`의 3rd percentile은 낮은 높이 진단 참고값으로만 남긴다. 자동 prepare의 지지면으로 쓰지 않는다. static 평면은 사용자가 지정했거나 읽은 scene geometry여야 하며, 계단은 실제 별도 surface/triangle, moving support는 위 시간별 transform을 사용한다.

물리적 접촉 후보는 support-local 거리·상대속도로 찾는다. 기본 candidate threshold는 normal gap ≤0.02 m, tangential relative speed ≤0.05 m/s, 연속 시간 ≥0.10 s; 종료 hysteresis는 gap >0.03 m 또는 speed >0.10 m/s가 0.05 s 지속이다. 이 값은 오직 후보 분류이며 의도 증거가 아니다. profile 크기나 용도에 맞는 override는 저장하고 report에 넣는다. 검출만으로 intentional slide/moonwalk/hand gesture를 planted로 확정하지 않는다. 명시 contact schedule, imported semantics, 또는 사용자가 승인한 detection이 없으면 해당 구간은 `CONTACT_INTENT_AMBIGUOUS`로 보고하고 변경하지 않는다. 이런 구간이 사용자의 필수 해결 대상으로 지정되었다면 전체 결과는 unsupported이며 no_change가 아니다.

`approved_detection`은 최초 finite recipe grant에서 detection policy를 승인하는 방식도 허용한다. 그 계획은 허용 support/roles/frame 범위, 위 threshold/hysteresis, 보존할 rolling/sliding/gesture locks, 모호성의 종료 조건을 포함해야 한다. 그 범위 안에서 검출된 각 contact마다 재승인을 요구하지 않는다. support가 둘 이상 가능하거나 선언한 intent와 충돌하거나 필수 coverage가 부족하면 여전히 needs_input/unsupported이며, 처음 grant를 근거로 모호성을 무시하지 않는다. ContactSegment와 SupportTrack artifact refs/hash는 RecipeSpec의 `intent` 및 `references: ReferenceInputs`를 통해 plan/SourceBinding.inputs_digest에 연결한다.

heel/ball/toe의 접촉 일정을 각각 유지한다. heel-to-toe roll에서 세 점을 동시에 고정하지 않는다. `rolling`은 선언한 활성 접촉점과 transition만 고정, `sliding`은 normal contact만 유지하고 tangent 궤적은 원본 유지, `free`는 보정 없음. jump의 공중 구간은 contact gap 평활로 메우지 않는다.

### 3.2 Moving support의 앵커

rigid support에서 `q_i=R_s(i).T*(p_i-o_s(i))`이며, planted anchor `a`의 world target은 `o_s(i)+R_s(i)*a`다. tangent slip은 `P_t*(q[i+1]-q[i])/dt_i`, normal gap은 실제 support normal 방향으로 측정한다. 월드 속도 0을 강제하지 않는다. anchor가 미제공이면 해당 contact의 첫 확인 sample에서 잡고 이후 전체 clip 동안 같은 값을 사용한다. 구간별 median이나 chunk 시작점에서 anchor를 다시 잡지 않는다.

deforming support는 stable `(mesh_id, triangle_id, barycentric)`로 고정해 프레임별 세 vertex에서 anchor와 normal을 재구성한다. topology가 바뀌면 anchor를 nearest vertex로 재부착하지 않고 `SUPPORT_TOPOLOGY_CHANGED`. body hand-rest도 torso/pelvis translation만 빼는 대신 같은 surface anchor를 사용한다.

### 3.3 제약과 최적화

preserve 기본 intent는 root transform·contact onset/off frame·편집 구간 밖 포즈를 잠근다. `steps` 미지정은 preserve. 과거 `steps=True`를 명시한 호출만 스타일 변경 의도로 해석하되 lift/root 범위를 구체적으로 정한 plan을 요구한다. `step_pass`는 repair 기본 경로에서 제거하고 `synthesize_steps`라는 별도 명시 action으로 남긴다. 잔여 slide를 자동 누적 root offset이나 sine lift로 감추지 않는다.

foot solve는 실제 bone lengths와 knee pole/axis를 RigProfile에서 받는다. rest lengths가 없고 충분한 valid joint samples가 있으면 각 thigh/shin 길이의 중앙값을 사용하되 시간별 편차가 허용 뼈 길이 오차를 넘으면 rig model unavailable로 처리한다. hip–ankle 최대 거리를 cap으로 쓰지 않는다.

발 방향/회전 지지면을 표현하기 위해 각 foot의 sample-space 변수는 ankle translation `u_s(t)∈R³`와 원래 foot pose에 대한 rotation increment `theta_s(t)∈R³`다. `a'=a+u`, `p_c'=a'+Exp(theta)*(p_c-a)`를 각 해당 foot role/driver에 적용한다. 원래 toe articulation은 그 프레임의 `(p_c-a)` 안에 유지되고 전체 correction만 rigid하게 적용된다. translation-only offset으로 돌아가는 fallback은 없다. 좌측 회전 increment의 contact Jacobian은 `[I, -skew(R_delta*(p_c-a))]`이며 support anchor/normal 조건에 사용한다. one-contact에서 남는 yaw 자유도는 원본 대비 rotation 최소 objective가 결정하고, 두 점 이상 planted 또는 명시 sole-normal lock은 해당 방향을 제약한다. root/pelvis는 intent가 따로 허용하지 않으면 고정한다. ankle 목표로 exact two-bone knee/pole을 계산하고 verified controller adapter가 필요한 IK foot/knee driver만 준비한다. 해당 controller role/IK mode를 지원하지 않으면 `RIG_ADAPTER_UNVERIFIED`다. 발 angular trust region 초기 제안은 iteration당 5°, 전체 15°이며 승인 envelope에 들어가고 자동 확대하지 않는다.

objective는 원본 대비 최소 변위 + D1/D2 평활이며, contact residual·root lock·양쪽 limb lengths·profile joint limits·허용 write scope가 hard constraints다. nonconvex length/contact는 trust-region sequential QP와 아래 exact two-bone projection으로 처리한다. projection 이후 반드시 contact와 collision을 다시 계산한다. 허용안의 선택 순서: (1) hard locks 유지, (2) required feasibility, (3) correction norm 최소. metric 개선을 위해 root/안무를 풀거나 slack 위반을 숨기지 않는다.

기본 sample quality 한계(사람 크기 rig의 제안 기본값; profile에 고정해 승인 plan에 포함): `position_readback_m=0.0005`, `rotation_readback_rad=deg2rad(0.1)`, `contact_gap_m=0.002`, `contact_drift_m=0.002`, `bone_length_error_m=max(0.0005, 0.001*length_m)`, `collision_allow_m=0.001`. position 오차는 Euclidean norm, rotation은 quaternion geodesic angle, contact drift는 support-local anchor로부터 최대 tangential distance, bone error는 선언 length 대비 절댓값, collision은 policy가 선언한 signed penetration으로 측정한다. 수치는 실제 현재 scene의 검증 결과가 아니다. scene 정밀도가 문턱을 충족 못 하면 자동 완화하지 않고 구체적 residual을 반환한다. 유효한 원래 soft contact가 이보다 깊으면 사용자가 지정한 contact-specific allowance를 써야 한다.

QualityPolicy의 `calibration_status=proposed`가 초기 상태다. host synthetic case로 측정법을 확인한 것과 실제 rig의 readback 오차·mesh 정밀도·exporter 오차가 이 문턱을 충족하는 것은 다르다. 첫 실제 소규모 representative interval에서 수정 전후·roundtrip 오차를 측정하고, 사용자가 선택한 문턱을 통과하면 해당 rig/version/profile 조합에만 runtime calibration 기록을 붙인다. 실패를 통과시키기 위한 자동 threshold 확대는 없다. profile을 변경하면 새 revision과 구체적인 차이를 plan에 포함한다. 손가락 한계, 허용 soft contact, source intent, intended root trajectory는 calibration으로 추론할 값이 아니라 사용자가 선택할 의미 제약이다.

default foot correction trust region은 iteration당 축별 0.01 m, 전체 endpoint correction cap은 0.03 m; 초과 필요시 `CORRECTION_ENVELOPE_EXCEEDED`로 더 큰 envelope의 별도 계획을 반환한다. root correction은 default 0. 범위는 임의로 계속 확대하지 않는다. contact와 reachable limb가 양립하지 않으면 `CONTACT_REACH_CONFLICT`.

## 4. 회전 연속성·손 의미·IK

### 4.1 Quaternion helper 교체

```python
normalise_quaternions(wxyz, *, valid_mask, norm_tolerance=1e-3) -> np.ndarray
hemisphere_continuous(wxyz, reference_wxyz=None) -> np.ndarray
rotation_mean(wxyz, weights, reference_wxyz) -> np.ndarray
angular_velocity(wxyz, time_s) -> np.ndarray
align_vectors(a, b, *, previous_axis=None, rest_axis=None) -> np.ndarray
smooth_rotations(wxyz, time_s, *, sigma_s, editable_mask, locks) -> np.ndarray
```

nonfinite/零 norm/<1e-12 norm은 invalid. unit quaternion 오차 ≤1e-3는 정규화하되 normalization error를 기록하고 그 이상이면 input invalid. hemisphere는 `dot(q_i,q_{i-1})<0`일 때 반전하며 `sign(w)`를 쓰지 않는다. 정적 reference는 `M=sum(w_i*q_i*q_i.T)`의 주 eigenvector로 계산한다. top eigenvalue gap이 `1e-8*trace(M)` 이하이면 profile reference를 사용하거나 `AMBIGUOUS_ROTATION_REFERENCE`; component median을 정규화하지 않는다.

frame 간 각도는 `2*atan2(norm(vec(q_i^-1*q_j)), abs(w(q_i^-1*q_j)))`, angular velocity는 `/dt`. rest 기준 rotvec의 차분을 쓰지 않는다. smoothing은 q_i tangent에서 `log(q_i^-1*q_j)`를 time-kernel로 평균하고 exp로 되돌린다. π 부근 로그 축이 모호한 창은 창을 줄이거나 원본을 유지하고 flagged로 보고한다. lock/gesture/contact 경계를 가로질러 smooth하지 않는다.

`align_vectors`는 0 벡터 오류, 같은 방향 identity, antiparallel에는 prior/rest pole을 a에 직교화한다. 그 pole도 퇴화하면 a와 절댓값 내적이 가장 작은 canonical basis를 택해 `normalize(cross(a,basis))`를 축으로 π 회전한다. temporal 호출은 이전 축과 부호를 맞춘다. 이 deterministic fallback을 quality report에 남기고 필요한 pole semantics가 있으면 profile을 요구한다.

Euler는 전송 serialization 직전에만 변환한다. 현재 `rotation_from_euler_xyz`의 확인된 inverse converter가 없으면 다른 convention으로 fallback하지 말고 `UNSUPPORTED_ROTATION_CONVENTION`. quaternion round-trip을 통과한 adapter에서만 Euler write를 준비한다. ±π Euler representation jump 자체를 모션 spike로 세지 않는다.

### 4.2 손가락 cleanup과 pose styling 분리

기본 cleanup은 원래 각 손가락 독립 궤적과 contact/grip locks를 보존한다. spike 자동 제거 후보는 양 옆 orientation의 차이가 5° 이하이며 가운데 orientation과 두 이웃의 time-weighted slerp 차이가 지정 `spike_angle_rad`를 넘는 고립 샘플이다. duration threshold도 초로 계산한다. 양 옆이 서로 멀거나 여러 샘플에 걸친 fast gesture면 `AMBIGUOUS_HIGH_FREQUENCY_MOTION`이며 자동 평활하지 않는다. 이 방식으로 개별 finger gesture를 global open/fist scalar로 치환하지 않는다.

spread/twist 축과 한계는 QRT라는 이름으로 추정하지 않고 profile anatomical axes에 따른 swing/twist로 계산한다. profile이 없으면 quaternion spike 분석만 허용한다. 의도된 fan/point/pinch/sign/prop grip 구간은 명시 locks로 제외한다. `finger_fan`, `hand_pose`, `fixed_closure`, `wrist_accent`, `hand_rest`는 각자의 범위와 스타일 의도가 명시된 action일 때만 실행한다. 손이 hip 부근에 느리게 있다는 이유만으로 접촉 의도를 만들지 않는다.

thumb는 기존 13 Powell starts×4000 반복을 폐지한다. 명시 styling일 때만 현재 pose, profile relaxed pose, profile fist pose의 최대 3개 deterministic seeds를 사용한다. `minimize(method="Powell", bounds=declared_joint_bounds)`로 seed당 `maxiter=200`, `maxfev=2000`, 전체 monotonic deadline(기본 2 s)과 cancellation callback을 적용한다. objective는 지정 target fit+원본 deviation+collision violation penalty이며, Powell이 nonlinear constraint를 직접 보장한다고 가정하지 않는다. 최종 feasible 판정은 별도 hard check다. target은 명시한 surface anchor를 우선하고 자동 wrap target은 index/middle phalanx의 바깥 방향에 `finger_radius+thumb_radius+margin`만큼 둔다. 바깥 방향은 palm center에서 해당 phalanx 중심으로 향하는 벡터의 phalanx 축 직교 성분이며 퇴화시 profile 방향이 필요하다. radius는 profile 또는 실제 surface에서 얻고 기존 1.7/1.3 cm 상수를 쓰지 않는다. geometry/radius가 없으면 collision-required thumb wrap은 unsupported다. `result.success`, finite x, target residual, joint bounds, 전체 thumb segments 대 finger/palm collision을 검사한다. 한 번도 feasible 해가 없으면 `THUMB_FIT_FAILED`; 기존 best.fun이 작다는 이유로 쓰지 않는다. 성공 seed가 목표 한계를 충족하면 나머지 seed 탐색은 생략한다. 시간 예산은 정책상 설정치이며 플랫폼 성능 약속이 아니다.

### 4.3 Exact two-bone 결과 계약

```python
solve_two_bone(shoulder_m, original_elbow_m, target_wrist_m,
               upper_length_m, fore_length_m, *, pole_axis,
               previous_bend_axis=None, reach_policy="fail") -> TwoBoneResult
# TwoBoneResult: status, elbow_m, wrist_m, requested_wrist_m,
# reached_target: bool, upper_error_m, fore_error_m, reason
```

reach shell은 `[abs(l1-l2), l1+l2]`다. target이 shell 밖이면 default fail; `reach_policy=project`가 명시되면 **wrist 자체**를 shell에 투영하고 projected wrist와 elbow를 함께 반환한다. 두 뼈 길이를 위한 scalar distance만 clamp하지 않는다. contact locked wrist에는 project를 쓰지 않는다.

가능한 d>0에서 `axis=(w-s)/d`, `a=(l1²-l2²+d²)/(2d)`, `h=sqrt(max(l1²-a²,0))`, `center=s+a*axis`, elbow는 center에 original elbow/pole의 axis 직교 성분을 정규화한 방향×h를 더한다. 직교 성분이 작으면 previous bend, 그다음 rest pole, 그다음 deterministic axis 순으로 선택한다. d=0이고 l1≈l2면 `w=s, e=s+pole*l1`; 길이가 다르면 default unreachable. fully extended h≈0에서도 NaN 없이 e=center. 항상 두 길이와 actual wrist residual을 재계산한다.

## 5. Triangle collision과 양팔 공동 solve

### 5.1 Mesh 입력과 분류

`mesh_sample` host export 제안 확장은 `mesh_id`, stable joint ids/names, positions, triangles, skin weight CSR `(indptr, indices, weights)`, validity mask, frames, topology hash다. 현재 source가 이미 접근하는 `vertices_weights`에서 weight CSR는 구성 가능하다. bind transforms나 실제 skinning evaluator는 현재 접근 근거가 없으므로 별도 capability다. dominant는 호환 필드로 유지하되 읽기 전에 `0 <= dominant < len(joints)`를 검사한다. `-1`은 unknown이며 마지막 joint로 index하지 않는다.

mixed weights는 dominant 하나로 arm/body를 확정하지 않는다. RigProfile 역할 joint 집합에 대한 weight 합을 구하고, 관련 moving group weight가 있으면 deformation dependency로 포함한다. unweighted/unknown vertex는 제외해 clear로 보이지 않게 한다. 관련 triangle에 unknown이 있으면 그 coverage를 unsupported로 표시한다. meshes는 profile의 여러 mesh ids를 frame별로 합쳐도 `(mesh_id, triangle_id)` identity를 보존한다. 다른 캐릭터/prop은 explicit obstacle/read dependency로만 추가한다.

### 5.2 실제 geometry 연산

```python
build_triangle_surface(mesh_capture, rig_profile, obstacle_policy) -> TriangleSurface
closest_surface(surface, frame, query_points_m) -> SurfaceQuery
query_mesh_pairs(surface_a, surface_b, frame, exclusion_pairs) -> CollisionQuery
solve_arm_offsets_v2(batch, rig, surfaces, key_model, intent, limits) -> SolverResult
```

SurfaceQuery는 closest triangle/point/barycentric/unsigned distance/oriented normal와 `signed_distance_m: Optional[float]`, `classification: known|ambiguous|unsupported`를 반환한다. missing sign을 0 penetration으로 해석하지 않는다.

새 외부 패키지 없이 numpy로 triangle AABB BVH를 구축한다. longest centroid axis median split, leaf ≤8 triangles, closest-point query는 AABB lower bound로 branch-and-bound하며 leaf에서 정확한 triangle face/edge/vertex closest point를 계산한다. cKDTree는 후보 순서를 위한 선택 최적화일 뿐 고정 k nearest triangle만으로 종료하지 않는다. degenerate triangle은 zero-area로 기록하고 edge geometry로 처리하되 oriented sign은 unknown이다.

닫히고 orientable한 obstacle component는 edge incidence=2 및 winding consistency를 확인하고 component별 signed volume으로 outward를 정한다. query sign은 solid-angle winding(near-surface는 robust face/edge pseudo-normal)으로 구한다. 하나의 total volume으로 여러 component orientation을 단정하지 않는다. open/nonmanifold obstacle의 내부를 억지로 정의하지 않는다. policy가 `oriented_patch`를 명시한 경우에만 다음 모두를 만족하는 query에 patch signed clearance를 허용한다: triangle barycentric 최솟값 >1e-6, unsigned distance ≤declared patch band(초기 제안 0.01 m), zero-area 아님, orientation이 선언/관측됨, 해당 triangle과 one-ring의 normal angle이 20° 이하. 이는 그 patch의 측면 판정이며 `volume` 판정의 대용이 아니다. 나머지 boundary/서로 반대 normal/깊은 interior 추정은 ambiguous다. 완전한 체적 판정이 필요한 구간은 profile의 closed collision proxy 또는 검증된 닫힌 obstacle component가 필요하다. single character mesh에서 own-arm faces를 제거한 뒤 남은 열린 torso를 watertight라고 취급하지 않는다. 닫힘 검사·winding은 해당 topology hash당 한 번 수행하고 매 frame 전체 topology 재감사를 하지 않는다.

mesh–mesh self collision은 triangle pair AABB broad phase 후 정확한 vertex–face 및 edge–edge 거리/triangle intersection을 계산한다. 같은 face·edge를 공유하는 인접 topology와 profile이 명시한 관절 접합부만 제외한다. 양팔/손가락은 semantic side로 서로 제외하지 않는다. penetrating query가 `reach`보다 깊으면 clear로 바꾸지 않고 deep penetration 또는 geometry ambiguity로 남긴다. 숫자 closest-point 오류는 `GEOMETRY_QUERY_FAILED`다.

불확실 geometry에서 capsule 분석/후보는 제공할 수 있으나 report에 `coverage=proxy`로 표시한다. 사용자가 실제 mesh clearance를 required로 지정했으면 proxy 결과만으로 PASS를 주지 않는다. 이미 제한된 geometry 때문에 자동 수리가 불가능한 경우에만 unsupported로 끝내며, 정상 triangle surface를 불필요하게 막지 않는다.

### 5.3 Coupled arm 변수와 skinning 한계

Left/Right elbow/wrist를 하나의 global key-variable vector에서 푼다. 각 object의 키 집합과 interpolation operator는 따로 두고 키 교집합으로 줄이지 않는다. 상대 팔 obstacle도 현재 후보에서 같이 이동한다. contact pair (A,B)의 선형화는 `n.T*(J_A*delta - J_B*delta) >= required_separation`이므로 두 팔의 이동이 같은 제약에 들어간다. solver iteration 뒤 정확한 길이 projection→양팔/torso collision 재평가 순서를 지킨다. 한쪽 팔만 pass하고 다른 쪽 실패시 부분 성공 계획을 자동 준비하지 않는다.

현재 elbow/wrist translation blend는 approximate deformation model이다. full skin weights와 host FK/검증된 bind transforms가 있으면 그 모델의 Jacobian을 사용한다. 없으면 현재 blend를 candidate 생성용으로만 사용할 수 있고 `deformation_model=approximate`를 명시한다. 앱이 실제로 재샘플한 skinned mesh에서 required clearance를 만족하기 전에는 실제 품질 PASS를 줄 수 없다. 확인되지 않은 `csc` skinning setter/Jacobian API를 생성하지 않는다.

## 6. Target-space 리타겟과 local/global writes

현재 cleanup code에는 일반 host 리타겟 구현이 없다. 새 host 구현 위치는 `src/cascadeur_complete/retargeting.py`이며 `motion_cleanup.py`의 quaternion/IK/constraint helper를 재사용한다. 기존 `generation.retargeting` native 경로와 신규 host 경로는 `RetargetSpec.route: Literal["native", "host"]`로 plan 때 하나를 고정한다. 기존 native 도구 호출은 native로 유지한다. native는 verified installed action/settings+target actual readback을 사용하고, host는 아래 수학 계약으로 계산한 controller goals를 동일한 protected prepare/commit에 전달한다. native 실패를 host 실행으로 몰래 대체하거나 그 반대로 하지 않는다. 별도의 route variant를 최초 grant에 넣었으면 그 구체적인 유한 branch만 가능하다. 두 경로 모두 동일한 target-space QualityPolicy와 source/target scope 보호를 적용한다.

아래는 새 host 기능의 정확한 계약이며 기존 `animation.transform_get/set`의 `space` 허용값은 local/global로 유지한다. `space="target"`를 앱에 보내지 않는다.

```python
retarget_pose(source: SampleBatch, source_rig: RigProfile,
              target_rest: SampleBatch, target_rig: RigProfile,
              mapping: RetargetMapping, contacts, intent) -> SolverResult
controller_targets(goal_pose, target_rig, adapter) -> ControllerGoal
world_to_local(goal_world, planned_parent_world, parent_uniform_scale) -> Transform
```

RetargetMapping은 source→target role 대응, 각 joint의 source rest-local basis에서 target rest-local basis로의 proper rotation A_j, explicit root scale, source/target root anchors, missing-role policy를 담는다. parent chain이 달라 중간 twist joint를 배분해야 하면 배분 weights를 profile에 둔다. 누락 role을 이름 유사성으로 추측하거나 양손을 강제하지 않는다. missing optional role은 변경하지 않고 required role은 unsupported다.

source local rotation을 R_s(t), source rest local을 R_s0라 할 때 `D_s=R_s0.T*R_s(t)`, `D_t=A_j*D_s*A_j.T`, `R_t(t)=R_t0*D_t`. target bone translations/lengths는 target rest에서 유지한다. source global rotations를 target local로 바로 복사하지 않는다. root translation은 명시 scale ρ와 basis mapping C에 대해 `p_t(t)=p_t_anchor + ρ*C*(p_s(t)-p_s_anchor)`로 정한다. ρ가 미제공이면 양 rig의 선언된 leg length ratio로 한 번 산출해 plan에 포함하며 신뢰할 길이가 없으면 unsupported. root orientation mapping도 explicit initial alignment를 보존한다.

위 FK 결과에 target support의 접촉 anchor와 end-effector 목표를 world-space 제약으로 걸어 target 길이/관절 범위의 IK를 푼다. 길이가 다른 target에서 source 손·발 global 위치를 유지해야 한다는 가정을 하지 않는다. 이 target-space solve의 성공 후 제어기 adapter가 Box/Point driver 값을 산출한다. actual controlling parent가 joint인지 Box인지 profile과 read로 확인한다. 쓰려는 parent도 바뀌면 **계획된 parent transform**으로 `p_local=R_parent.T*(p_world-p_parent)/scale_parent`, `R_local=R_parent.T*R_world`를 계산한다. 원본 parent로 local을 만든 뒤 parent를 바꾸지 않는다.

QRT adapter는 현재 확인된 Point/Box role을 초기 preset으로 제공한다. generic rig·target constraints API가 있다는 가정은 금지한다. rest pose/parents/controller mapping의 round-trip이 검증되지 않은 rig에는 `RIG_ADAPTER_UNVERIFIED`. 실기기에서 확인해야 하는 최소점은 target root fixed 상태의 local/global 왕복, nontrivial parent rotation, FK/IK mode, AutoPosing이 controller goal을 재해석하는지다.

host retarget의 ControllerGoal도 §7 `fit_keys`를 거쳐 쓰며 무검증 dense 목표를 직접 write하지 않는다. target에 필요한 key가 없으면 최초 grant의 key insertion 범위와 verified key-creation adapter가 있어야 한다. 둘 중 하나라도 없으면 `KEY_LAYOUT_INSUFFICIENT` 또는 adapter unsupported로 preflight를 종료한다. 따라서 `retargeting.py` 구현 task는 quaternion helper(T11), exact IK(T12), key fitting/guarded readback(T19)을 직접 prerequisite으로 갖는다.

## 7. Constrained key fitting과 실제 보간

```python
build_key_model(capture, rig, *, interpolation_capabilities) -> KeyModel
fit_keys(goal, original, key_model, constraints, limits) -> SolverResult
evaluate_candidate(plan, evaluator, *, capture_scope) -> QualityReport
```

KeyModel은 object별 원래 key frames, frame→key operator B_i, interpolation/tangent/IK-FK/fixation metadata, mode `verified|approximate|unsupported`를 갖는다. 원본 sample frame 격자를 그대로 사용하며 이벤트 시각을 바꾸지 않는다. 기존 키 보존이 기본. 기존 layer의 cycle/section 속성도 input digest와 lock 대상이다.

검증된 선형 position channel이면 `min ||W(B*k-y)||² + λv||D1*B*(k-k0)||² + λa||D2*B*(k-k0)||²`를 OSQP로 풀고 root/외부구간 locks, contact/collision 선형화, envelope를 제약으로 건다. object별 B_i를 block 구성한다. orientation은 원본 key quaternion 주변 tangent increments로 풀고 quaternion으로 retraction한다. 모드가 STEP이면 해당 basis; 알려진 cubic coefficient가 있으면 실제 basis를 사용한다. Euler 숫자에 단순 선형 회전 fitting을 하지 않는다.

현재 graph_query는 interpolation/tangent **모드 이름**만 읽으며 실제 Bezier coefficients나 rig solver의 미분을 주지 않는다. 따라서 BEZIER를 linear_interpolation으로 예측한 값을 actual after로 표시하지 않는다. 이 경우 초기 근사 후보는 만들 수 있으나 `candidate_quality=unverified`로만 반환한다. protected working scene에서 실제 refresh 이후 별도 UI 요청으로 변경 영향 전체 sample interval을 다시 읽어야 한다. 실제 변경 영향 범위는 수정 key를 포함한 interval과 모드상 tangent 이웃, rig descendants/collision dependencies이며 범위를 판정 못 하면 해당 대상 전체 clip을 사용한다.

실측 fitting error `max_position_error_m`, geodesic rotation error, contact/collision/root/semantic locks를 별도로 비교한다. handler key equality는 trajectory quality를 대신하지 않는다. direct driver mismatch 문턱을 10 cm로 넓히지 않는다. derived ids는 원래 driver target과 같은 값 비교에서 제외하되 해당 joint/mesh의 길이·접촉·충돌 결과는 계속 필수로 검증한다.

bridge의 legacy `tolerance_cm`은 물리 cm로 해석한다. 비교할 raw scene 길이 허용치는 `tolerance_cm/100/metres_per_scene_unit`; error는 Euclidean norm×`metres_per_scene_unit`로 표준화한다. unit scale은 검증한 SourceBinding/profile에 속한 값이어야 하며 client 임의 인수만 믿지 않는다. 기존 raw `max_position_error` 필드를 유지하면 단위를 명시하고 새 `max_position_error_m`를 함께 제공한다. 이 변환을 하지 않으면 cm/m scene에서 같은 tolerance 이름이 다른 물리 허용오차가 되는 결함이 남는다.

실측 실패 뒤 repair는 approved envelope 안의 key 값만 변경한다. 최대 candidate solve passes는 RunBudgets의 명시적 유한값(초기 제안 2)이며 같은 입력·같은 후보를 반복 평가하지 않는다. 기본 `allow_key_insertion=False`에서는 실패 residual을 만족하는 기존 key 해가 없으면 `KEY_LAYOUT_INSUFFICIENT`; error가 큰 sample와 제안 key set을 새 계획에 넣는다. key insertion/bake/interpolation mode 변경은 기존 cleanup에 몰래 끼워 넣지 않는다. 최초 finite recipe grant에 허용 object/channel/frame range, 추가 key 수, 선택 규칙(위반량 최댓값 frame 우선, 동률이면 이른 frame), operation/adapter와 budget가 이미 포함됐으면 그 범위 안의 새 key 후보마다 사용자 승인을 다시 요구하지 않는다. 해당 adapter가 실제 확인되어야 하며 허용 범위 밖의 추가/모드 변경만 새 계획이 필요하다. 제한을 넘겨 무한 key 추가·재시도를 하지 않는다.

integer frame 전부의 pass는 `coverage=sampled_frames`다. controller API가 integer frame만 읽는데 연속시간 collision-free라고 보고하지 않는다. 검증된 continuous curve/deformation evaluator가 있는 경우에만 swept AABB 후 adaptive subdivision으로 interval을 확인한다. 이동 거리 upper bound가 clearance margin보다 작아질 때 종료하고 최대 subdivision depth=12에서 증명 못 하면 `CONTINUOUS_COVERAGE_UNVERIFIED`. host 시간 미분 연속화와 실제 앱 subframe 검증을 구분한다.

## 8. 긴 clip: 전역 일관성과 제한

read transport batch `READ_CHUNK=25`는 연산 요청 수 제한, mesh `MAX_MESH_FRAMES=2000`은 한 mesh 파일의 frame 수, `MAX_ROTATION_KEY_WRITES=60000`은 한 mutation payload의 write 수로 서로 다르다. 이 상한을 그냥 올리거나 UI thread에 무제한 배열을 올리지 않는다.

```python
capture_windows(frames, *, max_mesh_frames=2000, payload_budget_bytes) -> list[Window]
assemble_global_key_problem(manifest, goals, intent, limits) -> SparseProblem
stream_geometry_constraints(problem, mesh_windows, iterate) -> ConstraintSet
partition_writes(plan, *, max_writes=60000, payload_budget_bytes) -> list[WriteChunk]
```

읽기는 chunk여도 수학 문제는 전역 key grid 하나다. contact anchor와 quaternion reference는 전역 clip에 한 번 만들고 각 window에 재사용한다. D1/D2는 전역 time_s에서 생성해 2000/2001 같은 경계도 평상시 항으로 포함한다. 각 window에서 contact state/anchor/root offset을 0으로 초기화하지 않는다. mesh positions만 memmap/임시 chunk 파일로 stream하고 current global iterate에 대한 triangle 제약을 같은 전역 변수에 축적한다. solve iteration이 바뀌면 변경된 pose에서 필요한 geometry를 다시 평가한다. 다른 window를 독립 solve한 뒤 평균/concat하는 방식은 사용하지 않는다.

요구 메모리는 `(N_key, nonzeros, vertex-window-bytes)`로 prepare 전 추정하고 configured budget를 넘으면 `RESOURCE_BUDGET_EXCEEDED`와 필요한 크기를 반환한다. clip을 몰래 잘라 결과를 내거나 필수 충돌 체크를 생략하지 않는다. bounded memory로 못 푸는 경우 지원하지 않는 결과를 정확히 반환하는 것이 이 범위의 fallback이다. 별도 domain-decomposition solver를 이 변경에 끼워 넣지 않는다.

write는 deterministic `(frame,id,channel)` 순서, 중복 pair 없음, 원본 전체 candidate digest와 chunk index를 포함한다. split 기준은 write 수와 serialized bytes 둘 다이며 원래 한 key 값을 두 chunk가 소유하지 않는다. 보호 token/continuation/부분실패 rollback은 자동화·안정성 명세를 따른다. 전체 candidate 완료와 실제 whole-impact-scope readback 전에는 어떤 중간 chunk도 quality pass/export-ready가 아니다. 동일 경계 frame의 read가 중복되면 frame/id/channel value hash가 일치해야 하며 불일치시 섞어서 평균하지 않는다.

## 9. Export roundtrip의 최종 모션 품질

```python
validate_export_roundtrip(before_export: SampleBatch,
                          exported_capture: SampleBatch,
                          export_profile, rig_mapping,
                          intent: IntentConstraints,
                          policy: QualityPolicy) -> QualityReport
```

사용자가 export를 요청한 recipe의 성공 조건에는 staging artifact의 의미 검증을 포함한다. 공개/publish와 overwrite 권한은 자동화·안정성 명세에서 다루고, 품질 명세는 파일 size 안정화나 exporter return을 모션 통과로 삼지 않는다. source scene의 stable post-cleanup capture digest, export settings digest, artifact bytes digest, reimport/consumer capture digest를 함께 연결한다.

ExportProfile은 target take, character/skeleton role map, first/last time, FPS, units/basis, root policy, target consumer/adapter version, mesh 포함 여부, key baking/resampling 허용 여부를 고정한다. default는 source time 유지다. FPS 변환을 요청한 경우에만 explicit resample grid를 만들며 비교도 그 시간 grid에서 한다. fps만 바꾸어 clip duration을 바꾸는 것을 허용하지 않는다. integer frame id가 달라도 물리 time_s가 같은 위치끼리 비교한다.

가능한 importer/consumer adapter가 실제 존재하고 사용 가능한 경우에만 staging artifact를 별도 격리 scene/consumer에서 읽는다. 현재 source 작업 scene을 덮어 import하지 않는다. 재import 후 ids가 바뀌는 것을 전제로 profile의 semantic roles와 parent topology/rest-pose lengths를 다시 확인해 mapping을 만든다. 이름만 같은 다른 character/take를 선택하지 않는다. 해당 exporter/importer가 stable tags를 보존하지 않으면 unique name+topology+rest pose의 일치가 전부 필요하며 중복/불일치는 `EXPORT_RIG_MAPPING_AMBIGUOUS`.

비교 metric은 root world position/rotation, skeletal joint local geodesic angle, end-effector global position, bone lengths, 원본 contact/support-relative drift, key-pose locks, clip duration/event times, non-target scope다. mesh가 export 대상이면 actual reimport skinned surface의 collision metric도 required다. skeleton-only export에서 original render mesh collision을 측정했다고 표시하지 않는다. export의 clipping/key reduction/retarget으로 의미 있는 궤적 차이가 생기면 `EXPORT_MOTION_QUALITY_FAILED`; 파일이 열리고 joint animation이 존재한다는 것만으로 통과하지 않는다.

roundtrip 문턱은 QualityPolicy의 초기 제안값을 사용하되 exporter quantization·target consumer interpolation 오차는 runtime calibration 대상이다. export에 다른 rig를 의도했다면 위 target-space retarget 결과가 비교 기준이며 원래 source bone positions와 무조건 같아야 한다는 검사를 하지 않는다. moving support가 export 밖이면 그 support의 원래 transform trace를 검증 dependency로 보존해 source time에서 contact metric을 평가한다.

해당 format/consumer를 읽을 검증된 adapter가 없으면 artifact staged 상태와 `export_quality=unverified`, reason `ROUNDTRIP_ADAPTER_UNAVAILABLE`를 반환한다. 이 상태를 validated/export_roundtrip_verified로 승격하지 않는다. 소비자 전용 기능을 검증 못 하는 제한을 file-size 확인으로 대체하지 않는다. 이 검사는 요청한 결과 artifact의 경로 하나에 대한 직접 확인이며 모든 format을 전수 export/import하는 작업은 아니다.

## 10. 기존 함수·workflow 연결과 호환

| 위치 | 명세상 변경 |
|---|---|
| `CleanupWorkflow.__init__/_points/_arm_points/_hand_track` | `profile/context/intent`를 resolve하는 내부 공통 경로. QRT 이름은 preset의 role resolver로 한정. 한손·멀티 mesh는 profile roles에 따라 선택. |
| `CleanupWorkflow.sample` | SampleBatch+coverage 반환 내부 구현으로 교체; 기존 dict가 필요한 private callers에는 adapter 제공. 소스 binding은 전달받은 것을 보존. |
| `prepare_feet` | preserve 기본, context/support/contact validation→solve_contacts_v2→fit_keys→candidate plan. 명시 legacy steps는 styling plan으로 분리. |
| `prepare_arm_clearance` | 한 번의 coupled solve, full required metric 판정; no writes 성공 오인 제거. |
| `prepare_fingers/prepare_finger_fan/prepare_hand_pose` | quaternion continuity, per-finger semantic locks, styling 명시 범위, finite thumb solve. |
| `prepare_wrists/prepare_hand_rest/prepare_wrist_accent` | 실제 parent/hand frame, exact IK, moving surface anchors, 초 기반 envelope, empty/out-of-range pulse 오류. 양 direction/additional point 키 coverage 둘 다 확인. |
| `src/cascadeur_complete/retargeting.py` (new) | `retarget_pose/controller_targets/world_to_local`; `RetargetSpec.route=host`의 명시 mapping/rest/target IK 계산. native route는 기존 `handlers/generation.py`에 유지하며 같은 actual quality로 검증. |
| `motion_cleanup` 기존 함수 | 숫자 퇴화·solver status 공통 수정은 모든 caller에 적용. 단위/intent가 없는 legacy 직접 호출은 deprecated legacy mode로 남길 수 있으나 production prepare가 이를 우회 호출하지 않음. |
| `handlers/mesh.py` | 입력 frames 범위/유일성, topology/weight index 검증, immutable capture identity, CSR weights와 unknown mask export, window 단위 출력. |
| `handlers/animation.py` | strict driver readback, quaternion converter unsupported 명시, input finite/unique checks. mutable scope/transaction 보호는 안정성 명세. |
| 보고 형식 | 기존 before/predicted fields는 유지 가능하되 `prediction_model/coverage/runtime_verified`를 추가. 실제 after는 actual capture digest가 있는 경우만 사용. |

공개 함수 인수 추가, 기본 `steps` 의미 변경, payload schema 확장은 이번 문서가 제안하는 API 변경이며 실제 적용 전 사용자 승인 범위에 포함해야 한다. 기존 함수를 조용히 다른 의미로 연결하지 않는다. 스타일 기능을 삭제하는 것이 아니라 explicit action으로 유지한다.

## 11. 최소 수정 확인 사례와 실행 구분

아래는 구현시 직접 대응할 L1/L2 사례이며 지금 실행하지 않았다. 새로운 전수회귀·CI·benchmark 체계를 만들지 않는다. 같은 helper에 해당하는 값들은 parameterized case로 묶고 각 버그를 재현하는 최소 fixture만 추가한다.

| 테스트 묶음 | 입력 / 반드시 확인할 값 |
|---|---|
| scope/sample/status | 두 캐릭터와 이름 다른 external Point; write ids가 profile subset. 누락/중복/NaN transform은 fail. QP `primal infeasible`+잔여 침투+zero writes는 `failed`, clear baseline만 `no_change`. |
| time/unit/basis | 같은 물리 곡선을 30/60 FPS, cm/m, 회전한 up basis로 입력; SI correction과 contact 이벤트 시간은 선언된 sampling tolerance 안에서 같음. irregular time 미분 상수속도→0 가속도. |
| support/intent | translating+rotating platform 위 고정 support-local 발은 skating 0; 계단/rolling/toe-off/intentional slide 각각 schedule 보존; locked root 변화 0. |
| quaternion/short clips | w=0의 180° q와 -q, ±179° 통과, antiparallel vector, 0 vector 오류, N=1/2, missing quaternion; 유한 결과·geodesic spike 기준·empty diff 없음. |
| IK | reachable/unreachable/zero distance/fully extended/collinear elbow; default fail와 explicit projected wrist를 구분; 양 길이 residual 및 locked target 보존. |
| mesh geometry | dominant=-1/out-of-range, large triangle 중앙에 가까운 점, reversed connected component winding, open boundary ambiguity, 깊은 침투, edge-edge crossing, 양팔 공동 이동 교차; unsupported를 clear로 처리하지 않음. |
| key fitting | object별 다른 key grid, 한 키/빈 키, nonuniform key spacing, mid-key collision, BEZIER unknown model, rig readback deviation; predicted와 actual 구분, 부족한 기존 키에 `KEY_LAYOUT_INSUFFICIENT`. |
| hand semantics | pointing/pinch/grip lock은 그대로, 고립 spike만 수정, intentional fast motion flag; thumb optimizer failure/deadline이 성공 포즈로 반환되지 않음. |
| retarget | source/target 다른 rest axes·길이, rotated parent, 바뀐 parent planned transform, 단일 손 rig, missing required mapping; target length/contact 유지와 local/global FK 일치. |
| longclip boundaries | 동일 작은 sparse 문제를 mesh window 두 크기로 읽어 global plan digest/해가 허용 수치오차 안에서 동일; contact가 chunk 경계를 가로지름. payload 60000 초과의 deterministic split, 중복 write 없음. 실제 큰 benchmark는 필요 없음. |
| export roundtrip | frame id가 달라도 같은 time_s 비교, 잘못된 take/character/scale/up/duration, 다른 target rig mapping, skeleton-only collision unavailable, adapter 없음; artifact exists를 quality pass로 대체하지 않음. 실제 exporter 사례는 requested format/consumer의 한 representative interval에 한정. |

L1은 변경한 Python 파일의 compile/type/lint 중 저장소에 이미 있는 최소 명령, L2는 이 helper/경로의 명명된 test 필터만 실행한다. 공개 공유 helper 영향이 실제 존재하면 해당 모듈 L3까지만. L4 전체 테스트/워크스페이스 빌드/CI는 별도 명시 승인 없이는 수행하지 않는다.

**실기기 의존으로 남는 확인**: FPS/unit/up accessor provenance, QRT/custom rig ownership/parent mapping, local/global/Euler round-trip, AutoPosing/IK-FK driver 반응, actual BEZIER/rig readback, actual skinned surface 변화, UI-thread source capture freshness, protected chunk rollback. Host synthetic pass를 이 항목의 실행 완료로 보고하지 않는다. 실제 수정이 승인되면 해당 기능에 필요한 대표 clip/작은 구간만 직접 확인하고, 같은 결과를 확인차 반복하지 않는다.

## 12. 설계 판정 기준

합격은 Q01–Q16이 계약·알고리즘·실패 상태·최소 확인 사례 중 적어도 한 곳에 모두 연결되고, 구현자가 중대 정책을 추정할 필요가 없으며, required metric을 측정 못 한 상태가 success가 되지 않을 때다. 알려지지 않은 앱 기능은 구현 방향을 임의로 선택하는 빈칸이 아니라 **unsupported로 처리하는 확정 분기**다. 실제 모션 결과에 대한 보증은 required direct readback과 명시한 coverage의 범위로 제한한다.
