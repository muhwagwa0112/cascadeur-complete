# Cascadeur MCP — 구현 착수 명세

기준일: 2026-11-15 · 문서판: r3 / 구현 전 명세 · 실행 검증: 미실행

## 1. 이번 산출물과 적용 기준

대상은 `muhwagwa0112/cascadeur-complete`의 모션 품질, 작업 자동화, 실행 안정성이다. 이 문서는 기존 소스의 결함을 고칠 함수·데이터 계약·알고리즘·실패 처리·작업 순서를 확정하기 위한 **구현 명세**다. 이번 작업에서 제품 코드 수정, 의존성 설치, 테스트 실행, Cascadeur 실행, 커밋, PR 변경, 푸시는 하지 않았다. 아래 새 타입·함수·도구 이름은 특별한 표시가 없으면 **이 저장소에 추가할 제안**이며 Cascadeur SDK에 이미 존재하는 API라는 뜻이 아니다.

분석 기준은 main `82b350cad4deda2ff5df288f46764a899115252d`, 열린 PR #8 `1bb447898e8ced16b6931b72cfeb0f563127f746`이다. 구현은 PR #8의 수정 내용을 포함하는 격리된 작업 기준점에서 시작한다. PR을 자동 병합하거나 main에 중복 패치를 적용하지 않는다. 실제 착수 시 두 ref가 바뀌었다면 이 명세의 대상 함수에 해당하는 차이만 대조한다.

기존 환경 계약은 host Python 3.12 계열, bridge Python 3.11 호환, Windows Cascadeur 2026.1.3.0.15619다. 이 설계는 이미 선언된 numpy/scipy/osqp/pydantic/stdlib를 활용한다. 다른 제품 버전 지원은 별도 `VersionProfile`의 기능·서명·후조건이 확인된 때 활성화한다. 최신 문서의 함수가 기존 설치에도 존재한다고 가정하지 않는다.

### 검수 완료의 의미

품질·자동화·안정성 세 검수역이 같은 최종 명세를 읽고 다음 고정 기준으로 판정한다.

1. 기존에 확인한 관련 결함이 구현 작업에서 빠지지 않는다.
2. 구현자가 다시 결정해야 하는 중요한 입력·출력·상태 전이·실패 정책이 남지 않는다.
3. 실제 실행, 실제 품질, 파일 공개를 서로 잘못 성공 처리하지 않는다.
4. 원본·다른 캐릭터·승인한 모션 의도를 보호한다.
5. 지원 조건과 실기기에서 확인할 조건을 구분하고, 미확인 조건에서는 명시적으로 멈춘다.

설계 통과는 이 범위에서 미해결 검수 지적이 없다는 뜻이다. 실제 장면에서의 결과 품질, 설치 버전의 API 동작, 임의의 캐릭터·모션에 대한 무조건적인 완전자동화까지 검증했다는 뜻은 아니다.

## 2. 기존 PR에서 유지할 수정

PR #8의 `*_prepare` 분리, 원자적 JSON 쓰기의 임시 파일 충돌 제거, `CASCADEUR_MCP_ROOT` 일치, 잘못된 요청 파싱 처리, batch의 개별 feature gate, license 재평가, 지원하지 않는 snapshot 경로의 명시적 거부는 기반으로 유지한다. 서비스 분할 후 수정 위치는 `change_flow.py`, `host_postconditions.py`, `ui_file_flow.py`를 따른다.

이미 PR에서 해결한 내용을 새 작업으로 중복 작성하지 않는다. PR의 테스트 통과 서술은 이 검토에서 직접 실행한 결과로 취급하지 않는다. 모션 수학, scene/source 바인딩, JobStore 경합, 결과 불명 처리, 출력의 의미 검증은 별도 수정 대상이다.

## 3. 성공 계약

하나의 `ok`로 모든 상태를 표현하지 않는다. 외부 응답에는 아래 필드를 독립적으로 담는다.

| 차원 | 값 | 성공에 필요한 증거 |
|---|---|---|
| execution | not_dispatched / canceled_pre_dispatch / rejected_pre_dispatch / succeeded / failed_after_dispatch / outcome_unknown | 자동화 명세의 ExecutionOutcome과 요청·장면 식별자, bridge receipt, 부작용의 관찰 결과 |
| quality | pass / fail / unverified / not_applicable | 실제 리그 평가 결과와 고정된 원본·접촉·의도 제약에 대한 QualityReport |
| export | not_requested / staged / validated / published / failed / outcome_unknown | 지정 take·캐릭터·프레임·단위·축의 검증과 파일 공개 journal |
| workflow | planned / authorized / queued / running / cancel_requested / waiting / succeeded / failed / canceled / outcome_unknown | 아래 공개 projection과 필요한 모든 단계의 종료 상태 및 artifact 참조 |

**Workflow의 `succeeded`**는 해당 recipe가 요구하는 execution/quality/export 조건을 모두 만족할 때만 가능하다. 단일 native execution의 succeeded는 그 단계의 실행 계약에만 해당한다. solver 실패, 0개 write, 관찰 불가, readback 생략, 다른 take의 애니메이션 존재, 파일 크기가 안정된 경우는 최종 성공의 대체 근거가 아니다. `SolverResult.status=no_change`는 원본이 요청된 제약을 이미 만족하고, 그 사실을 실제로 검사한 경우의 정상 결과다.

저장형 run/step 상태는 AUTOMATION_SPEC의 `RunState`/`StepState`가 정본이다. 공개 `workflow` 값은 저장형 `planned/authorized/queued/running/cancel_requested/succeeded/failed/canceled`를 그대로 표시한다. 저장형 `blocked`는 `blocked_reason=outcome_unknown`일 때 공개 `outcome_unknown`, 그 외는 공개 `waiting`으로 표시하며 반드시 원래 `run_state=blocked`와 구체적인 reason을 함께 반환한다. `cancel_requested` boolean은 blocked 상태에서도 보존한다. 표의 공개 요약을 별도 저장 enum으로 다시 구현하지 않는다.

레거시 `ResultEnvelope.ok`는 유지할 수 있으나 경로별 명시적 종료 계약으로 계산한다. 낮은 수준의 key write 성공은 품질 성공을 뜻하지 않으며, `quality=unverified`를 숨기지 않는다. 새로운 workflow의 `ok=True`는 최종 성공 조건이 성립한 경우에만 반환한다.

## 4. 모듈 경계와 공용 계약

공용 타입은 기존 `models.py`에 호환용 envelope를 두고, workflow·motion처럼 충분히 독립적인 새 타입은 작은 해당 도메인 모듈로 분리한다. 기존 관련 없는 파일의 이동·이름 변경·대규모 정리는 하지 않는다. 각 세부 명세의 타입 정의는 이 절의 바인딩 관계를 따른다.

| 계약 | 내용 | 소유 위치와 소비자 |
|---|---|---|
| SceneBinding | app/session epoch, 실제 scene instance, 문서 lineage | runtime 발급 → host receipt/recipe/rollback |
| SourceBinding | SceneBinding + 명시적 read/write scope + actual content_revision + sample artifact hash | sample → solve → prepare → guarded dispatch |
| MotionContext | 정확한 fps/시간, 단위 변환, 축 basis, 좌표 공간, 대상 키·프레임 | sampling/solver/quality/export |
| RigProfile | 캐릭터 소유권, semantic role, 계층·중립 자세·축·길이·skin/mesh 매핑 | cleanup/retarget/physics |
| IntentConstraints | 보존할 접촉·root 경로·키포즈·타이밍·소품·스타일 변경 허용 범위 | 모든 solver와 후검사 |
| QualityPolicy | 단위가 있는 임계치, 필수 측정 범위, 원본 대비 보존 한도 | candidate 선택과 실제 readback 판정 |
| SolverResult | 상태·수렴·잔차·실제 제약·candidate hash·목표 키 | cleanup prepare와 workflow |
| WorkflowPlan | 순서가 고정된 stage, 권한 scope, budget, 코드/adapter/profile fingerprint | prepare → 승인된 start → runner |
| RequestReceipt | request/idempotency key, durable lifecycle, dispatch/apply/observe 상태 | bridge/client/journal/recovery |
| ExportProfile | take, fps, 시간 범위, 축·단위, skeleton, root 정책, 목표 소비자, 파일 정책 | native export → 의미 검증 → publish |

`SourceBinding.binding.content_revision`은 native global revision counter로 부르지 않는다. 현재 native API에서 전체 문서 generation이 확인되지 않았으므로 `SceneBinding.revision_kind=scope_digest`라는 scoped content 해시 방식을 사용한다. `SceneBinding.scope_digest`는 canonical scope descriptor(대상 IDs·channel·frame·dependency 목록)의 hash이며, `content_revision`은 그 scope와 실제 channel 값·보간·계층·constraint·rig 의존성 데이터의 hash다. `SourceBinding.sample_digest`는 evaluated sample의 hash, `inputs_digest`는 MotionContext/RigProfile/params/manifest의 hash다. 서로 다른 projection의 hash를 직접 비교하지 않고, final runtime validation에서 각각 같은 projection으로 재계산한다. selection/playhead/view처럼 계산 입력이 아닌 값은 content digest와 분리한다.

`SceneBinding`은 파일명·경로·tab index로 식별하지 않는다. runtime epoch와 안정적으로 유지되는 실제 scene object identity를 registry에 결합한다. SDK wrapper identity의 안정성을 확인할 수 없으면 보수적으로 재바인딩을 요구한다. clone/reopen은 새 scene instance이며 `parent_snapshot_id`로 lineage만 연결한다.

`SourceBinding.complete`는 client가 임의로 넣은 True를 신뢰하는 플래그가 아니다. runtime/검증된 adapter가 operation과 RigProfile에서 required dependency closure를 도출하고, 요청 scope와 비교하고, 전체 sample coverage를 확인한 뒤에만 발급한다. 누락된 parent/constraint/support/mesh를 빼서 좁은 scope를 검증시키는 경로를 허용하지 않는다.

RecipeSpec에는 `intent: IntentConstraints`를 명시적으로 포함한다. 의미 제약은 IntentConstraints, 품질 문턱은 QualityPolicy, 허용 candidate variant는 StepPermit, 반복·시간 한도는 RunBudgets가 각각 단일 소유한다. QualityPolicy에 다른 계약의 필드를 중복 정의하지 않는다. 원본 intent/contact/support trace와 실제 수정 후 capture는 끝까지 따로 참조하여, 개선된 결과를 새 원본처럼 삼아 의도 훼손을 숨기지 않는다.

## 5. 실행 프로토콜과 이행 방식

보호 필드를 구버전 bridge가 무시한 채 mutation을 실행하는 혼용은 금지한다. 새 guarded mutation은 protocol 3 계약으로 협상한다. 현재 2.0 host/bridge와 섞이면 별도 legacy session의 read-only 기능·종료 조회만 제공하고 새 mutation은 `error_code=UNSUPPORTED_VERSION`, `result.error_details.code=PROTOCOL_MISMATCH`로 write 0건 종료한다. 양쪽 protocol version과 기능별 adapter fingerprint를 handshake에서 검사한다.

기존 `job_submit` read-only 계약을 유지한다. mutation은 새 recipe runner를 통해 정확한 per-step prepare token과 단일 사용 commit을 소비한다. workflow 권한은 파일 경로·scene lineage·캐릭터·채널·프레임·허용 operation·설정·budget를 제한하며, 임의의 `feature_id`/raw action 실행권으로 확장되지 않는다.

PR #8에서 바뀐 직접 mutation 도구의 구 이름은 deprecation shim으로 유지한다. shim은 `error_code=CONFIRMATION_REQUIRED`, `status=needs_prepare`, `result.error_details.code=NEEDS_PREPARE`, 대체 도구명과 인자를 반환한다. shim이 prepare를 대신 호출하지 않는다. snapshot 생성·scene 활성화도 부작용이므로 shim은 이들을 포함한 부작용 0건이어야 한다. 실제 prepare는 요청된 feature write를 수행하지 않지만 snapshot/working clone 활성화는 별도 journaled effect로 추적한다. 응답 snapshot/golden은 바뀐 공개 표면만 갱신한다.

기존 `ErrorCode`의 값은 유지하고 세부 이유는 기존 `result` 안의 `error_details`에 넣는다. 기존 문자열 `status` 필드는 세부 실행 상태를 표시할 수 있다. v3도 같은 envelope 정책을 사용하며, 새 상세 코드를 v2의 ErrorCode enum 값인 것처럼 보내지 않는다. 새 공개 도구는 AUTOMATION_SPEC의 `recipe_plan`, `recipe_authorize`, `recipe_start`, `recipe_status`, `recipe_cancel`, `recipe_resume`, `recipe_artifacts`가 정본이다. 데이터 모델은 `WorkflowPlan`, 실행 클래스는 `RecipeRunner`로 고정한다.

공개 API·schema·설정·지원 버전 변경은 **이 명세에서 제안한 구현 변경**이며 현재 적용된 상태가 아니다. 새 의존성은 요구하지 않는다. 실제 구현 단계에서 승인 대상 변경을 묶어 구체적으로 제시하고 적용한다.

## 6. native 기능의 계약 보강

`handlers/rigging.py::rig_state`는 장면 전체의 RigInfo/RigidBody/PhysicsSettings 개수로 특정 캐릭터의 준비 완료를 판정하지 않는다. 대상 controller→joint→chain→fulcrum/CoM의 소유 관계를 읽고 누락·중복·다른 캐릭터 참조를 구조화해서 반환한다. `handlers/generation.py::_generation_state`도 선택 layer의 key 합집합 대신 대상별 layer·keypose·시간 범위와 필요한 설정을 검사한다.

`retargeting`은 source/target이 서로 다른 layer에 있다는 조건만으로 충분하지 않다. RigProfile의 계층·semantic mapping·neutral pose·root 규칙을 검증하고, target-space 결과를 실제 샘플링하여 root/접촉/키포즈/시간 계약 및 non-target 불변성을 검사한다. 원래와 같은 유효한 결과는 `no_change`일 수 있으므로 revision 변화만 강제하지 않는다. 의도적인 sliding 보존 여부를 recipe 입력에 고정하고, 필요한 native 설정을 실제 읽거나 제어할 수 없으면 해당 recipe는 지원되지 않음을 명시한다.

`MotionStageSpec(mode=retarget)`는 `route=native|host`를 명시한다. native route는 기존 generation handler를 보강하며, host route는 새 `src/cascadeur_complete/retargeting.py`의 `retarget_pose`, `controller_targets`, `world_to_local`을 구현하고 같은 prepare/commit/actual readback으로 연결한다. host route에도 검증된 controller adapter가 필요하다. 두 route 사이에 승인하지 않은 자동 fallback을 두지 않는다. 실제 없는 generic target-space SDK를 호출하지 않는다.

`root_motion`/Motion Generation은 현재 확인된 action과 설치 버전 profile에 있는 입력만 노출한다. 임의 자연어 생성 API나 headless 실행을 가정하지 않는다. 생성된 candidate도 같은 품질 판정을 통과해야 하며 native 생성/AutoPhysics 실행을 통과 증거로 삼지 않는다.

`auto_enable`의 toggle action을 반복 호출하여 원하는 상태를 추정하지 않는다. 상태 관찰 가능한 setter/전이가 확인된 profile만 무인 실행한다. 상태를 확인할 수 없는 toggle은 `state_unknown`으로 중단한다. AutoPhysics snap의 확인 대화상자 처리 자체는 이미 있는 흐름을 유지하고, 완료는 실제 모션 readback·intent 제약으로 판정한다.

## 7. 증거와 지원 정보의 정확성

`ProductFeature.binding_material/binding_hashes`와 `LiveEvidenceStore._binding/_record_is_current/record`를 보강한다. 기존 metadata URL·test ID·fixture ID의 hash만으로 구현의 동일성을 주장하지 않는다.

제안 `ImplementationBinding`에는 feature에 실제 관련된 adapter/handler/shared guard/solver/quality 함수의 소스 bytes digest, 해당 fixture의 bytes digest, 실제 실행한 관련 test의 코드 digest, package/runtime/bridge/installed product build, native route·설정 계약, QualityPolicy와 ExportProfile digest를 담는다. feature→관련 파일/심볼의 의존 목록을 버전 관리하며, 이 목록 자체도 hash한다. source를 읽을 수 없는 패키징에서는 설치 시 생성한 검증 가능한 build manifest가 필요하다. 없으면 evidence를 현재 것으로 승격하지 않는다.

관련 없는 UI 기능 변경으로 모든 증거를 무효화하지 않는다. 공유 guard/모션 solver 변경은 그 의존 feature만 무효화한다. fixture/test **이름**만 같고 bytes가 바뀌어도 오래된 proof가 통과하지 않도록 한다. 구 schema record는 기록으로 유지하되 새 계약의 `quality_verified`로 자동 승격하지 않는다.

기능 목록은 `implemented`, `runtime_available`, `execution_observed`, `quality_verified`, `export_roundtrip_verified`를 구분한다. 숫자 하나의 “완전 지원”으로 합치지 않는다. 실제 동작한 특정 장면·프로필·버전의 근거가 없는 기능에 성공 표시를 붙이지 않는다. `docs/SUPPORT_STATUS.md`, `docs/SUPPORT_MATRIX.md`, README, MCP feature response는 같은 structured capability 결과에서 필요한 부분만 표시한다.

## 8. 구현 순서와 최소 확인 범위

| 순서 | 작업 묶음 | 먼저 필요한 이유 | 확인 범위 |
|---|---|---|---|
| 1 | PR8 기반·계약·protocol·원본/scene 바인딩 | stale write와 잘못된 target을 먼저 차단 | 바뀐 타입/핸들러 L1 및 직접 분기 L2 |
| 2 | durable receipt·mutation lane·job race·복구 | 계산 품질이 좋아도 중복 적용·오복구면 결과를 신뢰할 수 없음 | 해당 crash window와 경합 케이스 L2 |
| 3 | rig scope·단위·rotation/IK·solver 상태 | 모든 후속 품질 계산의 입력과 수학을 확정 | 각 재현 버그의 직접 수치 케이스 L2 |
| 4 | feet/contact·arms/collision·hands/intent | 품질 결함을 원래 동작 의도 안에서 수정 | 바뀐 solver/quality 모듈 L2, 공유 API 변경 때만 L3 |
| 5 | 실제 보간 readback·길이 제한·native adapters | 예측 결과와 Cascadeur에서 평가된 결과 연결 | 관련 adapter 계약과 버전별 실기기 확인 필요 목록 |
| 6 | finite recipe runner·target export·publish | 앞의 계약으로 무인 완료와 출력 보존 보장 | 상태 전이/파일 처리 직접 케이스 L2 |
| 7 | evidence·호환·사용 문서 | 구현/실행/품질의 지원 상태를 정확히 전달 | 변경된 관련 contract만 확인 |

이번은 설계 작업이므로 위 명령이나 실제 motion 작업을 실행하지 않았다. 구현 시 기본은 충분한 가장 낮은 L1~L3다. 전체 suite, 전체 build, E2E, benchmark, CI는 자동으로 이 계획에 끼워 넣지 않는다. 실제 Cascadeur/Blender를 사용하는 종단 확인이 필요한 경우 대상 clip·구체적인 위험·소요를 먼저 제시하고 별도로 승인받는다. 새 테스트는 확인된 버그 재현과 수정 검증에 필요한 최소 케이스만 추가한다. 통과 후 같은 명령을 확인차 반복하지 않는다.

각 작업의 정밀 명세는 다음 문서를 따른다. 상충하는 경우 합의 없이 한쪽을 구현하지 않으며, 최종 검수 전 이 통합본의 “합의된 보완”에 해소안을 기록한다.

- `QUALITY_SPEC.md`: 모션 입력, solver, 실제 품질 지표와 보호 조건.
- `AUTOMATION_SPEC.md`: recipe API, 단계·취소·재개, native 기능, target export/publish.
- `STABILITY_SPEC.md`: 바인딩, guarded mutation, durable receipt, unknown outcome와 복구.
- `implementation_tasks.json`: 위 설계의 파일·함수별 실행 순서와 의존 관계.
- `REVIEW_VERDICTS.md`: 같은 최종 설계에 대한 세 검수역의 최종 판정 및 검증 한계.

## 9. 실기기 확인이 남는 조건

아래는 구현 설계의 빈칸이 아니라 활성화 조건이다. 확인 전에는 결과를 통과시키거나 지원 범위를 부풀리지 않는다.

- 설치된 csc wrapper의 scene identity, modify callback의 실제 실행 시점·비동기 후속 작업 여부.
- 지정 버전에서 실제 읽을 수 있는 key/tangent/interpolation/constraint·rig state의 범위.
- AutoPosing 이후 안정된 readback, AutoPhysics 상태·완료 관측, generation/retarget 세부 설정.
- FBX exporter의 실제 settings/take/selected scope 적용과 목표 소비자의 평가 결과.
- 실제 mesh의 topology/skin weights/변형을 읽을 수 있는 범위, 각 rig의 재현 가능한 semantic mapping.

완전한 원본 의존범위를 읽을 수 없거나 UI 원자 확인의 작업 한도를 초과하는 장면, 확인하지 못한 SDK 조합, 모호한 접촉 의도, 충족 불가능한 제약은 `unsupported`, `needs_input`, `infeasible`, `outcome_unknown`처럼 원인을 구분한다. 성공 판정을 위해 threshold를 늘리거나 문제 frame을 빼거나 무조건 반복하지 않는다.

## 10. 근거

- [main 기준 소스](https://github.com/muhwagwa0112/cascadeur-complete/tree/82b350cad4deda2ff5df288f46764a899115252d)
- [PR #8 기준 소스](https://github.com/muhwagwa0112/cascadeur-complete/tree/1bb447898e8ced16b6931b72cfeb0f563127f746)
- [PR #8](https://github.com/muhwagwa0112/cascadeur-complete/pull/8)
- [Cascadeur Python API](https://cascadeur.com/python-api/csc.html): 문서에 제시된 API 존재의 근거이며 특정 설치 버전의 동일한 동작 증거는 아님.
- [Cascadeur Retargeting](https://cascadeur.com/help/category/219), [AutoPhysics](https://cascadeur.com/help/tools/physics_tools/autophysics), [Unbaking](https://cascadeur.com/help/category/221), [Motion Generation](https://cascadeur.com/help/category/309): native workflow 전제와 결과 한계.
- [Blender FBX 구현](https://github.com/blender/blender-addons/blob/main/io_scene_fbx/fbx_utils.py): FBX timecode legacy/new 값 및 TCDefinition 분기의 1차 소스. 8000 이상은 문서의 추측을 확정 동작으로 취급하지 않으며 지원 버전을 명시한다.

## 11. 교차검수에서 합의한 경계

- **Delayed callback의 guard 거절:** dispatch는 있었어도 실제 write 직전 guard가 거절하면 요청 feature write는 0일 수 있다. receipt는 `write_phase=not_started|started|completed|unknown`, `failure_kind`, `recovery_eligible`를 따로 기록한다. `guard_rejected_before_first_write`에는 rollback을 금지한다. feature dispatch 여부만으로 rollback을 허용하지 않는다.
- **실제 부작용 분류:** `animation.transform_get(refresh=True)`는 내부 `modify_update`를 수행하므로 순수 읽기로 취급하지 않는다. 결과 불명 동안 receipt 조회 대신 이를 호출하지 않는다. 평가 갱신도 별도 stage/receipt와 같은 mutation lane을 사용한다.
- **분류의 공용화:** `classify_effect(operation_name, normalized_arguments)`를 execute/batch/job_submit/runner에 함께 적용한다. operation 이름만 보고 read-only job 또는 batch로 평가 갱신을 우회하지 못하게 한다.
- **출력 교체:** 기본은 원자적 no-clobber다. 기존 `allow_overwrite=True`를 새 workflow의 무조건 교체권으로 승격하지 않는다. `replace_path`는 exact path·만료·`overwrite_semantics=replace_any_current_content`가 명시적으로 승인된 경우만 허용한다. 일반 `os.replace`에 기존 파일 hash와 조건부 교체를 묶는 CAS 보장이 있다고 주장하지 않는다. 그 보장이 필요한 경우 해당 OS/filesystem primitive가 없으면 unsupported다.
- **증거 파일 보존:** exporter staging, 검증 후 sealed candidate, 공개를 위한 publish temporary는 구분한다. sealed와 final은 별 inode로 만들고, 공개 파일의 나중 변경이 검증 증거를 바꾸지 않도록 한다. byte-copy 이후 hash와 validation artifact identity를 확인한 뒤 같은 filesystem에서 원자 공개한다.
- **긴 clip의 지원 경계:** transport/window 분할이 source의 원자성이나 native reader의 한계를 해결한다고 주장하지 않는다. 전체 dependency의 일관성을 보증할 수 있는 guard 범위에서는 전역 해와 연속된 chunk를 사용한다. guard budget나 필수 adapter가 미충족이면 이유와 정확한 범위를 반환한다. 임의 길이를 처리했다고 표시하지 않는다.
- **긴 clip의 수학:** window는 transport/geometry memory 단위다. 해는 전역 key 변수·D1/D2·contact anchors를 공유하는 sparse 문제 하나로 고정한다. 독립 window solve를 overlap 평균으로 붙이는 방식을 동시에 지시하지 않는다.
- **IK 투영 정책:** 도달 불가능한 목표의 기본 결과는 infeasible다. 미리 허용한 projection envelope 안에서만 target wrist 자체를 투영하고 elbow/wrist와 잔차를 함께 반환한다. scalar 거리만 잘라 원래 wrist를 그대로 두지 않는다.
- **최종 소비자 품질:** target validator는 joint/root 동등성에 더해 원본 intent/contact/support drift와, mesh를 포함하면 실제 skinned surface collision을 검사한다. 최종 소비자의 Capture가 QUALITY_SPEC의 `validate_export_roundtrip`으로 이어진다. source와 target의 임의 ID 동일성이나 action 존재만으로 통과시키지 않는다.
- **초기 계획 안의 자동 진행:** 필요하다면 contact detection 정책, key insertion/bake 허용, 제한된 correction variant를 처음의 구체적인 recipe grant에 포함한다. 그 범위 안의 각 contact·candidate마다 다시 승인받지 않는다. 의도 모호성, 새 대상·경로, 허용량 초과는 새 plan/needs_input을 요구한다.

