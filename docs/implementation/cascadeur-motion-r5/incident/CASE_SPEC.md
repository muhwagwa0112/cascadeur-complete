# 필요한 확인 사례 — 명세만, 실행하지 않음

이 목록은 이번 변경의 종료 조건을 늘리는 gate가 아니다. 제품 변경 승인을 받은 뒤 해당 변경을 직접 겨냥할 최소 L1/L2 사례다. 새 테스트 프레임워크·전체 suite·빌드·CI·벤치마크는 제안하지 않는다. 현재 참조 모듈은 제품/native adapter가 아니므로 참조 코드의 통과로 실앱 증거를 대신하지 않는다.

## L1

packet의 Python은 표준 라이브러리만 사용하는 Python 3.11 문법으로 작성했다. 상위 담당자가 수행하는 AST parse 결과는 `../VERIFICATION.md`에 기록한다. 제품 적용 후에는 **바꾼 파일만** compile/type/lint 중 프로젝트에서 이미 사용하는 가장 낮은 확인을 실행한다. 같은 입력으로 통과한 검사를 다시 실행하지 않는다.

## L2 직접 사례

| 사례 / 연결 함수 | 입력과 관찰해야 할 결과 |
|---|---|
| `test_original_unknown_is_observation_only` / `BridgeClient.execute`, `decide` | 두 원 요청 중 하나와 동일 signed digest는 원 terminal 조회만 한다. 같은 ID에 다른 digest는 conflict. 새 nonce/sidecar/dispatch가 생기지 않고 원 request/terminal bytes는 동일하다. |
| `test_domains_and_legacy_unknown_remain_distinct` / `verify_chain`, `project_domain`, `decide` | global entry를 isolated key/store로 검증하면 거절한다. journal이 없는 authenticated legacy unknown도 열린 incident로 남는다. isolated만 retire하고 global이 열린 채면 새 source/effect 후보가 나오지 않는다. |
| `test_journal_transition_integrity` / `verify_chain`, `project_domain` | 한 entry를 바꾸거나 누락·재정렬·중복 등록·잘못된 predecessor/head로 만들면 거절한다. 승인 없이 retire-start, pending 없이 retire-commit, 다른 original의 evidence도 거절한다. 원 terminal 뒤에는 새 runtime event를 쓰지 않는다. |
| `test_retirement_requires_actual_closure` / `project_domain`, `decide` | 승인된 plan만 있으면 pending/deny. producer/alias/footprint verifier가 `EvidenceUnavailable`이면 commit 불가. 모두 결합된 실제 closure가 있을 때만 retire projection이 생기며, late completion observation을 추가해도 retirement 제한이 유지된다. |
| `test_restart_requires_distinct_baseline_and_resources` / `decide` | retired epoch·원 run·old/alias output·불명확 baseline·다른 head에 묶인 separation은 거절한다. 새 workspace/baseline/원장 heads에 정확히 결합한 separation은 **후보**만 반환하고 기존 source/confirmation을 생략하지 않는다. |
| `test_diagnostic_never_creates_source_or_evaluation` / native diagnostic entry | unknown 동안 host inspection/기존 receipt 조회가 가능하다. native diagnostic은 code-owned bounded reader만 가능하며 `_ISSUED_SOURCES`, token, grant, interpolation/evaluation, file write에 도달하지 않는다. capture_source를 diagnostic 이름으로 바꾸면 거절한다. |
| `test_sidecar_order_and_stale_head` / `AtomicQueue.submit`, native admission | outbox→sidecar→queue 순서 중 실패한 지점을 직접 좁혀 확인한다. sidecar 미완성 시 queue를 publish하지 않는다. sidecar 발급 뒤 head/resource identity를 바꾸면 native가 confirmation 소비·첫 effect 전에 거절한다. 원 요청이 이미 claim된 경우 same-ID 재dispatch가 없다. |
| `test_direct_setup_cannot_bypass_admission` / `assert_setup_admission` | qualifier 메뉴의 sidecar 없는 호출은 RetainedProbe/create/save 이전에 멈춘다. 같은 setup ref 재호출은 조회뿐이다. 유효한 허가에서도 원 unknown workspace를 fixture input/output으로 재사용하지 않는다. |

순수 함수 사례에서 signed/typed synthetic fixture를 쓰면 그 결과는 **자료형·결합·분기만 확인한 것**이라고 명시한다. OS producer 종료, 파일 alias, SDK completion의 진실을 synthetic `True`로 대신하거나 native 자격 증거로 저장하지 않는다. 해당 verifier의 positive 경로는 실제 evidence가 없는 환경에서 미검증으로 남긴다.

## 범위 내 실앱 관측이 필요한 항목

이 항목은 현재 실행한 결과가 아니다. 적용·실행 승인 후 Windows 원 환경에서 다음 두 연결만 직접 확인하면 된다.

1. old/unknown source와 sidecar 누락·stale 상태가 첫 SDK/file effect 전에 거절되고, 승인된 독립 새 workspace의 제한된 한 작업만 정상 admission을 받는지.
2. 실제 process/consumer 종료·파일 identity와 저장된 original request 증거가 retirement closure를 만들 수 있는지. 어느 부분도 확보되지 않으면 그 사건은 closed로 남으며 다른 성공 사례를 복사하지 않는다.

기존 원 unknown 요청을 재실행하거나 실패를 유도하기 위해 같은 request를 다시 보내지 않는다. 전체 테스트·전체 빌드·E2E·CI는 실행하지 않는다.
