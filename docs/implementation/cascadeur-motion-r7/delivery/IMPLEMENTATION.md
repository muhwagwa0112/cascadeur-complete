# R7 최종 FBX·소비자 품질 연결

기준: `muhwagwa0112/cascadeur-complete@99b85163c4125a621ef7e2deeabe22270032c60b`.
이 디렉터리는 **제품 미적용 변경안**이다. 실제 Cascadeur·Blender 실행 또는 일반 캐릭터
export 자격 확인을 수행한 결과가 아니다.

## 이번에 코드로 준비한 부분

현재 `RecipeRunner._export_host_step()`에는 원 native export receipt → immutable FBX seal →
구조 검사 → 실제 Blender import/capture → 원 의도 품질 → publication이 이미 연결돼 있다.
이 경로를 새로 만드는 대신, 최종 시각 결과에 필요한 **native/consumer mesh 형상 비교**를
추가한다. 기존 `target_capture.evaluate_target_capture()`는 consumer의 골격 모션과 충돌
지표를 검사하지만, 그 mesh가 최종 native mesh와 같은 형상인지를 측정하지 않는다.
뼈 transform이 같고 충돌이 없더라도 잘못된 skin·mesh 변형이 통과할 여지가 있는 부분이다.

`product-integration.patch`는 다음 4개 제품 파일을 대상으로 한다.

| 파일 | 구체 변경 |
|---|---|
| `src/cascadeur_complete/mesh_delivery.py` | `make_mesh_delivery_reference()`와 `measure_mesh_delivery()` 추가. 실제 native geometry window와 imported surface를 global metre 좌표에서 양방향으로 비교한다. |
| `src/cascadeur_complete/export_models.py` | 제안된 `TargetImportSettings.native_mesh_mapping`, `max_mesh_distance_checks` 필드 추가. |
| `src/cascadeur_complete/recipe_runner.py` | export 준비 전 최종 geometry reference 생성, signed run의 stage/artifact 보관, validate/resume에 동일 reference 전달. native geometry 검증 호출을 bridge budget에 반영한다. |
| `src/cascadeur_complete/target_capture.py` | 이미 인증한 consumer raw capture의 mesh track과 native reference를 비교해 `mesh_surface_readback_m`을 quality report에 넣는다. 초과 시 publication으로 진행하지 않는다. |

### 실제 데이터 흐름

1. `quality_capture`의 실제 global `SampleBatch`와 `geometry_capture`의 sealed manifest를 읽는다.
2. `_prepare_step()`의 `export_stage`에서 실제 `before_export` motion을 새로 읽는다.
   두 source는 같은 epoch·scene instance·document lineage·loaded fingerprint여야 한다.
   두 source 모두 실제 `native-model-assets-v1` whole-scene reader의 complete scope이며,
   명시된 native mesh ID 전부를 포함해야 한다. `sample_digest`가 같아야 한다.
3. 전체 measured position·rotation·validity, frame/time/FPS/unit/basis도 일치해야 한다.
   Position은 기존 capture처럼 모든 요청 ID에서 확인하고, rotation은 실제 제공된 ID에서만
   확인한다. Position-only ID에 새 rotation 관측 의무를 추가하지 않는다. 원 의도·골격 품질에
   필요한 rotation은 기존 capture/quality 계약이 계속 요구하며, 제공된 모든 채널과 validity는
   두 capture 사이에서 정확히 비교한다.
   평가와 checkpoint의 `scope_digest`/`content_revision`은 operation arguments를 포함하므로
   서로 같은 값으로 억지로 만들지 않는다. 이 차이를 허용하는 근거는 기준 코드
   `NativeSceneAdapter.capture()`가 두 operation 모두 같은 전체 `read_scene` projection을
   `sample_projection`으로 발급한다는 사실이다. 다른 adapter에는 이 규칙을 확대하지 않는다.
4. 기존 `load_native_geometry()`와 실제 `service.verify_geometry_capture()`로 native manifest,
   motion capture digest, canonical units, frame/time, window bytes를 확인한다. reference는
   `before_export_digest` 및 원 sealed manifest를 보관하며 export request를 바꿔치기하지 않는다.
5. native export가 원 request의 authenticated succeeded terminal을 낸 뒤 기존 `seal_export()`로
   파일을 봉인한다. 새 reference는 동일 signed run의 export result에 보관한다.
6. consumer validator는 기존 nonce/artifact/importer/settings 검증을 마친 raw mesh를 사용한다.
   `ExportExpectation.reference_digests['native_geometry']`도 원 native geometry digest에 묶는다.
7. sample별 native→consumer, consumer→native 거리를 모두 측정한다. maximum이 기존
   `ExportProfile.tolerances.position_m`보다 크면 `EXPORT_MESH_SURFACE_READBACK_FAILED`다.
   기존 골격·원 의도·접촉·충돌 검사는 그대로 실행된다.
8. retained `validated.json` 재조회도 동일 context/reference로 실제 품질을 재구성한다.
   명시적 resume은 기존 read-retry 한도, sealed FBX와 원 native 요청을 유지한다.

이 flow는 새 exporter 실행이나 소비자 재시도를 자동으로 발급하지 않는다. runtime이 바뀌어
원 native reference를 인증할 수 없으면 새 성공으로 간주하지 않는다.

### 측정 정의와 계산 한도

- 입력 좌표: native와 Blender가 이미 변환·인증한 global **metres**. 추가 정렬·축 추정·scale fit 없음.
- sample: 각 frame에서 triangle에 실제 참조된 모든 vertex와 모든 triangle centroid.
- 방향: 두 mesh의 sample을 각각 반대편 triangle surface에 투영한다. vertex 순서/개수가 같다고 가정하지 않는다.
- nearest calculation: 저장소의 `TriangleSurface` BVH와 `closest_triangle()`를 재사용한다.
  전체 point×triangle 거리 행렬을 만들지 않는다. nearest 탐색의 실제 triangle check를 센다.
- 메모리: 기존 `WindowedSurfaceTrack` 예산과 consumer report 예산을 유지한다. 한 native/consumer
  frame 쌍의 BVH를 사용한 뒤 해제한다. 전체 clip의 N×M 거리 배열을 만들지 않는다.
- 결과: max·mean·sample 수·최악 mesh/frame/direction/vertex-or-centroid·실제 계산 수를 기록한다.
- 범위: **관측 frame의 sample 거리**다. surface 전체 Hausdorff bound, frame 사이 충돌 자유,
  topology/UV/material/normal/tangent/texture 동일성, 사람의 미감 판정을 입증하지 않는다.
  동일 정점 집합에 다른 face를 연결한 경우도 centroid sampling만으로 전부 식별할 수 있다고 주장하지 않는다.

## 제품 적용 전에 검토해야 하는 schema 제안

이번에 제품 model을 바꾼 것이 아니라 아래 변경을 patch로 제안한다. 새 의존성·MCP tool은 없다.

```python
class TargetImportSettings(ExportModel):
    # 기존 필드 유지
    native_mesh_mapping: dict[str, str] = Field(default_factory=dict)
    max_mesh_distance_checks: StrictInt = Field(default=10_000_000, gt=0, le=100_000_000)
```

`native_mesh_mapping`은 `{export_mesh_node_path: native_stable_mesh_id}`이며,
`mesh_mapping`은 기존대로 `{export_mesh_node_path: blender_object_name}`이다.
이름 유사성이나 입력 순서로 두 mapping을 추정하지 않는다. `include_mesh=True`일 때만
정확한 exported mesh path coverage와 일대일 native ID를 요구한다. meshless operation에는
새 geometry capture/측정을 실행하지 않는다.

새 필드, profile digest 의미, 내부 quality context/reference 및 추가 bridge read 예산은
**제품 반영 전 승인·호환성 검토 대상**이다. 추가 필드를 기본값으로 채우면 기존 serialized
profile의 canonical digest가 달라진다. 이미 발급된 plan/grant/validation을 덮어쓰거나 재서명해
계속 사용하지 않는다. 현재 서명과 native byte pin은 원본으로 보존하고, 반영 뒤 필요한 새
profile/plan을 명시적으로 발급한다. adapter fingerprint도 새 code bytes에 맞게 관측해야 한다.

`mesh_surface_readback_m`은 consumer 결과에 추가되는 지표이며 원 `QualityPolicy.required_metrics`
목록을 축소하지 않는다. threshold는 승인한 export profile의 `position_m`을 그대로 쓴다.
별도 mesh tolerance가 필요하면 그것은 별도 명시 schema 변경으로 다룬다.

## 아직 필요한 실제 native export 구현

이번 host patch만으로 일반 캐릭터 export를 활성화하지 않는다. 기준 코드의 다음 제한은 실제로 남는다.

| 위치 | 현재 제한 | 다음에 구현할 구체 동작 |
|---|---|---|
| `NativeExportAdapter._scope()` | 정확히 한 parentless Transform, identity rotation/unit scale, asset 없음 | 실제 한 RigInfo owner의 parent-closed FK skeleton과 대응 mesh/skin closure를 관측하는 별도 adapter. character R7의 rotation-only FK 범위와 맞춘다. |
| `native_export._request_arguments()` | no mesh/helpers, frame 0 시작, dense bake | 실제 exporter가 관측·검증한 mesh 포함 profile만 별도 contract로 허용. 기존 independent contract를 느슨하게 바꾸지 않는다. |
| `_set_selection()`, `_TemporarySelection` | 하나의 object, 원 selection은 empty | explicit skeleton/mesh ID 집합을 실제 session selector에 전달하고, exact pivot/selection·authored projection 복귀를 관측한다. 비어 있지 않은 원 selection은 별도 복원 증거가 있어야 한다. |
| `qualify_export_disposable()` | 독립 Transform fixture와 고정 export contract | 소유한 작은 FK chain+skin fixture에서 실제 frame range/FPS/take/axis/unit/mesh 설정, export bytes와 실제 완료 event를 관측한다. source/memory 부담을 확인하지 않고 일반 character scene을 먼저 통째로 읽지 않는다. |
| `execute_export()` / `_COMPLETIONS` | 실제 현재 process completion/readback만 허용 | 새 adapter도 같은 private observation과 실제 host artifact conformance를 결합한다. caller가 digest나 success 문자열을 제공해 등록하지 못한다. |
| host `_assert_export_source()` | 단일 selected ID | 새 native adapter의 실제 발급 scope를 전용 lowering으로 확인하고 parent/mesh closure·출력 path·budget·profile digest를 정확히 비교한다. |
| Blender `_artifact_object_rest()` | animated parentless Null만 static FBX rest decode | 실제 FBX skeleton/container/skin bind의 static 근거를 분리해 decode한다. pose frame 0을 rest로 재사용하지 않는다. bone axis correction·animated armature container·negative/nonuniform scale·shear는 관측된 importer formula가 있을 때만 지원한다. |

다음 native 구현의 함수 단위 계약은 아래와 같다. 이름은 **제안**이며 설치 SDK의 존재하지 않는
함수라고 주장하지 않는다.

```python
def observe_character_export_scope(scene, profile, reader):
    # actual stable IDs, parent closure, RigInfo ownership, mesh↔joint bindings,
    # actual export flags, full projection, explicit selection/pivot; read-only
    ...

def qualify_character_export(admitted_setup, fixture, profile):
    # one approved owned fixture; actual export call and operation-correlated
    # completion; parse exact artifact settings/topology/skin/binds; restore tab
    ...

class NativeCharacterExportAdapter(NativeSceneAdapter):
    # required_scope/capture/execute follow the existing adapter interface;
    # code-owned private qualification must carry actual scope+output results.
    ...
```

필요 증거의 최소 집합은 실제 요청·terminal, build/epoch/fingerprint, scope 전후 projection,
원 selector/pivot와 복원 관측, exporter 설정, 원 FBX bytes/hash, artifact의 skeleton/mesh/skin/bind
readback, 대응 native mesh window, Blender의 pinned decoder와 raw/canonical capture다.
현 저장소에 없는 일반 캐릭터 native 완료·skin export·container-rest 결과를 만들지 않았다.

## 적용·실행 순서와 실패 동작

1. 제안 schema/threshold/예산을 검토하고 host 변경을 적용한다. 기존 원본 state·receipt·grant는 유지한다.
2. character의 실제 writer/whole-scene source·geometry 관측 범위를 먼저 연결한다.
   마지막 checkpoint가 projection을 바꾸면 기존 geometry를 재사용하지 않는다. 승인된 plan에서
   **그 checkpoint 뒤**의 final motion/geometry capture를 구성해야 한다. source digest 비교를
   제거하거나 이전 batch에 새 source binding을 덧씌우지 않는다.
3. 위 native export adapter와 필요한 Blender static-rest 경로를 실제 installed source에 맞춰 구현한다.
4. 같은 승인된 recipe의 native final geometry → export → consumer surface/original-intent 결과 →
   publication을 한 번 연결한다. 필요한 직접 확인은 잘못된 mesh 변형을 거절하는 사례와 정상적인
   vertex 재배열을 처리하는 사례, stale native reference 거절, budget 소진 시 미게시다.
   이 목록은 자동 CI·반복 검사 지시가 아니며 이번에 실행하지 않았다.
5. native unknown은 원 요청을 observe한다. 실제 quality fail은 terminal failure로 남긴다.
   unverified consumer는 기존 명시 resume/read-retry 경로만 사용한다. 이미 publication intent가
   있으면 기존 `reconcile_publish()`를 사용하며 새 native export나 중복 게시를 만들지 않는다.

## 확인 상태

이 영역의 검토는 실제 export/consumer 호출 연결과 위 새 측정의 provenance·메모리·publication
조건에 한정했다. 부모 작업에서 통합 patch의 L1 및 적용 문맥을 확인한다. 이 문서는
pytest/실앱/Blender/FBX 왕복/CI가 통과했다고 주장하지 않는다.

### 기준 소스

- [native export의 현재 범위와 selector](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_export.py)
- [독립 export adapter](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_export_adapter.py)
- [기존 consumer capture와 품질](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/target_capture.py)
- [full scene projection 발급](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/cascadeur_side/cascadeur_complete/native_scene_adapter.py)
- [recipe export/consumer/publish 연결](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/src/cascadeur_complete/recipe_runner.py)
