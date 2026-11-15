# Cascadeur motion r4 구현 상태와 남은 문제

작성일: 2026-11-15 / 갱신: 2026-11-16 (Asia/Seoul)  
대상: `feat/cascadeur-motion-r3`, r3 구현 `c55981152f40afee24221d70aa972235754a105e` 이후 변경  
읽은 원격 개선안: `origin/docs/cascadeur-motion-plan-r4`, `6a9338c`의 `ADDITIONAL_IMPLEMENTATION_PLAN.md`와 `implementation_tasks.json` 전체  
고정 제품 목록: Cascadeur `2026.1.3.0.15619` / 실제 설치·실행: `2026.2.3.0.16863`

## 이번 변경과 관찰 범위

### 최신 추가: 설치 상태 이관과 보관 자료 삭제 범위

이전 turn은 실제 export 왕복·게시 성공과 commit `ff1f2b8` 푸시로 진행됐다. 기존 16개 r4 목표를 유지하며 R4-16의 source/frozen 상태 연속성 경로를 이어 확인했다. 이번 변경은 native bridge bytes를 바꾸지 않으며 전역 설치·인증키·기존 unknown을 교체하지 않았다.

- source installer는 의존성 준비 전 old state를 미리 staging에 복사하고, 이후 hook에서 최신 backup을 다시 병합했다. 준비 중 바뀐 mutable 파일은 conflict로 설치를 중단했고, 삭제된 파일은 초기 사본에서 부활할 수 있었다. 초기 복사를 없애고 최종 idle 확인 뒤 이동한 old runtime backup을 authoritative state로 한 번 이관한다. 기존 policy가 없을 때만 default policy를 넣고 새 runtime import보다 먼저 완료한다.
- frozen installer는 persistent state와 policy를 제자리에 보존하는데 hook이 과거 backup을 다시 병합했다. 이 병합을 제거했다. source도 activation 전 이관을 마쳤으므로 hook은 상태 복사를 반복하지 않는다. transaction backup은 rollback 용도로 남긴다.
- state copier는 같은 root뿐 아니라 서로 중첩된 source/target도 거부한다. 기존 키·receipt·unknown·claim bytes를 해석하거나 재서명하지 않는 원칙과 reparse/conflict/hash 검사를 유지한다.
- `build-release.ps1`의 `artifacts` 전체 재귀 삭제는 retained native runtime·receipt·증거도 지울 수 있었다. 소유한 빌드 폴더 7개와 생성 파일 4개만 정리한다. 삭제 전 workspace/artifacts의 직접 하위 절대 경로·타입·reparse 경로를 확인하고 `native-r4` 같은 무관 sibling을 보존한다. 빌드 자체는 실행하지 않았다.

필요한 직접 확인은 Windows PowerShell 5.1의 임시 root 복사/이동과 새 host 코드의 인증 조회로 제한했다. 증거는 ignored `artifacts/native-r4/upgrade-continuity-f59ee4b4-7bfe-448e-9a0b-0f167f8b9bc2/observation.json` 및 같은 폴더의 backup/이관 자료다.

| 확인 | 결과와 한계 |
|---|---|
| 실제 과거 요청 복사 | 전역 root의 원본을 읽어 복사본에서만 실행. terminal `0309765d-8bf5-4f5f-99df-20480cc075af`의 원 인증 receipt 동일, unknown `ffb7fc8e-417c-454c-a669-48625a086eda`는 새 코드에서도 `outcome_unknown` 유지. native dispatch `0` |
| 이관 bytes·삭제 상태 | backup의 persistent bytes와 이관본 동일. 준비 중 삭제한 임시 token은 부활하지 않고 이후 생성한 상태와 사용자 policy는 보존. 두 키 내용은 출력하지 않음 |
| one-attempt | 별도 새 UUID의 명시적 `isolated_upgrade_copy_reproduction` marker/서명 관측을 복사. 소비 후 `claim()`은 이관 뒤에도 false. 실제 native 실패·복구 permit·eligibility를 관측한 증거는 아님 |
| 실제 recipe 기록 | 성공 run `11fb359a-c07a-408a-bb87-09dd1200dc62`와 그 원 confirmation key를 별도 인증 도메인의 임시 root로 copier를 통해 이관. 새 `RecipeRunStore.read`에서 인증 및 `succeeded/published` 유지. 원 run을 재개·dispatch하지 않음 |
| 빌드 정리 | 실제 cleanup 함수 정의만 로드해 임시 `stage` 삭제와 `native-r4/receipt.json` sentinel 보존 확인. release build·installer·CI 미실행 |

첫 재현은 Codex PS7 모듈 경로를 Python 경유로 PS5에 상속하면서 호환되지 않는 Utility 모듈이 선택되어 `Get-FileHash`를 찾지 못했다. 임시 복사 단계에서 중단됐으며 원본은 수정하지 않았다. PS5 child에 기본 PS5 module 경로를 지정한 별도 재현이 위 결과다. 제품 전역 환경이나 Codex 설정은 변경하지 않았다.

R4-16을 전체 완료로 표시하지 않는다. 실제 source/frozen 설치 교체·재시작/loaded manifest는 이번에 실행하지 않았다. idle PID scan은 독점 잠금이 아니며 검사 직후 이전/새 process가 재시작하는 경합과 환경변수로 root를 지정한 외부 host의 식별은 남아 있다. 안정된 maintenance gate와 installer single-writer 연계가 후속 구현 대상이다. 기존 unknown을 삭제·재분류하거나 source/token을 새 권한으로 재서명하지 않았다. 전체 suite/build/CI도 실행하지 않았다.

### 이전 추가: 실제 export 선택 복원과 소비자 좌표 연결

원격 개선안은 다시 fetch했으며 최신 SHA는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`다. r4의 기존 16개 목표를 유지한다. 이번에는 독립 Transform의 저장된 원본 → 작업 복제 → 실제 평가·품질 → FBX → Blender → 게시 연결을 진행했다. 일반 리그와 설치 교체까지 완료한 것으로 보지 않는다.

- export qualification이 이미 비어 있다고 확인한 이전 탭을 한 객체 전용 reader로 읽어 차단하던 문제를 고쳤다. 이전 빈 탭 보존에는 전체 reader를 사용하며 실제 fixture와 production target의 독립 객체 제한은 유지한다.
- 첫 레시피 `a266c9c7-ed74-4afe-a383-d9232cef775a`는 native 품질·후속 checkpoint 성공 뒤 `SOURCE_REATTESTATION_FAILED`로 차단됐다. `.casc` 파일 bootstrap이 UI session의 선택을 복원하지 않아 export 어댑터의 기존 선택 일치 조건에 걸렸다. FBX dispatch 전이며 원 run·승인·receipt·checkpoint를 보존했다.
- export scope에 실제 초기 빈 selector, ordered IDs, pivot position/rotation을 결합한다. 원 source guard를 첫 선택 변경 전에 실행하고 승인된 단일 객체만 잠시 선택한다. 공식 clear 명령으로 빈 선택을 복원한 뒤 관측값과 전체 authored projection이 정확히 같아야 완료를 발행한다. 복원 실패는 `NATIVE_COMPLETION_UNKNOWN`이다. host sealing도 dispatch source와 completion에 봉인된 복원 proof를 대조한다. 비어 있지 않은 최초 선택은 지원하지 않는다. SDK는 pivot ID를 노출하지 않으므로 hidden pivot identity 복원은 `unobserved`로 남긴다.
- Blender의 animated parentless Null 경로는 importer root frame `G`와 명시 canonical basis `B`를 분리하고 rest/실제 sampled 회전에 `B @ R_blender @ (B @ G).T`를 적용한다. artifact static model/template에서 rest를 별도 decode하고 실제 native model-pose rest와 비교한다. native rest를 FBX 기본값으로 대체하지 않으며 armature/mesh 경로에는 적용하지 않는다.
- native 품질 단계에서 소비자 전용 `position_readback_m/rotation_readback_rad`를 요구해 export에 도달할 수 없던 순환을 고쳤다. 승인된 전체 policy/digest/threshold는 유지하고 두 지표만 `pending_export_roundtrip`으로 명시한다. 최종 consumer 검증에서는 원래 intent와 전체 필수 지표를 모두 요구한다.

중간 새 프로세스의 실제 qualification에서 `Quaternion.w/x/y/z`를 값으로 읽는 오류를 발견했고 설치 공식 stub의 메서드 호출로 수정했다. export 전에 실패했으며 해당 process도 정상 종료했다. native hot reload 없이 다시 시작한 **PID 34864**, build `2026.2.3.0.16863`, bridge fingerprint `68458d4d8812fc216bdb9bb9e49025ab1bed492479e0e06e3fb47708761cb7da`, epoch `ba16f4aa-3354-4d7d-bd4d-bd4d70f6f3a3`에서 scene/motion을 재자격 확인했다. 같은 프로세스의 실제 animated export 두 번에서 선택 전환·관측 복원·전체 projection 동일성과 FBX 설정/구조 읽기를 통과해 `io.export_fbx`를 등록했다. export qualification 증거는 `export-qualification-796a4ab8-95b1-4767-b23b-3c261c2636ad/qualification.json`, SHA-256 `76964e0990e2723c6e25dc98900b153035a21539f512970d0ac8e534032ac2d7`이다. 이 qualification 자체의 품질은 `not_evaluated`, consumer roundtrip은 `unverified`다.

실제 recipe `b44ae572-600a-41f4-b4a6-9a01f1fb865b`는 native 품질·checkpoint·export 및 선택 복원 proof sealing까지 성공했지만 consumer 결과 저장에서 `WORKER_EXCEPTION:PydanticSerializationError`로 차단됐다. 저장된 원본 capture와 sealed FBX로 host 단계만 재현한 결과 `external._compare_target_capture`의 비교식이 `numpy.bool`을 결과의 `ok`에 남기는 것이 원인이었다. 판정 조건과 threshold를 유지하고 Python `bool`로 반환하도록 수정했다. 보존된 FBX SHA-256 `79090c480eaa398f91d46cb3dd164cb715b4b64cb435f0d8ca435aa038ecac5c`로 실제 Blender 재검증 및 validation JSON 저장은 성공했다. 원 run의 성공 native effect는 replay하지 않았으며 원 manifest/승인/receipt도 수정하지 않았다. 구현 pin이 바뀌었으므로 종단 게시 확인에는 별도 새 작업 복제·새 plan/승인을 사용한다.

별도 새 recipe `11fb359a-c07a-408a-bb87-09dd1200dc62`는 `succeeded / quality=pass / export=published`로 끝났다. 동일 loaded bridge에서 실제 `.casc` 입력 → 새 작업 복제 → 초기 checkpoint → 평가 → source/baseline capture → native 품질 → checkpoint → selected FBX → strict 구조 → 실제 Blender capture → original-intent 품질 → 게시를 완료했다. `input/rig/motion` 단계의 `skipped`는 이 보존 레시피에서 변환을 요청하지 않았기 때문이며 새 retarget나 cleanup 성공의 증거가 아니다.

| 실제 확인 | 결과와 범위 |
|---|---|
| 입력 보존 | `export-source-66063891-5f64-4871-a1fa-a333ccd5ed29/source.casc`, 13,966 bytes, SHA-256 `2797e96df6ed7279331c9cfc32a2dbb862d31fe94ad8ca2ae34fe260fb10ed4b`, 실행 뒤 동일 |
| 유한 target | `MCPActualExportRoot`, object ID `394917b4-db75-427c-bb3d-c2f95976b0af`, parentless·identity model rest·unit scale·mesh 없음, 0..4 다섯 sampled frames |
| 명시 policy | FPS 30/1, 0.01m/scene unit, scene basis identity는 author policy다. consumer basis/import offset도 명시했다. 실제 native 물리 metadata 관측으로 주장하지 않는다. import 전에 선언한 위치·회전·root·correction limit은 각 `1e-6 m/rad`, duration `1e-9 s`, envelope 위반 count `0`이며 관측 후 완화하지 않았다 |
| 소비자 품질 | Blender `[4,5,8]`의 pinned executable/importer를 사용했다. 원 native model-pose rest 비교와 original-intent 전체 8개 필수 지표가 measured pass. 위치 readback/root/correction max `4.998001410623543e-10 m`, 회전 readback/root/correction max `1.6292067073209145e-7 rad`, duration max `0 s`, envelope 위반 `0` |
| validation 기록 | `state/runs/11fb359a-c07a-408a-bb87-09dd1200dc62/artifacts/960eeec47e8b9518e6893d83c23dd24ccbf7a77242e413bf21a87046e8709fa5.json`; SHA-256는 파일명과 같음. raw/canonical capture와 인증 provenance는 같은 export stage의 `target-noykddkg`에 보관 |
| 최종 게시 | 같은 source 폴더의 새 `final.fbx`, 22,176 bytes. sealed artifact·publication receipt·실제 destination SHA-256 모두 `b1aeddffd92750e29a359a617dac99ff751f9976d8b219345434fe4a7ef129b1`로 일치. 승인된 `fail_if_exists` 게시 경로 사용 |

직접 확인에 필요한 native qualification과 위 레시피/오류 재현만 실행했으며 전체 suite/build/CI는 실행하지 않았다. 실제 자료는 ignored `artifacts/native-r4/isolated-runtime`에 보관한다. 확인한 범위는 단일 독립 객체·sampled frames이며 humanoid/mesh·연속 시간 품질, 비어 있지 않은 초기 selector, hidden pivot ID, 일반 관절 axes/limits, final-root readonly graph, 실제 partial failure의 조건부 복구, 설치 상태 이전의 실기 확인은 남아 있다. 기존 unknown 요청 `ffb7fc8e-417c-454c-a669-48625a086eda`와 global runtime/auth/receipt는 건드리지 않았다. 아래 섹션은 각 이전 시점의 관측이며 당시 남아 있던 독립 객체 consumer frame 문제는 위 유한 경로에서 해결했다.

### 이전 추가: 입력 자동 구성, 실제 host retarget와 소비자 프로필 준비

원격 개선안 SHA `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`가 현재도 최신임을 확인했다. 기존 16개 r4 목표를 유지하며 R4-02 입력 수집, R4-10 host controller와 R4-13 소비자 준비를 이어 연결했다. 전체 목표는 아직 진행 중이다.

- `native_independent_inputs.py`는 현재 private model 자격이 있는 부모 없는 단일 Transform의 ownership/root, 실제 model-pose rest, 회전 채널과 기존 위치 writer의 읽기 전용 closure 검사를 연결한다. 공개 inspect/resolve가 raw rig JSON 없이 프로필을 구성한다. 이 객체는 joint가 아니므로 axes/limits를 만들지 않는다. 일반 캐릭터의 필수 관절 metadata는 그대로 요구한다. `{root: None}` 계층만으로 측정 불가능한 bone-length 지표를 요구하던 조건도 실제 edge/선언된 길이 기준으로 수정했다.
- `independent-parentless-position-v1`은 exact source/profile/context/원본 artifact/명시 mapping·scale·anchor·intent를 묶어 실제 native rest와 direct controller를 관측·재인증한다. host retarget 수학 → 실제 기존 key model fitting → prepare/commit → exact float32 readback 경로를 사용한다. 지원 범위는 root 하나의 global position, 기존 LINEAR/STEP 키이며 rotation/coupled/IK/키 삽입으로 확대하지 않는다.
- 실제 첫 run `a914e65e-e3d2-472a-ba5f-013e6cced279`는 쓰기 성공 뒤 평가 준비에서 `IMPLEMENTATION_CHANGED`로 중단됐다. 읽기 전용 진단에서 변경된 runtime 필드는 `retarget_inputs.native_projection_digest` 하나였다. 구현 identity 비교에서 장면별 `native_projection_digest/object_ids/target_scope`만 분리했다. model/writer 자격, epoch/fingerprint, 미지 capability 필드와 실제 source/controller 재검증은 유지한다. 기존 run·성공 receipt·미전송 prepared 평가를 보존했고 성공한 쓰기를 replay하지 않았다. 수정 후 별도 새 복제본/새 승인 run으로 확인했다.
- 새 MCP `prepare_blender_export_profile`은 고정 background Blender adapter로 실제 설치 버전·실행 파일·FBX importer bytes를 읽어 누락된 pin과 settings digest를 채운다. 명시된 map/axes/units/options는 보존하고 기존 pin 충돌은 `TARGET_INSTALLATION_PIN_CONFLICT`로 거부한다. artifact import나 recipe 승인·품질·게시 작업은 수행하지 않는다.
- export 후 continuation이 native scope의 ExportProfile을 RigProfile로 오인하던 경로를 수정했다. 검증된 `native-selected-export-v1`의 exact export operation/profile/arguments digest, 객체·selection·layer·range·raw staging 경로를 확인한 뒤 기존 private recipe target 관측으로 실제 rig/rest/ownership을 다시 인증한다. 일반 profile 검사나 target 검증을 건너뛰지 않는다. 이 후속 수정의 실제 export 종단 실행은 아직 관찰하지 않았다.

아래 실앱 관측은 새 PID 37508, Cascadeur `2026.2.3.0.16863`, bridge fingerprint `eb7fa16eb51c2ab926824f3c4ba14cdbaa20d5fff8815349b42c1bcc2349133a`, epoch `b095e01e-7c5d-4666-8452-8a14e64ecd76`에서 수행했다. native hot reload는 하지 않았다.

| 실제 확인 | 결과와 범위 |
|---|---|
| fresh 자격 | 실제 model 40 trials 후 같은 private proof 재사용, writer 16 trials. model digest `9a57a501d63eee68df9f23c7b08c220af7a1ce68d228c0459f5a38d0564006b1`, writer digest `8ec012e016d597c1ed5b9746961c99514504e796b1663fafe66966185b1805be` |
| 자동 입력 | `independent-input-observation-2cfad58c-24c5-4f69-b6b5-88dad10d71ec/{draft,resolved}.json`. 실제 root/rest/회전/writable을 관측하고 명시 conversion policy로 resolve 성공. FPS 30/1, 0.01m/unit, identity basis는 native 물리 metadata 관측이 아니다 |
| 실제 host retarget recipe | run `8fd739e0-158c-45a1-915d-e129e4c55fe6`, `succeeded`. 보존된 실제 source capture와 native model rest에서 canonical source artifact를 만들고 다른 target root에 scale 0.5, anchor `[0,0,0]`을 명시. 자동 관측 target 프로필을 사용. 쓰기 요청 `6bc65f2f-5bfe-4811-b952-3b77e89797dc`, 실제 기존 key 2=`[1,0.5,-0.125]`, 4=`[0,1,0.375]` scene units, key 0은 변경 없음 |
| 평가·품질·저장 | 평가 `9e5997ff-2298-4d9b-aca0-40911d257537`, checkpoint `ddf15ddd-42dc-4374-b75e-aa1311f923ec`, native/host 확인 성공. 0..4 actual capture의 네 필수 지표가 measured pass. quality artifact SHA-256 `cd3d8bbbb4f63947b512199e29f61523e3ed08d249c3b17b813f1ddac9894091` |
| 소비자 공개 도구 | 실제 MCP 호출 성공. 설치 Blender `[4,5,8]`, executable SHA-256 `2157db89aa366f94a6c216078d1457ac0bd141532990c23e4e11ac7019418ed9`, importer fingerprint `8c345bc570f2870a7b1de8e7a6398acec4ff4c8f848f55a650858d8a9417816e`. prepared profile digest `12aa241bf85cc8f3b69376037866f7eb938fa8b484b449683284dd47e9914394` |
| 원본·기록 | 새 qualification input SHA-256 `a9e3bfc498bd075b8c4d14bbedfb2b4b56d50611c91c626c005f2317cc437da6` 유지. 모든 산출물은 ignored local runtime에 보관. 기존 unknown·인증키·receipt를 보존 |

이 retarget는 명시적으로 작성한 mapped trajectory다. source/baseline 품질 캡처는 retarget 쓰기 **이후**이며 네 지표의 0 오차는 입력 animation 보존이나 source-to-target mapping 오차 0의 증거가 아니다. fitting residual은 host prediction이며 actual motion quality와 구분한다. humanoid cleanup, 연속 시간 충돌, 실제 FBX consumer 왕복·게시 성공을 주장하지 않는다. export는 `not_requested`. 전체 suite/build/CI는 실행하지 않았다. 새 공개 도구의 golden surface는 실제 MCP schema에 맞춰 추가했다.

일반 리그 입력은 여전히 구체적인 SDK 제한이 있다. 공식 typed `AngleConstraints`는 parent/child rigid-body와 3성분 min/max 및 rotation offset을 노출한다. 공식 builder는 parent rigid 회전의 inverse와 child 회전을 곱해 offset을 만든다. 그러나 각도 단위·Euler 순서·0 제한의 자유/고정 의미·joint-rest frame 및 flexion/splay/twist 축 대응은 확인되지 않았다. host의 radian hinge/rotvec 계약에 이 원시 벡터를 직접 대입하지 않았다. final-root의 fresh readonly graph, 실제 실패 후 conditional recovery, 원본 intent/rest와 결합한 consumer 왕복·게시 및 설치 상태 실기 검증도 남는다.

consumer rest의 남은 문제도 분리한다. 보존된 이전 Blender 관측의 독립 객체 rest는 X축 90도 회전, native model pose는 identity였다. importer의 root frame left conversion과 canonical basis conjugation은 서로 다르며, conjugation만으로 이 차이를 없앨 수 없다. native rest를 FBX rest로 대체하거나 허용 오차를 완화하지 않는다. 설치 importer의 실제 root frame 변환을 분리해 처리하고 같은 native rest와 재대조하는 후속 연결이 필요하다.

### 이전 추가: 키포즈 작성과 독립 객체 model-pose rest

원격 개선안 branch의 최신 SHA `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`를 다시 확인했다. 기존 r4 목표를 유지하며, 이번에는 실제 키포즈 쓰기와 target rest 관측을 연결했다. 전체 r4 목표는 진행 중이다.

- scene/motion 자격 명령이 각각 interpolation 실험을 재생성해 먼저 등록한 adapter의 model digest를 무효화하던 문제를 수정했다. 현재 loaded bytes/build/epoch의 private 성공 관측만 재사용한다. 새 프로세스에서는 실제 실험이 필요하며 caller가 proof를 넣을 수 없다.
- existing-position writer는 native float32 인코딩과 exact readback 계약을 source scope에 발급한다. host의 쓰기 후 확인도 이 계약을 확인하고 같은 float32 값과 정확히 비교한다. 기존 코드가 존재하지 않는 source `context.metres_per_scene_unit`를 읽어 native 성공 뒤 실패하던 문제를 해결했다. native 값 비교에 물리 단위를 추정하지 않으며 SI 품질은 별도 명시 MotionContext를 사용한다.
- recipe planner의 rotation adapter 조회를 연결하고 `wrist_soften`의 permit를 실제 rotation operation/channel과 일치시켰다. 이 두 수정의 실제 character rotation 실행은 아직 관찰하지 않았다.
- 설치 SDK의 공식 Set/Go To Model Pose 명령이 사용하는 `Node3d.model_local_position/rotation/scale`을 읽는 전용 reader를 추가했다. private qualification이 유효한 부모 없는 단일 Transform, 실제 owned Static data, 정상 quaternion과 unit scale만 허용한다. recipe target은 선언된 rest와 이 실제 native 행렬을 정확히 비교하며 private observation을 재인증한다. 일반 리그의 inverse-bind reader나 bone length 요건을 이 경로로 우회하지 않는다.

새 Cascadeur PID 36280, build `2026.2.3.0.16863`, bridge fingerprint `e2f73393d8c96ea6c8692bcb5d83b0cc3e8f396cf6c55acb74a0e39ac4fec21a`, epoch `fe71b8c1-4df5-4d2e-b895-15a34e6d075b`에서 아래를 직접 관찰했다. native 코드를 hot reload하지 않았다.

| 실제 확인 | 결과와 범위 |
|---|---|
| scene → motion 자격 명령 연속 실행 | 최초 40 model trials, 후속 명령의 같은 private model digest 재사용(`reused=true`), 실제 writer 16 trials. model digest `8e5abd2d6b3f7cc8be22aaa085fc3b36a2e12d9c1c61fb67faf1fc64514e3c9f`, writer digest `863fa8b90efab7876d712df4b7cd471fcbf1e12f775542835b640aca4ecddeea` |
| 독립 scene 관측 | `independent-scene-qualification-3309e929-c93f-4b27-b1c6-31b7732717be/qualification.json`, SHA-256 `459b0192a0847024edc02b77dab8fdd411479bebc224e1f16bea2a922d34ba2f` |
| 실제 공개 recipe | run `9142c760-f8ad-4c1d-be76-53a51a1d9368`, `succeeded`. 기존 0/2/4 키의 위치를 각각 `[0.25,-0.25,0.5]`, `[2.25,0.75,0.25]`, `[0.25,1.75,1.25]`로 작성. 쓰기 요청 `63e726d2-5807-49d1-84e9-c2dfe6f05d12`, exact settled readback과 인증 성공 receipt 확인 |
| 평가·품질·체크포인트 | 평가 요청 `2cbb111a-b3df-4e75-ad91-2842f5a15f53`, 최종 checkpoint `6f4648d6-98b3-4f9c-8360-7920942f6513` 성공. 0..4 sampled global/local capture 뒤 여섯 필수 preservation metric의 measured max 0. quality artifact SHA-256 `92e2bd25dfb31079f04a97ea99b018b7d2fad5c96c0a871fc96c333236c08c8f` |
| rest 관측·공개 target 인증 | 실제 저장된 model pose는 identity, 작성한 frame-0 위치는 위의 nonzero 값. current pose를 rest로 사용하지 않았다. 공개 `recipe_observe_target`과 원 native private record 재인증 성공, provenance `native_node3d_model_pose`. target artifact SHA-256 `f52f131ce47ce9fd8091ce1f43765eae6ca30b1759c6917f71ee80e29be36796` |
| 원본 | qualification의 입력 파일 SHA-256 유지. receipt·checkpoint·기존 unknown을 보존. 산출물은 ignored local runtime 폴더에 보관 |

이 recipe의 source/baseline은 **키포즈를 작성한 뒤** 캡처했다. 30fps, 0.01m/scene-unit, identity basis는 확인용 명시 정책이다. 결과는 입력 애니메이션 보존, jerk 개선, humanoid cleanup, 실제 물리 metadata, FBX consumer 왕복/게시의 성공 증거가 아니다. export는 `not_requested`다. 전체 suite/build/CI는 실행하지 않았다.

다음 연결의 구체적인 제한도 확인했다. 설치된 root constraint part의 내부 graph와 공식 builder의 외부 edge 정의는 찾았지만, 현재 scene graph를 읽는 `Update.root_group()`은 edit callback 안에서만 제공된다. 기존 readonly 전체 projection과 revision에는 graph edge가 포함되지 않아 캐시된 graph를 현재 권위로 사용할 수 없다. fresh readonly graph 관측/변경 감지 근거를 확보하기 전에는 final-root를 추정하지 않는다. general retarget의 native input observer/controller, 실제 실패 후 conditional recovery, 원본 intent/rest와 연결한 consumer 왕복·게시도 남아 있다.

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

### 독립 complete-scene와 실제 recipe 실행 — 11월 16일 추가

원격 개선안 branch를 다시 fetch/ls-remote 했으며 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4` 그대로다. r4의 16개 연결 전체 목표는 활성 상태로 유지한다. 아래 독립 객체 실행은 전체 character/consumer 목표 완료가 아니다.

- `native-independent-complete-scene-v1`을 별도 profile로 구현했다. 현재 프로세스의 실제 finite interpolation proof와 build/epoch/fingerprint를 요구하고, 부모 없는 단일 Basic/Node3d/Transform, 관측된 선택적 FbxExport metadata, 최대 33 frame, asset/controller/cycle/additive 없는 전체 closure만 읽는다. 파일 bootstrap의 원래 빈 탭만 예외이며 새로 load한 대상은 이 domain을 만족해야 한다. 전체 data/settings/sections projection의 exact save equality는 유지한다. Cascy의 차이가 나는 채널을 제외하거나 수치 허용 오차를 추가하지 않았다.
- 명시적인 `Cascadeur Complete.Qualify independent scene adapter` 명령을 추가했다. import나 wire 요청으로 자동 실행하지 않는다. 실제 40개 LINEAR/STEP perturbation, 새 source 저장, full-project file bootstrap, 평가, 후속 checkpoint와 원본 탭 복원이 끝난 뒤에만 세 operation을 등록한다. source/packaged installer는 bridge 전체를 복사하므로 이 command도 함께 배포한다. 실제 전역 설치 교체는 실행하지 않았다.
- recipe preflight가 실제 capture의 필수 회전 ID와 같은 함수를 사용한다. root quaternion이 필요한 recipe의 `rotation_correction_rad` 누락을 native 효과 전에 거절한다.
- 실제 queue 실행에서 새 bootstrap grant가 자체 인증에 실패했다. 서명 후 Pydantic이 `schema_version` 기본값을 넣던 순서가 원인이었으며, 저장할 typed model을 먼저 완성한 뒤 전체를 서명하도록 수정했다. 잘못 발급된 이전 grant/run은 재서명하거나 교체하지 않는다.
- 실제 상태 polling과 worker의 manifest 교체가 경합해 Windows `PermissionError`가 발생했다. 상태 read도 기존 process-shared reentrant store lock을 사용하도록 고쳤다. 이 오류로 중단된 run의 bootstrap 성공과 evaluation prepared/not_dispatched를 보존했다. 취소는 이전 host lease가 종료됐음을 확인한 뒤 원 intent/request/token을 유지하며 실행 전 취소 또는 원 receipt 관측으로 이어지도록 연결했다.
- export expectation은 원본 intent의 모든 role 및 비수정 dependency의 실제 target 관측을 요구한다. 현재 skeleton map에 표현할 수 없는 dependency를 source 값으로 채우지 않고 `EXPORT_INTENT_TARGET_COVERAGE_UNAVAILABLE`로 차단한다. source/baseline 시간 격자와 정확한 RigProfile digest도 고정하여 뒤늦은 rest/limits 변경을 거절한다.
- installed SDK의 정확한 `ProtoRootConstraint.root → TechnicalLinks.joint` 타입/owner 연결을 읽고 actual local/global quaternion 채널까지 확인할 때만 root orientation 후보를 낸다. `BehaviourType`/`BehaviourRangeType`의 실제 참조 ID·이름·owner도 보존한다. final rig graph나 이름, 회전 상수로 대체하지 않는다. native 3축 AngleConstraints를 canonical 단일 unsigned hinge 범위로 바꿀 근거가 없어 joint axis/limit은 계속 미확인이다.

실제 설치 앱의 bridge fingerprint `641a8dcf12f985978b0c472cb5b62bdf1e3c69032f776cc799fceae9f0f60ba9`, epoch `33bcc094-f065-4ad5-996a-66f5b12382e4`에서 다음 실행을 관찰했다. 아래 결과는 얇은 independent-scene command wrapper 추가 전 bytes이며 이후 fingerprint의 자격으로 승계하지 않는다.

| 관찰 | 실제 결과 |
|---|---|
| independent model + scene qualification | 40 trial 및 source→file load/save→evaluation→checkpoint exact projection 통과. `independent-scene-qualification-0cb390ac-52fe-4649-a6ac-e080904775ad/qualification.json`, SHA-256 `8462f71eece4b4d26ac7d445062276d4418015cc16d164ea7537d0ecc30db032` |
| 전체 preservation runner | run `0676eb0e-61a8-4842-b9d7-45b28c5a5dc7`, `succeeded`, quality `pass`, export `not_requested`. 실제 0..4 dense global/local position+quaternion capture. existing rig/motion 단계는 live preflight 후 skip |
| bootstrap terminal | `454ca4b7-28b4-4cfa-88d0-d3c9e2012f22`, `succeeded` |
| evaluation terminal | `65aea564-9275-4106-8284-3a1b323d2054`, `succeeded` 및 durable 평가 receipt를 capture에서 재인증 |
| preservation quality | required 6개 metric의 measured max 0, sampled_frames, runtime_verified=true. 품질 artifact SHA-256 `23007131e6dabc5a152878d42bf8642f95debbaef93ac04b33218cf61cb372fb`. acceleration/jerk 등 진단 수치의 품질 기준을 추가로 통과했다는 의미는 아님 |
| final checkpoint terminal | `08f8ab91-af33-4caa-a167-181d6ea510e0`, `succeeded`. manifest SHA-256 `70ac2a445b302860006273822fe2be2ab12e8a40c2a0d9e86d5886571ef5ed75` |

host와 native 응답은 double로 대체하지 않았다. `CascadeurService.recipes.plan/authorize/start/status`와 실제 BridgeClient 인증 queue를 사용하고 공식 localhost script server는 drain trigger로만 사용했다. FPS 30·cm·identity basis는 명시적 진단 conversion policy이며 native 물리 메타데이터 인증이 아니다. local 산출물은 `artifacts/native-r4/isolated-runtime` 아래 ignored 파일이고 키·state·receipt는 Git에 포함하지 않는다. 변경된 host 경계의 직접 확인은 topology·품질 정책·target coverage/rest mutation에 한정했으며 broad suite/build/CI는 실행하지 않았다.

별도 Cascy 읽기 진단은 288 selected 객체, behaviour 참조 property 540개를 오류 없이 관찰했다. 이 final rig에는 ProtoRootConstraint 연결이 없어 root는 `PROTO_ROOT_TOPOLOGY_UNOBSERVED`로 남는다. `motion-input-topology-ee0700f7-04f0-4cac-809d-0a560a1e20e7/observed.json`, SHA-256 `d567851efc847d46d715ecb0dc699383f7658701bb64576ef288355f1eebb5b3`. 원본 Cascy SHA-256 `0d6ae171db831e4738fddc86014fd0a0b77e9991c74308972603810ee34fc723`은 동일하다. 해당 호출은 복사본을 읽고 원래 빈 탭을 복원했으나 이후 PID 11060이 종료됐다. Windows Application Error는 `Qt6Core.dll`, `0xc0000005`, offset `0x779f8`, report `2de514bc-73c7-4300-bfc7-655a6d91f33a`를 기록했다. 특정 reader/탭 제거/native API를 원인으로 확정하지 않는다. 새 PID 35576에서는 Cascy를 다시 열지 않고 위 independent recipe를 완료했다.

### 현재 command qualification과 중단 run 취소

얇은 command wrapper까지 포함한 최종 native fingerprint `41ab505eb77812733a04396b220c26200a7007a74fd18fac79dd0efa17137f46`, epoch `ff08eddc-f8f4-4b4d-a762-917198b349b0`, 설치 앱 PID 34604에서 새 명령을 직접 호출했다. 공식 command가 받는 `csc.domain.Scene`을 전달했고 실제 Success 메시지와 반환값을 확인했다. 40 model trials, full-project file bootstrap, 평가, exact checkpoint 및 최초 빈 탭 복원이 완료됐다. 증거는 `artifacts/native-r4/isolated-runtime/snapshots/independent-scene-qualification-856b5b7d-d58b-4838-b473-04c4413466b8/qualification.json`, SHA-256 `faddca1fefaef29506cde890d4175117bc83aacb9a67c36730b9d03565d81b8f`다. 이 프로세스는 bootstrap/checkpoint/interpolation 세 operation만 해당 좁은 domain으로 등록했다. 전체 preservation recipe를 새 fingerprint에서 다시 실행한 결과는 아니다.

직전 command 호출에서는 내가 `csc.view.Scene`을 전달해 qualification 자체와 탭 정리가 끝난 뒤 마지막 `scene.success`에서 AttributeError가 났다. 원인 확인 후 올바른 command 인자를 사용한 새 소유 fixture 실행으로 위 명령 성공을 관찰했다. 이전 증거를 수정하거나 실패한 bridge 요청을 재전송하지 않았다.

중단된 실제 run `dba7d928-ea96-4318-b9e4-185b88276695`를 새 host에서 취소했다. 종료된 이전 host의 lease를 1→2로 인수하고 prepared/not_dispatched `005-evaluation`만 `canceled_pre_dispatch`로 종료했다. 원래 request `ad954145-d365-4fa8-b786-87e8832d5cc6`, token, attempt, dispatch lease, grant, source binding, artifact와 budget은 그대로다. run 상태는 `blocked`→`canceled`이며 기존 bootstrap 성공도 보존했다. 이 취소에는 앱 호출이나 native dispatch가 필요하지 않았다. 별도 실제 자식 host/임시 store 재현에서도 살아 있는 owner 인수를 거부하고 종료 후 인수, 취소 intent가 있는 resume, unknown 유지와 원 terminal receipt에 의한 종료를 확인했다.

Windows에서는 종료된 프로세스의 handle이 남아 있으면 OpenProcess/GetProcessTimes가 성공할 수 있었다. 생성 시각만으로 live owner라 판정하던 코드를 `SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION`과 `WaitForSingleObject(handle, 0)`의 실제 종료 상태 확인으로 고쳤다. 접근 거부·상태 불명은 인수를 허용하지 않는다. 손상된 bootstrap grant가 남은 이전 run `585e3fb7-9375-426b-8208-0ae39144fb97`와 전역 runtime의 기존 unknown 요청은 재서명·삭제·재실행하지 않았다.

여전히 일반 character의 exact checkpoint/restore, final root graph/해부학적 joint/물리 메타데이터, 실제 실패 attestation→조건부 복구, source-rest가 결합된 consumer roundtrip·최종 게시, 실제 설치 교체는 미완료다. preservation recipe의 성공을 correction writer, 일반 휴머노이드, continuous coverage, export 성공으로 확대하지 않는다.

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
