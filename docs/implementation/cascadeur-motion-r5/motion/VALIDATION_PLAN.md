# Motion 검증 명세 — 실행하지 않음

이 준비 작업에서는 pytest, 코드 import, native SDK 실행, qualification, 설치, 전체 suite를 실행하지 않았다. 부모 작업이 준비물의 Python 3.11 AST와 적용 가능한 patch의 형식만 한 번 확인할 예정이며, 그 결과는 부모 보고에 따른다.

## L1: 준비물 구문 확인

준비물 root에서 아래 범위만 확인한다. 제품 repository 전체 compile/build가 아니다. import, 실제 실행, 타입체크를 대체하지 않는다.

~~~bash
python - <<'PY'
import ast
from pathlib import Path
root = Path("motion")
paths = sorted([*root.glob("*.py"), *root.glob("*.pyi")])
for path in paths:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 11))
print(f"Python 3.11 AST: {len(paths)} files")
PY
~~~

부모 작업이 전체 준비물 AST를 한 번 확인하면 이 명령을 중복 실행하지 않는다.

## L2: 실제 구현 후 필요한 직접 사례

아래 테스트 파일과 함수명은 **구현 단계의 제안 명세**다. 현재 준비물에는 테스트 파일을 만들지 않았고 명령도 실행하지 않았다. 기존 프로젝트 테스트 프레임워크를 사용하며 새 framework/fixture 체계를 만들지 않는다.

| 파일/선택 사례 | 확인할 구체적 위험 |
|---|---|
| tests/test_serialization_equivalence.py::test_authored_and_unclassified_remain_exact | authored 또는 미분류 float가 1 ULP 변해도 거절. raw exact input은 통과 |
| 같은 파일 ::test_derived_binding_and_fixed_limits | 고정 policy의 정확한 derived owner/property/type만 수용. 한도 초과, binding/shape 변경 거절 |
| 같은 파일 ::test_reference_anchor_prevents_drift | P0≈P1 및 P1≈P2여도 P0와 직접 비교해 누적 오차 거절. source hash를 rounding하지 않음 |
| tests/test_native_checkpoint_restore.py::test_actual_successor_digest | restore가 성공하면 실제 target raw digest를 source/receipt에 기록. 원 anchor hash를 복사하면 거절 |
| tests/test_native_geometry_capture.py::test_two_stage_receipt_seal | observe result 불변, terminal 뒤 봉인, final manifest receipt 연결. private pending 부재/다른 request/unknown origin으로 봉인 불가 |
| 같은 파일 ::test_source_closure_and_window_bytes | source/evaluation/scene/skin/transform drift 및 실제 사용하는 window array hash 불일치 거절 |
| tests/test_unbaking_bounds.py::test_unqualified_prepare_has_no_token_or_budget | private qualified step 없으면 prepare/token/예약 전 차단. 요청 stage를 생략/대체하지 않음 |

필요한 사례만 선택하는 명령 예시:

~~~bash
python -m pytest tests/test_serialization_equivalence.py -k 'authored_and_unclassified or derived_binding_and_fixed_limits or reference_anchor_prevents_drift' -q
python -m pytest tests/test_native_checkpoint_restore.py -k actual_successor_digest -q
python -m pytest tests/test_native_geometry_capture.py -k 'two_stage_receipt_seal or source_closure_and_window_bytes' -q
python -m pytest tests/test_unbaking_bounds.py -k unqualified_prepare_has_no_token_or_budget -q
~~~

이들은 구현 논리의 직접 사례이고 실제 SDK 근거를 만들지 않는다. 이미 통과한 명령을 확인차 재실행하지 않는다. 실패하면 수정한 실패 사례만 재실행한다.

## Native 관측: 별도 승인된 작업

- mesh: fixture/허용 writer/reader/evaluation이 준비된 경우에만 2 evaluation + 5 calc + 1 guarded edit 본체 상한. fixture 생성/로드/설치 비용은 포함하지 않는다.
- 순서가 다른 [0,2,1,0] calc는 qualification 전용. production frames는 증가 순서 유지.
- restore: 정확한 typed field 분류 및 사전 고정 tolerance가 준비된 뒤 fixed P0 대비 한 번의 저장/복원 경계 관측. 원 탭 exact 불변.
- unbaking: 실제 installed action binding과 completion path가 없으면 native probe를 dispatch하지 않는다.
- 원 unknown/barrier, epoch/loaded fingerprint, 승인 조건이 먼저 충족되어야 한다.

실행하지 않은 항목: 테스트 전부, import/타입체크, native probe, schema 적용, 실제 복원, 실제 mesh quality, unbaking, L3/L4, 전체 build/E2E/CI.

