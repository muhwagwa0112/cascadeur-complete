# 리팩토링 준비: 현황 검토와 계획

검토일 2026-10-16 · 기준 커밋 `82b350c` (origin/main 과 동일, 원격 feat 브랜치 3개는 모두 병합됨)
대상 빌드 Cascadeur `2026.1.3.0.15619` (Pro)

## 1. "Cascadeur 의 모든 기능을 쓸 수 있는가" — 아니오

제품 카탈로그(`inventory/product_features_2026_1_3.json`)는 231개 기능을 정의한다.
Pro 라이선스에서 Cascadeur 가 실행 중일 때의 실제 상태:

| 상태 | 수 | 내용 |
|---|---|---|
| supported (live 증거) | ~186 | 184개 live 증거 유효 + 호스트 전용 2개 |
| unhealthy (어댑터 있음, 증거 없음) | 22 | 9/30 문서의 15개 + 이후 추가된 7개 (`auto_posing_state`, `close_working_tabs`, `dialog_probe`, `interpolation_range`, `interpolation_refresh`, `position_keys`, `rotation_keys`) |
| not_implemented | 9 | Filament 렌더 설정 전부 (AO, bloom, dynamic lights, environment ×5, shadows) |
| missing_dependency | 8 | Daz/Unity/Unreal/Roblox/LiveLink + developer 전용 3개 |
| ui_only | 3 | `mocap`, `scene_linking`, `settings_set` |
| unsupported | 2 | `settings_get`, `tool_inspect` |
| unsupported_version | 1 | `export_vrm` — 실제 버전 문제가 아니라 `feature_registry.py:652` 에 하드코딩 |

카탈로그 밖의 영역: 런타임 ToolsManager 에 등록된 GUI 도구 58개가 discovered/ui_only 로만 잡혀 있다
(AttractorTool, ManipulatorsTool, OutlinerTool, TopologyController, Hotkeys, Textures 등).
이 중 일부는 카탈로그 기능의 내부 구현이지만, 카탈로그가 "Cascadeur 전체"를 대표한다는 근거는 없다.

### 실사용에서 막히는 지점 (검증됨)

1. **직접 변경 도구가 항상 실패한다.** `service.execute` 는 mutation 연산을 무조건
   `CONFIRMATION_REQUIRED` 로 거부한다(`service.py:893`). 따라서 아래 MCP 도구는 문서상 기능과 달리
   항상 실패한다: `timeline_set_frame`, `undo`, `redo`, `auto_posing`, `auto_physics_enable`,
   `auto_physics_snap`, `render_output`, `io_transfer`. `object_write`/`scene_file`/`layer_write`/
   `key_edit`/`transform_edit`/`selection_edit`/`animation_curve`/`viewport_camera` 의 쓰기 액션도 동일.
   `confirmation_token` 인자는 받지만 쓰이지 않는다.
2. **`viewport_mode` 읽기가 브리지에서 거부된다(정적 분석).** 호스트는 `system.view_mode_get` 을 읽기로 보고
   토큰 없이 보내지만(`server.py:131`, `service.py:2046`), 브리지 `READ_ONLY_OPERATIONS`
   (`cascadeur_side/.../runtime.py:24`)에 없어 mutating 으로 판정된다(`runtime.py:180-188`).
3. **Cascadeur 가 꺼져 있으면 지원 수가 4개로 무너진다.** 라이선스 기본값이 `"Basic"`(`service.py:398`)이라
   Pro 로 기록된 증거가 전부 걸러진다. 마지막으로 관측한 라이선스를 캐시하거나 "unknown" 상태를 둬야 한다.
4. **설치본 드리프트.** 지금 등록된 MCP 서버는 `%LOCALAPPDATA%\CascadeurMCP\cascadeur-complete`(9/30 설치)이며
   저장소와 5개 파일이 다르다(adapter_bindings, cleanup_workflow, motion_cleanup, server, uia).
5. **`docs/SUPPORT_STATUS.md` 가 낡았다** (224개 기준, 새 7개 누락).

## 2. 기준선

- `uv run --frozen --all-extras pytest -q` → **160 passed, 199 skipped** (스킵은 전부 `tests/live`, `CASCADEUR_LIVE=1` 필요)
- `ruff check .` → 1건 E501 (`cascadeur_side/cascadeur_complete/handlers/mesh.py:64`)
- 핸들러 본문, `server.py` 도구 로직, 브리지 `execute_request`/`_drain_once`/`scene_state` 는 오프라인 테스트가 없다.
  행위 검증은 live 시나리오(`src/cascadeur_complete/live_scenarios*.py`)뿐이다.

### live 증거와 리팩토링의 관계 (중요)

증거 바인딩(`product_catalog.py:75` `binding_material`)은 **코드가 아니라 카탈로그 메타데이터**에 묶인다:
route, action, operation, pre/postconditions, fixed_arguments, `contract_test_ids`, live_test_id, fixture_id.

- 코드만 옮기면 증거는 유효하게 남는다 → **증거가 회귀를 잡아주지 않는다**. 리팩토링 후 live 재검증 필수.
- 반대로 operation 이름, postcondition id, **테스트 파일/함수 이름**(contract_test_ids 에 들어감)을 바꾸면
  해당 기능의 증거가 즉시 무효화된다. 테스트 이름 변경은 카탈로그 갱신 + live 재실행과 한 묶음으로 처리한다.

## 3. 고정해야 할 계약 (리팩토링 중 불변)

- MCP 도구 이름·인자 스키마(82 tools, 6 resources, 2 templates). 골든 파일로 고정.
- 브리지 프로토콜 `"2.0"`, canonical-JSON HMAC, nonce 규칙, UUID request id, 확인 토큰 서명 필드
  (`runtime.py:151-215`, `queue_auth.py`, `safety.py`).
- 큐 경로 `state/requests|responses|seen|tokens`, `drain_active.json`, `pump.json`(schema 1), `*.working.casc`.
- operation 이름 182개와 postcondition id (카탈로그·`adapter_bindings.py`·핸들러 데코레이터).
- 호스트 `VIEW_OPERATIONS` ⊆ 브리지 `YIELDING_OPERATIONS`.
- 브리지 쪽 제약: 임베디드 Python 3.11(3.12 문법 금지), `handlers/*.py` 만 hot-reload 됨
  (`__all__` 알파벳 순). 공용 헬퍼를 새로 만들면 `handlers/` 안에, 사용하는 모듈보다 먼저 reload 되게 둔다.
  `runtime.py`/`pump.py` 변경은 Cascadeur 재시작이 필요하다.

## 4. 리팩토링 후보 (근거 위치)

### 호스트 (`src/cascadeur_complete`)

| 영역 | 문제 | 위치 |
|---|---|---|
| 단일 진실원 | 같은 사실이 최대 6곳에 선언: 카탈로그 JSON, `CORE_FEATURES` 파이프 DSL, `ADAPTER_SPECS`, `BINDINGS`, server 리터럴, fallback read-only 집합. `CoreSpec.destructive` 34개와 `ADAPTER_SPECS` postcondition 12개가 JSON 과 다르지만 JSON 이 우선이라 죽은 값 | `feature_registry.py:62-622`, `adapter_bindings.py`, `service.py:2038-2071` |
| god class | `CascadeurService` 1700줄: `_execute_ui_file_flow` 196, `prepare_change` 179, `commit_change` 146(연산별 postcondition if-체인 1260-1323), `execute` 122 | `service.py` |
| 복붙 | `execute`/`prepare_change` 의 기능 상태 게이트 ~35줄 동일(852-887 / 1047-1082). 실패 envelope 조립 4회. 정책 JSON 3회 파싱 | `service.py` |
| server 보일러플레이트 | 수동 에러 dict 35개, `.model_dump(mode="json")` 44회, 액션→operation 인라인 맵 7개. `motion_cleanup_prepare` 는 8-kind if 체인 + 조용한 fall-through(1648) | `server.py` |
| UIA | `complete_file_dialog` ~208줄, `invoke_process_pending` ~176줄. 큐 JSON 을 직접 읽음(421-432), 경로 하드코딩 3회 | `uia.py` |
| 수학/IO | `solve_contacts` 144줄, `solve_arm_offsets` ~147줄. `cleanup_workflow` 가 `client.execute` 를 직접 호출해 빌드 핀·기능 게이트를 우회(53). 프레임 범위 필터 패턴 6회 | `motion_cleanup.py`, `cleanup_workflow.py` |
| 죽은 코드 | `_all_queued_requests_are_scene_bound`(uia.py:401), 도달 불가 분기(service.py:1012, 920-935), `refresh_inventory` 이중 rebuild(489-495). 테스트에서만 쓰는 `recover_stale_claims`(위험), `csc_mutate_allowed` | |
| 성능 | `PRODUCT_CATALOG.by_id` 가 접근마다 dict 재생성(product_catalog.py:110), `feature()` 선형 탐색, 성공 실행마다 레지스트리 전체 재기록(service.py:941) | |

### 브리지 (`cascadeur_side/cascadeur_complete`)

| 영역 | 문제 | 위치 |
|---|---|---|
| 인라인 디스패치 | `_run_operation` 안에 ~30개 연산이 ~370줄 if/elif 로 남아 있음 → `handlers/` 로 이전 | `runtime.py:962-1357` |
| `scene_state` | 요청당 2회 이상, 매번 fingerprint 4종 + `tar` 서브프로세스. `suppress(Exception)` 로 실패 시 fingerprint 가 None 이 되어 revision 해시가 약해짐 | `runtime.py:612, 662-805` |
| 중복 헬퍼 | `call_action` 래퍼 8곳, `get_tool(X).editor(view)` 15회, "Unknown object/layer IDs" 검증 ~15곳, `_select*` 6곳, `_behaviour_ids` 3곳, `_fingerprint` 2곳 | handlers 전반 |
| 결합 | `generation.py:155` 이 `timeline_edit` 의 private 함수 import, `animation.py` ↔ `runtime.py` 지연 순환 import | |
| 연산 이름 추론 | 핸들러 6곳이 `request["operations"][0]` 에서 자기 이름을 추론 → `dispatch` 가 이름을 넘겨야 함 | animation:130, behaviours:164/234, objects:178, render:21, view:62 |
| 전역 상태 | `scene.py:8 _TAB_IDENTITIES` 무한 성장, hot-reload 시 탭 id 변동 | |

## 5. 리팩토링 전에 고칠 버그 (동작 변경, 별도 커밋)

1. ~~직접 변경 도구 18개가 항상 실패~~ — **Phase 1 에서 `*_prepare` 로 전환 완료.** 규칙: 도구 X 의 쓰기는
   `X_prepare` 가 담당하고(토큰 반환 → `change_commit`), X 에는 읽기만 남는다. 쓰기만 있던 11개
   (object_write, io_transfer, timeline_set_frame, layer_write, render_output, auto_posing, auto_physics_enable,
   auto_physics_snap, action_invoke, undo, redo)는 `_prepare` 버전으로 대체됐다. 도구 75 → 82.
   `io_transfer_prepare` 는 브리지가 직접 처리하는 형식(FBX/DAE/오디오/이미지 export/selection groups)만 받고,
   `render_output_prepare` 는 video 를 받지 않는다 — 둘 다 예전에는 받아도 commit 에서 실패하던 경로였다.
   `tests/test_direct_mutation_tools.py` 가 execute 로 가는 mutation 이 0개임과, 각 `_prepare` 도구의
   feature/operation 쌍이 서비스 바인딩 규칙과 브리지 처리기를 통과함을 검증한다.
2. ~~`system.view_mode_get` 을 브리지 `READ_ONLY_OPERATIONS` 에 추가~~ — 완료. 공용 핸들러가 `mode` 를 받으면 실제로 바꾸므로,
   `mode` 가 있는 `view_mode_get` 은 여전히 토큰을 요구한다(`runtime._operation_is_mutating`).
3. ~~`_save_snapshot` 에 `working_id` 누락~~ — 완료(요청마다 새 UUID). 호스트는 여전히 이 경로를 쓰지 않는다.
4. ~~`_drain_once` 가 깨진 요청에서 중단~~ — 완료. 읽을 수 없거나 객체가 아닌 요청은 claim 을 지우고 다음 요청으로 진행한다.
5. ~~`atomic_write_json` 임시 파일 경쟁~~ — 완료. 쓰기마다 고유한 임시 파일, 실패 시 정리(8 스레드 동시 쓰기 테스트로 재현·검증).
6. ~~런타임 루트 규칙 3종 불일치~~ — 완료. uia 는 `RuntimePaths` 를 쓰고, 브리지 `runtime_root` 는 같은 규칙
   (`CASCADEUR_MCP_ROOT` → 실제 USERPROFILE Local AppData → LOCALAPPDATA)을 따른다. 쓰이지 않던 uia 헬퍼 1개 삭제.
   `CASCADEUR_MCP_ROOT` 를 쓰려면 Cascadeur 프로세스에도 같은 값이 보여야 한다.
7. ~~미실행 시 라이선스 `"Basic"` 가정~~ — 완료. 마지막으로 관측한 라이선스를 `state/license.json` 에 빌드별로 저장하고,
   `cascadeur_status` 의 `license.source` 가 `live`/`cached`/`default` 를 알려 준다. 상태 확인마다 실제 값으로 갱신된다.
8. ~~`export_vrm` 하드코딩~~ — 완료. 카탈로그대로 `unsupported` 로 보고된다.
9. ~~`status.result` 타입 검사 / `cancel` 서명 미검증~~ — 완료. prepare·commit·rollback 이 공용 `_checked_status` 로
   상태 dict 를 확인하고, `cancel` 은 서명이 맞는 토큰(만료 포함)만 지우며 잘못된 토큰에 예외 대신 `false` 를 돌려준다.
10. ~~ruff E501 1건~~ — Phase 0 에서 수정.

## 6. 단계별 계획

**Phase 0 — 안전망 (동작 변경 없음)** — 완료(설치본 갱신·live 검증 제외)

| 테스트 | 고정하는 것 |
|---|---|
| `tests/test_mcp_surface_golden.py` + `tests/golden/mcp_surface.json` | 도구 82 / 리소스 6 / 템플릿 2 의 이름·스키마·설명. 의도된 변경은 `CASCADEUR_UPDATE_GOLDEN=1` 로 갱신 |
| `tests/test_operation_contract.py` | 호스트가 보내는 operation ↔ 브리지 처리 목록, 양쪽 read-only 판정, VIEW ⊆ YIELDING. 예외는 `KNOWN_*` 집합에 명시 |
| `tests/test_direct_mutation_tools.py` | 모든 도구를 기록용 서비스로 호출: `execute` 로 가는 mutation 0개, `_prepare` 도구별 feature/operation 쌍 |
| `tests/test_bridge_request_flow.py` | fake csc 로 `execute_request`/`_drain_once`: scene guard, 토큰 게이트, 예외→에러코드, HMAC·nonce 재사용·TTL·프로토콜, 응답 서명, yield, scene 필터. §5-2/3/4 는 `xfail(strict=True)` |

`KNOWN_*` 항목이나 xfail 은 해당 버그를 고치는 커밋에서 같이 지운다(고치면 테스트가 일부러 실패한다).

남은 항목:
- MCP 도구/리소스 스키마 골든 테스트 (`server.py` 이름·인자·docstring).
- 계약 테스트: 호스트 mutating 판정 ≡ 브리지 `_operation_is_mutating`, 호스트가 보내는 모든 operation 이 브리지에 등록됨(의도된 예외 목록 명시).
- fake `csc` 로 브리지 `execute_request`/`_drain_once` 특성화 테스트 (인증 실패, TTL, 깨진 JSON, scene guard).
- 설치본을 저장소 HEAD 로 갱신하고 live 검증 1회 → 새 기준 `SUPPORT_STATUS.md`.

**Phase 1 — 버그 수정** (§5, 항목별 커밋, 1번은 사용자 결정 후)

**Phase 2 — 호스트 정리**
- 카탈로그 JSON 을 단일 진실원으로: `CORE_FEATURES`/`ADAPTER_SPECS` 에서 JSON 과 겹치는 필드 제거, fallback read-only 집합 제거.
- `CascadeurService` 분해: `FeatureGate`(상태 게이트 공용화), `ChangeFlow`(prepare/commit/rollback), `HostPostconditions`(연산별 테이블), `UiFileFlow`.
- `server.py` 에 공용 에러/결과 헬퍼, 액션 맵을 데이터로.
- `cleanup_workflow` 가 `service` 경유로 실행하도록.

**Phase 3 — 브리지 정리** (Cascadeur 재시작 + live 재검증 필요)
- `runtime.py` 인라인 연산을 `handlers/` 로 이전, `dispatch` 가 연산 이름 전달.
- `handlers/_common.py`(reload 순서 보장)에 `call_action`, tool editor, ID 검증, 선택 헬퍼 통합.
- `scene_state` 캐시/경량화, 예외 억제 범위 축소.

**Phase 4 — 커버리지 확장**: unhealthy 22개 live 증거 확보, Filament 렌더 설정 어댑터, ui_only 3개 재조사.

각 Phase 끝: `pytest` + `ruff` + (Phase 3 이후) `CASCADEUR_LIVE=1` live 검증, `scripts/support_report.py` 로 상태 문서 재생성.
