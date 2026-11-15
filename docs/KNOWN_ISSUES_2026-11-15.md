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

## 후속 구현: bind 입력과 복구 결과 연결

원격 개선안 `6a9338c`를 다시 fetch해 변경 없음을 확인했다. 설치 실행 파일의 ProductVersion/FileVersion은 모두 `2026.2.3.0.16863`이며 기존 프로세스 PID 8012와 script server가 응답한다.

- 설치 SDK의 공식 `commands/go_to_bind_pose.py`와 `MeshDependency.inverse_bind_matrices()`를 근거로 순서 있는 `MeshObject.linked_objects`를 연결하는 compact bind reader를 입력 수집에 추가했다. 현재 pose나 behaviour 기본값을 rest로 사용하지 않는다. 관찰한 mesh bind evidence를 source/rig structure fingerprint에 포함하며 parent closure가 없는 객체의 local rest는 누락으로 남긴다. native scene 좌표/단위이며 물리 단위나 FBX 좌표 변환을 인증하지 않는다.
- rollback host postcondition은 checkpoint의 실제 부모 폴더에서 successor 파일을 찾는다. 중첩 snapshot 경로 한 건의 직접 host check를 통과했다. 원 결과의 snapshot ID도 파일명에서 추측하지 않고 manifest UUID를 사용한다.
- native recovery는 predecessor/successor identity, 동일 lineage/새 instance, successor manifest·scope와 실제 저장 bytes를 함께 확인한다. native proof가 빠졌다고 legacy byte-copy 성공으로 전환하지 않는다. 실제 임시 파일을 사용하는 좁은 host predicate check에서 native resave를 허용하고 누락 proof·다른 lineage·stale workspace·같은 instance·변경된 bytes를 거부했다.
- 늦게 도착한 recovery receipt와 이미 소비된 rollback token은 원 요청을 재확인한다. 복구 요청을 새로 만들거나 재실행하지 않는다.
- independent position writer에 요청별 private failure attestation 경로를 추가했다. native transaction이 동기적으로 정상 반환하고 완료된 setter prefix와 전체 projection·post-source가 정확히 일치하는 실제 실패만 대상으로 한다. setter 도중 예외·미완료/재진입 callback·native 예외·scope 밖 변경은 계속 unknown이다. 성공 trial을 실패 증거로 재사용하지 않는다.

실앱의 첫 입력 진단에서 Cascy의 `bindShapeMatrix`가 Animation data여서 불필요한 static gate에 막혔다. 공식 native bind 경로는 이 행렬을 적용하지 않으므로 이 조건을 분리했다. 이제 해당 값은 현재 frame 한 개의 진단 metadata로만 보존하고 native→FBX 변환은 unobserved로 명시한다. inverse-bind 자산의 유효성·순서 매핑·공유 joint 일치·부모 closure 조건은 유지했다.

수정 후 최종 reader bytes를 별도 진단 namespace에서 실제 앱에 읽혔다. 기존 product 모듈을 reload하거나 adapter를 등록하지 않았다. 샘플의 선택된 288 객체 중 mesh 하나에서 **57 global bind / 57 local rest**를 관찰했고 입력 draft의 57 객체 row에도 연결됐다. 오류는 없으며 나머지 231 객체는 `BIND_POSE_NOT_OBSERVED`로 남는다. 증거는 `artifacts/native-r4/bind-input-observation-b59c3315-c90a-4c93-831b-ec34771b5601.json`, SHA-256 `ec6c2be686710e8ede9620890bfa58df2e658541f2d9c6e5da47329e000b763c`이다. 원본 `Cascy.casc`의 SHA-256 `0d6ae171db831e4738fddc86014fd0a0b77e9991c74308972603810ee34fc723`은 동일하고 원래 빈 탭으로 복원했다. 진단 artifact는 ignored local 산출물이며 Git에 포함하지 않는다.

새 writer의 실제 실패→인증 terminal failure→one-attempt permit→조건부 복구 실행은 아직 관찰하지 않았다. 아래 `c9c355...`의 qualification은 이전 게시 코드 `f9e0cfa`에 대한 결과이며 이번 bridge bytes의 새 자격 확인을 대신하지 않는다. Cascy의 계산 채널 재로드 차이, native FPS/물리 단위·semantic roles/joint limits, 전체 recipe와 원본 intent를 결합한 consumer 품질/최종 게시 문제도 남아 있다.

### host recipe·cleanup 연결 수정

- native checkpoint 관측의 실제 `project_load` 필드를 strict host 모델에서 보존한다. 일반 checkpoint는 현재 소유 탭을 저장하므로 `same_instance`로 처리하고, bootstrap의 별도 instance와 구분한다. receipt의 두 경로·실제 파일 hash·successor manifest·epoch·digest를 함께 확인한다.
- native 평가가 끝난 다음 source/baseline capture를 실행한다. 이미 runtime이 발급한 canonical batch의 source binding을 나중에 다른 쓰기 scope로 덮어쓰지 않는다.
- verifying/checkpointing에서 막힌 run의 resume은 기존 receipt 검증을 다시 예약할 때 blocked 상태를 해제한다. 늦은 terminal 성공이 확인된 checkpoint/export의 관측을 재구성할 수 있으며, 알려진 host postcondition 실패는 계속 차단한다. 원 요청을 다시 dispatch하지 않는다.
- cleanup fitting은 정확한 operation/arguments로 native reader가 자체 source scope와 전체 projection digest를 발급하도록 연결했다. host motion sample의 digest를 native 전체 scene digest로 보내지 않는다. 보존한 canonical capture·평가 receipt를 재인증하고 scene/lineage/epoch/checkpoint/쓰기 인자가 유지되는지 확인한 뒤 후보를 발급한다.

필요한 좁은 host 확인만 실행했다. 위 실제 bootstrap/checkpoint 산출물 두 개의 strict parsing과 임시 저장소의 blocked resume/late terminal/cancel/known-postcondition-failure 재현은 exit 0이었다. cleanup은 실제 sparse LINEAR/STEP fitting의 기존 `[0,2,4]` key grid와 canonical source 요청·stale capture/scene 변경 거부를 제한된 service doubles로 확인했다(exit 0). 이 host 재현은 인증된 queue나 전체 실앱 recipe의 성공 증거가 아니다. broad suite/build/CI는 실행하지 않았다.

당시 runtime source에는 profile·ownership 발급 경로가 없어 active scene과 파일 bootstrap 후 continuation이 `RIG_MAPPING_AMBIGUOUS`에서 차단됐다. 아래 후속 구현에서 별도 runtime target 관측을 연결했다. 전체 `recipe_authorize → recipe_start → quality → publish`는 여전히 미완료다.

### runtime target 발급과 명시적 conversion policy 연결 — 11월 16일 후속

원격 개선안 branch를 다시 fetch했으며 최신 문서는 여전히 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`다. r4의 16개 연결과 실제 SDK 증거 범위를 다루는 전체 목표를 유지한다. 이번 변경은 그중 target/profile 경계와 모션 입력·rest 좌표 연결을 구현한 것이며 전체 목표 완료가 아니다.

- `system.observe_recipe_target`을 양쪽 읽기 전용 정책과 실제 native dispatcher에 연결했다. 이미 발급된 현재 source와 target/profile/context의 정확한 digest를 묶고, native RigInfo ownership 또는 현재 프로세스에서 자격 확인된 독립 객체 identity를 읽는다. 실제 layer 소속·Basic 부모·공급된 native inverse-bind rest·mesh 존재/소유권을 확인한다. 임의 identity rest나 현재 pose를 bind evidence로 대체하지 않는다.
- 관측은 bounded private registry에 보존한다. private verifier는 현재 활성 scene/source와 전체 native projection을 다시 읽는다. caller hash, `complete`, capability flag만으로 발급할 수 없다. profile의 역할명·관절 제약·물리 변환은 명시적 선언이며 native semantic/physical 증명이나 writer 권한으로 승격하지 않는다. 기존 source의 비어 있지 않은 profile/ownership이 충돌하면 새 관측으로 덮어쓰지 않는다.
- recipe의 plan/authorize/start/continuation 공통 preflight에 이 경로를 연결했다. clip context 할당 전 메모리 예산을 확인한다. source 자체의 scope와 mutation/receipt/authorization 규칙은 보존한다.
- `resolve_motion_inputs`는 `overrides.conversion_policy`의 FPS numerator/denominator 쌍·길이 scale·proper basis로 누락된 변환만 채운다. 관측값 충돌·stale draft와 누락 ownership/root/rest/joints는 계속 거부한다. provenance는 `native_physical_metadata_verified=False`다. 관측 frame에 FPS timing을 명시했을 때만 time grid를 유도하며 명시적 sample time 누락을 FPS로 대체하지 않는다.
- builder가 이미 관측한 dependency 조상의 native local rest까지 보존한다. styling은 native local 4×4 rest 회전을 `B R Bᵀ`로 한 번 변환한다. 좌표 미표기 legacy quaternion과 global rotation batch는 명확히 unsupported다. anatomical axis는 기존 canonical rest-relative 계약을 유지하며 native axis 증명으로 해석하지 않는다.
- native motion-capture verifier가 기존 private `verify_capture`를 호출하도록 고쳤다. 정확한 현재 batch 확인과 함께 실제 `evaluation_receipt_digest`를 반환하므로 host의 기존 평가 receipt 요구를 약화하지 않는다.

최종 bridge fingerprint는 `3ff8c7df77ac3e06b26dec11504facce071c970c9780ca7006d2f3c5ba008dfb`, runtime epoch는 `864bf15b-f40a-4a0c-b6a3-17fc145b07bc`다. 설치된 Cascadeur Pro `2026.2.3.0.16863`의 새 프로세스 PID 37144에서 좁은 independent adapter를 다시 자격 확인했다. 실제 쓰기/readback과 새 파일 저장·복제·후속 checkpoint 증거 SHA-256은 `b10f2144a5048452fc75987bc13b8699aa5750d387418425a546d2b121306d33`이다. complete-scene/interpolation/export adapter를 이 프로세스에 등록한 결과는 아니다.

실제 host `recipe_observe_target` → 인증 queue → native reader → strict host DTO → private verifier가 통과했다. observer 요청 `6845c918-37e0-449c-a00b-1d5fe0000fd2`와 verifier 요청 `7b0fc8bd-6e57-4ef9-bc5c-d823d93ec0a6`은 모두 `effect_class=none`, terminal `succeeded`다. queue drain을 깨우는 데 공식 localhost script server를 사용했으며 native 응답은 double로 대체하지 않았다. 대상은 별도 임시 단일 객체·frame 0이며 48 FPS/cm 변환은 진단용 명시 선언이다. native 물리 메타데이터나 전체 recipe 실행 증거가 아니다.

같은 최종 bridge에서 위조 관측과 native bind 없는 임의 identity rest를 거부했다. 임시 객체에 guarded native 위치 `[0.25,0.5,-0.75]`를 쓴 뒤 readback을 관찰했고, 이전 target의 재검증은 `SCENE_CHANGED`로 거부했다. 이 쓰기는 진단 callback의 guarded SDK 경로이며 위 두 인증 queue 읽기 요청과 구분한다. 확인용 탭을 닫고 원래 빈 scene을 복원했다. local artifact 폴더는 `artifacts/native-r4/isolated-runtime/snapshots/recipe-target-wire-ab417643-ff6c-4afb-a54b-0b881380b93e`이며 `host-observed.json` SHA-256은 `cd58274e6cf22066be77240bd9cce06cdaa1c7c31da4285c8e57d368dc3fbc9b`, `native-boundary.json`은 `d7f91d5322a2e82cf0676540e7c616de5c58f262985be9e08d79f21530be9b25`다. ignored 진단 산출물이며 인증키/queue/state 파일은 Git에 포함하지 않는다.

필요한 host 경계 재현에서 conversion 충돌·누락·stale 거부, target digest/ownership/private issuance 거부와 예산 선차단을 확인했다. 비항등 basis의 styling 직접 수치 재현은 목표 회전 오차 `5.59e-17 rad`와 native 역변환 일치를 보였다. 이는 solver 수치 확인이며 실제 rotation write/quality pass가 아니다. public tool 설명의 golden 항목도 의도한 설명에 맞춘다. broad suite/build/CI는 실행하지 않았다.

남은 문제는 일반 character의 writer qualification, native root/joint/axis/물리 메타데이터, Cascy 첫 저장의 정확한 수치 차이, 실제 실패 후 조건부 복구, 원본 intent에 결합한 consumer quality·최종 게시다. 새 target 발급의 실앱 확인은 독립 객체에 한정되며 Cascy의 supplied rest/mesh target 발급과 full recipe 성공은 아직 확인하지 않았다. 앱 재시작 중 한 번 발생한 `Error syncing with master instance`는 오류 창 종료 후 정상 실행했으며 원인을 확정하거나 제품 수정으로 해결했다고 주장하지 않는다.

## P0: 남아 있는 실행 제한

### 전체 project 로딩에서 발견한 설정 손실

설치 SDK는 `ProjectLoader.load_from`을 domain 데이터만 읽는 minimal load로 설명하고, 추가 데이터를 포함하려면 `DataSourceManager.load_scene`을 사용하라고 명시한다. 기존 bootstrap/restore는 minimal API를 사용했다.

사용자 원본 대신 기존 독립 객체 파일에서 만든 별도 입력의 `scene/scene_settings.json`에 FPS 48과 UnitLength `m`를 명시했다. 실제 앱에서 minimal load 후 저장한 파일은 FPS 30/`cm`로 바뀌었고 `gravity_per_frame()`은 `1.0888888835906982`였다. complete load는 실제 True 반환, 새 소유 placeholder 재사용 및 완료 메시지를 관찰했고 저장 후에도 FPS 48/`m`를 보존했다. 이때 `gravity_per_frame()`은 `0.4253472089767456`이었다. 진단 증거 `artifacts/native-r4/full-project-io-0e3e13c7-3d62-4b7f-bc98-33e86308b857/observed.json`, SHA-256 `cf2fc13ecc27ffc0eec2c0b5070c05f4f21223b44ba30f31fe0056b7115164e3`. 확인용 탭만 닫고 이전 빈 탭을 복원했다.

bootstrap/restore는 이제 잠근 입력 bytes를 새로운 소유 working path에 복사하고 전체 project API로 열도록 연결한다. 기존 탭·원본 입력을 열기 대상으로 쓰지 않으며, 예상하지 못한 탭 전환·완료 부재는 unknown으로 남긴다. 복원 후 전체 projection exact equality도 그대로 요구한다. 이 변경만으로 Cascy의 1 ULP 재로드 차이가 해결됐다고 주장하지 않는다.

새 앱 프로세스에서 repository의 최종 helper를 직접 실행했다. runtime fingerprint `e394531202d3cc6c2a4452650d4d47661944404486b411e19246f0c7accf448f`, epoch `c09edd0b-5db8-437d-b139-e858afef2d72`에서 `DataSourceManager.load_scene`의 동기 True 반환과 대상 `csc.domain.Scene`의 정확한 완료 이벤트를 확인했다. 새 파일 저장 후 archive의 FPS 48/UnitLength `m`/Gravity 980이 유지됐으며 원본 SHA와 기존 탭을 보존했다. 진단 탭은 닫고 이전 빈 탭으로 돌아왔다. 증거 `artifacts/native-r4/isolated-runtime/snapshots/project-copy-check-e9cde440-aacd-4e20-a760-5d3cd9105e19/observed.json`, SHA-256 `978de80cb88662a188152f725cd8b4a6d81f0a336c2cbfbc92803884d751681f`. 이는 helper의 실제 복사→load→save 확인이며 변경된 bootstrap/restore 전체 authorization 경로나 Cascy strict restore의 새 qualification을 의미하지 않는다. 이전 프로세스의 adapter 자격은 승계하지 않았다.

같은 fingerprint/epoch에서 `NativeSceneAdapter.execute`의 파일 bootstrap → 후속 checkpoint → `qualify_restore`의 실제 새 탭 복원을 독립 객체 입력으로 이어서 실행했다. 전체 projection exact equality, 동일 lineage/새 instance, 원본 파일·장면 불변과 이전 탭 복귀를 확인했다. bootstrap backup/working, 후속 backup/working, restored working 다섯 파일 모두 FPS 48/UnitLength `m`/Gravity 980을 보존했다. 증거 `artifacts/native-r4/isolated-runtime/snapshots/full-project-entrypoint-e3ae79b1-e9b7-44c8-8056-8f62ef87fa48/observed.json`, SHA-256 `49e194608f523549e2ab841ddb0fcbc0661125a50087574958dba786b05c78cd`. 자격 확인용 private source와 실제 executor를 사용했으며 wire authorization/terminal failure/one-attempt permit은 실행하지 않았다. 이 확인으로 production operation을 새로 등록하지 않았고 Cascy의 strict restore도 재실행하지 않았다.

파일 안의 FPS/UnitLength를 읽을 수 있다는 사실은 현재 편집 중인 장면의 live getter를 확보했다는 뜻이 아니다. SettingsHandler의 조회 후보들은 0/빈 문자열을 반환했으며 기본값으로 사용하지 않았다. 또한 [공식 Measurements 문서](https://cascadeur.com/help/category/302)는 내부 Cascadeur 단위와 scene system units를 구분하므로 UnitLength 문자열만으로 좌표 scale을 치환하지 않는다. 입력 context의 물리 시간·단위 인증은 계속 제한된다.

설치 stub의 `SettingsHandler`는 이름 두 개를 받는 typed getter만 제공하며 키 열거·존재 확인·메모리 내 scene-settings 직렬화 API는 노출하지 않는다. 현재 `MotionContext`의 시간·길이·basis는 명시한 변환 정책으로 source/capture digest에 결합하고 `native_physical_metadata_verified=False`를 유지한다. 저장 파일의 값도 현재 unsaved 설정의 인증으로 승격하지 않는다.

### 전체 로더 적용 뒤 Cascy의 정확 비교 차단

같은 `e394531...` 프로세스에서 Cascy 파일 bootstrap을 실제 실행했지만 `NATIVE_COMPLETION_UNKNOWN: clone or source changed during checkpoint`로 차단됐다. 새 복원은 도달하지 않았다. 증거 `artifacts/native-r4/isolated-runtime/snapshots/cascy-full-project-restore-860a1a77-5bbd-465c-bd2a-3e67eeadc71b/observed.json`, SHA-256 `94d60532704edb5b7db01dc35df12364bbbcd5312fc983e55facbcab2060fbd4`.

별도 소유 복제본에서 load 직후 → 첫 save → 둘째 save를 비교했다. 첫 save에서 3개 owner의 26개 data 값이 바뀌었고 data 외 top-level projection은 같았다. 두 save 뒤 projection은 서로 정확히 같았다. Position/Rotated Additional Vector/Corrected Vector/Angle Rotation/Twist 등의 작은 수치 차이도 임의 cache로 제외하지 않았다. 증거 `cascy-project-save-difference-80290d50-417d-4c32-8222-b99b4b5e8e28/observed.json`, SHA-256 `8bdc1b43c44c5490c003026faf8e04cf98654e213de44e31c78610da8566039d` (위와 같은 snapshots root).

명시적인 native interpolation reload/interpolate를 load와 save 사이에 넣은 별도 진단에서도 evaluated projection은 load 직후와 같았고 첫 save 후에는 달랐다. 증거 `cascy-load-evaluate-save-11e876a3-055a-44f9-a2a1-4b253fc72aee/observed.json`, SHA-256 `80d04439549cab209bafe2a2af352113284ef6c4f1b73fad82e95466d4089353`. 저장·재로드의 정확한 authored/computed 경계가 확보되지 않아 허용 오차나 이름 규칙을 추가하지 않았다. 실패한 소유 탭을 관찰한 후 닫았으며 원본 샘플과 파일·기존 빈 탭을 보존했다. 전체 project 설정 손실 수정과 Cascy 전체 projection 안정성은 서로 다른 문제다.

### 후속 연결: 실제 보간·키 쓰기·animated FBX·소비자

원격 r4 branch는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`로 다시 확인했다. 아래의 이전 fingerprint별 관찰은 역사적 결과이며, 현재 작업의 후속 관찰과 구분한다.

- 실제 독립 Transform에서 5 frames / keys 0,2,4의 LINEAR, STEP, 두 혼합 구간을 관측했다. baseline과 각 key/XYZ perturbation을 합한 40 trials에서 local/global 값과 finite influence의 최대 오차가 0이었다. 이 증거는 private process-local 발급이며 caller 문자열로 모델을 활성화하지 않는다. controller·parent·additive·rotation·key insertion으로 확대하지 않는다.
- 새 existing-position writer는 실제 `domain.modify`가 요청 키뿐 아니라 중간 보간값·전역 위치·Global Matrix·Inverse Matrix도 갱신한다는 직접 관찰에 맞췄다. 네 채널의 전체 frame을 finite model로 예측하고 나머지 전체 projection 불변을 비교한다. 명시적 SceneUpdater 호출은 없지만 native transaction의 graph/interpolation 갱신은 포함한다. durable explicit evaluation receipt는 별도로 요구한다.
- Global Position 출력 cache를 직접 쓰면 요청 결과가 native graph에 반영되지 않았다. 관찰한 부모 없는 항등 Transform 범위에서는 local/global 좌표가 같으므로 두 요청 모두 authoritative Local Position을 쓴다. 요청 space·요청 data ID·실제 write data ID·항등 변환 조건을 source scope에 결합하고 요청 space의 실제 값으로 readback한다. 최종 writer의 local/global × 두 operation × 네 보간 조합 **16 trials 모두 실제 통과**했다. fingerprint `003f4a9c045e8f03937d1d9fa03723e885d2e7162bd11efa7491b0d649d1b0d9`, epoch `2f71dd44-8838-4eb4-9ab7-4ffa8b3c8fff`, writer digest `67353833a81cf4d7a4e01dc8afe7df294a6a77b5189cf05db446ba82e98b4097`; 같은 프로세스의 40-trial model digest `1a29f0711fb2cd9a79a3682fba30987ebad007e2a247071781f7b01fb7235257`.
- SDK timestamp footer checksum과 값 없는 Compound property를 엄격하게 처리하도록 parser를 수정했다. `AnimationStack`에 구간 property가 없는 실제 파일은 정확한 `Takes/Take/LocalTime`을 사용한다. 중복·역전·stack와 take의 불일치는 거부한다. 전역 timeline은 해당 take를 포함해야 하며 take 구간·dense XYZ coverage는 정확히 검증한다.
- 실제 animated export에서 같은 scene의 Success(4) `Custom export: animation exported from 0 to 4`를 관찰했다. `export-qualification-c83964e0-a4d5-4625-bb48-f8fdaa0d208a/raw.fbx`, 21,984 bytes, SHA-256 `664bc7eb45f7144e0918646d6f5c7cf6596ea304f29abdb92ce680ce0b51069d`는 footer·0..4 take·세 XYZ dense channel 구조 검증을 통과했다. 구조 통과는 motion 품질 판정이 아니다.
- 이후 `export-qualification-29c8d37b-542e-48fe-a42a-5c5ba1beb46a`에서 같은 basename의 두 실제 animated export와 엄격한 host parser를 함께 통과했다. confirmed artifact는 22,000 bytes, SHA-256 `78987eac813f944fbb5e711da757de2177b714329eced9b9301e739369ddf0dd`; retained `observed.json` 결과 digest `ac9d62370f9de5792614fbe2b1cbaffc3239398626afcc97458f8f6bb11ea67b`. 결과는 `observed_structural_only`, 남은 reason은 `TARGET_ROUNDTRIP_UNVERIFIED`이다.
- 위 실제 파일을 설치된 Blender **4.5.8 LTS**의 background/factory-startup 독립 프로세스에서 기존 adapter로 import했다. exit 0, FBX 7700 import FINISHED, 실제 Action `MCPExportQualification|raw|Anima_Layer`와 0..4의 다섯 월드 sample을 읽었다. identity diagnostic basis의 Blender-world metres: `[0,0,0]`, `[.01,0,.005]`, `[.02,0,.01]`, `[.01,-.005,.015]`, `[0,-.01,.02]`. 회전 rest delta는 거의 항등값이었다. retained `diagnostic-blender-jw1pxnhi/capture.json`의 rest는 `artifact_static_model_and_template`이며 독립 native source-rest 관측으로 취급하지 않는다. 원본 intent/reference 및 production target context·품질·trusted issuance는 남아 있다.
- native checkpoint restore 실행기는 관찰한 checkpoint bytes와 전체 projection을 새 owned tab에 재로드·저장·readback하고 새 instance/동일 lineage를 발급하도록 연결했다. signed one-attempt permit, 원 실패 terminal receipt, 원본·현재 source·epoch를 요구하고 unknown에는 실행하지 않는다. runtime의 정상 rollback successor 승인도 private completed observation/permit/source에 결합했다. 실제 실패 후 conditional recovery는 원 실행기의 partial-write attestation까지 필요하다.
- Cascy의 실제 strict restore는 `scene-qualification-21cd9a87-ca8b-4f9b-b70d-c31fff08a8f2`에서 `RECOVERY_NATIVE_READBACK_DIFFERS`로 차단됐다. reload 뒤 일부 계산 채널(Position, RotatedAdditionalVector, CorrectedVector, AngleRotation, Twist 등)에 float32 약 1 ULP 차이가 관찰됐다. 정확한 전체 projection 비교를 완화하지 않았으며 해당 복원 route는 자격 확인되지 않았다. 원본과 checkpoint 파일을 보존했고 실패한 소유 탭만 관찰 후 닫았다. base reader·평가·checkpoint 확인과 strict restore 확인은 별도 명령으로 나눴다.
- 네 명시 command를 bridge source에 추가했다: 빈 current tab에서 실행하는 `Qualify independent motion adapter`, `Qualify complete scene adapter`, `Qualify independent export adapter`, 그리고 활성 owned checkpoint를 요구하는 `Qualify checkpoint restore adapter`. 실제 관찰이 성공한 해당 process만 operation을 등록한다. source/packaged installer가 이 bridge를 복사하지만 현재 실행 중인 앱의 설치 폴더를 교체하지 않았다. import/startup에서 scene 생성이나 export를 자동 실행하지 않는다.
- 같은 `003f4a9c...` 프로세스의 `scene-qualification-f210d89c-7542-442c-9fab-5ef44b61dc55`는 reader·bootstrap·평가·후속 checkpoint와 소유 탭 정리를 모두 완료했다. 증거 SHA-256 `e2439e25398c6c39d6be9e30663664152471e3bd8dd2948545e093007f358680`. 공식 script server 응답 제한을 넘겼지만 요청을 재실행하지 않고 fsync progress의 `qualification=observed`, `restore_owned_tabs=complete`와 실제 등록 상태를 별도로 확인했다. `export-qualification-3056d4e1-60ac-44c5-b61b-ca6b1113ee0d`의 두 실제 export와 strict parser도 통과해 `io.export_fbx`가 좁은 관찰 profile로 등록됐다. 증거 SHA-256 `9eb406e828976051f985d71c0db7f6f2d908b387b1a9aeb5f67c571966fd8009`; quality는 `not_evaluated`, target roundtrip은 `unverified`다.
- 독립 객체 복원 진단 `independent-restore-qualification-768ef976-3edd-4f74-a979-901997df2995`는 reload·저장 후 전체 projection이 anchor와 정확히 같았지만 SDK의 `/` 경로와 요청의 `\` 경로 문자열 비교로 차단됐다. 이를 canonical `Path.resolve()` 비교로 수정했다. 실패한 소유 탭/파일은 자동 폐기하지 않으며 current tab은 source로 돌려놓도록 보완했다. 이 변경 뒤에는 새 앱 프로세스에서 다시 관찰해야 한다. Cascy의 실제 계산값 차이는 이 경로 표기 수정으로 해결되지 않는다.

### 이전 bridge의 새 프로세스 확인 (f9e0cfa)

경로 비교 수정 후 Cascadeur를 깨끗이 재시작했다. 아래 결과는 fingerprint `c9c355557327272b66c421db25078d8b852e69be4c9e83133b2f8aa143e60238`, epoch `056bc310-81fe-41d6-a6df-9fe15eea66d8`에서 직접 관찰했다. 앞선 fingerprint의 자격 확인을 가져와 등록하지 않았다.

| 실제 확인 | 현재 결과 |
|---|---|
| finite model / existing-key writer | 40 model trials와 16 writer trials 통과. model digest `00d08e2f4f316dd5d096d399cbea28f4d159bd4cd01f71e0f5bac23c9ff54d45`, writer digest `e820a1578a0bdfdc330ba95b1095afdf6d1d7dfaff190f0b465c96df4aed6024` |
| Cascy reader/bootstrap/evaluation/checkpoint | `scene-qualification-cdb32a03-650c-4899-b7c8-4f4f0d98f37d`, 증거 SHA-256 `688962c274ca03a6e409030a7ecccf0a043e4f6adbf4a253bcd091150c7a6db1`. server 응답 제한 뒤 재실행 없이 실제 완료·등록·소유 탭 정리를 확인 |
| animated FBX 두 회와 export 등록 | `export-qualification-ae8e1a25-485c-41d0-a0ac-d54276dd8a6c`, 증거 SHA-256 `234024125375cdf13ef4c08a4a0c44e031f5666073cffd579c0db626c608ad3a`. `io.export_fbx` 등록, 새 독립 객체의 실제 required scope와 complete capture 연결 확인. 생산 recipe export는 실행하지 않음 |
| 독립 객체 exact restore 명령 | `independent-restore-qualification-192ae0dd-c021-41fd-8a10-989b19af9cd1/restore-qualification-dd62ba67-291e-4087-903e-dec7b63b22ca.json`, 증거 SHA-256 `bfe81cc28e48aab0e87a17eb33fbdf60f415edc612df80072f35d18017fbd25d`. 실제 새 tab reload·save·전체 projection exact equality·동일 lineage/새 instance·원본 보존·탭 복원 통과. `safety.rollback` primitive 등록 |

당시 등록된 일곱 operation은 위 관찰 범위에서만 활성화됐다. 이후 코드 변경·앱 재시작 뒤의 현재 자격을 의미하지 않는다. 실제 실패 후 recovery의 partial-write attestation/인증 terminal failure/one-attempt signed permit, Cascy의 strict restore, 일반 controller·rotation·key insertion, 원본 intent/rest와 결합한 roundtrip 품질·최종 게시는 여전히 미완료다. 독립 객체 복원 성공으로 실패한 Cascy 복원을 통과 처리하지 않는다. 전체 r4 목표를 완료로 표시하지 않았다.

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

native key-layout reader와 private evaluated-capture 발급기를 host capture/인증 경로에 연결했다. 캡처된 값·현재 활성 scene·source·실제 evaluation receipt·build/epoch가 일치해야 한다. SDK key의 영구 ID가 없어 `layer_frame_locator`로 표현하며, existing-key fitting과 영구 ID가 필요한 insertion을 구분한다. 당시 perturbation 자격 확인이 없어 `qualified_models`는 빈 목록이었다. 후속 명시 qualification은 위의 좁은 독립 position 모델만 활성화한다. key-layout 관찰은 별도 명시 요청일 때만 수행한다.

### export 진단 중 native 메모리 급증

Cascy 작업 복제본이 열린 상태에서 export 확인 helper를 실행하던 중 Cascadeur가 응답하지 않고 working set이 106,283,376,640 bytes까지 증가했다. 첫 `discover.fbx`는 생성되지 않았고 해당 폴더 `export-qualification-0141b7cf-67e6-4c09-b0b7-196e82cabb3f`는 비어 있다. 당시 helper가 첫 fixture 생성 전에 이전 Cascy scene 전체를 읽도록 되어 있었으므로 **정확한 실패 호출은 알 수 없다.** fixture나 exporter가 원인이라고 단정하지 않는다. 최초 빈 탭과 소유한 작업 복제본만 열린 것을 확인한 뒤 해당 프로세스를 종료했고 원본 hash와 기존 request/receipt/unknown은 보존했다. 새 프로세스는 빈 장면으로 복구했다.

기본 `Qualify native adapter`는 다시 좁은 독립 Transform 확인만 수행한다. complete-scene 자격 확인은 별도 명시 경로로 분리했으며 기본 import/명령에서 Cascy를 자동으로 열지 않는다. export helper는 이전 장면의 값 전체를 읽기 전에 객체 수를 확인해 비어 있지 않으면 차단한다. native 호출마다 fsync된 작은 phase marker를 남기고, 설치된 공식 Add.Transform callback을 domain transaction에서 사용한다. 이 조치는 native 단일 호출의 메모리를 강제 제한하는 장치가 아니며, 앞선 대규모 할당 원인을 해결한 것으로 취급하지 않는다.

빈 장면의 별도 진단에서는 fixture 생성과 실제 20,704-byte FBX 생성까지 진행했고 같은 scene의 synchronous Success(4) 메시지 `Custom export: animation exported from 0 to 0 (only one frame)`를 관찰했다. 최초 코드가 다른 exporter의 완료 문구를 기대해 파일이 있어도 `NATIVE_COMPLETION_UNKNOWN`을 반환했다. 실제 관찰한 0..0 범위와 정확한 메시지만 완료로 인정하도록 수정했다. 다른 frame 범위는 dispatch 전에 차단한다. 두 번째 확인 파일은 별도 폴더의 같은 basename을 사용해 basename에 따른 take 이름 변경을 피한다.

이 파일의 SHA-256은 `00bb1f05965e4072f3b6aa696034756b937357932b39b6759075a9d0f4094be6`이다. 엄격한 FBX parser는 timestamp footer 시작 값이 고정 상수와 다르므로 `FBX_FOOTER_UNSUPPORTED`로 거부한다. diagnostic parse에서는 길이 162-byte footer의 version 7700·zero padding·마지막 signature가 관찰됐지만 checksum 변형을 검증한 것은 아니다. 또한 값이 없는 `('TimeMarker', 'Compound', '', '')` property와 AnimationStack의 span 부재가 확인됐다. native 성공 메시지가 이 구조 차이를 해결하지 않으며 parser 기준을 낮춰 통과시키지 않았다. production export adapter는 아직 등록하지 않았고 소비자 import·왕복 품질·최종 게시 성공을 주장하지 않는다.

이전 게시 시점의 bridge fingerprint `db01c92a1805438bc726e8891327f4250c9cd907e9d9be22c505ad8613e0828c`, epoch `37fdbe5a-2147-4a4d-9807-843741256e84`의 새 프로세스에서 좁은 세 operation을 다시 자격 확인했다. 증거는 `qualification-96cbbdd1-996c-422a-b6ab-02fa4f8e1f8d/qualification.json`, SHA-256 `05b9e394f25e0dea756f5e9b61498d781a1b6a393f6db26cb603b727c6679a4a`이다. complete-scene 자격 확인은 `not_requested`이며 interpolation_refresh는 등록하지 않았다. 같은 프로세스의 빈 장면 export 진단은 `export-qualification-7e6a1897-1d98-4fc3-91cf-446349fde304`에서 실제 완료·artifact hash·take 읽기·고정 host parser 호출까지 진행한 뒤 `NATIVE_EXPORT_SETTINGS_UNVERIFIED / FBX_FOOTER_UNSUPPORTED`로 차단됐다. 앱은 정상 응답했고 확인용 탭을 제거해 최초 빈 장면으로 복원했다. 이 결과로 앞선 character-scene 메모리 문제나 전체 recipe가 해결됐다고 보지 않는다.

### 기존 결과 불명 요청 보존

첫 번째 실앱 확인 중 이중 token 소비 결함으로 기본 runtime에 요청 `ffb7fc8e-417c-454c-a669-48625a086eda`가 `outcome_unknown`으로 남았다. 기본 root는 `%USERPROFILE%\AppData\Local\CascadeurMCP\cascadeur-complete`이다. 이 요청의 원 token·인증키·요청·terminal receipt는 변경하지 않았다. 현재 projection이나 파일 부재만 보고 과거 결과를 실패로 재분류하지 않으며 원 요청을 다시 실행하지 않는다.

이 기본 root의 새 변경은 unresolved effect로 차단된다. 이후 독립된 disposable 확인은 위의 새 runtime root에서 진행했으며, 그 성공으로 기존 unknown이 해결되었다고 주장하지 않는다. 기존 요청을 권위 있는 증거로 종결할 reconciliation 어댑터는 아직 없다. 상태 폴더 삭제·새 키 생성·receipt 수정으로 해제하면 안 된다.

### 일반 리그·파일 입력·복구 (R4-01/03/04/05/06/10/11)

- saved active scene의 좁은 Transform 및 위 Cascy `.casc` 파일 복제·평가·후속 checkpoint를 관찰했다. 현재 build/bridge/epoch에서 별도 자격 확인이 필요하다. 저장되지 않은 원본, FBX bootstrap, 일반 controller/physics 쓰기와 전체 리그 closure 지원은 남는다.
- `StageEffect`, signed `BootstrapGrant`, 독립 checkpoint step, typed checkpoint observation, continuation, derived-target mapping, original-receipt resume은 host와 runner에 연결했다. 하지만 실제 생성자의 파생 ID/rig ownership 관측이 없으면 관련 plan은 차단된다.
- host retarget lowering은 canonical source와 실제 target rest/controller 관측을 요구한다. template/explicit rig, native retarget/generation/unbaking/AutoPhysics의 해당 build 완료·설정·closure 어댑터는 자격 확인되지 않았다. 전체 recipe는 preflight에서 차단된다.
- 조건부 rollback permit/receipt와 실제 새-tab native restore executor를 연결했다. 원 실행기의 partial-write attestation과 인증 실패/permit가 없는 conditional recovery는 계속 차단한다. unknown/부분 변경을 추정으로 복구하지 않는다.
- bootstrap은 이미 저장된 원본을 Windows read-sharing lock 안에서 hash/reload하고 live projection과 비교한다. 원본을 먼저 저장해 덮어쓰는 방법으로 복제하지 않는다.

### 실제 모션/키/품질 (R4-02/07/08/09/15)

- readonly native 입력 reader와 inspect/resolve 도구를 연결했다. 설치 SDK에서 관측되지 않은 물리 FPS, 단위, basis, rest, semantic roles, ownership은 기본값이나 이름 추정으로 채우지 않는다. draft는 완전한 rig profile 또는 mutation 권한이 아니다.
- key layout은 source/capture/build/evaluator/key/mode/tangent/influence provenance와 runtime의 원 관측 일치를 요구한다. 독립 position의 세 finite interpolation model은 명시한 실제 perturbation 뒤에만 활성화한다. key insertion executor, 일반 controller/rotation 모델은 남는다. 호출자가 digest/evidence 문자열만 주어 활성화할 수 없다.
- sparse key fitting/retarget 후보, triangle 평가와 필수 품질 계약을 연결하고 dense n*n 추정 대신 capture·행렬·factorization을 반영한 공유 예산을 적용했다. 대규모 실제 클립 peak 측정은 하지 않았다.
- native evaluated transform capture는 위 한 joint/frame의 실제 경로를 관찰했다. 전체 humanoid capture, reskin/mesh/controller-target 관측과 물리 메타데이터는 미완성이다. 필수 관측을 인증할 수 없으면 해당 품질은 `unverified`다. sampled metric을 연속 구간 충돌 자유나 full-rig pass로 확대하지 않는다.

### FBX와 소비자/게시 (R4-12/13/14)

- runner에 export prepare → native receipt → immutable seal → validation → target capture → publication을 연결했다. publish journal은 이미 게시된 동일 결과를 권한 만료보다 먼저 원 기록으로 reconcile하며 취소/중단 후 중복 게시를 막는다.
- consumer raw/canonical capture는 단위·basis·sample time·원본 profile/intent·rest alignment·정확한 실행 컨텍스트와 artifact bytes에 묶어 인증한다. quaternion 비교도 실제 정렬과 provenance가 필요하다.
- 해당 build 전용 selected-object FBX helper·실제 artifact 설정 parser·explicit export adapter qualification을 연결했다. 실제 Blender import/sample은 위 독립 object 파일 한 개에서 관찰했다. 원본 기준 왕복 품질·최종 FBX 게시를 실행하지 않았다. host 코드 연결이나 구조 pass로 납품 성공을 보고하지 않는다.

### 설치 교체 (R4-16)

- upgrade-state helper를 source install/packaged installer에 연결했다. 첫 새 host import보다 앞서 기존 state·snapshots·logs·policy와 인증키·request/receipt/unknown·recipe/resume·publish 상태를 보존한다. 실행 중 Cascadeur에는 교체를 거부한다.
- 별도 fixture의 10개 상태 파일 byte 보존, 반복 호출과 충돌 거부 및 PowerShell parse를 확인했다. 실제 설치 교체·frozen build·전역 MCP 재등록은 실행하지 않았다. 설치 시 host/bridge를 함께 갱신하고 앱을 깨끗이 재시작해야 한다.

## 수행한 좁은 확인과 미확인 범위

아래 결과는 각 변경 시점의 필요한 대상 확인이며 최종 tree 전체 회귀 결과가 아니다.

- recipe r4 경계: `tests/test_recipe_execution.py -k r4_`: 3 passed, 13 deselected.
- 모션 draft/실제 metric/host retarget 등: 대상 4 passed, 8 deselected. moving support 대상 1 passed, 11 deselected. 앞선 sparse/보간 대상 5 passed, 6 deselected.
- 11월 16일 existing-key piecewise fitting 대상 `-k 'observed_piecewise or different_driver_key_grids'`: 2 passed, 13 deselected. 이후 추가된 native capture/최종 tree 전체를 검증한 결과는 아니다.
- export r4 경계: `tests/test_export_r4_boundaries.py`: 4 passed.
- 실제 FBX footer/Compound 결함에 대한 추가된 두 대상 test: 2 passed. 전체 export suite 결과가 아니다.
- 변경한 native reader/모션 모듈의 문법 확인, PowerShell 5개 파일 parse와 위의 직접 실앱 queue 확인.
- 의도한 두 공개 입력 도구와 준비 도구 설명에 맞춰 MCP golden surface를 실제 schema로 갱신했다. golden 재생성 자체를 독립 검증 통과로 세지 않는다.

실행하지 않은 범위: 전체 pytest, broad lint/format/typecheck, CI, installer/release build, full humanoid cleanup recipe, 실제 실패 후 conditional rollback/AutoPhysics, 원본 품질에 결합한 consumer roundtrip/FBX 납품, 대규모/장시간 benchmark. 기존 r3 메모의 과거 테스트 숫자를 이번 최종 상태의 전체 검증 결과로 이월하지 않았다.

다음 구현은 character-scene native 할당 급증 원인, 실제 실패 후 복구 attestation, 일반 controller/rest/물리 메타데이터 관측과 원본 품질에 결합한 소비자 왕복을 연결해야 한다. 좁은 fixture 성공을 일반화하지 않으며 원본·unknown·권한·receipt를 보존하고 자격 확인된 build/operation/rig 범위만 활성화한다.

관련 문서: [README](../README.md), [workflow](MOCAP_CLEANUP_WORKFLOW.md), [r4 개선안](implementation/cascadeur-motion-r4/ADDITIONAL_IMPLEMENTATION_PLAN.md).
