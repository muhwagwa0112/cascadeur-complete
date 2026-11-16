# Motion 구현 직전 명세

기준 HEAD: fc0e98eaa30e819f98880a32dce30c6767a5cc64. 제품 소스·원격·설치 파일은 수정하지 않았다. 이 디렉터리의 Python은 stdlib 참조 구현이며, SDK 실행기·private evidence issuer·capability 등록기가 아니다. 테스트/native 실행은 하지 않았다.

우선순위는 기존 incident의 권위 있는 처리 및 미래 unknown 감소가 먼저다. 그다음 현재 필요한 mesh/restore 관측을 수행한다. 이 준비물의 fixture나 새 operation으로 기존 unresolved-effect barrier를 우회하지 않는다.

## 1. 준비물과 실행 환경

| 파일 | 포함 내용 | 반환값의 의미 |
|---|---|---|
| serialization_equivalence.py | exact JSON/hash, typed field binding, float32 ULP+절대 오차, derived rotation 거리, 비교 예산 | ComparisonCandidate: 수학적 결과이며 인증 아님 |
| geometry_policy.py | 증가 frame/window 계획, 계산/배열 예산, read–compute–read equality, 관측된 규약에 따른 변환 | 계획/좌표 후보이며 native_actual 발급 권한 없음 |
| proposed_contracts.pyi | geometry wire/manifest 및 checkpoint v2 타입 | 제안 타입 선언. issuer 구현 없음 |
| unbaking_requirements.py | 세 step의 누락 근거, 항상 차단하는 함수 | prepare 전 차단에 사용할 준비용 조건 |
| VALIDATION_PLAN.md | 필요한 L1/L2 명령과 직접 사례 | 실행하지 않은 명세 |

Python 3.11 기준 reference package다. 배포 ZIP의 root를 import 경로로 두고 motion.geometry_policy처럼 import한다. sibling import는 상대 import이며 별도 pip 의존성이 없다. 실제 bridge에는 기존 NumPy를 재사용하고 새 의존성을 추가하지 않는 설계다.

**Schema/public API 변경 제안:** 신규 system operation 2개, verification kind 1개, checkpoint manifest v2는 현행 API가 아니다. 실제 구현 시 승인된 범위와 schema golden에 명시한다. v1 receipt/unknown/manifest bytes를 바꾸거나 새 의미로 해석하지 않는다.

## 2. 실제 geometry private capture

### 2.1 현재 함수별 변경점

| 현재 위치 | 제안 변경 |
|---|---|
| cascadeur_side/cascadeur_complete/handlers/mesh.py::mesh_sample | 기존 반환/NPZ 유지. 배열 reader/sampler만 내부 함수로 분리하여 새 observer와 공유. raw handler는 native_actual 발급 안 함 |
| 신규 native_geometry_capture.py | NativeGeometryCaptureAdapter(required_scope/capture/execute), stage/finalize/get/verify 및 private pending/sealed |
| native_adapters.py::verify_observation | kind=geometry_capture 명시 분기. 기본 observation_digest 성공 분기로 보내지 않음 |
| runtime.py::_run_operation/_run_operation_legacy | observe는 effectful adapter 경로만 사용. legacy에는 read-only get만 연결하고 observe fallback은 명시 거절 |
| runtime.py::execute_request | 기존 terminal receipt_event 뒤 finalize_geometry_capture. terminal result를 봉인 뒤 수정하지 않음 |
| src/cascadeur_complete/recipe_native_service.py | geometry prepare/commit과 get/recipe_verify_geometry 추가. observe를 읽기 execute로 보내지 않음 |
| src/cascadeur_complete/effects.py::classify_effect 및 runtime.py::_request_effect | system.observe_geometry_capture를 명시 file effect로 동일하게 분류. read-only 목록에는 get만 추가 |
| src/cascadeur_complete/motion_geometry.py::WindowedSurfaceTrack._load | 새 canonical window의 실제 배열 bytes hash까지 대조. 동일 handle로 hash/decode하고 사용 배열의 hashes를 검증 |
| src/cascadeur_complete/motion_quality.py::actual_mesh_metrics/evaluate_actual_quality | 수용 기준 유지. 새 producer/decoder/verifier를 기존 인자에 연결 |

아래는 **신규 프로젝트 함수 시그니처**다. 이미 설치된 SDK 함수라는 뜻이 아니다.

~~~python
# Proposed native_geometry_capture.py
class NativeGeometryCaptureAdapter:
    def required_scope(self, scene, scope: dict) -> dict: ...
    def capture(self, scene, scope: dict) -> dict: ...
    def execute(self, scene, arguments: dict, request: dict) -> tuple[dict, list]: ...
def stage_geometry_capture(scene, arguments: dict, request: dict) -> dict: ...
def finalize_geometry_capture(scene, request: dict, result: dict, receipt: dict) -> None: ...
def get_geometry_capture(scene, capture_id: str) -> dict: ...
def verify_geometry(manifest: dict, geometry_digest: str) -> dict: ...

# Proposed extraction from existing handlers/mesh.py
def _read_mesh_arrays(domain, object_id, context) -> dict: ...
def _sample_mesh_positions(domain, object_id, frames, vertex_count, context): ...
~~~

실제 확인된 native 호출은 csc.domain.calc_skinned_mesh(domain, object_id, frame)이다. 현재 handler는 반환 positions의 (N,3,1)을 (N,3)으로 정규화한다. namespace/shape 근거만으로 world/local·freshness·reskin 완료를 인증하지 않는다.

### 2.2 입력과 dependency closure

GeometryCaptureArguments에 capture_id(UUID), motion_source_binding, motion_capture_digest, origin_request_id, context, mesh_ids/pairs와 예산을 받는다. request 최상위 source_binding은 geometry operation scope이며 arguments.motion_source_binding과 구분한다. 임의 path, raw space, calibration true, native_complete true, SDK getter 이름은 받지 않는다.

1. guards.assert_loaded_package/assert_source로 최상위 source를 정확한 system.observe_geometry_capture operation 및 arguments와 대조한다.
2. native_motion_capture.lookup_capture를 호출한다. private canonical_batch.source_binding/context가 arguments.motion_source_binding/context와 정확히 같아야 한다. 현재 motion source도 별도로 assert_source한다.
3. mesh asset, dependency asset, linked joint의 순서, weights/inverse-bind, parent/mesh 변환과 필요한 data/setting 참조가 scope에 닫혀 있어야 한다.
4. 현재 complete projection과 private evaluation receipt의 scene/epoch/projection/grid가 일치해야 한다. interpolation receipt는 calc 호출 자체의 완료 증거가 아니다.
5. origin_request_id는 인증된 terminal 성공 request/receipt를 읽는 데만 사용한다. source/successor digest를 caller 문자열에서 복사하지 않는다. baseline은 해당 evaluation request, mutation readback은 원 mutation request를 가리킨다.
6. origin request.source_binding과 terminal result.post_source_binding을 실제로 읽는다. 역사적인 origin source는 변경 이전 값이므로 current assert_source 대상이 아니다. 원 signed request/receipt 연결로만 인증한다. origin successor와 현재 motion source만 현재 native guard로 재검증한다. scope가 다르면 같은 현재 complete dependency projection에 대한 private rebinding 관계가 필요하다. origin unknown은 성공으로 바꿀 수 없다.

geometry_policy.ReadBoundary는 build/epoch/loaded bytes, scene/active scene/lineage, source/motion/evaluation/full projection/topology/skin/transform/context/selection/frame을 exact 비교한다. current frame/selection/transform 조회의 installed binding이 미확인일 때 임의 getter나 항등 변환을 채우지 않는다. 확인된 경로로 얻거나 그 profile을 차단한다.

### 2.3 계산과 space

다음은 통합 제어 흐름 명세이며, 실행 가능한 issuer stub이 아니다. NEW PRIVATE helper가 없는 상태에서는 실제 capture가 차단되어야 한다.

~~~python
motion_record = lookup_capture(arguments["motion_capture_digest"])
geometry_source = request["source_binding"]
guards.assert_source(scene, geometry_source,
    operation_name="system.observe_geometry_capture", arguments=arguments)
guards.assert_source(scene, arguments["motion_source_binding"])

# NEW PRIVATE prerequisite: actual installed calibration evidence required.
contract = require_observed_geometry_contract(scene, mesh_ids, context)
before = read_geometry_boundary(scene, arguments["motion_source_binding"], motion_record, contract)

for window in approved_plan.windows:             # mesh-major, ascending frames
    raw_window, canonical_window = allocate_approved_window_arrays(window)
    for row, frame in enumerate(window.frames):
        returned = csc.domain.calc_skinned_mesh(domain, exact_mesh_id, frame)
        owned_raw = copy_returned_positions(returned, exact_vertex_count)
        canonical = convert_using_observed_contract(owned_raw, frame, contract)
        raw_window[row], canonical_window[row] = owned_raw, canonical
    # Before the first mkdir/O_EXCL/file write; no artifact effect precedes this.
    guards.before_write(lambda: guards.assert_source(scene, geometry_source))
    write_new_owned_immutable_window(raw_window, canonical_window, topology, skin, window)

after = read_geometry_boundary(scene, arguments["motion_source_binding"], motion_record, contract)
assert_read_compute_read(before, after, ...)
write_candidate_and_authenticated_completion_sidecar_with_fsync(...)
guards.finish_write()
guards.observe_effect("system.observe_geometry_capture", "completed", ...)
# Store private pending state and return candidate only; no native_actual yet.
~~~

위 helper는 프로젝트 신규 구현 지점이다. 성공하는 require_observed_geometry_contract나 private issuer는 이 준비물에 없다.

- raw world: solver_basis @ (scale × raw_world).
- raw mesh-local: 확인된 frame별 column-vector affine mesh→world 변환을 한 번 적용한 후 basis·scale.
- raw world에 mesh matrix를 동시에 제공하면 참조 코드가 거절한다.
- 어느 data ID가 필요한 변환인지는 installed behaviour/property binding으로 확인한다. 확인된 data_viewer().get_data_value(data_id, frame)를 써도 data ID의 의미가 자동 증명되지는 않는다.
- explicit MotionContext conversion을 쓰면 native physical metadata를 직접 관측했다고 기록하지 않는다.
- calc가 model projection을 바꾸거나 deferred reskin/UI yielding에 의존하면 read-only synchronous profile을 발급하지 않는다.
- probe의 [0,2,1,0] 호출 순서를 production 입력 계약에 넣지 않는다. production은 항상 증가 frame schedule이다.

geometry_policy의 좌표변환은 수학 후보이며, 기존 MotionContext와 동일한 convention을 native integration에서 확인해야 한다. reference의 proper-basis 수치 검사는 증거 발급용 tolerance가 아니다.

### 2.4 receipt 순환 hash 없이 봉인하기

최종 manifest에 그 capture의 terminal receipt digest를 넣으면서 terminal result에 최종 manifest digest도 넣으면 순환한다.

1. system.observe_geometry_capture는 capture ID, candidate_digest, 원 request ID, awaiting_terminal_receipt 상태만 반환한다.
2. candidate_digest는 source/dependency/calculation/window 관측을 포함하지만 아직 없는 terminal receipt digest는 포함하지 않는다.
3. 기존 runtime이 원 result에 대한 durable terminal receipt를 기록한다.
4. finalize_geometry_capture가 exact private pending record와 그 receipt를 대조해 final manifest를 **memory-only**로 봉인한다. 파일을 새로 쓰지 않는다.
5. 원 result/receipt는 수정하지 않는다. system.get_geometry_capture가 final manifest와 geometry_digest를 반환한다.
6. system.verify_observation(kind="geometry_capture")가 private issuance, exact manifest, 실제 window bytes, 현재 source/evaluation을 검증한다.

finalizer의 필요조건:

~~~python
operations == [{"name": "system.observe_geometry_capture", "arguments": exact_arguments}]
pending.request_id == request["request_id"]
pending.scene_object is scene
result["ok"] is True
result["outcome"] == "succeeded"
result["result"]["geometry_capture_id"] == pending.capture_id
result["result"]["candidate_digest"] == pending.candidate_digest
receipt["phase"] == "terminal"
receipt["outcome"] == "succeeded"
receipt["request_digest"] == guards.digest(request)
receipt["result_digest"] == guards.digest(result)
pending.runtime_epoch == guards.RUNTIME_EPOCH
pending.runtime_fingerprint == guards.LOADED_FINGERPRINT
~~~

위 JSON만 만들면 통과하는 구현은 금지한다. pending record는 실제 calc와 source closure 경로만 생성하며, process-private 객체/record와 연결해야 한다. finalizer 실패 시 get/verify는 완료 증거 부재로 거절한다. raw 계산 자동 재dispatch 없이 원 request/capture ID로 조회한다.

candidate/window와 인증된 completion sidecar는 원 file effect 안에서 terminal 이전에 durable하게 완료한다. sidecar는 request/operation/argument digest, geometry 최상위 source 및 실제 successor, motion/origin/evaluation 연결, build/epoch/loaded bytes, candidate/window hashes와 observed synchronous closure를 포함한다. 원 작업의 code-owned writer만 MAC으로 봉인하며 caller 파일이나 문자열을 증거로 채택하지 않는다. Geometry 전용 신규 geometry-candidate-completion-v1 schema로 발급한다. 기존 admission sidecar/private failure record와 목적·MAC 입력·authority가 다르며 공통 completion module/type에 의존하지 않는다. 최종 receipt를 포함한 manifest를 native 파일로도 저장해야 한다면 **별도의 file-effect 요청**을 선언한다. finalize/get에서 숨은 추가 write를 하지 않는다. 재시작으로 private record가 사라져도 이전 sidecar를 새 epoch의 qualification으로 재사용하지 않는다.

### 2.5 actual_mesh_metrics 입력 매핑

| manifest 필드 | 발급 원천 |
|---|---|
| capture_kind | 실제 private 봉인 뒤 native_actual |
| source_digest | 인증된 origin request.source_binding |
| successor_digest | origin terminal result.post_source_binding |
| capture_source_digest | 현재 native-issued motion capture의 exact source |
| geometry_operation_source_digest/successor_digest | 이 file-effect 요청의 최상위 원 source 및 실제 post_source_binding |
| completion_receipt_digest | geometry observe의 durable terminal receipt |
| origin_completion_receipt_digest | origin terminal 성공 receipt |
| evaluation_receipt_digest | private motion record의 현재 evaluation receipt |
| motion_capture_digest | native-issued canonical motion batch digest |
| topology_digest | 실제 mesh ID, vertex/triangle coverage, asset/polygon mapping |
| skin_digest | linked joint 순서, weights offsets/indices/values, inverse-bind |
| context_digest, frames, time_s | actual motion과 같은 physical grid |
| windows | NPZ SHA + canonical <f8 metres/triangles <i8 C-order array hashes |
| pairs | approved pair closure 및 required RigProfile mesh 포함 |
| space, units | 확인된 변환을 완료한 global, metres |
| orientation_evidence | 실제 관측한 oriented_patch에만 존재 |

새 private NPZ는 legacy mesh_sample 파일과 별도다. raw positions와 canonical_positions_m을 구별하고 canonical dtype/shape/order/hash를 명시한다. raw SHA와 canonical SHA를 혼용하지 않는다. WindowedSurfaceTrack._load는 선택한 position_field와 실제 owned arrays를 hash 대조한다. 파일 SHA를 읽은 뒤 다른 path open에서 바뀐 배열을 사용하지 않도록 같은 handle로 decode하고 사용 배열의 hash도 확인한다.

Host 연결:

~~~python
geometry = {
    "manifest": sealed["manifest"],
    "tracks": {
        mesh_id: WindowedSurfaceTrack(
            sealed["manifest"]["windows"][mesh_id],
            sealed["manifest"]["frames"], context=actual.context,
            semantics=policy.collision_semantics,
            orientation_observed=verified_orientation_for_this_mesh,
            memory_budget_bytes=approved_window_budget,
        )
        for mesh_id in exact_mesh_ids
    },
    "max_pair_checks": approved_pair_budget,
    "max_surface_queries": approved_query_budget,
}
evaluate_actual_quality(
    original, actual, rig, intent, policy,
    geometry=geometry, capture_verifier=service.recipe_verify_capture,
    geometry_verifier=service.recipe_verify_geometry,  # new proposed method
)
~~~

open mesh의 volume sign, 미관측 oriented patch, contact-region allowance는 기존 quality 규칙대로 거절한다. 좌표계 qualification으로 collision semantics까지 인증하지 않는다.

### 2.6 Effect/admission 및 geometry 전용 sidecar

**분류:** host effects.py::classify_effect와 native runtime.py::_request_effect 양쪽에서 system.observe_geometry_capture를 file effect로 명시한다. READ_ONLY_OPERATIONS에는 get만 추가한다. observe는 NativeGeometryCaptureAdapter가 등록된 guards._ADAPTERS 경로로만 실행하며 legacy fallback은 거절한다. handler_registry에 성공을 선언하는 raw observe handler나 정적 completion postcondition을 추가하지 않는다.

**Admission:** 신규 proposed feature ID native_geometry_capture를 product_catalog.py/feature_registry.py::build_registry에 연결한다. recipe_native_service.py의 prepare_geometry_capture는 기존 prepare_change/change_commit 및 원 recipe grant/lease/일회용 token을 사용한다. recipe_planning.py/recipe_runner.py에서 해당 file-effect stage와 calculation/array/artifact 상한을 승인 plan에 미리 선언하고 preparing CAS에서 한 번 예약한다. 읽기 client.execute로 observe를 실행하거나 승인 후 readback helper가 effectful stage를 임의 추가하지 않는다.

**Adapter required_scope:** exact operation/arguments/digest, complete reader의 object/layer IDs와 전체 frame 범위, 요청 context/sample grid, motion_capture_digest, 실제 mesh/skin/joint/parent dependency closure, private profile digest, artifact_plan을 반환한다. artifact_plan은 canonical capture_id UUID와 고정 runtime-owned root로 만든 window/candidate/sidecar 경로 및 bytes 한도다. caller path나 임의 evidence flag는 받지 않는다.

**Adapter capture:** scope/private profile 및 현재 motion/evaluation을 재검증한 뒤 실제 full scene projection을 authored_projection/sample_projection으로 반환한다. 원 historical origin source를 current guard하지 않는다. 현재 geometry top-level source와 arguments.motion_source_binding만 각각 그 정확한 scope로 검증한다. artifact target bytes는 scene identity에 섞지 않고 별도 artifact observation에 묶는다.

**Adapter execute:** strict arguments와 profile을 다시 검증하고 첫 mkdir/O_EXCL/write 전에 guards.before_write를 호출한다. output freshness를 prepare/execute에서 확인하며 overwrite하지 않는다. calc와 owned arrays, 모든 window/candidate/sidecar fsync 및 전후 scene closure를 완료한 뒤 finish_write/observe_effect(completed)를 호출한다. 예외 시 partial 파일을 자동 삭제하거나 성공으로 재분류하지 않는다.

**입력 검증 위치:** 신규 host native_geometry_contract.py::GeometryCaptureArguments 모델에서 extra-forbid/UUID/strict budget/unique IDs/pairs/source 형태를 검사한다. native_geometry_capture.py::validate_geometry_arguments는 동일 allowed-field set을 다시 확인하며 required_scope와 execute 양쪽에서 호출한다. context는 기존 native_motion_capture._context 계약을 사용하고 native counts/closure/budget은 독립적으로 읽어 검증한다. TypedDict 선언만으로 검증했다고 하지 않는다. read-only get은 capture_id 하나만 받고, verify는 geometry_capture kind를 명시 분기한다.

**신규 sidecar schema:** geometry-candidate-completion-v1, schema_version=1, 경로는 owned capture directory의 candidate-completion.json이다. native_geometry_capture.py가 writer/reader 구현 책임을 가진다. payload는 원 request/session/host/execution context와 request/operation/arguments digest, geometry top-level source/실제 successor, motion/origin/evaluation, build/epoch/fingerprint, candidate/window hashes, calc call schedule, 전후 complete projection/dependency closure를 포함한다.

MAC은 기존 runtime._bridge_key(root)의 key bytes를 사용한 HMAC-SHA256이다. 입력은 UTF-8 domain separator "cascadeur.geometry-candidate-completion-v1\0" 뒤에 mac을 제외한 canonical JSON bytes를 붙인다. admission sidecar와 domain/purpose를 공유하지 않는다. 실제 guarded adapter writer만 생성하며 caller JSON/file을 issuer 입력으로 받지 않는다. reader는 purpose/schema/MAC 및 exact request/candidate/window 연결을 확인한다.

이 sidecar는 완료된 calculation/file effect 관측이며 terminal receipt를 주장하지 않는다. terminal 뒤 finalize는 private pending과 원 receipt를 연결하는 **memory-only** seal이다. 최종 manifest 파일이 추가로 필요하면 별 file-effect 요청으로 선언한다. finalize/get 실패 시 원 ID 조회만 하며 raw calc 재dispatch하지 않는다.


## 3. typed serialization equivalence와 exact anchor

### 3.1 reference comparator

serialization_equivalence.compare_projections는 expected_before_digest를 exact 검증한다. raw hashes가 같으면 exact candidate다. 다를 때 policy가 없으면 거절한다.

typed policy는 exact build/fingerprint, 구조 digest, data owner/behaviour/property/range index, dtype/dependency evidence, 단위와 사전 고정 수치 한도를 포함한다. 허용된 data[id].values만 비교용 복제본에서 제거하고 나머지 모든 값/구조는 exact hash로 비교한다.

- float32는 해당 값이 float32로 정확히 roundtrip되는지 먼저 검사한다. ULP 상한과 native-unit 절대 오차 상한을 모두 적용한다.
- derived rotation은 단위 quaternion 제약을 확인한 뒤 q/-q의 동일 회전 거리를 비교한다.
- authored/unclassified 값, keys/sections/tangents/labels/settings/구조에는 tolerance가 없다.
- 새/누락 field, shape/type 변경, NaN/Inf, 예산 초과는 거절한다.
- 실패에서 threshold를 학습하거나 자동 확대하지 않는다.

DerivedPolicy를 wire에서 받지 않는다. native는 private installed 역할 분류에서만 policy를 얻는다. reference가 확인하는 evidence_digest 문자열은 증거 인증이 아니다. 가짜 policy로 numeric candidate를 만들 수 있어도 production relation/capability가 생겨서는 안 된다.

현재 reader에는 dtype/producer 역할 분류가 없다. DataMode.Animation이나 Position/Twist라는 이름으로 DerivedRule을 만들지 않는다. 다른 behaviour가 같은 data ID를 입력으로 공유하는 경우까지 private dependency classification에 포함한다.

### 3.2 tolerance는 전이적이지 않으므로 기준을 고정한다

a≈b, b≈c만 확인하면 반복 save/restore에서 오차가 누적될 수 있다. 같은 snapshot에서는 fixed pre-save reference P0를 유지하고 모든 serialization 결과를 P0와 직접 비교한다.

~~~python
reference = reader(target)               # P0, fixed semantic reference
checkpoint_file = _save_observed(target, backup)
checkpoint_projection = reader(target)  # P1, actual after checkpoint save
working_file = _save_observed(target, working)
working_projection = reader(target)     # P2, actual working state

r1 = compare_with_private_policy(reference, checkpoint_projection, phase="checkpoint_save")
r2 = compare_with_private_policy(reference, working_projection, phase="working_save")
~~~

P0/P1/P2 exact hashes는 별개다. 원 파일 SHA/길이는 locked bytes 그대로다. 같은 snapshot에서 workspace가 바뀌어도 P0/P1/file identity를 덮어쓰지 않는다. 명시적 새 checkpoint 파일 생성 때만 새 immutable anchor를 만든다.

~~~python
_CHECKPOINT_ANCHORS[checkpoint_anchor_digest] = immutable_anchor
# Exact P0 + exact P1 + original file manifest + pinned policy/evidence.
_CHECKPOINTS[snapshot_manifest_digest] = {
    "manifest": current_workspace_manifest,
    "anchor_digest": checkpoint_anchor_digest,
    "working_projection": exact_current_raw_projection,
    "run_id": run_id,
}
~~~

checkpoint_anchor_digest는 fixed fields만 포함한다. 현재 scene/path/projection이 바뀌면 snapshot_manifest_digest는 바뀔 수 있지만 원 immutable anchor는 유지된다.

### 3.3 전 호출 경로 변경

| 함수 | 변경 내용 |
|---|---|
| native_scene_reader.read_scene | raw projection 그대로. 역할/type 근거는 별도 descriptor/private registry |
| native_adapters.checkpoint | P0/P1/P2 개별 capture, P0 대비 2회 비교, v2 manifest에 각각 digest와 private relation |
| native_checkpoint_restore.remember_checkpoint | fixed anchor와 current working projection 분리 |
| native_checkpoint_restore._anchor | 요청 manifest와 원 bytes exact 확인 후 immutable anchor 조회. current 값을 새 기준으로 삼지 않음 |
| native_checkpoint_restore._restore_native | load/save 결과를 각각 P0와 직접 비교. 실제 restored projection 반환. 원 실패 탭 exact 불변 |
| qualify_restore | restored_projection_digest에 실제 target digest 기록 |
| NativeCheckpointRestoreAdapter.execute | _capture_with_adapter의 sample_digest를 실제 restored raw digest로 지정 |
| execute activation 검사 | 방금 관측한 restored projection과 exact 비교. activation 중 추가 tolerance 금지 |
| approve_successor | private completion/relation, fixed anchor, 원 manifest/permit/receipt, actual source_after digest 확인 |
| qualify_checkpoint_restore_adapter._observe | 현행 136행의 actual digest exact 검사를 유지. 늦은 변화에 tolerance 적용 금지 |
| guarded_runtime.digest/capture_source/assert_source | 변경 없음. raw current source identity exact 유지 |

제안 시그니처:

~~~python
def remember_checkpoint(
    scene, manifest, *,
    immutable_anchor, working_projection, serialization_observation, run_id=None,
) -> None: ...

def _restore_native(scene, anchor, working) -> NativeRestoreResult: ...
# NativeRestoreResult carries target, identities, actual restored_projection,
# saved file, failed-scene digest, project_load, immutable anchor,
# private serialization observation and successor manifest.
~~~

restore 본체:

~~~python
target, load_observation = load_project_copy(
    checkpoint_path, working,
    expected_sha256=anchor.checkpoint_file["sha256"],
    expected_length=anchor.checkpoint_file["bytes"],
)
loaded_projection = read_scene(target)
loaded_relation = compare_with_private_policy(
    anchor.reference_projection, loaded_projection, phase="project_load",
)
saved = _save_observed(target, working)
restored_projection = read_scene(target)
saved_relation = compare_with_private_policy(
    anchor.reference_projection, restored_projection, phase="restored_save",
)
assert guards.digest(read_scene(source_scene)) == original_failed_projection_digest
successor = guards._capture_with_adapter(
    target, scope, source["inputs_digest"],
    guards.digest(restored_projection), None, adapter,
)
assert guards.digest(read_scene(target)) == guards.digest(restored_projection)
~~~

compare_with_private_policy는 신규 프로젝트 authority 경계다. 실제 observed load/save phase, native private role evidence, exact anchor에서만 relation을 발급해야 한다. 이 준비물에는 그 issuer가 없다. ComparisonCandidate.accepted나 JSON evidence digest만으로 relation을 만들면 안 된다.

v1은 종전 exact route를 유지한다. v2에 필요한 분류 근거가 없으면 차이를 거절한다. 기존 receipt/manifest를 재서명하거나 새 policy로 과거 unknown을 소급 성공 처리하지 않는다. 새 schema/bytes는 새 plan/grant/qualification 대상이다.

## 4. unbaking은 prepare 전에 capability reason으로 차단

현재 준비할 수 있는 코드는 step/input/source/scope/budget 검증과 기존 native_unbaking.compare_projections 연결이다. installed action→callable binding 및 완료 계약은 없다.

**차단 위치:**

- recipe_native_service.py::recipe_preflight에서 사용자가 native_unbaking stage를 선언했는데 해당 step의 private qualified executor가 없으면, 구체적인 missing_evidence를 포함한 preflight 실패를 반환한다.
- src/cascadeur_complete/server.py::animation_unbaking_prepare(747–758행)는 현재 입력 검증 뒤 _prepare('unbaking', 'generation.unbaking', ...)로 간다. 신규 공통 service.require_native_unbaking_step(step, source_binding) 판정을 _prepare 호출 전에 둔다. 실패는 기존 _invalid 형식으로 반환하며 permit/token/budget 예약에 도달하지 않는다. recipe_preflight도 같은 판정 helper를 사용한다.
- cascadeur_side/cascadeur_complete/handlers/generation.py::unbaking(103행)에서도 같은 조건을 재검증한다. 134행의 exact source 검사 뒤, 163행의 _select_objects/_select_interval 이전에 native_unbaking.require_step_contract를 호출한다. host preflight만 통과한 것으로 간주하지 않는다.

현재 ActionManager.call_action은 None 반환이며 AnimationUnbakingTool 공개 페이지에는 get_interpolation_difference만 있다. ml/editable_animation.py가 세 action의 실제 binding이라는 근거도 아직 없다. AutoPosingTool.add/update로 대체하지 않는다. 사용자가 요구한 stage를 자동 생략하거나 sparse fitting으로 바꾸지 않는다.

향후 등록에 필요한 chain:

~~~python
step -> installed_action_id -> exact_callable_source_digest
     -> explicit scope lowering
     -> completion_contract
     -> build + loaded_fingerprint + epoch
     -> process_private_qualification_record
~~~

현재 guarded_runtime.register_adapter는 synchronous_no_yield만 허용한다.

1. 확인된 동기 leaf만 실제 completion/scope/failure 관측 뒤 등록할 수 있다.
2. callback/future가 발견되어도 synchronous로 거짓 등록할 수 없다. pending request를 terminal로 넘기지 않고 완료 continuation까지 연결하는 별도 runtime protocol이 필요하다.
3. opaque deferral이면 prepare 전 차단을 유지한다. wrapper 반환, idle 두 번, quiet period는 완료 계약을 만들지 않는다.

unbaking_requirements.py는 이 준비 범위에서 항상 거절한다. 성공하는 fake executor, None→success, marker-file 증거, 자동 sparse 대체는 없다.

## 5. native probe는 조건부 계획이며 실행하지 않음

mesh의 “evaluation 2 + calc 5 + guarded edit 1”은 아래 전제가 이미 충족된 경우의 **관측 본체 상한**이다. fixture 생성/설치/로드/탭 관리까지 포함한 전체 작업 비용이 아니다.

- 기존 unknown/barrier가 권위 있게 처리됐고 native 작업이 승인됨.
- 소유 fixture와 정확한 transform/skin 입력이 준비됨.
- fixture driver의 합법적 변경 경로와 evaluation이 확인됨.
- source/selection/frame/parent transform reader binding이 확인됨.

하나라도 없으면 다섯 calc로 자격을 만들어내지 않는다. fixture driver가 현재 qualified independent writer 범위 밖이면 그 writer를 사용할 수 있다고 가정하지 않는다.

비대칭 tetrahedron·두 joint·세 frame으로 좌표계/frame/freshness를 구별한다. 주요 비교 꼭짓점은 single-joint weight=1로 두어 임의 skinning 공식을 가정하지 않는다. 이 관측으로 mixed weights/additive/blendshape/임의 rig를 일반 인증하지 않는다. production은 sorted frames를 유지한다.

restore는 알려진 Cascy 차이의 field/type/producer 확인과 소유 clone 한 번의 serialization 경계 관측만 계획한다. threshold를 실패에 맞추지 않는다. 통과 뒤 반복 save나 자동 close/종료 crash probe를 추가하지 않는다.

## 6. 근거 및 준비 상태

현재 코드 근거: handlers/mesh.py::mesh_sample, native_motion_capture.py::observe_motion_capture/lookup_capture, native_scene_adapter.py::finalize_evaluation, runtime.py:1652 이후 terminal/finalizer, motion_quality.py:353–391 및 453–460, native_adapters.py::checkpoint, native_checkpoint_restore.py, qualify_checkpoint_restore_adapter.py::_observe.

공식 문서:

- https://cascadeur.com/python-api/_generate/csc.app.ActionManager.html
- https://cascadeur.com/python-api/_generate/csc.tools.AnimationUnbakingTool.html
- https://cascadeur.com/python-api/csc.html

설계 준비 PASS: stdlib comparator, geometry planning/conversion/closure, 제안 타입, fixed-anchor 원칙, receipt 순환 해소, 함수별 변경 지점과 prepare 전 차단 계약.
미검증: 코드 실행/타입검사, 실제 SDK space/freshness/completion, private issuer 구현, schema 적용, 실제 restore/unbaking/일반 rig 지원. 부모 작업이 수행하는 별도 AST/L1 결과는 그 범위로만 보고한다.

