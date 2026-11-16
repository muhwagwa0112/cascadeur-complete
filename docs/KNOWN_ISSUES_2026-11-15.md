# Cascadeur motion r6 구현 상태와 남은 문제

작성일: 2026-11-15 / 갱신: 2026-11-16 (Asia/Seoul)  
대상: `feat/cascadeur-motion-r3`, r6 기준 구현 `7f1565a0ffad1595b9824cba25443bc581997fb6` 이후 변경  
읽은 최신 원격 개선안: `origin/docs/cascadeur-motion-plan-r6`, `d31bdf3210f83fea2964a05d185d9bc976ef04ca`의 73개 파일 전체(29,843행); 아래 r5/r4 기록은 당시의 이력  
고정 제품 목록: Cascadeur `2026.1.3.0.15619` / 실제 설치·실행: `2026.2.3.0.16863`

## 이번 변경과 관찰 범위

### 실앱 전환 대기: 열린 원 탭과 새 코드의 loaded epoch

Computer Use로 실제 Cascadeur 창을 읽기 전용 확인했다. 창 제목은 `artifacts/native-r4/isolated-runtime/snapshots/guarded-spaced-key-insertion-8e409ec0-0054-4982-a654-ce04d572c37c/working.casc`이며 `trial-2`, `trial-3`, `source`, `untitled (1)`, `evaluated-working`, `source`, `working` 등 여러 탭이 보인다. 제목이나 화면만으로 각 탭의 저장 여부를 확정하지 않았다. 창을 전면에 표시한 것 외에 클릭·저장·탭 전환·닫기·재시작은 수행하지 않았다.

isolated runtime의 실제 pump PID **2328**과 CIM의 `cascadeur.exe` creation **2026-11-16T06:14:42.902727+09:00**가 일치했다. 조회 당시 heartbeat age는 **0.30초**, `busy:false`, `last_error:"package changed: clean Cascadeur restart required"`였다. 살아 있는 이전 runtime이 코드 변경을 감지한 상태이므로 새 bytes의 native qualification을 추가 queue 요청이나 hot reload로 대신하지 않는다. 기본 runtime root에는 현재 state/snapshots/logs만 있고 source installer의 최종 `src/.venv` 설치는 아직 없다. 기존 Python 설정의 Path는 빈 목록이다. 이는 현재 실행 중인 bridge의 정확한 import 경로 전체를 증명하지 않는다.

실제 전환 순서는 **사용자가 원 탭의 저장 위치/보존을 결정하고 앱 정상 종료 → source `scripts/install.ps1 -SkipCodexRegistration`로 기본 runtime 및 두 user-script code target 교체 → 앱 정상 시작 및 새 fingerprint/epoch metadata 확인 → 정확한 유한 fixture 계획 prepare → 별도 로컬 operator 검토·승인 → bounded setup/continuation**이다. 설치는 runtime/state/snapshots/logs의 기존 물리 ID와 인증 상태를 보존하며 전역 Codex 등록을 변경하지 않는 경로를 사용한다. 정상 종료 자체나 이 순서의 열람은 legacy unknown의 위험 수용 승인, 종료/격리/비간섭 증거를 뜻하지 않는다. 별도 독립 환경의 실제 supervisor/transport/custody 근거도 아직 제공되지 않았다. 이 전제 변화 전에는 남은 실앱 qualification을 진행할 수 없으며 전체 완료로 처리하지 않는다.

### 후속 보완: native Update 반환 확인과 unbaking 설치 위치 구체화

설치 `csc/domain/__init__.pyi:293`의 `Scene.modify_update(...)->bool` 계약과 실제 binding을 대조해, `bind_native_update_runner.invoke`가 기존 `handler_registry.transact`의 반환을 버리던 연결을 수정했다. 이제 literal `True` 반환이 없으면 `UPDATE_NATIVE_TRANSACTION_ACCEPTANCE_UNOBSERVED`로 private snapshot 발급 전에 거절한다. 콜백이 끝났다는 사실만으로 native transaction acceptance를 대신하지 않는다. `False/None`의 rollback·완료 의미는 선언만으로 확정하지 않았다. 그룹/interface/typed Data 접근의 이번 한정 대조에서는 추가 method/signature 불일치가 발견되지 않았지만 실제 callback 인자·no-yield·반환 후 안정성 및 authored/derived storage는 여전히 실앱 근거가 필요하다.

실제 `bind_native_update_runner`→기존 `handler_registry.transact`를 로컬 Domain double에 연결한 단일 inline 재현은 **exit 0 / 1.09s**였다. 동일 callback을 동기 완료시키되 native 반환만 True/False/None으로 달리하여 True만 private snapshot 1개, False/None은 예외와 runner/shared store 발급 0개를 확인했다. modify 진입 전 첫 effect guard도 확인했다. imports/admission/context는 fixture이며 SDK·앱·운영 store·설치·종료는 실행하지 않았다.

비실행 문자열 조사는 설치 `tool_auto_interpolation.dll`의 UTF-16 UI metadata에서 세 exact ID를 추가로 찾았다. 파일 길이 **89,088 bytes**, SHA256 **b3c9b608c958d3a8658f04778b93ce0d7286a64cb0fd00e11f614ec8922b635b**이며 raw file offset은 `View.Animation unbaking` **65772**, `View.AutoInterpolation_Keys` **65828**, `AutoPosingTool.AutoUnlock` **65972**다. 인접 metadata에는 `unbakingButton`, `onPressed`, `toolManager`, `editableAnimation`과 세 UI label이 있다. `cascadeur.exe`에도 `AutoPosingTool.AutoUnlock` ASCII 참조가 있다. 이는 compiled UI/소비 참조의 위치를 좁힌 결과이며 action 등록 owner/callable/인자/완료 callback의 증거가 아니다. 선택한 다섯 binary만 읽었고 로드·호출·patch하지 않았다. 이 위치의 실제 등록/실행 source 또는 operation-correlated trace가 확보되면 `native_unbaking.require_step_contract`와 `handlers/generation.unbaking`에서 qualified leaf를 연결해야 하며, 현재는 gate를 유지한다. `auto_interpolation.pyi`도 빈 `__all__` 선언뿐이다.

### 후속 보완: terminal 저장 후 중단된 producer archive 재개

native terminal을 durable 저장한 뒤 producer archive를 기록하기 전 또는 prefix 도중 중단되면, 새 host의 원 요청 조회가 archive를 완성하지 못하던 연결 공백을 수정했다. `BridgeClient.reconcile_request`는 먼저 원 request/terminal을 인증한 뒤 기존 prospective host/claim chain에 한해서 `reconcile_terminal_if_prospective`를 호출한다. 같은 writer lock 아래 정확히 일치하는 연속 raw prefix만 이어 쓰며, 이미 index가 있으면 사라진 prefix를 재생성하지 않는다. 기존 record의 MAC·request/digest·관측 epoch, index의 outcome·원 terminal raw hash를 다시 대조한다. 원 operation 재실행·process 재관측·SDK 호출·새 claim/first-effect 생성은 없다. legacy 두 요청에는 소급 기록하지 않는다.

archive 변조나 파일/lock 실패는 반환 envelope의 `PRODUCER_ARCHIVE_UNAVAILABLE` 경고로 드러내되 독립적으로 인증된 원 native outcome과 원 receipt bytes는 바꾸지 않는다. 원 terminal 자체의 인증 실패는 계속 예외로 거절하며 archive 재개도 시도하지 않는다. 조회 기록은 여전히 `observed_partial_v1`, `closure_authority:none`이고 producer closure를 발급하지 않는다.

필요한 두 한정 재현만 실행했다. 실제 Win32 자기 identity와 임시 signed outbox를 사용하는 `tests/test_r6_producer_installer_boundaries.py::test_prospective_process_records_preserve_actual_terminal_bytes`는 **1 passed in 7.24s**였다. archive prefix 중단 후 별도 Python 프로세스에서 재개·중복 조회하고 변조 prefix/index/epoch 거절과 원 unknown/request/receipt bytes 불변을 확인했다. child의 process/SDK/claim/effect entry point는 trap이며 SDK epoch만 fixture다. 공개 hook의 `tests/test_guarded_protocol.py::test_terminal_reconciliation_preserves_native_outcome_on_archive_failure`는 **1 passed in 0.34s**로, 실제 인증 ledger의 succeeded/unknown 결과 보존·명시적 archive 오류 경고·receipt digest 변조 시 hook 이전 거절을 확인했다. 최초 실행은 새 fixture에 필수 created_at/expires_at 누락으로 실패했고 필드를 추가한 뒤 이 단일 항목만 다시 실행했다. helper는 이 hook 확인에서 명시적 double이다. 실제 앱·운영 store·설치·종료·승인은 실행하지 않았다.

설치 stub의 추가 한정 확인에서도 `csc/app/__init__.pyi:29–55`의 `ActionManager.call_action(str)->None`, `csc/tools/__init__.pyi:119–126`의 `AnimationUnbakingTool.get_interpolation_difference()->float`, `177–187`의 `AutoPosingTool.add/update(Session)->None` 선언만으로는 세 exact action의 인자·원 operation에 결합된 완료 callback을 확정할 수 없었다. 선택 선언의 근거 공백이며 SDK 전체 부재나 native 소유를 뜻하지 않는다. unbaking gate와 실앱 qualification의 미완료 상태는 유지한다.

### 최신 추가: R6 전체 intake와 실제 제품 경로 통합

`origin/docs/cascadeur-motion-plan-r6`에 새 개선안이 있다. 최신 `d31bdf3210f83fea2964a05d185d9bc976ef04ca`의 **73개 파일, 29,843행 전체**를 읽고 R6-01~07 전체를 새 native goal로 설정했다. 기준 구현은 `7f1565a0ffad1595b9824cba25443bc581997fb6`이다. 원문은 `docs/implementation/cascadeur-motion-r6`에 보관했다. 29개 최종 source의 길이/SHA256/Git blob, aggregate patch의 기준→결과를 모두 대조했다. aggregate patch SHA256은 `3fcb36db838969fec171b69cc84a54c7a026b0064e58e4663a034584c8a25453`이다. 제안 자체에 없는 실제 SDK leaf와 연결 결함은 제품 코드에서 보완했다. 원문의 `product_applied:false`는 제안 작성 당시의 값이다.

- **설치:** source/frozen 경로 모두 runtime 디렉터리 전체 이동 대신 허용된 code entry만 교체한다. runtime/state/snapshots/logs의 Win32 물리 ID, 기존 policy bytes와 code preimage를 고정하며 rollback은 해당 transaction의 code·ownership/DACL 변경만 복원한다. 임시 재현은 실제 설치, Inno 전체 실행 또는 강제 장애 주입을 대신하지 않는다.
- **수동 setup과 continuation:** CLI와 MCP의 prepare/commit를 연결했다. 두 legacy unknown/open을 유지한 채 정확한 새 setup 계획과 별도 로컬 승인에만 admission v2를 발급한다. 기존 outbox 관측도 승인된 epoch/fingerprint/source/scene/시간 범위까지 대조한다. 실제 succeeded owned-pair setup이 있어야 고정 10/12단계 continuation을 만들 수 있다. pending/unknown/실패에서 중단하며 요청을 replay하거나 원 탭을 자동 정리하지 않는다. context의 단위·basis·FPS는 명시적 변환 정책이다.
- **미래 producer 관측:** 새 signed outbox의 게시 전 host 기록, native claim의 실제 PID/creation/image identity, 첫 효과 경계, 원 terminal raw archive를 실제 queue/guard/receipt 경로에 연결했다. 조회는 `observed_partial_v1`, `closure_authority:none`만 발급한다. 원 두 incident에 소급 기록·완료·retirement를 생성하지 않는다. 관리 supervisor/transport/VM/VHD/certificate custody가 인증하는 전체 scope·closure backend는 아직 없다.
- **유한 native 경로:** 설치 SDK의 `Update.root()`부터 typed node/port/edge/data/owner/producer를 읽는 실제 extractor와 private closed-snapshot source를 추가했다. readonly source 검증은 historical observation이라고 표시하고 fresh graph 검사는 admitted Update callback에서 첫 실제 계산/쓰기 전에 한다. 전체 projection의 비대상 channel/frame까지 검사하고 mutation 없는 evaluation의 실제 callback bookends도 private terminal/geometry 연결에 보존한다. checkpoint는 immutable P0에 직접 비교하며 authored/미분류 field는 exact로 유지한다. 새 코드의 실앱 qualification 성공을 주장하지 않는다.
- **MCP surface:** 실제 in-process MCP Client 목록·schema에서 새 도구 5개(`manual_setup_prepare/commit`, `pair_continuation_prepare/commit`, `incident_producer_observation`)만 추가된 것을 확인했다. 기존 모든 tool 계약과 resource/template는 동일하다. 의도된 추가만 golden에 반영했다. golden 갱신 자체는 native 검증이 아니다.

**Unbaking의 정확한 남은 leaf:** 제품 collector를 실행해 명시적으로 선택한 설치 stub와 `ml.editable_animation`, `python_actions_rule`, `common.selection_operations` source를 비실행 수집했다. 결과는 로컬 ignored `artifacts/native-r6/unbaking-installed-sources.json`(336,321 bytes)이다. 선택한 source에서는 `View.AutoInterpolation_Keys`, `View.Animation unbaking`, `AutoPosingTool.AutoUnlock` 세 exact ID의 등록이 발견되지 않았다. 이는 SDK 전체에 없다는 뜻이 아니다. `editable_animation.run`은 후보일 뿐이며, nested callback(1023/1031), `show_buttons_dialog`(1044), global current-scene(858)/settings(644) 때문에 exact argument 및 원 operation의 완료 소유권이 확정되지 않는다. 선택 source SHA256: editable_animation `58e0a35072d8491c87cf14677562f3d609a6387d5a76d3aa59f322eac28c228c`, python_actions_rule `71f6fdcddade64ab349eda51873fcb791d0870473b0ce0208dc057a1c1fca995`. 실제 등록 소유자·인자·완료 callback을 확인해 native unbaking lowering/completion 경계에 연결해야 한다. 세 action은 계속 gate하며 sparse key 생성으로 대체하지 않았다.

추가로 설치 `resources/scripts/python/commands`와 `inner_scripts`의 파일 목록·관련 문자열/등록 지점만 한정 조사했다. inner_scripts는 빈 `__init__.py`와 Transform/Mirror 생성 예제 `functions.py`뿐이며 세 동작의 등록은 없다. commands에도 직접 구현/등록은 발견되지 않았다. `python_actions_rule.py:9/25/38`의 일반 `run/name/description` discovery와 `CommandInfo(next_pkg, description)`는 세 ID의 binding을 증명하지 않으며, editable_animation의 `command_name`과도 계약이 다르다. 실제 owner는 여전히 미관측이다. 이 부재만으로 C++/native 소유라고 단정하지 않는다.

**실제 환경과 남은 승인/증거:** 설치 exe는 이번에도 `2026.2.3.0.16863`, CIM의 실제 실행 프로세스는 PID `2328`, creation `2026-11-16T06:14:42.902727+09:00`이다. 이 실행 확인은 새 bridge bytes의 실앱 성공 근거가 아니다. 실행 중인 앱 종료·탭 닫기·hot reload·실제 설치 교체를 수행하지 않았다. 별도 로컬 operator가 구체적인 legacy 위험 수용 계획과 continuation을 검토·승인하지 않았으며 새 fixture를 생성하지 않았다. 실제 loaded epoch qualification, 독립 target/producer closure, unbaking 완료 계약과 최종 native recipe/consumer 납품은 미완료다. 두 원 요청·raw terminal·키·nonce·소비 상태를 변경하지 않았다. 전체 goal은 완료 처리하지 않는다.

**이번 R6의 한정 확인:**

- `tests/test_incident_admission.py::test_two_domain_admission_and_bounded_diagnostic`: **1 passed in 1.75s**. 실제 임시 queue→native drain→signed metadata receipt와 원 terminal 중복 조회를 확인했다. SDK scene 접근은 trap이며 실앱 실행이 아니다.
- `tests/test_r6_producer_installer_boundaries.py::test_in_place_code_rollback_retains_real_store_identity`: **1 passed in 1.92s**. 임시 디렉터리에 실제 PowerShell helper를 실행해 인증된 IncidentStore의 물리 root ID·marker·unknown/state/snapshot/log/policy bytes와 새 evidence를 유지하고 code만 복원했다. corrupt preimage는 clear 전에 거절했다. 실제 source/frozen 설치 전체는 실행하지 않았다.
- `tests/test_r6_producer_installer_boundaries.py::test_prospective_process_records_preserve_actual_terminal_bytes`: **1 passed in 1.81s**. 실제 query-only Win32 자기 process/image identity와 임시 signed outbox→private claim/first-effect→unknown terminal raw archive를 확인했다. SDK epoch attestation만 fixture로 격리했으며 source/terminal bytes를 그대로 보존했다. Windows의 `fstat` change time과 path `stat` creation time 차이를 같은 시간으로 가정하던 결함을 수정했다. 같은 descriptor의 전후 ctime은 계속 대조하고 handle↔path의 volume/file ID·size·mtime을 대조한다.
- 실제 임시 `AtomicQueue`/v2 sidecar 재현(exit 0)에서 동일 요청 재전송·변조 epoch·pending setup·추가 unknown·bool frame을 거절하고, 만료 후에는 원 요청 관측만 수행함을 확인했다. 승인·native 관측은 명시적 fixture이며 실제 local operator 승인/SDK/app 함수는 호출하지 않았다. 중간 observer double의 누락된 `execution_mode`를 고쳐 이 한정 재현만 재실행했다.
- 실제 두 원 terminal 파일도 읽기 전용으로 다시 hash했다. global `f871806f1b62d7127a4316a160e83f6baa249fa7078024eb0b659d09b49a30fb`, isolated `ac0afaf64891be8405acdf2c66c7d98789555f55acb2969904d851ba6f2e1138`로 기존 raw bytes와 같다. 이는 종료·격리 증거가 아니다.
- `.venv` Python의 단일 SDK-shaped inline 재현은 **exit 0 / 0.71s**였다. 실제 extractor의 dtype/shape·paired interface·graph-only 변경·외부 endpoint 거절, runner late callback 증거 폐기, private snapshot identity·historical source와 fresh graph의 구분, 전체 source의 4-channel 위치 예측·다른 object/assets 보존·nonunit scale 거절을 확인했다. 첫 실행에서 내부 tuple 주소가 strict JSON 계약에 어긋나는 결함을 발견해 leaf의 주소 표현만 JSON 배열로 고쳤다. 실제 SDK/앱 실행이 아니다. rollback의 exclusive marker 생성과 `modify_update` 진입 전에도 producer/효과 guard를 두고 callback 내부 재검사는 유지했다.

전체 suite/lint/build/독립 audit은 실행하지 않았다. 이 결과로 실제 callback 완료·native save/load·geometry·unbaking 또는 OS realm closure를 주장하지 않는다.

### 최신 추가: setup 효과 경계와 retirement 재개 보완

원격을 다시 fetch했으며 R5 개선안은 `dffa8f9956a01c15e9db02cee33e490f3569cd05`로 동일하다. R5-01~10 전체 목표를 유지하며 기존 구현 `e53a8f7` 위에서 다음을 보완했다.

- setup의 승인된 부모/step 디렉터리를 물리 ID로 고정하고 매 효과 전에 재확인한다. 원 탭·파일 경로·projection 보존 검사를 private setup context에 묶어 fixture callback 내부에서도 setter 전에 실행한다. 실패 diagnostic 파일도 이 경계를 통과해야 쓰며, fixture 활성화 실패가 탭 자동 삭제로 이어지지 않는다.
- 명시적 `setup.qualify_geometry_calculation`을 연결했다. 설치 SDK의 소유 self-bound cube와 실제 typed return을 사용하는 관측 코드이며, 새 탭 1개·`.casc` 2개·계산 5회·평가 2회·기존 driver key 변경 1회로 승인 범위를 고정한다. 좌표계/순서 의존성/driver 반영과 read-compute-read를 관측하고 탭·파일을 보존한다. 아직 실앱에서 실행하지 않았고 일반 mesh 계약을 발급하지 않는다.
- retirement는 동일 승인·계획으로 이미 durable start된 경우에만 만료 뒤 관측 재개를 허용한다. signed component result를 결정된 경로에 보존하고 journal commit 전에 재검증한다. 원 OS attempt/result가 없는 새 host에서는 종료를 재dispatch하지 않는다. 아직 시작하지 않은 만료 계획, 다른 승인·snapshot·head는 거절한다. 실제 종료나 격리는 실행하지 않았다.

**이번 한정 확인:** 프로젝트 `.venv`의 `tests/test_incident_admission.py tests/test_native_probe_retention.py`는 **`5 passed in 1.97s`**다. 같은 lexical 경로의 부모 디렉터리 교체 거절, callback 내부 원 projection 변경 거절, geometry helper의 admission 없는 진입 거절을 포함한다. 최초 시스템 Python 3.11 호출은 패키지 미설치로 collection에 실패했고, 위 결과는 프로젝트 환경에서 실행했다. 실앱 calibration 성공 근거는 아니다.

별도 `tests/test_incident_retirement_resume.py::test_started_retirement_expiry_resumes_evidence_without_os_replay`는 **`1 passed in 1.14s`**다. 실제 임시 authenticated journal/result append·reload를 사용해 만료 전후 missing attempt의 새 실행 금지, never-started 만료·다른 valid-MAC 승인·무관한 head 변경 거절, 저장된 동일 결과 재사용과 원 terminal bytes 보존을 확인했다. OS scope/receipt 검증은 명시적 double이며 실제 Win32 executor는 금지했다. 실제 종료·격리 검증으로 세지 않는다.

**진행을 막는 실제 근거 공백:** 두 legacy unknown의 원 producer PID/creation/image 및 하위·외부 consumer/리소스 전체 범위를 인증하는 issuer가 없어 실행 가능한 retirement 계획을 만들 수 없다. native completion trace에는 이를 소급 복구할 정보가 없다. 직렬화 field-role의 SDK dtype/producer graph는 Update callback에서만 보이며, 현재 readonly Scene에는 graph-only 변경을 인증할 accessor/revision이 없다. 따라서 이름이나 Animation 모드로 tolerance policy를 발급하지 않았다. 새 geometry 관측도 incident가 해소되고 승인된 새 loaded epoch에서 실행해야 하며, 임의 새 root·현재 PID·mock로 대체하지 않는다. 전체 목표는 미완료다.

이번 설치 파일 재조회는 ProductVersion/FileVersion `2026.2.3.0.16863`을 확인했다. 같은 시점의 `Win32_Process` 조회에는 항목이 반환되지 않았다. 이는 앞서 관측한 PID의 정상 종료나 producer closure 증거가 아니며, 앱 종료·재시작·설치 교체·hot reload는 수행하지 않았다.

### 이전 추가: R5 전체 목표 재설정과 호스트·브리지 연결

원격을 다시 fetch해 r5 최신 `dffa8f9`, 구현 branch의 기준 `fc0e98e`를 확인했다. 문서·참조 코드·patch·task 전체를 읽은 뒤 **R5-01~10 전체를 새 목표로 설정**했다. 목표는 원 unknown을 보존하면서 incident admission, 원 시도 완료 판정, 유한 setup 보존, geometry 파일 효과/품질, P0 직렬화와 unbaking 계약을 실제 entry point에 연결하는 것이다. 원격 제안 26개 파일은 `docs/implementation/cascadeur-motion-r5`에 원문으로 보관했으며, 제안 파일 내부의 `not_applied` 등은 작성 당시 상태다. 현재 구현 상태는 이 절을 따른다. 실앱 증거가 필요한 전체 목표는 아직 완료하지 않았다.

- 별도 목적 키로 인증하는 incident journal/control과 고정 domain registry를 추가했다. 원 signed outbox·terminal의 canonical/raw digest, store UUID·물리 ID, journal seq/이전 hash/MAC/head를 검증한다. 실제 global/isolated 두 store를 새 registry에 등록하고 host-only inspect로 읽었다. 원 키와 요청/receipt는 변경하지 않았고 registry digest는 `f615836ace3cb61a91152b40d0f394504190c083cb7bd6f4ef08b26af552c89d`다. 원 두 요청 `ffb7fc8e-417c-454c-a669-48625a086eda`, `fcf3352a-483c-4f9c-bc18-8b61a58822eb`는 모두 **open**, journal seq 0이며 새 종료·격리 작업은 하지 않았다. 두 raw terminal hash는 각각 `f871806f1b62d7127a4316a160e83f6baa249fa7078024eb0b659d09b49a30fb`, `ac0afaf64891be8405acdf2c66c7d98789555f55acb2969904d851ba6f2e1138`로 원 기록과 같다.
- 공개 incident inspect/observe/prepare/commit, bounded native metadata/original-observation reader, 별도 local operator 승인 명령을 연결했다. immutable outbox 뒤 발급하는 admission sidecar는 전체 domain snapshot, request/source/안전 인자, epoch/전체 loaded bytes, 만료와 한 번의 native claim을 묶는다. native는 scene routing 전과 각 쓰기 경계에서 다시 검증한다. sidecar 없는 이전 sender, 다른 root, stale peer incident로 새 source/setup/effect를 통과시키지 않는다. 원 request ID의 terminal 재조회는 기존 결과를 그대로 반환한다. 원 시도 private evidence를 잃으면 새 프로세스의 성공으로 대체하지 않는다.
- 실패 완료 기록은 원 adapter attempt·실제 after·callback trace·effect closure와 결합하며 terminal 기록 직전 다시 확인한다. 원 terminal 뒤의 callback revocation은 receipt를 다시 쓰지 않고 epoch를 격리한다. 실패에서 `result=None`이어도 원 오류와 별도 post-source 오류를 보존한다. insertion source는 성공·실패 모두 소비한다. 성공-only trial을 실패 lifetime 증거로 사용하지 않는다.
- `verify-install.ps1`에 catalog-2026.1과 independent-2026.2의 exact profile을 분리했다. setup은 별도 검토·승인한 유한 helper sequence만 dispatch하며 snapshot 하위의 새 계획 폴더/정확한 step 폴더와 tab/file 상한을 묶는다. 통합 중 계획의 중첩 경로와 보존기의 단일 경로 제한이 불일치하던 결함을 수정했다. helper 자체도 admission을 먼저 확인한다. 성공·실패의 탭/파일은 보존하고 자동 삭제·재실험하지 않는다. broad scene qualifier는 별도 lifecycle이 없어 거절한다.
- geometry capture를 별도 file effect와 recipe stage로 연결했다. mesh/frame/계산·배열·파일 예산, read/compute/read, exclusive 파일과 목적별 completion sidecar, terminal 이후 메모리 봉인/원 manifest 조회, 같은 handle의 제한된 NPZ 검증을 추가했다. 기존 raw mesh sampler의 NPZ 생성도 readonly가 아닌 file effect로 분류하고 미자격 route를 gate했다. 실제 NPZ 재현에서 float64 frame grid가 정수와 같다는 이유로 통과하던 결함을 찾아 canonical little-endian int64 grid를 요구하도록 고쳤다.
- checkpoint schema v2는 P1/P2/load/restored-save를 모두 하나의 불변 P0와 직접 비교한다. 원 anchor와 실제 복구 raw projection·작업 파일 hash·후속 source를 분리하고 기존 v1 exact 경로를 유지한다. unbaking 세 step은 공개 prepare/recipe 예약/native selection 전에 각 exact lowering·scope·완료 계약을 요구한다. 새 공개 MCP 도구 11개와 `recipe_plan` geometry policy schema를 등록하고 의도된 golden을 갱신했다.

**실제 설치 확인:** 이번 재조회에서도 `C:\Program Files\Cascadeur\cascadeur.exe`의 ProductVersion/FileVersion은 `2026.2.3.0.16863`이며 PID `2328`, 시작 `2026-11-16 06:14:42.902727 +09:00`이다. 실행 파일/프로세스 확인이며 새 native 코드의 실앱 실행 확인은 아니다. 실행 중인 앱의 탭을 닫거나 설치 교체·hot reload·재시작하지 않았다. 이 새 source와 기존 loaded bridge의 자격은 서로 재사용할 수 없다.

**현재 남은 구체적 작업과 한계:**

- 두 legacy unknown에는 원 생산자·하위 작업·외부 consumer·리소스 범위를 닫는 독립 증거가 없다. 원 private completion도 소급 생성할 수 없다. 따라서 실제 executable retirement plan은 준비되지 않았고 operator 승인을 요청하거나 발급하지 않았다. Windows handle/file ID·정확한 PID/creation time·이미지 hash·termination wait·OS receipt·물리 분리 구현은 추가했으나, production의 원 scope/baseline/workspace lineage verifier enrollment와 producer-closure issuer 연결은 아직 없다. 이 hook을 실제 증거와 연결해야 종료·격리 및 새 workspace로 진행할 수 있으며 현재 OS executor는 실행하지 않았다. 임의 PID 목록이나 현재 PID `2328`로 원 생산자를 추정하지 않는다.
- geometry의 설치 SDK 좌표/transform·동기 완료·dependency closure calibration registry는 비어 있다. mutation-origin successor rebind도 미지원이다. 경로는 실패 전에 gate되며 일반 rig geometry/최종 품질의 실앱 성공을 주장하지 않는다.
- 직렬화 numeric field-role/tolerance의 실제 native qualification registry는 비어 있다. exact 비교는 유지하고 허용 오차를 임의로 늘리지 않았다. 비정확 저장 drift가 생기는 실앱 checkpoint/복구 성공은 미확인이다.
- unbaking 세 step의 exact action/lowering/완료/topology·key 생성 상한 증거와 insertion 실패 lifetime issuer는 미자격이다. setup 경로를 추가한 것이 기능 자격이나 원 unknown 해결을 뜻하지 않는다. clean 설치/새 loaded epoch와 실제 recipe·consumer 납품도 미완료다.

**실행한 한정 확인:** 최종 `tests/test_incident_admission.py tests/test_native_probe_retention.py`는 **`4 passed in 1.31s`**였다. 실제 queue/outbox/sidecar/native drain·signed receipt 연결, scene 접근 trap, 원 terminal 재조회, 이전 sender 거절, peer snapshot 변경/복제 키 거절, journal append/reload·변조 거절, exact setup 부모/step 폴더·단일 dispatch와 fixture 보존 경계를 확인했다. SDK helper는 double이며 실앱 자격 증거가 아니다. 별도 agent의 좁은 완료/원 증거 재현은 실제 guard/receipt 경로에 private adapter/producer double을 사용했고, NPZ 10사례는 실제 파일로 shape/dtype/frame/hash/길이·과대 header·중복 ZIP 거절을 확인했다. 새 MCP 도구는 in-process MCP Client의 실제 목록/스키마 조회로 등록을 확인했다(기존 도구 삭제 0, resource/template 변화 0). golden 생성 자체를 독립 검증으로 세지 않는다. 전체 suite/build/lint/CI, 새 Windows OS executor, 새 profile verifier와 실제 native qualification은 실행하지 않았다.

### 이전 추가: 설치 SDK의 실제 mesh 계산 경로 수정

현재 checkout의 원격 개선안은 앞 절과 같은 r4이며 전체 목표를 축소하지 않았다. 실제 앱 PID `2328`이 이번 CIM 조회에 다시 반환됐다. 앞선 빈 조회 결과는 종료 증거가 아니며, 현재 실행 중인 앱에 설치를 강행하거나 bridge를 hot reload하지 않았다.

설치 `resources/scripts/stubs/csc/domain/__init__.pyi:636`은 `csc.domain.calc_skinned_mesh(Scene, ObjectId, int) -> SkinnedMeshCalcResult`를 선언한다. 기존 `animation.mesh_sample` handler는 이 함수를 `csc.domain.assets`에서 찾고 있어 실제 typed namespace와 맞지 않았다. 설치 stub의 `positions` 선언(`565–567`)은 `float32[3,1]` 목록인데 기존 handler는 `(N,3)` 배열만 받았다. 호출 namespace를 정정하고 정확한 `(N,3,1)` 배열을 `(N,3)`으로 정규화했다. 기존 NPZ·triangle·joint/skin-weight·frame·hash·반환 계약은 유지했다. 의심했던 vertex 필드는 실제 SDK property가 `position_index`이므로 변경하지 않았다.

이 결함에는 직접 호출 경계 확인이 필요하여 작은 SDK-shaped double에서 실제 handler와 NPZ 쓰기/읽기만 실행했다. `tests/test_native_mesh_sample.py -q`는 **`5 passed in 0.46s`**였다. 두 좌표 배열 형태에서 정확한 frame별 호출·기하/skin 배열·파일 SHA를 확인했고, 잘못된 layout/vertex coverage/nonfinite 값은 파일 생성 전에 거절했다. 이는 실제 설치된 Cascadeur에서 mesh API를 실행한 결과가 아니다. 새 native bytes의 실앱 qualification, 전체 suite/build/CI는 실행하지 않았다.

**남은 연결의 구체적 한계:** 설치 stub과 Python source에는 이 mesh 결과의 world/local 좌표계, reskin 완료·평가 신선도·operation-correlated 완료 계약이 없다. 현재 interpolation receipt는 mesh 계산을 관찰하지 않는다. 따라서 raw 파일 hash/count를 global canonical metres 또는 `native_actual` geometry manifest로 인증하지 않았다. `actual_mesh_metrics`가 요구하는 원 source/successor·motion capture·완료 receipt·topology/skin/window hash 연결은 이 실제 관측이 없으면 활성화할 수 없다. 기존 consumer의 finite parentless Transform 경로에는 원본 baseline/rest/intent/policy → 공통 roundtrip → 동일 sealed artifact 게시 연결이 이미 있으며, 일반 animated armature container/mesh는 해당 native/rest 관측이 더 필요하다. 이 조사에서 consumer 코드는 변경하지 않았다.

두 원 runtime의 인증키로 기존 request/receipt MAC·identity·sequence·result digest를 읽기 전용 확인했다. global `ffb7fc8e-417c-454c-a669-48625a086eda`는 terminal `outcome_unknown`, dispatched true, write phase `not_started`, recovery false다. isolated `fcf3352a-483c-4f9c-bc18-8b61a58822eb`는 terminal `outcome_unknown`, dispatched true, write phase `completed`, recovery false다. 어느 write phase도 완료 불명을 임의로 미실행/실패로 바꿀 근거가 아니다. 키·원 요청·receipt·unknown·소비 기록은 수정하지 않았다. 이 barrier는 여러 이전 목표 턴부터 계속 존재하며, 원 완료 근거 없이 새 capture/mutation/복구로 우회할 수 없다. 실제 부분 실패의 private attestation/recovery 연결 코드는 이미 있으나 기존 unknown을 그러한 실패로 바꾸어 적용할 수 없다.

추가 실앱 qualification·실제 설치 교체/재시작 후 상태 연속성은 현재 환경에서 미완료·차단 상태다. 앱 종료만으로 unknown이 해결되지는 않는다. 원 요청의 권위 있는 완료 근거와 지원 operation/좌표계의 실제 SDK 관측 없이, 새 root·직접 setter·receipt 수정으로 목표 완료를 만들어 내지 않는다.

### 이전 추가: unbaking의 명시적 topology 권한과 예산 연결

원격 개선안의 live SHA는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`로 동일하며, 전체 16개 목표를 유지한다. 설치 실행 파일의 ProductVersion/FileVersion은 `2026.2.3.0.16863`으로 다시 확인했다. 이번 `Win32_Process` 조회에는 Cascadeur 항목이 반환되지 않았다. 앞 절들의 PID `2328` 실행 관찰은 당시 기록이며, 이번에 앱 종료 원인·정상 종료·새 프로세스의 loaded bridge를 관찰한 것은 아니다. 전역 설치 교체나 실제 unbaking은 실행하지 않았다.

- `MotionStageSpec`의 `native_unbaking`은 `unbaking_limits`의 `maximum_added_keys`, `maximum_removed_keys`, `maximum_written_keys`를 모두 명시해야 한다. bool/실수 count, 음수, 추가+삭제가 write 상한을 넘는 계약, 무시될 `settings`는 거절한다. 다른 mode의 unbaking 전용 제한도 거절한다. 추가 키는 원 intent의 opt-in·추가키 상한·run 예산에 묶인다.
- 원 intent의 `allow_key_insertion`/`allow_interpolation_change`와 세 count만 native `topology_policy`로 내린다. 공개 MCP `animation_unbaking_prepare`도 같은 필수 계약을 요구한다. 승인 경계는 원 step·정확한 객체/레이어/단일 구간·원 선언/permit·source의 operation 인자와 digest를 비교한다. 인자와 digest를 함께 바꾸어도 권한을 넓힐 수 없다.
- runner는 prepare 전에 원 request/attempt를 기록하는 동일 CAS에서 최대 added/written을 한 번 예약한다. cleanup 삽입 배정은 unbaking 예약을 뺀 원 생성키 상한을 공유한다. `outcome_unknown` 재조회는 원 request/token/소비 예산을 보존하며 환급·재dispatch하지 않는다.
- native handler에 실제 전체 projection의 전후 비교를 연결했다. 승인 밖 layer/객체/구간·공유 reference·정적 값·원 라벨·허용하지 않은 interpolation/fixation 변경과 추가/삭제/write 초과를 거절한다. write 수는 추가/삭제/변경 section과 변경 sample을 제어하는 authored key의 고유 `(layer, frame)` 합집합이며 SDK setter 호출 횟수가 아니다. 전체 reader의 raw label ID 중 실제 `Key.no_label_id()`와 일치하는 값만 이 비교용 projection에서 `None`으로 정규화한다. 실제 라벨은 지우지 않는다.

**완료 근거는 여전히 없다.** 설치된 `resources/scripts/stubs/csc/tools/__init__.pyi`의 `AnimationUnbakingTool`에는 interpolation difference getter만 있고, `AutoPosingTool`의 add/update와 `ActionManager.call_action -> None`은 세 step의 동기 완료 증거가 아니다. 설치 `resources/scripts/python/ml/editable_animation.py`의 `run(scene)`도 전역 application/current scene을 사용하며 hierarchy 대화상자·deferred callback·layer 범위 확장·내부 실패 처리가 있다. 이 모듈이 각 action ID의 정확한 binding이라는 근거도 확인하지 못했다. 임의 SDK symbol 탐색, global SDK 교체 또는 반환 `None`을 성공으로 처리하는 어댑터는 만들지 않았다.

따라서 handler는 post-dispatch projection이 범위 안이어도 `native_completion: unverified`와 effect `unknown`을 유지한다. snapshot은 이후 비동기 효과를 닫는 증거가 아니다. production unbaking gate는 열지 않았고 native 완료/result/non-target의 실앱 검증은 미완료다. 기존 unknown 기록·인증키·receipt·전역 unresolved-effect barrier는 수정하거나 우회하지 않았다. bridge bytes가 변경되어 과거 loaded fingerprint의 자격을 재사용할 수 없다.

이 권한·예산 경계에는 직접 실행 확인이 필요해 해당 사례만 실행했다. `tests/test_unbaking_bounds.py tests/test_recipe_execution.py -k unbaking -q`는 **`25 passed, 30 deselected in 3.23s`**였다. 이후 SDK no-label 정규화를 추가하고 그 새 사례만 실행하여 **`1 passed in 0.15s`**를 확인했다. 고유 사례 26개이며, 실제 host lowering/store/CAS·projection 비교와 MCP 입력/전달 확인이다. projection/SDK/source doubles를 사용했으므로 실제 Cascadeur action 완료 증거가 아니다. 공개 golden은 이번 unbaking/recipe 계약과 앞서 추가되어 누락됐던 position 준비 도구 세 개, 설명 공백 차이 한 개를 실제 MCP schema로 갱신했다. 갱신 자체를 독립 검증으로 세지 않는다. 전체 suite/build/CI, 실제 recipe·새 loaded 자격·설치 연속성은 실행하지 않았다.

### 이전 추가: 새 키와 기존 키의 공동 fitting 및 후속 보정 연결

원격 개선안 branch를 다시 조회했으며 최신 SHA는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`로 동일하다. 기존 16개 목표는 계속 진행 중이다. 실제 설치 파일의 ProductVersion/FileVersion은 `2026.2.3.0.16863`이며 이번 CIM 조회에도 PID `2328`이 실행 중이었다. 전역 설치 교체나 앱 종료·재시작, loaded qualification은 이번에 실행하지 않았다.

- `refine_sparse_keys`의 기본 동작은 원 키 고정이다. cleanup fallback만 `allow_existing_key_updates=True`를 명시하여 새 키와 변경 가능한 기존 키 값을 공동 QP로 푼다. 원 key/frame/mode/tangent/section은 유지하며 lock/contact/event/편집 범위 밖/root-preserve 값은 고정한다. 기존 키만으로 해결되는 결과를 삽입 또는 `no_change` 성공으로 위장하지 않고 `KEY_INSERTION_NOT_REQUIRED`로 돌려준다. 이전 existing-key fit 경로는 유지한다.
- 공동 fitting은 실제 원 곡선의 중립 값으로 새 키만 먼저 삽입한다. 원본 capture/layout/source, 삽입 직후 private 예측, 요청 목표와 최종 float32 driver/full-grid 목표를 별도로 보존한다. float32 변환 후 fit 잔차와 원본 기준 전체 영향 구간의 correction/pose/보호 조건을 다시 검사한다. 삽입 단계에서 기존 키를 함께 쓰지 않는다.
- 승인 plan은 `solve → key_insert → insertion_evaluation → insertion_readback → refinement_correction → correction → actual_readback`을 미리 선언한다. 후속 host planner는 같은 cleanup index의 원 삽입 receipt, private topology completion, 새 실제 local/global capture 및 정확한 삽입 layout을 다시 확인한 뒤 일반 `animation.position_keys_set` 후보만 발급한다. 쓰기는 기존 별도 permit/prepare/commit 경로로 간다. 나중 cleanup의 후보나 다른 receipt를 가져와 이어갈 수 없다.
- 중간 readback은 `insertion_interim_integrity`로 원본 불변 조건과 private 삽입 예측을 확인하고 최종 repair/contact 등의 의무를 명시적으로 연기한다. 최종 readback은 원본 intent의 전체 native quality policy와 retained 최종 full-grid 곡선을 확인한다. 중간 pass를 최종 pass로 재사용하지 않는다. 필요한 root/lock/이미 관측된 회전은 실제 global/local capture로 수집하며 추정 quaternion으로 채우지 않는다.
- QP의 변경 가능 기존 키 변수·최대 두 번의 grid별 fitting·3축·각 `fit_iterations` 상한, 추가 실제 capture/read 및 메모리를 호출 전에 예약한다. 미세한 기존 키 수치 오차는 모든 해당 열을 실제 원 값에 고정한 전역 재계산 한 번으로 처리하며, 최종 예측에 남긴 변경을 write에서 누락하지 않는다. 기본 run 예산은 자동 확장하지 않는다.

이 계산과 continuation 경계를 확인할 필요가 있어 선택한 호스트 사례만 실행했다. 첫 실행은 **`1 failed, 9 passed, 59 deselected in 1.93s`**였다. 실패는 테스트에서 `SourceBinding` DTO를 dict와 직접 비교한 assertion이었으며 canonical JSON 비교로 고쳤다. 여기에 최종 품질 경계와 보호 회전 실제 요청 사례를 묶어 해당 두 사례만 실행한 결과는 **`2 passed in 0.93s`**다. 고유 사례 11개가 통과했다. 기존 키 고정 기본값/opt-in, 기존 키 lock, 새 키 native units, 중립 삽입과 기존 키 후속 보정, 원 capture 보존, private 완료 없는 continuation 거절, topology/prediction 변조 거절, 동일 cleanup/원 receipt 연결을 확인했다. 중간 중립 곡선은 무결성만 pass이고 최종 곡선과 다르면 실패하며, 최종 full-grid 값과 실제 품질 계산이 일치할 때만 최종 경계가 pass였다. native proof/capture/receipt doubles는 호스트 계약용이며 실제 앱 성공 증거가 아니다.

**남은 제한:** 현재 isolated/global의 원 `outcome_unknown`과 전체 unresolved-effect barrier를 보존한다. 새 runtime root, 직접 setter 또는 원 요청 재분류로 우회하지 않았다. 새 공동 fitting 레시피의 native 실행, 새 loaded bytes의 자격 확인, 일반 rig/rotation/coupled 모델·retarget refinement·unbaking·실패 복구·실제 설치 연속성·최종 consumer 납품은 미완료다. 새 host bytes/compiled 단계에는 새 plan/grant가 필요하다. 전체 suite/build/CI는 실행하지 않았다.

### 이전 추가: 설치 실패 정리와 설치 진단 연결

원격 개선 문서 branch의 최신 SHA는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`로 동일하며 기존 16개 목표를 유지한다. 실제 설치 파일의 ProductVersion은 `2026.2.3.0.16863`이다. **이전 턴의 "실행 중 프로세스 없음" 기록을 정정한다.** `Win32_Process`와 `Get-Process -Id 2328`에서 `2026-11-16 06:14:42 KST`부터 실행 중인 Cascadeur를 확인했고, UI에서도 `guarded-spaced-key-insertion-8e409ec0-0054-4982-a654-ce04d572c37c/working.casc`와 기존 retained 탭들이 열려 있음을 확인했다. 앱은 응답했다. 해당 프로세스에 새 bridge bytes를 hot reload하지 않았다.

- 실제 `scripts/install.ps1 -SkipCodexRegistration`을 실행했으나 초기 idle 검사에서 PID `2328` 때문에 교체 전 거절됐다. 강제 종료·우회 설치·전역 MCP 재등록을 하지 않았다. 전역 런타임의 인증된 요청 7건(성공 6건, `outcome_unknown` 1건)을 읽었으며 기존 unknown ID는 `ffb7fc8e-417c-454c-a669-48625a086eda`다. 거절 전후 state/snapshots/logs/policy의 파일 59개 hash가 모두 같았고 추가 파일도 없었다. 아래 isolated-runtime의 삽입 unknown과는 별도 원 기록이다.
- source installer의 dependency/fingerprint/smoke 준비를 기존 실패 정리 범위 안으로 옮겼다. 준비 중 실패해도 staging 정리를 거치며, staged smoke가 예외로 끝나도 `CASCADEUR_MCP_ROOT`를 `finally`에서 복원한다. 활성화 후 rollback과 maintenance lease 수명은 기존 경로를 유지한다.
- `verify-install.ps1`은 installer와 같은 canonical Local AppData를 사용한다. host manifest의 schema·전체 Python 파일 map·fingerprint를 확인하고 실제 bridge의 누락/변경/추가 파일을 개별 보고한다. command/event import 파일과 `settings.Python.Path` 등록도 확인한다. event package는 import 파일 존재만 확인하며 그 bytes는 기존 bridge manifest 범위 밖이다. 디스크 일치는 running process의 loaded bytes나 qualification 증거가 아니다. 2026.1 고정 버전 조건과 명시적 `SkipCascadeurVersion`을 유지하며 capability는 열지 않는다.

두 설치 스크립트의 PowerShell 구문 확인은 오류 0건이었다. 저장소 bridge Python 파일 56개의 실제 map으로 호스트 Python과 새 PowerShell verifier의 fingerprint가 모두 `d8eee3b8ed61fe1f2ebad9c3cbaa19e8182c800f2467593c5361b261b5f9a71e`임을 확인했다. **실제 `verify-install.ps1`은 exit 1**이었다. 전역 runtime의 `bridge-package.json`이 없고 Cascadeur command/event/Python.Path 등록과 Codex 등록이 모두 false였다. 설치 build도 2026.1 고정 baseline과 다르며 stdio smoke는 실행되지 않았다. 이 진단으로 전역 MCP 설치 완료를 주장하지 않는다. 현재 실행 중인 시험용 bridge와 전역 설치 등록은 구분한다.

임시 fixture에서 staged-smoke 예외를 주입하는 확인 명령은 자동 승인 정책이 `blocked by policy`로 거부해 실행되지 않았다. 우회 재시도하지 않았으므로 실제 실패 정리·환경 복원을 실행 검증했다고 주장하지 않는다. 실제 설치 교체·clean restart·새 manifest의 loaded 일치와 이전 receipt의 업그레이드 후 조회는 미완료다. 기존 unknown/global barrier·native 종료 crash와 일반 rig/recipe의 남은 요구도 유지한다. 전체 suite/build/CI는 실행하지 않았다.

### 이전 추가: sparse refinement와 별도 recipe 삽입 단계 연결

원격을 다시 fetch했으며 개선 문서 최신 커밋은 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`로 동일하다. 전체 16개 목표를 유지한다. 설치 파일 `C:\Program Files\Cascadeur\cascadeur.exe`의 ProductVersion은 `2026.2.3.0.16863`으로 다시 확인했다. 당시 기록한 프로세스 부재 진술은 위 설치 진단 절에서 현재 PID를 직접 재확인해 정정했다.

- 기존 key fitting이 `KEY_LAYOUT_INSUFFICIENT`일 때만, 원 intent의 명시적 opt-in과 별도 승인 생성 키 예산으로 sparse refinement를 호출한다. 실제 발급된 local layout/capture, 0부터 시작하는 전체 3–33 frame grid, 한 독립 position driver, LINEAR/STEP 구간을 요구한다. 원 키 값은 변수에서 제거해 고정하고 기존 mode를 보존한다. 잔차가 큰 frame부터 같은 잔차면 이른 frame을 택하며 기존/새 key와 최소 2 frame 간격, 원 key/section 부재, lock/contact/event/편집 구간을 지킨다. 새 키 8개·전체 16개 상한, full-grid QP·sparse/메모리 예산을 적용한다.
- workflow는 실제 global/local capture의 일치와 parentless 관측을 확인한 제한된 경우만 global 목표를 local로 사용한다. solver metre 값을 정확한 context로 native scene units에 변환하고 float32로 제한한 뒤 native-private 예측을 인증한다. 그 예측으로 전체 frame의 fit 잔차·correction envelope·role/pose/root/lock/contact 보호를 다시 확인한다. 원 capture/source/layout와 요청 목표·예측·delta는 별도로 보존하며 발급된 capture의 binding을 덮어쓰지 않는다.
- recipe는 승인 시 `solve → key_insert → insertion_evaluation → insertion_readback → correction → actual_readback`를 고정한다. 각 cleanup의 생성 상한 합은 원 intent와 run budget을 넘지 않으며 실제 추가 수와 written 비용을 원 request의 `preparing` CAS에서 한 번 계상한다. 이 최초 경로는 기존 키를 쓰지 않는 insertion-only 후보이며, 원 terminal receipt·private actual topology·전체 예측 readback·원 baseline 대비 quality가 맞은 뒤만 correction을 생략한다. ordinary 후보는 삽입 단계를 생략하고 기존 key만 쓸 수 있다. unknown은 원 요청 재관측만 하며 재dispatch하지 않는다.

현재 native `key_topology_write` capability는 여전히 열지 않았다. 일반 리그·retarget refinement·unbaking의 action 완료/생성 key 예산은 이 제한된 경로의 지원 근거가 아니다. 아래의 원 unknown 요청과 global barrier, native 탭 수명/종료 crash 및 설치 연속성의 미완료 범위는 유지한다. 새 native 코드의 실앱 recipe 성공은 아직 관측하지 못했다. 과거 proof/grant를 새 bytes에 재사용하거나 runtime root를 바꾸어 barrier를 우회하지 않았다.

필요한 host 경계만 실행한 최종 결과는 **`5 passed, 59 deselected in 1.14s`**다. 새 키만으로 내부 tent 궤적 fitting·원 키 고정, opt-in/행렬 할당 전 예산 거절, lock/contact 경계 보호, metre→native float32 변환·원 capture 보존·인증된 예측과 다른 목표 거절, 단계별 불변 생성 상한을 확인했다. native proof/receipt double은 호스트 계약 확인용이며 실앱 완료 근거가 아니다. 전체 suite/build/CI는 실행하지 않았다. 삽입 가능 positional solve는 3축과 모든 유한 refit의 `fit_iterations` 상한을 호출 전 예약하고 메모리 ceiling을 승인 run 상한으로 좁힌다. 기본 `solve_iterations=100`을 자동 확장하지 않으므로 opt-in recipe는 필요한 수치 반복 예산을 명시적으로 승인해야 한다.

### 이전 추가: private locator 예측과 durable 완료 인증 연결

`native_key_insertion_evidence.py`와 실제 공개 readonly 도구 `position_keys_insertion_plan`, `position_keys_topology_verify`를 연결했다. 예측은 현재 native registry가 발급한 evaluated capture/key-layout와 source, 전체 frame grid, owned checkpoint, 현재 finite/insertion proof만 사용한다. caller가 준 layout/완료 flag를 registry에 등록하지 않는다. 실행기의 section/전체 projection 예측 함수를 공유하며 기존 key/section·비대상 채널을 생략하지 않는다. 값은 정확한 native float32 local scene units, tangent는 실제 생성할 section 값과 같아야 한다. 예측 자체는 intent·삽입 예산·recipe 권한을 발급하지 않는다.

실제 삽입 전 기존 private prediction을 그 원 request와 single-use native source에 연결한다. runtime이 원 terminal event를 durable 기록한 **뒤에만**, 성공 outcome·완료된 native source·정확한 전체 예상 projection·successor source를 대조해 private 완료를 봉인한다. readback은 원 authenticated terminal chain을 다시 읽고 private 완료·현재 checkpoint/epoch/fingerprint·전체 projection·별도 explicit evaluation의 fresh capture·전체 driver가 모두 맞아야 한다. unknown, 실패/미완료, scene 변경, 재시작으로 유실된 private evidence는 완료로 바뀌지 않는다. registry는 16개 예측/시도로 제한하며 초과하면 거절한다. host는 strict DTO와 원/후속 digest를 대조하고 native 실패/unknown 응답을 보존한다.

필요한 host locator 계약 사례만 실행해 **`6 passed, 27 deselected in 0.84s`**였다. 원 source와 request 결합, 기존 section·새 event·가짜 GUID 거절 및 exact readback 계약을 확인하는 synthetic domain 사례이며 새 native emitter나 실제 terminal/evaluation 성공 증거가 아니다. 전체 suite/build/CI는 실행하지 않았다. 이번 native bytes는 실행 중인 앱에 hot reload하지 않았고 새 실앱 qualification도 실행하지 않았다. 아래 기존 unknown/global barrier와 native crash는 미해결이며, 새 코드의 실제 관측에는 새 프로세스와 그 epoch의 명시적 qualification이 필요하다.

조사한 production 호출 경로에서 sparse fitter는 여전히 기존 key frames만 반환하고 부족하면 `KEY_LAYOUT_INSUFFICIENT`로 거절한다. recipe에는 삽입 전용 stage/permit/lowering·added-key 계상·원 baseline quality 및 실제 topology readback 연결이 남아 있어 capability와 runner의 삽입 차단을 유지한다. 설치 SDK의 `ActionManager.call_action(str) -> None` 및 AnimationUnbakingTool에는 action 완료를 인증할 공개 인터페이스가 확인되지 않았다. 설치 `ml/editable_animation.py`에는 dialog 지연·선택 layer 확장 분기도 있어 projection 반복 조회를 완료 신호로 사용하지 않는다. unbaking 전용 동기 transaction·scope/예산/완료 adapter가 필요하다. 전체 16개 목표는 계속 진행 중이다.

### 이전 추가: 소유 checkpoint의 키 삽입 연결과 실제 unknown 경계

원격 개선안을 다시 fetch했으며 r4 최신은 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`로 동일하다. 전체 16개 목표는 계속 진행 중이다. 아래에는 이번 구현과 실제 관측을 구분했다. 이전 절의 "production 미등록"은 당시 관측이며 현재의 명시적 제한 route 등록과 구분한다.

- `native_key_insertion_adapter.py`를 추가하고 실제 현재-process 자격 확인이 끝난 명령에서만 `motion.key_topology_insert`를 등록한다. 공개 `position_keys_insert_prepare` → 기존 `change_commit` 경로를 연결했다. explicit object/layer, local **native scene units** 값, 삽입 opt-in, 1–8개 예산, 현재 epoch/scene/lineage의 native-owned working checkpoint와 변경되지 않은 backup bytes를 요구한다. 기존 원본·전체 native projection·single-use source 검사를 유지한다. 성공 projection만 별도 successor capture 대상으로 인정하며 같은 삽입을 재실행하지 않는다. 등록 여부를 capability로 표시하되 실제 공개 execution 성공으로 표시하지 않는다.
- host의 locator 계약을 native ID 계약과 분리했다. `layer_frame_locator`를 영구 key GUID로 바꾸지 않으며 source/capture/context/scene/epoch와 전체 예상 driver를 묶은 native-private prediction을 요구한다. 기존 key/section/value/tangent/metadata와 boundary 보존, 정확한 새 row, 실제 terminal receipt에 묶인 readback을 확인한다. **native prediction/completion 발급·인증 연결은 아직 없으므로 recipe topology gate는 그대로 닫힌다.** standalone 등록은 recipe `key_topology_write` 권한을 주지 않는다.
- unbaking lowering과 공개 prepare는 승인된 object/layer 및 단일 frame interval을 실행 인자에 고정한다. handler는 source closure·전체 선택 layer의 object closure·실제 selection을 대조한다. `call_action(str) -> None`을 완료로 세지 않으며 static `scene_revision_changed` 성공 선언을 제거했다. action dispatch 뒤 effect는 `unknown`이다. 전용 완료/topology/생성 key 예산 adapter는 여전히 미자격이며 실제 unbaking을 실행하거나 capability를 열지 않았다.
- independent-scene qualifier는 성공·실패 모두 새 탭/파일을 보존하고 retained ID/path/ownership을 반환한다. 원 탭의 활성 상태·projection·inventory를 확인한 뒤만 등록한다. 자동 `remove_application_scene`/fixture release를 제거했다. 실패 시 retention 조회도 실패하면 원 예외를 보존한다. 명령 래퍼의 잘못된 `scene.success`도 제거했다. 이 변경은 native crash 원인 해결이나 탭 종료 안정성 보장이 아니다.

**실제 공개 요청 실패:** PID `27416`, epoch `beb0c783-2287-44f2-bee9-dbfc6cd9ec39`에서 source capture와 prepare를 거쳐 request `fcf3352a-483c-4f9c-bc18-8b61a58822eb`를 commit했다. 기존 keys `0,2,4,6,8`에 frame `1`을 추가하자 callback/setter는 반환했지만 SDK가 기존 section `0`과 새 section `1`의 LINEAR를 STEP으로 바꿨다. 전체 projection 대조가 이를 잡아 **`outcome_unknown` / `POSTCONDITION_FAILED` / `NATIVE_COMPLETION_UNKNOWN`**으로 남겼다. 실제 terminal receipt 재조회도 같은 unknown이며 source 재사용·재dispatch·복구 성공 승격을 하지 않았다. 원 빈 탭 projection은 보존했고 실패 후 소유 작업은 별도 `unknown-after-insertion.casc`로 남겼다. SHA-256 `2de6cda5c8e4dab134dc77126ded7d6f1383bc9b97a1b94db87db978ffd08bca`다. 원 immutable request/terminal receipt는 그대로 유지한다.

이 관측에 따라 native preflight와 host locator 계약 모두 **삽입 후 모든 인접 key 간격 최소 2 frames**로 자격 범위를 제한했다. 1-frame interval을 새로 만드는 요청은 첫 setter 전에 `KEY_INSERTION_SPACING_UNQUALIFIED`로 거절한다. 기존 key 모드를 SDK가 바꾼 결과를 허용하도록 예상값을 약화하지 않았다.

**최종 새 프로세스의 한정 관측:** 실제 설치 `C:\Program Files\Cascadeur\cascadeur.exe`, build `2026.2.3.0.16863`, PID `2328`(06:14:42 KST 시작), epoch `aea96fff-c90c-4d8c-bba3-4ad5724e77a4`, loaded fingerprint `458d8d570dfe07b7924c2dac91e82d066380ae5bd6f7240407254101a3ddd2f9`에서 수행했다. 과거 private proof를 재사용하지 않고 finite-model 40개와 LL/SS/LS/SL 네 삽입·별도 보간을 다시 확인했다. 실제 `Qualify key insertion adapter` 래퍼가 `observed/complete`와 guarded route 등록을 반환했다. 이어 실제 independent-scene qualification은 세 새 탭을 유지하고 원 활성 탭/projection/inventory를 보존했다. 별도 SDK event에서 새 `0,4,8` fixture를 생성·저장하고 새 owned working/checkpoint로 bootstrap했다. 이는 setup용 직접 native bootstrap이며 host token commit 성공 근거가 아니다. frame `1`의 readonly preflight는 위 spacing 오류로 거절했고 전체 working projection이 그대로였다. 당시 원 빈 탭을 포함한 10개 탭을 보존했다.

그러나 frame `2`를 대상으로 한 **새 host source capture는 dispatch 전에** `An earlier effect has no authoritative completion`으로 차단됐다. 원 `fcf3352a-…` unknown 때문에 bridge가 상태/로그 외 새 요청을 막는 기존 정책이다. runtime root 변경, ledger/receipt 삭제, ID 재사용 또는 직접 SDK 삽입으로 우회하지 않았다. 따라서 새 2-frame route의 공개 commit·successor source·별도 evaluation receipt 성공은 **미확인**이다. 마지막 UI 조회에서는 소유 `working.casc`와 fixture 객체가 표시됐고 프로세스는 존재했지만, 같은 종료 전 점검에서 `Responding=False`도 관측했다. 이를 현재 안정 실행 또는 장시간 정상 상태로 표현하지 않는다. 탭을 추가로 닫거나 사용자 autosave를 열지 않았다.

ignored 실제 근거: `artifacts/native-r4/guarded-key-insertion-adjacent-unknown.json` SHA-256 `b6d95b7fa1c05aba4ba2025c2697c11bc47aee90a29d59e7b9ef4a50a0c36d82`; `guarded-key-insertion-unknown-inspection.json`; `guarded-key-insertion-unknown-retained.json`. 최종 새 epoch의 `key-insertion-spaced-prerequisites.json` SHA-256 `4351cdb4ad29a5b795a73325ec42844dece93a5d3f841b98dc4671223fd057e2`; `key-insertion-spaced-scene-qualification.json` SHA-256 `e55ba3e3a94d597d38ad89fd8a29dc3cbc2b44fcceebdd5d5377a8e9251ef376`; `key-insertion-adapter-setup.json` SHA-256 `94375ca96cc379fb1e790b527a721d7cc856e2bc859ea0c184986b48174089e5`. 원 request/receipt는 `isolated-runtime/state/request_records/fcf3352a-483c-4f9c-bc18-8b61a58822eb/` 아래 있다. auth/state와 실제 작업 파일은 Git에 넣지 않는다.

**추가 crash 관측:** 종료 중 PID `37920`(06:04:52 KST)와 `27416`(06:10:28)은 `Qt6Core.dll` 6.5.3.0 / `0xc0000005` / offset `0xb4c7f`를 기록했다. report는 각각 `4fa23f71-f4d5-4446-9777-da977e3c8052`, `27da418d-06d0-4fb8-bf44-6b6b49f37f4d`다. PID `33988`은 06:12:54 KST, offset `0xae815`, report `ab2ffd23-7854-4546-b19f-cbebfd044048`로 종료했다. 마지막 경우 qualification 후 다음 fixture의 evaluate/read 단계에서 crash가 났으며 HTTP는 idle 대기 timeout을 반환했다. 당시 qualifier의 자동 탭 제거가 있었다는 시간상 관측만 있고 원인 확정은 아니다. 최종 retained-tabs 구현과 별도 SDK event는 해당 단계를 통과했지만 종료/soak를 검증하지 않았다. 근거는 ignored `key-insertion-adapter-restart-exit.json`, `key-insertion-spacing-restart-exit.json`, `key-insertion-spacing-qualification-crash.json`이다.

남은 작업은 native locator prediction/completion 인증, 실제 공개 terminal/successor/evaluation 연결, 승인 intent와 sparse/continuation 및 원본 baseline 품질, bounded unbaking 완료/예산 검증, 실제 실패 복구와 lifecycle/installer 연속성이다. 일반 character·rotation·coupled/shared layer 삽입은 미자격이다. 새 domain 계약 사례는 기존 테스트 파일에 추가했지만 이번에 실행하지 않았다. 전체 suite/build/CI도 실행하지 않았다. 전체 목표를 완료 처리하지 않는다.

### 이전 추가: 실제 absent-frame 키 삽입 primitive

원격 개선안과 구현 브랜치를 다시 fetch했다. r4는 `6a9338c`로 동일하며 전체 16개 목표는 진행 중이다. R4-09의 native 연결을 위해 `native_key_insertion.py`와 명시적 `Qualify key insertion adapter` 명령을 추가했다. 기존 전체 key-grid 재작성과 달리 `set_section`은 **현재 key와 section이 없는 내부 frame에만** 호출하고, 해당 새 key의 local position만 쓴다. 새 구간의 LINEAR/STEP 모드는 원래 나누는 구간과 같아야 한다. 기존 key/section 변경·삭제·retime이나 모드 변경 권한을 추가하지 않았다.

private source는 exact scene/object/owning layer, 전체 projection, build/epoch/fingerprint, 현재 finite-model proof와 callback generation에 묶이고 한 번만 소비된다. callback 진입의 동기·동일 thread·단일 실행과 첫 setter 전 source guard를 확인한다. dispatch 뒤 불확실/불일치는 unknown으로 남기며 같은 source 또는 unresolved scene을 재삽입하지 않는다. 늦은 callback은 setter 전에 차단하고 자격을 폐기한다. 이 방어의 실패 경로를 실제 native partial failure로 관측했다는 주장은 하지 않는다.

최종 실제 관측은 설치 `2026.2.3.0.16863`, PID `37920`, epoch `87d2ea78-eb1e-4d48-9f7f-581de36acddd`, bridge fingerprint `81bfb37530b613aea4303be795682731e1ea6d52fc4951a2308b92e339769537`에서 수행했다. 새 프로세스에서 finite-model 40개 사례를 먼저 확인한 뒤 LL/SS/LS/SL 네 구간 조합 각각에 대해 9 frames / 기존 keys `0,4,8`에 새 keys `2,6`을 추가했다. 새 key 값뿐 아니라 **unkeyed `1,3,5,7`의 실제 보간**, 기존 모든 key/section, 비대상 회전·스케일·빈 기본 Track과 전체 projection을 모델의 예측값과 비교했다. 별도 native interpolate 후에도 같은 projection 비교를 통과했다. 명령은 `observed/complete`로 반환했고 네 `.casc`는 13,998–14,043 bytes로 저장됐다. 다음 idle 조회에서도 각 evaluated projection digest가 유지됐고, 원 빈 탭 보존·활성 복귀·전체 5탭 inventory를 확인했다. 이 비교는 native 값의 동등성으로, JSON 표현의 bitwise 동일성이나 영구 key GUID 증거가 아니다.

ignored 실제 근거: `artifacts/native-r4/key-insertion-repaired-actual-observation.json`, SHA-256 `5683c496e979abff95c78a3a96398d96bdc0660f1c9175d3b479da1761b16302`; `key-insertion-repaired-next-idle.json`; `isolated-runtime/snapshots/key-insertion-qualification-b83d194b-b7db-4bd6-b2cc-8a6553930b41/trial-{0,1,2,3}.casc`. 성공·실패 탭은 자동 제거하지 않으며 각 새 경로에 보존한다.

진행 중 발견한 실제 결함 두 개도 수정했다. 첫 시도는 SDK가 빈 `Track0`와 owning Transform 트랙을 함께 생성해 총 트랙 하나 검사에서 **쓰기 전** 차단됐다. 이제 exact owning layer 하나를 선택하고 제한된 빈 다른 트랙만 허용하며 전체 projection으로 보존한다. 다음 시도는 native 네 사례를 마쳤지만 명령 래퍼의 잘못된 `scene.success` 호출로 반환이 실패했다. 해당 호출을 제거하고 위 최종 새 프로세스에서 명령까지 다시 확인했다. 이전 성공 관측·private proof를 새 fingerprint에서 재사용하지 않았다.

**남은 연결:** 이 primitive는 production 등록을 하지 않았으며 실제 조회에서도 registered operation은 0개였다. 공개 prepare/commit, 승인된 intent/added-key budget, owned checkpoint, durable terminal/evaluation receipt, 원본 baseline quality, recipe sparse planner·continuation과의 통합은 남아 있다. 현재 host의 persistent-native-ID gate를 해제하거나 locator를 native GUID로 위장하지 않았다. 일반 character·rotation·coupled/shared owning layer·새 interpolation mode도 미자격이다. 전체 suite/build/CI는 실행하지 않았다.

**종료 crash 유지:** 위 관측 전 재시작 과정에서 PID `31060`(05:45:25), `15664`, `27824`의 종료는 다시 `Qt6Core.dll` 6.5.3.0 / `0xc0000005` / offset `0xb4c7f`를 기록했다. report는 각각 `79f8d1ab-d8c8-461e-a0a0-2774284f3d4d`, `7aba5fee-25e8-4edb-9a37-cd5c2273e357`, `7e8034ce-2360-4eb0-9fca-ead3473e36a2`다. 첫 두 실행은 삽입을 실행하지 않았거나 쓰기 전에 차단됐으므로 이 이벤트를 새 insertion setter의 원인으로 단정하지 않는다. ignored `retained-restore-next-exit-crash.json`, `key-insertion-first-blocked-exit-events.json`, `key-insertion-wrapper-failed-exit-events.json`에 보존했다. 최종 PID는 응답하는 상태로 두었고 종료 안정성·장시간 안정성 해결을 주장하지 않는다.

### 이전 추가: 비대상 회전 보존과 baseline 품질 의무

R4-08의 원본 보존 경로에서 비대상 role/dependency의 위치만 비교하고 회전 변화는 누락하는 결함을 수정했다. 원본 capture에 회전 채널이 관측된 비대상 객체에는 `non_target_scope_rad`와 원래 승인된 임계값을 요구한다. 위치가 같다는 이유로 회전 보존을 pass로 만들지 않는다. 원본에 관측된 회전이 실제 capture에서 누락되면 `INCOMPLETE_CAPTURE`로 거절하며, 필수 role/dependency의 누락도 건너뛰지 않는다. 시간값이 같아도 frame ID가 다르면 원본 grid 불일치로 거절한다.

잠긴 role/frame 또는 editable 범위 밖에 관측된 회전이 있으면 `key_pose_rotation_rad`도 필수다. 비대상 dependency 회전은 보존 오차뿐 아니라 실제 회전 correction/envelope와 범위 밖 잠금에도 포함한다. recipe는 새 baseline capture의 실제 채널을 기준으로 quality policy의 필수 지표를 **solve/write 전에** 검사한다. 누락된 임계값을 새 기본값으로 채우거나 기존 승인 policy를 재서명하지 않는다. native 품질과 소비자 roundtrip이 같은 공통 metrics/필수 지표 경로를 사용한다.

필요한 호스트 사례 6개를 확인했다. 비대상 role/dependency의 위치 오차가 0이어도 0.25 rad 회전은 실패하며, 누락 회전·필수 role·frame 재지정, 잠금/범위 밖 회전 의무, baseline의 정책 누락을 차단한다. 첫 실행은 테스트의 SciPy 단일축 angle 배열 모양 오류로 `2 failed, 4 passed`였고, 입력 모양 수정 후 해당 두 사례만 `2 passed`였다. dependency만 회전 채널을 가진 경우까지 연결한 뒤 영향받은 같은 두 사례를 다시 확인해 `2 passed in 0.71s`였다. 실제 native recipe나 전체 suite/build/CI는 실행하지 않았다. 이 host bytes 변경 후 이전 plan/grant를 재사용하지 않는다.

설치 SDK와 원격 r4의 키 삽입 요구도 한정 확인했다. SDK `csc.layers.Layer`는 layer GUID/frame locator와 section/ownership을 노출하지만 영구 key GUID는 노출하지 않는다. 원격 R4-09는 영구 GUID 자체를 명시적으로 요구하지 않는다. 따라서 남은 연결 조건은 locator를 native ID로 위장하는 것이 아니라, source/epoch/전체 layer·channel closure에 묶인 별도 locator 계약과 실제 absent-frame 삽입 후 기존 key/section·공유 채널 보존·평가 검증이다. 기존-key writer/전체 fixture key-grid 재작성은 그 증거를 대신하지 못한다. 이번에는 이 증거를 만들지 않았으므로 현재 삽입 gate를 해제하지 않았다.

R4-10 native unbaking에는 추가 연결 누락이 있다. 현재 lowering은 `{step}`만 만들며 handler는 UI의 현 layer/range를 사용한다. 승인된 대상 object/layer/range를 실행 인자에 고정하고 실제 전후 topology와 생성 key 예산을 검증하는 전용 adapter가 필요하다. SDK `call_action(str) -> None`은 완료 신호가 아니다. 현재 미자격 adapter gate가 있어 이 route를 실행하지 않았으며 단순히 gate를 해제하지 않는다. native 탭 수명/종료 crash, 실제 부분 실패 복구 및 일반 리그 입력·설치 교체는 계속 미완료다.

### 이전 추가: export 검증 재개와 메모리·보고서 경계

원격 r4 문서를 다시 fetch했으며 최신 SHA는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`로 같다. 기존 16개 목표를 유지한다. 이번에는 native bytes를 바꾸지 않았고 실제 설치 경로 `C:\Program Files\Cascadeur\cascadeur.exe`의 PID `31060`이 계속 응답함을 확인했다. 아래 호스트 확인은 이전 epoch의 native 실행 근거를 새 구현의 실행 근거로 승계하지 않는다.

- export 검증이 nonpass여도 step을 기본 `succeeded`로 저장해 resume가 검증을 건너뛰던 결함을 수정했다. 명시적 품질/구조/소비자 실패는 원 관측과 함께 step/run `failed`로 보존한다. 미확정 결과는 `ready` step과 `blocked/EXPORT_VALIDATION_UNVERIFIED` run으로 남긴다. 명시적 resume에서만 같은 sealed artifact·profile·원 intent context를 기존 `read_retries` 예산으로 다시 관측한다. 새 native export를 만들거나 기존 요청을 replay하지 않는다.
- 이미 잘못 완료 표시된 legacy validation은 원 authenticated artifact의 nonpass를 읽고 run을 `failed/EXPORT_VALIDATION_FAILED`로 종결한다. 원 step/artifact는 고치지 않는다. publish에는 pass validation 및 artifact/profile digest가 같은 immutable bundle을 요구한다. 기존 publish intent의 reconciliation은 새 import나 권한 발급 없이 원 journal을 계속 조회한다.
- contact solver가 각 nonfree contact마다 유지하는 전체 클립 float64 배열 네 개를 사전 메모리 예산과 반복 계산에 포함했다. 짧은 active 구간만 세어 누락되던 비용을 보완했으며 전역 해·목적함수·클립 범위를 바꾸지 않는다. 이는 host의 알려진 배열 비용 검사이며 native 보간기 `bad allocation`의 원인 해결이나 전체 프로세스 peak RSS 보장이 아니다.
- export stage/validation, consumer raw/canonical capture, manifest와 provenance의 재읽기를 공통 bounded reader로 연결했다. regular file/reparse·크기·열린 descriptor identity를 확인하고 제한된 chunk로 읽은 뒤 변경을 다시 확인한다. raw report는 원 profile 상한, retained sidecar는 기존 report hard ceiling인 256 MiB를 적용한다. MAC/hash와 exact 내용 검사는 유지한다. legacy Blender stdout도 기존 bounded runner의 4 MiB 로그로 제한하며 성공 등급은 계속 legacy다. 이 상한은 파일 bytes에 대한 것으로 JSON 객체 전체 메모리나 Blender RSS의 상한은 아니다.
- 실제 2026.2의 제한된 native 목록이 순수 호스트 기능인 `feature_search/feature_describe`까지 지원 불가로 만들던 표시를 수정했다. 두 contract 기능은 연결 없이 제공하되 live execution으로 세지 않는다. `inventory_refresh` 같은 native dispatcher와 미자격 mutation은 계속 gate한다.

필요한 호스트 대상만 실행해 **`9 passed in 3.73s`**였다. contact 준비 전 예산 거절, JSON 크기/교체/비정규 파일의 parse 전 거절, nonzero consumer 거절, 실패·미확정 validation의 저장/예산 내 동일 입력 재관측/취소/legacy publish 차단, 두 버전의 host-only 표시를 확인했다. consumer/capture double은 실제 FBX·native 실패·Blender 품질 증거가 아니다. 전체 suite/build/CI나 새 native recipe는 실행하지 않았다. host 구현 digest가 바뀌었으므로 과거 plan/grant를 재서명하거나 재사용하지 않는다.

아래의 실제 탭 수명/종료 crash 원인, 진짜 bounded partial-write 실패 뒤 조건부 복구, 일반 rig metadata·영구 key ID·공개 native 삽입과 source/frozen 설치 교체는 계속 미완료다. 전역 인증키·기존 unknown·원 receipt와 사용자의 autosave는 변경하지 않았다.

### 이전 추가: 혼합 키 구간 계획과 복원 qualification 수명

원격 r4 문서를 다시 fetch했으며 최신 SHA는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`다. 기존 16개 목표를 유지한다. 아래 변경은 일반 리그, 실제 부분 실패 복구나 설치 교체의 완료를 뜻하지 않는다.

- 키 삽입 계획은 새 키의 outgoing mode를 해당 키가 나누는 원래 구간과 비교한다. 기존에는 클립의 모든 구간과 비교해 혼합 LINEAR/STEP 클립의 정당한 삽입을 거절했다. 기존 키의 모드 보존, 새 모드 변경에 대한 별도 권한, endpoint/기존 키/중복 거절은 유지한다.
- 필요한 순수 host 대상 두 개만 실행해 `2 passed`였다. 혼합 구간별 삽입과 기존 모드 보존, 새 outgoing mode 변경 권한을 확인했다. 추가한 경계 거절 사례는 실행하지 않았다. 테스트의 receipt double은 native 자격 근거가 아니다. 공개 네이티브 삽입 경로는 아직 연결되지 않았으며 SDK의 `layer_frame_locator`를 영구 native key ID로 승격하지 않는다.
- PID `7452`에서 실제 checkpoint bootstrap→exact 새 탭 복원→별도 source-idle callback의 단일 target 닫기→다음 callback 확인을 관찰했다. 원 작업 탭도 원 빈 탭을 활성화한 뒤 별도 callback에서 닫았고 원 projection/inventory를 보존했다. `staged-restore-observation-41fc570f-0858-4d27-970a-908f6f8cdfa1/restore-qualification.json`의 SHA-256은 `7c9e00dde166859b12a75c438acd7f0df55216e0a000b51c058babb7bd6877ea`다. 이후 해당 epoch에서 primitive만 등록했으며 실패 receipt나 permit은 발급하지 않았다. 이 수동 관찰은 아래 제품 명령의 후속 확인과 구분한다.
- **종료 crash 재관찰:** 원 빈 탭만 남은 PID `7452`에 Alt+F4를 보낸 뒤 `2026-11-16 05:10:55 KST` Event 1000이 `Qt6Core.dll` 6.5.3.0, `0xc0000005`, offset `0xb4c7f`, report `f71a5956-7211-4a8f-a42c-97166c8f8d6b`를 기록했다. 종료 전 응답과 callback 분리만으로 종료 안정성이 해결됐다고 볼 수 없다. ignored 근거는 `artifacts/native-r4/staged-restore-exit-crash-events.json`이다. 정확한 native 원인은 여전히 미확인이며 이 이벤트를 인증된 부분 쓰기 실패로 바꾸지 않는다.

복원 qualifier의 자동 정리를 후속 idle로 나눈 중간 구현도 새 PID `15404`에서 실제 확인했다. `05:15:56.162 KST`에는 `pending/awaiting_close`, production operations 빈 목록을 반환했고, 로그 `05:15:56.863`에는 검증 후 등록 성공 메시지가 있었다. 그러나 `05:15:56.866` 보간기 `[0,101]` reload가 `bad allocation`으로 실패하고 `05:15:57.291` FATAL 종료했다. Event 1000은 `ucrtbase.dll`, `0xc0000409`, offset `0xa527e`, report `a674c3f5-1165-4aad-b3bc-4b00071db554`다. 당시 fingerprint는 `5069238115c734f7ecb02cc733e43fb62ea8477328e9f5c10ccd2d6887b6149a`, epoch는 `1c2b874f-26fa-432a-9189-43bba2424016`이었다. `product-restore-observation-dc46d408-2087-435a-af2e-8ea178e9d4a5/restore-qualification-659ba1e3-140c-466d-9c22-5e34e30dca9f.json`은 SHA-256 `5272677aa9ceec6708f2f8e699d468271b5c96daebe6b8a3b8d360c0b088717e`로 남았지만 종료한 epoch의 근거이며 현재 자격으로 승계하지 않는다. 로그와 이벤트는 ignored `product-restore-crash-log-tail.txt`, `product-restore-crash-events.json`에 보존했다.

설치 SDK의 `execute_when_idle`은 같은 idle manager 호출의 persistent callback 순회 뒤 실행되며 Qt/native event 반환 경계를 보장하지 않는다. C++ scene-idle caller 구현은 노출되지 않아 scene 목록 무효화나 특정 native API를 원인으로 확정하지 못했다. **최종 제품 변경은 복원 실행 자체에 필요하지 않은 자동 close/remove를 제거한다.** 새 owned 복원 탭을 유지하고 다음 source-idle에서 실제 source/target instance·path·전체 projection, 원 inventory, checkpoint manifest·epoch·disk fingerprint를 확인한 뒤 evidence를 `xb/fsync`로 저장하고 등록한다. `pending` 결과에는 qualification ID와 retained target path/ID를 돌려준다. `qualification_status(id)`는 SDK 호출 없는 snapshot이며, 같은 source/checkpoint의 재호출은 원 관측 조회만 한다. source/manifest가 바뀌면 과거 완료를 새 자격으로 쓰지 않고 거절한다. 진행 중 write/재진입은 차단하고 실패한 관측을 재실행하거나 남은 파일·탭을 자동 정리하지 않는다. 이 변경을 native crash 원인 해결로 표현하지 않는다.

최종 bytes는 hot reload 없이 다시 실행한 **PID `31060`**, 실제 build `2026.2.3.0.16863`, fingerprint `0a0213db88ecad5d45cf24f83016f82fb7049bd43c9bd4d822035ff148d27505`, epoch `9de8bfd8-a874-4f21-90bf-fa1ca4d30849`에서 직접 확인했다. 새 소유 입력 복제/checkpoint 후 제품 명령의 `pending/awaiting_verification`에서는 미등록, 이후 조회에서는 `complete`와 `safety.rollback` 등록을 관찰했다. 원 빈 탭·작업 source·retained 복원 target의 전체 projection, 세 탭 inventory와 target path/새 instance·동일 lineage를 보존했다. 같은 source의 재호출도 같은 결과·같은 inventory였으며 loaded/disk fingerprint가 일치했다. 앱은 응답했다. 근거는 ignored `retained-restore-observation-4dbdb391-9604-48dc-91d6-a5632ea65dc8/{bootstrap-observation,qualification-start,qualification-status}.json`과 같은 폴더의 `restore-qualification-92c454c2-d6a7-4538-9550-71591bf366c9.json`, SHA-256 `f4b1ef6eabee52ac2fcceadf307dde22513a8d2df7cfeb26d4e66042889298ae`다.

최종 확인은 작은 독립 객체의 exact restore와 관측 조회 범위다. 작업·복원 탭 두 개는 각 새 `.casc` 파일과 함께 열어 두었고 종료·장시간 안정성은 확인하지 않았다. 실제 부분 쓰기 실패 receipt/attestation/일회용 permit은 발급하지 않았으며 일반 character·키 삽입·전체 installer 교체는 여전히 미완료다. 사용자 autosave·전역 runtime/auth·기존 unknown·원 receipt는 변경하지 않았다. 전체 suite/build/CI를 실행하지 않았다.

### 이전 추가: actual readback 실패의 재개 우회 차단

실제값이 candidate와 어긋나 `DRIVER_READBACK_MISMATCH`가 발생해도, 기존 runner는 run만 `blocked/ACTUAL_READBACK_FAILED`로 쓰고 step은 기본 `succeeded`로 저장했다. resume가 이 blocked reason을 유지하지 않아 이미 완료 표시된 readback을 건너뛰고 다음 checkpoint·quality로 진행할 수 있었다. 원 intent의 correction envelope 안인 불일치라면 뒤의 quality만으로 앞선 candidate 검증 실패가 사라질 수 있었다.

- 새 readback 실패는 관측 artifact와 `verification_status=fail`, step/run `failed`로 저장한다. 원 native request나 실패 관측을 성공으로 바꾸지 않는다.
- 이전 코드로 이미 `succeeded`가 된 readback은 원 terminal step을 고치지 않는다. resume/advance가 소유 run의 hash·길이를 확인한 immutable artifact를 읽고 실패가 있으면 run을 `failed/ACTUAL_READBACK_FAILED`로 종결한다. 이 확인은 승인 갱신·취소 계속 진행·early publish보다 앞선다. 관측 누락/무결성 오류는 차단하며 새 native dispatch나 게시를 실행하지 않는다. 이미 terminal인 과거 run을 다시 쓰지는 않는다.
- 필요한 대상만 실행했다: 새 실패 저장과 legacy resume/advance/early-publish 세 경로, `4 passed`. 실제 store/artifact 저장을 사용하는 host 상태 회귀이며 capture/verification double은 실제 native 실패 증거가 아니다. 전체 suite/build/CI는 실행하지 않았다.

### 이전 관찰: 실제 파일 닫기

아래 crash의 root cause를 확인할 native stack은 확보하지 못했다. 설치 SDK `samples/change_visibility_data_type.py`는 `DataSourceManager.load_scene` 뒤 `close_scene`을 사용하고, `samples/casc_import_export.py`는 `ProjectLoader.load_from` 뒤 `SceneManager.remove_application_scene`을 사용한다. 둘 중 하나의 API 자체가 금지됐다고 단정할 근거는 없다. 직전 복원 helper가 한 callback에서 새 파일 load/save 후 서로 다른 세 소유 탭을 연속 제거한 사실만 확인했다.

PID `7452`의 새 epoch `e23c2520-9a66-4dd6-bba9-7c35b7bf1da1`에서, 기존의 14,001-byte 단일 객체 소유 fixture를 새로운 `working.casc`로 복사해 제품 `load_project_copy`로 로드하고 `_save_observed`로 저장했다. 별도 callback에서 원 빈 탭을 활성화한 뒤, 다시 원 탭의 idle callback에서 SDK `DataSourceManager.close_scene`으로 새 탭 하나만 닫았다. 그 다음 callback에서 원 탭·projection·inventory 보존을 확인했고, 이후 main window와 PID도 응답했다. bridge fingerprint는 `dfbd3b9afbd68e7d80606d5a57b9d88505d8fbc4e38de80ebb32c1e15d862e99`였다.

ignored 근거는 `artifacts/native-r4/isolated-runtime/snapshots/project-close-observation-577d94ee-2c41-4de9-872f-3eb656d24ffe/{load-observation,close-started,close-returned,next-callback}.json`과 `artifacts/native-r4/project-close-*-response.json`이다. 이 관찰은 단일 파일의 로드·저장·닫기 경로만 다루며, 앞선 연속 복원/정리 crash의 원인이나 해결·장시간 안정성 증거가 아니다. 이 관찰 시점에는 제품 native 코드를 변경하거나 production operation을 등록하지 않았다. 당시 원 빈 탭으로 복귀했고 사용자의 autosave·전역 인증키·기존 unknown은 변경하지 않았다. 이후 같은 프로세스의 복원 관찰과 종료 crash는 위에 따로 기록했다.

### 이전 추가: 늦은 실패 복구 연결과 native crash 정정

소스 추적에서 타임아웃 후 늦은 `failed_after_dispatch/recovery_eligible` receipt를 받은 경우 자동 조건부 복구가 빠지는 결함을 확인했다. `commit_change`의 consumed-token 재호출은 기존 request 조회만 했고, recipe resume도 원 실패만 terminal로 기록했다.

- `reconcile_consumed_change`는 인증된 `.used` 승인, 원 immutable outbox의 feature/operation/source/scene/token, 정확한 request ID와 execution context를 대조한다. 원 native operation은 dispatch하지 않고 원 request만 조회한다. terminal eligible 실패일 때만 기존 source/snapshot 검사·일회용 claim·서명 permit 경로로 연결한다.
- 이미 claim한 복구는 기존 recovery request ID만 조회한다. recipe는 원 실패 receipt와 별도 host recovery 결과 artifact를 보존한다. 복구 unknown/owner unresolved이면 blocked로 남아 resume가 같은 복구를 관측하고, recovered가 되어도 원 run/step의 `failed_after_dispatch`를 성공으로 바꾸지 않는다. `request_reconcile`, `recipe_status`는 계속 읽기 전용이다.
- 필요한 호스트 회귀 세 유형만 실행했다: 실제 `ChangeManager.consume`/`AtomicQueue.submit` outbox 대조, unknown 복구의 동일 ID 조회/재dispatch 방지, 늦은 실패의 recipe resume·원 실패 보존. 최초 `3 passed` 뒤, 일반 custom context에 내부 `request_id`가 없어도 기존 계약대로 허용하도록 불필요한 제한을 제거했다. 영향받은 outbox 대조만 recipe/custom 두 context로 다시 확인해 `2 passed`였다. 전체 recovery/recipe suite 결과가 아니며, 이 fixture들은 host routing 확인용으로 실제 native partial-failure attestation/permit 증거가 아니다. host 구현 digest 변경 후 과거 plan/grant를 새 실행에 사용하지 않는다.

**실앱 관측 정정:** 아래 복원 helper는 `04:34:47.897`에 성공 메시지를 쓰고 `04:34:48`에 HTTP 응답을 반환했지만, `2026-11-16 04:34:49 KST` Windows Application Error 1000은 **PID `12340` (`0x3034`), `Qt6Core.dll` 6.5.3.0, 예외 `0xc0000005`, offset `0x00000000000ae88c`**의 crash를 기록했다. 따라서 반환된 exact projection/파일 근거만 보존하며 안정된 restore 성공이나 현재 활성 runtime의 증거로 쓰지 않는다. 이 epoch는 종료됐고 새 프로세스에서 옛 private proof를 재사용할 수 없다.

또한 앞서 정상 종료로 판단했던 PID `34864` (`0x8830`)도 Alt+F4 이후 `04:21:22 KST` 같은 모듈/예외, offset `0x00000000000b4c7f`의 crash 이벤트가 있었다. **종료 UI 동작과 프로세스 소멸만으로 정상 종료를 단정했던 표기를 정정한다.** 종료 전에 두 소유 작업 탭을 새 `.casc`로 보존한 사실은 유지한다.

이벤트는 ignored `artifacts/native-r4/maintenance-restore-crash-events.json`, 복원 직전·반환 시각의 제품 로그 발췌는 `independent-restore-crash-log-tail.txt`에 보존했다. 확인된 실행은 scene-idle script callback 안의 파일 bootstrap·새 탭 복원·소유 탭 정리지만, 어느 native 호출/지연 callback이 원인인지 특정하지 못했다. WER 상세 archive 폴더는 OS 접근 거부였으며 이를 우회하지 않았다. native 탭 수명/Qt crash는 미해결이다. 이 crash를 인증된 부분 쓰기 실패나 복구 eligibility로 변환하지 않는다.

crash 뒤 설치된 앱을 `04:44:21 KST`에 다시 실행했다(PID `7452`). 새 빈 `untitled` 장면과 응답하는 main window를 확인했다. 이 프로세스에는 SDK script server나 위 qualification을 실행하지 않았으므로 현재 MCP qualification·안정성 근거는 없다. 표시된 사용자 autosave는 열거나 삭제하지 않았다.

### 이전 추가: 독립 checkpoint의 실제 복원 primitive

아래 새 PID `12340`/epoch `9d124044-b683-4d39-b56d-936e1af2cf10`에서, 실제 독립 Transform `.casc` 입력을 새 소유 working tab으로 bootstrap하고 checkpoint를 만든 뒤 제품 `qualify_checkpoint_restore_adapter.run`을 실행했다. checkpoint를 또 다른 새 `.working.casc`/탭으로 로드·저장하고, 원 checkpoint의 완전한 authored projection과 정확히 같은지, 새 instance/같은 lineage인지, 원 탭과 projection이 유지되는지 직접 관찰했다. 성공한 qualification 탭과 소유 복제본만 닫고 원 빈 탭을 복원했다.

`safety.rollback` primitive가 해당 프로세스에 등록됐다. 근거는 ignored `artifacts/native-r4/isolated-runtime/snapshots/independent-restore-qualification-5cfc9ec2-c83e-4ae1-9f92-a4162721cb51/restore-qualification-736a4069-55fd-4d95-99a2-d888c69015a6.json`, SHA-256 `ee4393c894e34b7716a76610649c7c84c3d6d25eaf40fb3ea24cce67048c1137`이다. helper 응답은 `artifacts/native-r4/independent-restore-qualification-response.json`에 보존했다.

이는 실패가 없는 명시적 code-owned qualification이다. 실제 부분 실패 receipt·failure attestation·일회용 recovery permit을 발급하거나 이전 unknown을 처리한 증거가 아니다. 현재 독립 position writer의 정상 legal 입력에서 안전하게 의도할 수 있는 진짜 bounded partial-failure 경로는 확인되지 않았다. 의도적 예외나 fake callback/receipt를 native 실패 증거로 대체하지 않는다. 일반 character의 exact restore는 여전히 별도 미확인이다.

### 이전 추가: 설치 maintenance lease와 실제 앱 재시작

원격을 다시 fetch했으며 r4 개선안 최신 SHA는 `6a9338cfb5edeff7b6d6cb1c9a619cffd80c57e4`다. 기존 16개 목표를 유지한다. 이번 변경은 R4-16의 설치·재실행 경합을 줄이며 전체 목표나 실제 installer 교체 완료를 뜻하지 않는다.

- host와 embedded bridge에 같은 dependency-free gate 모듈을 추가했다. runtime root의 **부모 폴더**에 `.<runtime-name>.maintenance.lock`을 두고 Windows `GENERIC_READ/FILE_SHARE_READ` handle을 프로세스 수명 동안 유지한다. host main과 state 생성, native pump 첫 heartbeat보다 앞서 획득하며 설치 중이면 `INSTALLATION_BUSY`로 중단한다. 파일 존재·PID·TTL로 잠금 소유권을 추정하지 않고 OS가 종료 시 해제한다.
- source installer는 최종 idle 확인 전에 같은 gate를 `ReadWrite/FileShare.None`으로 열고 old runtime 이동·상태 이관·activation·hooks·rollback·정리까지 유지한다. frozen installer는 부모 Setup 프로세스가 backup 전 `CreateFileW` 독점 handle을 획득하고 `DeinitializeSetup`에서 닫는다. 자식 hooks에 우회 권한이나 인증키 재생성 경로를 추가하지 않았다.
- 기존 `verify-install.ps1`은 source console entry에도 `--smoke`를 넘겼으나 source entry는 이를 처리하지 않고 서버를 실행했다. smoke client를 `src/cascadeur_complete/mcp_smoke.py`의 공통 구현으로 옮기고 source에도 dispatch를 연결했다. verification은 고유한 disposable state에서 MCP initialize/list/status를 호출하므로 설치 중 실제 state를 열지 않는다. 자식 종료를 기다린 뒤 소유한 임시 root와 gate만 정리하며 기존 환경변수를 복원한다.

실제 Windows 다중 프로세스 확인은 ignored `artifacts/native-r4/maintenance-lease-9a577ad0-7a1e-49f4-84bc-d16f1bcddc32/observation.json`에 있다. source checkout의 실제 console entry와 PowerShell 5.1의 제품 gate 함수를 사용했다.

| 직접 확인 | 결과와 범위 |
|---|---|
| runtime reader 두 개 | host/native guard reader가 공존하며 installer를 차단. 한 reader가 종료돼도 남은 reader가 차단 |
| installer 독점 유지 | 두 번째 installer와 새 host entry/native guard가 거부됨. runtime 폴더를 이동한 뒤에도 거부하며 거부된 host가 새 state를 만들지 않음 |
| 비정상 종료·stale 파일 | 해당 재현용 child를 종료하면 OS가 handle을 해제. 남은 gate 파일을 삭제하지 않고 reader와 installer가 다시 획득. 기존 sentinel bytes 보존 |
| source smoke | 실제 root 독점 lease 중 별도 state의 `--smoke --server`에서 initialize/list/status 성공, 도구 108개. 실제 설치·Codex 등록·버전 검사 전체를 통과한 증거는 아님 |

native bytes 변경 때문에 이전 Cascadeur를 hot reload하지 않았다. 기존 탭은 빈 탭 또는 소유한 단일 객체 복제본인지 SDK로 확인하고, 복제본 두 개를 `restart-preservation-d69c58b3-4a66-4288-a20b-f6c37bb6a672/owned-tab-1.casc`, `owned-tab-2.casc`에 각각 13,989 bytes로 저장했다(각 SHA-256 `19dd95910c03b671d006268fb2fea54f45983b00766c9aed565826e14791951f`). 종료 UI 동작 뒤 이전 프로세스가 사라진 것을 확인하고 설치된 **Cascadeur `2026.2.3.0.16863`, PID `12340`, embedded Python `3.11.0`**을 새로 실행했다. 이전 종료를 정상 종료라고 표현했던 내용은 위 crash 이벤트에 따라 정정한다.

새 프로세스는 checkout의 `cascadeur_side/cascadeur_complete/installation_guard.py`를 로드했으며 isolated runtime을 사용한다. epoch `9d124044-b683-4d39-b56d-936e1af2cf10`, loaded bridge fingerprint `dfbd3b9afbd68e7d80606d5a57b9d88505d8fbc4e38de80ebb32c1e15d862e99`를 현재 disk bytes와 대조했다. pump `last_error=null`, 실제 native reader가 같은 root의 installer 독점 open을 차단했다. 관측은 `artifacts/native-r4/maintenance-actual-process-observation.json`이다. 전역 MCP 설치를 교체하거나 재등록한 결과는 아니다.

같은 새 epoch에서 독립 scene bootstrap/evaluation/checkpoint와 position model·기존 key writer를 재자격 확인했다. 새 disposable fixture의 실제 animated FBX export 두 번도 성공해 `io.export_fbx`를 등록했다. export 근거는 `export-qualification-d9ab8e74-3038-4b4b-a29f-d2fb3cf09862/qualification.json`, SHA-256 `f616135d1ec85e4eca06d798f08df929f934a6d7eedde16e73c3420324ca4e2f`다. 이 qualification의 quality는 `not_evaluated`, consumer roundtrip은 `unverified`이며 이전 epoch의 실제 Blender 왕복·게시 성공과 구분한다. 이전 run/승인/receipt를 새 구현으로 재서명하거나 native effect를 replay하지 않았다.

**남은 문제:** source/frozen installer 전체 교체와 Inno compile/release build는 실행하지 않았다. gate 미지원 구버전의 검사 뒤 재실행은 새 gate가 강제 차단하지 못하므로 기존 idle scan도 유지한다. lease는 같은 runtime state root 사이의 보호이며 별도 root로 실행한 외부 client까지 전체 설치 교체로 검증한 것은 아니다. `verify-install.ps1`의 고정 버전 검사는 여전히 `2026.1.3.0.15619`를 요구한다. 실제 `2026.2`의 제한된 operation 관측을 전체 제품 지원으로 승격하지 않는다. 일반 rig/물리 메타데이터, 실제 부분 실패 뒤 인증된 conditional recovery, 기존 unknown의 authoritative reconciliation은 계속 미완료다. 전체 suite/CI도 실행하지 않았다.

### 이전 추가: 설치 상태 이관과 보관 자료 삭제 범위

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
- 이후 실제 source 설치 시도는 실행 중 PID `2328` 때문에 첫 idle 검사에서 거절됐고, 기존 persistent 파일 59개와 인증된 unknown은 보존됐다. 실패 준비의 staging/환경 복원을 연결하고 verifier에 정확한 host/bridge 디스크 map 및 Python import 경로 진단을 추가했다. 실제 교체 후 연속성·새 loaded fingerprint는 아직 관측하지 않았다.

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
