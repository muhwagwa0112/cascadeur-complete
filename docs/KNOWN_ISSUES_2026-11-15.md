# Cascadeur motion r4 구현 상태와 남은 문제

작성일: 2026-11-15 / 갱신: 2026-11-16 (Asia/Seoul)  
대상: `feat/cascadeur-motion-r3`, r3 구현 `c55981152f40afee24221d70aa972235754a105e` 이후 변경  
읽은 원격 개선안: `origin/docs/cascadeur-motion-plan-r4`, `6a9338c`의 `ADDITIONAL_IMPLEMENTATION_PLAN.md`와 `implementation_tasks.json` 전체  
고정 제품 목록: Cascadeur `2026.1.3.0.15619` / 실제 설치·실행: `2026.2.3.0.16863`

## 이번 변경과 관찰 범위

r4의 16개 항목을 대상으로 source/완료/receipt, 입력 수집, recipe lowering·bootstrap·checkpoint·resume, 실제 품질 관측 계약, sparse 자원 예산, export·consumer capture·publish 및 설치 상태 보존 경로를 연결했다. **16개 항목 전체의 실앱 지원이나 전체 제작 파이프라인 완료를 의미하지 않는다.** native 동작과 리그 범위별로 아래 제한이 남는다.

실제 실행 파일은 `C:\Program Files\Cascadeur\cascadeur.exe`이며 ProductVersion과 FileVersion은 `2026.2.3.0.16863`이다. PE의 숫자 고정 버전 `2026.2.0.16863`과 구분해 실행 중인 파일의 ProductVersion을 읽도록 했다. 설치된 SDK와 embedded Python 3.11에서 실제 callback·저장·재로드를 관찰했다. 기존 2026.1 지원 표기를 2026.2 전체 지원으로 바꾸지 않았다.

`independent-transform-key0-v1`은 다음 조건에만 완전한 원본 바인딩을 발급한다.

- `Basic`, `Node3d`, `Transform`만 가진 부모 없는 단일 객체.
- 하나의 보이는 잠금 해제 layer, frame 0의 기존 key 하나, 최대 256 frames, cycle 없음.
- 모든 data 값·setting·behaviour link·layer·section을 읽을 수 있을 것.
- operation은 `animation.transform_set`의 frame 0 local position, `safety.bootstrap`, `safety.checkpoint` 세 가지.

자격 확인은 `Cascadeur Complete.Qualify native adapter` 명령으로 명시적으로 실행한다. disposable 장면의 실제 위치 변경/readback, native save completion, source/clone projection 동등성과 후속 checkpoint를 관찰한 증거 바이트를 현재 build·epoch·loaded fingerprint에 묶는다. 프로세스 재시작이나 bridge 변경 뒤에는 다시 확인해야 한다. import 시 자동 장면 변경은 하지 않는다.

## 직접 실앱 확인

새 파일과 작업 복제본만 사용했다. 최종 확인의 runtime root는 `D:\CS_MCP\artifacts\native-r4\isolated-runtime`이다. 전역 Codex 등록이나 설치 스크립트는 실행하지 않았다.

| 실제 진입점/관찰 | 결과 |
|---|---|
| native SDK 자격 확인 | callback/readback과 source·backup·working·후속 backup/working 저장 완료를 관찰. 증거 SHA-256 `8899b4576a12dcd61cb0954f5d373d6a5fc6b43f942e91efbf3be0826994c0d1` |
| 인증 queue → 초기 복제 | 요청 `7959d5c0-76a4-4d2e-b15a-44422423df15`, terminal `succeeded`, 별도 instance/동일 lineage와 checkpoint manifest 발급 |
| 공개 service prepare → commit → 별도 readback | 요청 `f58f5a85-d0bd-4a0f-b52c-1c6c9389f247`, 위치 `[3.25, -1.5, 0.75]`, terminal `succeeded` |
| 후속 checkpoint 준비/커밋 | 요청 `4051f616-fa7f-48e2-9dab-4e821712424f`, native 저장 완료와 terminal `succeeded` |
| 같은 토큰 재호출 | 새 쓰기 없이 요청 `4051f616-fa7f-48e2-9dab-4e821712424f`의 원 성공 영수증 반환 |
| 입력 자동 수집 | 실제 객체/채널/layer/key를 읽고 runtime이 발급한 관측만 인증. FPS·단위·basis·역할·character ownership은 누락 항목으로 반환 |
| 원본 보존 | `isolated-source.casc` 13,545 bytes, 작업 전후 SHA-256 `08d7537209d810833135ee3ddc8a3333f7b7984c37a98618b29e921a6a40afe7` 동일 |
| UI 복원 | 확인용 두 탭만 닫고 최초 빈 `untitled.casc` 탭으로 복원. checkpoint 파일과 receipt는 보존 |

초기 복제 확인은 좁은 adapter의 queue/ChangeManager 경로를 직접 사용했다. 전체 `recipe_authorize → recipe_start` 실행이나 휴머노이드 recipe 검증으로 해석하면 안 된다. 후속 checkpoint는 공개 service prepare/commit 경로를 사용했다.

실앱 연결 과정에서 두 결함을 수정했다. runtime wrapper와 내부 실행기가 confirmation token을 이중 소비해 첫 쓰기부터 거부하던 결함을 고쳤다. recipe가 사용하던 `snapshot` 기능 ID가 registry에 없어 후속 준비가 `KeyError`로 실패하던 문제도 고쳤으며, 자격 확인된 runtime 안전 기능으로 노출했다. prepare 자체는 저장이나 장면 변경을 하지 않는다.

## P0: 남아 있는 실행 제한

### 11월 16일 추가 구현과 실제 관찰

`native-model-assets-v1` reader와 checkpoint/evaluation adapter를 추가했다. 객체·behaviour의 모든 선언된 property와 순서 있는 reference, 실제 data/setting 값과 description, layer/key/section/tangent, folder 순서, cycle, cluster 및 지원되는 embedded Mesh/MeshDependency 내용을 읽는다. 관찰된 dangling reference는 없는 항목으로 명시하며 0으로 대체하지 않는다. 외부 asset link, 알 수 없는 asset/property, stacked additive content 또는 예산 초과는 차단한다. 이 projection은 checkpoint/evaluation의 source closure이며 물리 단위나 전체 리그 품질의 증거는 아니다.

`.casc` 파일 입력의 실제 hash/길이와 파일 잠금을 source에 결합하고 별도 instance·별도 document lineage의 작업 복제본을 만든다. host plan → input binding → signed bootstrap grant 경로에 해당 manifest와 typed capability를 연결했다. native 보간 완료는 callback 반환과 실제 projection으로 관찰하고, 인증 queue의 성공 terminal receipt가 기록된 뒤에만 evaluated capture에 사용할 수 있다.

아래는 bridge fingerprint `6e8a8955c2a68a94dc75cff27f4d596aaa575d09fe990da8c3a82d8bc5730e63`, runtime epoch `9950961c-4b7a-4cd4-a7e8-5921a0ef460e`에서 관찰했다. 이후 bridge가 변경되고 앱도 재시작했으므로 **현재 프로세스나 최종 tree의 재자격 확인을 대신하지 않는다.**

| 관찰 | 결과와 범위 |
|---|---|
| shipped `Cascy.casc` reader/복제/평가/checkpoint | 289 objects, 7,895 data, Mesh/MeshDependency 두 asset, 108 dangling setting references 관찰. 별도 disposable 자격 확인 증거 SHA-256 `2a2e2241f075c4b0918f0b3a620c46c8519250f3f602799fc8960afdf5740a50` |
| 인증 queue의 파일 bootstrap | 요청 `c5a6ce7a-3e59-4657-831e-7385b52d200b` succeeded. 새 instance `8a8f6ea3-098d-4f8f-9f0d-cfd0d4c7be04`, 새 lineage `6e706ab6-5722-45e6-a504-a77788c2eb24` |
| 공개 service prepare/commit의 보간 평가 | 요청 `c08100d2-49de-4eac-9609-a321585288ed` succeeded, durable terminal receipt 뒤에 private evaluation 발급 |
| 실제 evaluated transform capture/인증 | 실제 RigInfo 소속 joint 하나의 frame 0 global position/rotation을 독립 SDK read로 읽고 인증. capture digest `a315a942a92a2af02631b17401a773a950056d5a1510bd8cae1a4f72ae1b7fb5` |
| 원본 파일 | `C:\Program Files\Cascadeur\samples\Cascy.casc`, 4,069,260 bytes, SHA-256 `0d6ae171db831e4738fddc86014fd0a0b77e9991c74308972603810ee34fc723` 보존 |

파일 bootstrap 확인은 직접 queue/ChangeManager 준비 경로였으며 전체 `recipe_authorize → recipe_start` 실행은 아니다. capture의 FPS 30/1, metres/unit 1, identity basis는 명시한 확인용 변환 정책이며 Cascy의 실제 물리 메타데이터로 관찰한 값이 아니다. RigInfo의 `Units` 필드는 컨트롤러 단위 목록이며 물리 길이 단위가 아니다. 성공한 capture로 native FPS·단위·rest/semantic roles·finite interpolation model·전체 humanoid 품질을 입증하지 않는다.

native key-layout reader와 private evaluated-capture 발급기를 host capture/인증 경로에 연결했다. 캡처된 값·현재 활성 scene·source·실제 evaluation receipt·build/epoch가 일치해야 한다. SDK key의 영구 ID가 없어 `layer_frame_locator`로 표현하며, existing-key fitting과 영구 ID가 필요한 insertion을 구분한다. 실제 perturbation 자격 확인이 없으므로 `qualified_models`는 빈 목록을 유지한다. key-layout 관찰은 별도 명시 요청일 때만 수행한다.

### export 진단 중 native 메모리 급증

Cascy 작업 복제본이 열린 상태에서 export 확인 helper를 실행하던 중 Cascadeur가 응답하지 않고 working set이 106,283,376,640 bytes까지 증가했다. 첫 `discover.fbx`는 생성되지 않았고 해당 폴더 `export-qualification-0141b7cf-67e6-4c09-b0b7-196e82cabb3f`는 비어 있다. 당시 helper가 첫 fixture 생성 전에 이전 Cascy scene 전체를 읽도록 되어 있었으므로 **정확한 실패 호출은 알 수 없다.** fixture나 exporter가 원인이라고 단정하지 않는다. 최초 빈 탭과 소유한 작업 복제본만 열린 것을 확인한 뒤 해당 프로세스를 종료했고 원본 hash와 기존 request/receipt/unknown은 보존했다. 새 프로세스는 빈 장면으로 복구했다.

기본 `Qualify native adapter`는 다시 좁은 독립 Transform 확인만 수행한다. complete-scene 자격 확인은 별도 명시 경로로 분리했으며 기본 import/명령에서 Cascy를 자동으로 열지 않는다. export helper는 이전 장면의 값 전체를 읽기 전에 객체 수를 확인해 비어 있지 않으면 차단한다. native 호출마다 fsync된 작은 phase marker를 남기고, 설치된 공식 Add.Transform callback을 domain transaction에서 사용한다. 이 조치는 native 단일 호출의 메모리를 강제 제한하는 장치가 아니며, 앞선 대규모 할당 원인을 해결한 것으로 취급하지 않는다.

빈 장면의 별도 진단에서는 fixture 생성과 실제 20,704-byte FBX 생성까지 진행했고 같은 scene의 synchronous Success(4) 메시지 `Custom export: animation exported from 0 to 0 (only one frame)`를 관찰했다. 최초 코드가 다른 exporter의 완료 문구를 기대해 파일이 있어도 `NATIVE_COMPLETION_UNKNOWN`을 반환했다. 실제 관찰한 0..0 범위와 정확한 메시지만 완료로 인정하도록 수정했다. 다른 frame 범위는 dispatch 전에 차단한다. 두 번째 확인 파일은 별도 폴더의 같은 basename을 사용해 basename에 따른 take 이름 변경을 피한다.

이 파일의 SHA-256은 `00bb1f05965e4072f3b6aa696034756b937357932b39b6759075a9d0f4094be6`이다. 엄격한 FBX parser는 timestamp footer 시작 값이 고정 상수와 다르므로 `FBX_FOOTER_UNSUPPORTED`로 거부한다. diagnostic parse에서는 길이 162-byte footer의 version 7700·zero padding·마지막 signature가 관찰됐지만 checksum 변형을 검증한 것은 아니다. 또한 값이 없는 `('TimeMarker', 'Compound', '', '')` property와 AnimationStack의 span 부재가 확인됐다. native 성공 메시지가 이 구조 차이를 해결하지 않으며 parser 기준을 낮춰 통과시키지 않았다. production export adapter는 아직 등록하지 않았고 소비자 import·왕복 품질·최종 게시 성공을 주장하지 않는다.

최종 bridge fingerprint `db01c92a1805438bc726e8891327f4250c9cd907e9d9be22c505ad8613e0828c`, epoch `37fdbe5a-2147-4a4d-9807-843741256e84`의 새 프로세스에서 좁은 세 operation을 다시 자격 확인했다. 증거는 `qualification-96cbbdd1-996c-422a-b6ab-02fa4f8e1f8d/qualification.json`, SHA-256 `05b9e394f25e0dea756f5e9b61498d781a1b6a393f6db26cb603b727c6679a4a`이다. complete-scene 자격 확인은 `not_requested`이며 interpolation_refresh는 등록하지 않았다. 같은 프로세스의 빈 장면 export 진단은 `export-qualification-7e6a1897-1d98-4fc3-91cf-446349fde304`에서 실제 완료·artifact hash·take 읽기·고정 host parser 호출까지 진행한 뒤 `NATIVE_EXPORT_SETTINGS_UNVERIFIED / FBX_FOOTER_UNSUPPORTED`로 차단됐다. 앱은 정상 응답했고 확인용 탭을 제거해 최초 빈 장면으로 복원했다. 이 결과로 앞선 character-scene 메모리 문제나 전체 recipe가 해결됐다고 보지 않는다.

### 기존 결과 불명 요청 보존

첫 번째 실앱 확인 중 이중 token 소비 결함으로 기본 runtime에 요청 `ffb7fc8e-417c-454c-a669-48625a086eda`가 `outcome_unknown`으로 남았다. 기본 root는 `%USERPROFILE%\AppData\Local\CascadeurMCP\cascadeur-complete`이다. 이 요청의 원 token·인증키·요청·terminal receipt는 변경하지 않았다. 현재 projection이나 파일 부재만 보고 과거 결과를 실패로 재분류하지 않으며 원 요청을 다시 실행하지 않는다.

이 기본 root의 새 변경은 unresolved effect로 차단된다. 이후 독립된 disposable 확인은 위의 새 runtime root에서 진행했으며, 그 성공으로 기존 unknown이 해결되었다고 주장하지 않는다. 기존 요청을 권위 있는 증거로 종결할 reconciliation 어댑터는 아직 없다. 상태 폴더 삭제·새 키 생성·receipt 수정으로 해제하면 안 된다.

### 일반 리그·파일 입력·복구 (R4-01/03/04/05/06/10/11)

- saved active scene의 좁은 Transform 및 위 Cascy `.casc` 파일 복제·평가·후속 checkpoint를 관찰했다. 현재 build/bridge/epoch에서 별도 자격 확인이 필요하다. 저장되지 않은 원본, FBX bootstrap, 일반 controller/physics 쓰기와 전체 리그 closure 지원은 남는다.
- `StageEffect`, signed `BootstrapGrant`, 독립 checkpoint step, typed checkpoint observation, continuation, derived-target mapping, original-receipt resume은 host와 runner에 연결했다. 하지만 실제 생성자의 파생 ID/rig ownership 관측이 없으면 관련 plan은 차단된다.
- host retarget lowering은 canonical source와 실제 target rest/controller 관측을 요구한다. template/explicit rig, native retarget/generation/unbaking/AutoPhysics의 해당 build 완료·설정·closure 어댑터는 자격 확인되지 않았다. 전체 recipe는 preflight에서 차단된다.
- 조건부 rollback permit/receipt 경로는 유지하지만 실제 native rollback executor는 없다. unknown/부분 변경을 추정으로 복구하지 않는다.
- bootstrap은 이미 저장된 원본을 Windows read-sharing lock 안에서 hash/reload하고 live projection과 비교한다. 원본을 먼저 저장해 덮어쓰는 방법으로 복제하지 않는다.

### 실제 모션/키/품질 (R4-02/07/08/09/15)

- readonly native 입력 reader와 inspect/resolve 도구를 연결했다. 설치 SDK에서 관측되지 않은 물리 FPS, 단위, basis, rest, semantic roles, ownership은 기본값이나 이름 추정으로 채우지 않는다. draft는 완전한 rig profile 또는 mutation 권한이 아니다.
- key layout은 source/capture/build/evaluator/key/mode/tangent/influence provenance와 runtime의 원 관측 일치를 요구한다. native reader/발급기는 연결했지만 실제 perturbation으로 자격 확인된 interpolation model과 key insertion executor는 없다. 호출자가 digest/evidence 문자열만 주어 활성화할 수 없다.
- sparse key fitting/retarget 후보, triangle 평가와 필수 품질 계약을 연결하고 dense n*n 추정 대신 capture·행렬·factorization을 반영한 공유 예산을 적용했다. 대규모 실제 클립 peak 측정은 하지 않았다.
- native evaluated transform capture는 위 한 joint/frame의 실제 경로를 관찰했다. 전체 humanoid capture, reskin/mesh/controller-target 관측과 물리 메타데이터는 미완성이다. 필수 관측을 인증할 수 없으면 해당 품질은 `unverified`다. sampled metric을 연속 구간 충돌 자유나 full-rig pass로 확대하지 않는다.

### FBX와 소비자/게시 (R4-12/13/14)

- runner에 export prepare → native receipt → immutable seal → validation → target capture → publication을 연결했다. publish journal은 이미 게시된 동일 결과를 권한 만료보다 먼저 원 기록으로 reconcile하며 취소/중단 후 중복 게시를 막는다.
- consumer raw/canonical capture는 단위·basis·sample time·원본 profile/intent·rest alignment·정확한 실행 컨텍스트와 artifact bytes에 묶어 인증한다. quaternion 비교도 실제 정렬과 provenance가 필요하다.
- 해당 build 전용 selected-object FBX helper와 실제 artifact 설정 parser를 추가했다. 실제 완료·설정 확인은 위 진단 범위이며 production adapter는 등록되지 않았다. 실제 Blender import·왕복 품질·최종 FBX 게시를 실행하지 않았다. host 코드 연결이나 정적 fixture로 납품 성공을 보고하지 않는다.

### 설치 교체 (R4-16)

- upgrade-state helper를 source install/packaged installer에 연결했다. 첫 새 host import보다 앞서 기존 state·snapshots·logs·policy와 인증키·request/receipt/unknown·recipe/resume·publish 상태를 보존한다. 실행 중 Cascadeur에는 교체를 거부한다.
- 별도 fixture의 10개 상태 파일 byte 보존, 반복 호출과 충돌 거부 및 PowerShell parse를 확인했다. 실제 설치 교체·frozen build·전역 MCP 재등록은 실행하지 않았다. 설치 시 host/bridge를 함께 갱신하고 앱을 깨끗이 재시작해야 한다.

## 수행한 좁은 확인과 미확인 범위

아래 결과는 각 변경 시점의 필요한 대상 확인이며 최종 tree 전체 회귀 결과가 아니다.

- recipe r4 경계: `tests/test_recipe_execution.py -k r4_`: 3 passed, 13 deselected.
- 모션 draft/실제 metric/host retarget 등: 대상 4 passed, 8 deselected. moving support 대상 1 passed, 11 deselected. 앞선 sparse/보간 대상 5 passed, 6 deselected.
- 11월 16일 existing-key piecewise fitting 대상 `-k 'observed_piecewise or different_driver_key_grids'`: 2 passed, 13 deselected. 이후 추가된 native capture/최종 tree 전체를 검증한 결과는 아니다.
- export r4 경계: `tests/test_export_r4_boundaries.py`: 4 passed.
- 변경한 native reader/모션 모듈의 문법 확인, PowerShell 5개 파일 parse와 위의 직접 실앱 queue 확인.
- 의도한 두 공개 입력 도구와 준비 도구 설명에 맞춰 MCP golden surface를 실제 schema로 갱신했다. golden 재생성 자체를 독립 검증 통과로 세지 않는다.

실행하지 않은 범위: 전체 pytest, broad lint/format/typecheck, CI, installer/release build, full humanoid cleanup recipe, native rollback/AutoPhysics, 실제 consumer import/FBX 납품, 대규모/장시간 benchmark. 기존 r3 메모의 과거 테스트 숫자를 이번 최종 상태의 전체 검증 결과로 이월하지 않았다.

다음 구현은 character-scene native 할당 급증 원인을 단계별로 좁히고, finite interpolation perturbation·controller/rest/물리 메타데이터 관측, 실제 SDK FBX footer/property 변형과 animated range, 소비자 import/왕복 품질 순으로 남은 경계를 연결해야 한다. 원본·unknown·권한·receipt를 보존하며 자격 확인된 build/operation/rig 범위만 활성화한다.

관련 문서: [README](../README.md), [workflow](MOCAP_CLEANUP_WORKFLOW.md), [r4 개선안](implementation/cascadeur-motion-r4/ADDITIONAL_IMPLEMENTATION_PLAN.md).
