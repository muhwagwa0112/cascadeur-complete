# R7 준비물 확인 기록

기준 제품 commit은 `99b85163c4125a621ef7e2deeabe22270032c60b`다.
확인은 이번에 추가·변경하는 Python source, JSON과 통합 diff 문맥에 한정한다.
제품 코드나 SDK를 import/실행하지 않는다.

## 구체적 확인 범위

- 호스트 Python 구문 대상 3.12, native package 구문 대상 3.11.
- `ast.parse(..., feature_version=...)` 및 `compile(tree, path, "exec", dont_inherit=True)`.
- 준비 JSON의 `json.loads`, 작업 ID·의존 관계·문서 상대 경로 확인.
- 기준 target bytes와 원격 Git tree의 blob, 최종 source와 patch metadata의 해시 일치.
- pinned source 사본에서 `git apply --check`로 통합 patch 문맥 확인.

## 실제 결과 — 2026-11-17

| 항목 | 실제 명령·방법 | 결과 |
|---|---|---|
| Python | `python3 check_r7_static.py`의 `ast.parse` + `compile` | **12개 파일 통과**. host 9개는 3.12, native 3개는 3.11 구문 대상으로 확인. 실행 환경 Python **3.12.14**. 코드 실행/import 없음. |
| JSON·산출물 연결 | 같은 정적 확인의 `json.loads` 및 ID/경로 대조 | **JSON 7개, 작업 4개, 문서 상대 링크 9개 통과**. |
| 기준 source | 원격 기준 Git tree의 blob과 캐시 bytes 대조 | 기존 target **9개 일치**, 신규 target **3개는 기준 tree에 없음**. |
| 최종 source | component metadata의 proposed SHA256/Git blob과 최종 bytes 대조 | **12개 target 일치**, component 간 중복 target 없음. |
| 통합 patch 문맥 | `git apply --check /workspace/scratch/fc42dd265c37/cascadeur-r7-code-ready/product-integration.patch` | 기준 source 사본에서 **exit 0**, 출력 없음. |

통합 diff는 **70,987 bytes**, SHA256은 다음과 같다.

```text
08fb89a805f0bc0ab5b0d6d6accf2884e0f043a3efa32e787ac9e4651bbcdb52
```

검사는 위 범위에서 한 번 실행했다. 전체 repository에 적용하거나 동작을 실행한 결과가 아니다.
원격 branch/commit과 업로드 blob 일치는 푸시 완료 후 별도로 확인한다.

## 코드 연결 검토

unbaking의 실제 adapter dispatch, FK 후보와 기존 retarget caller, 최종 consumer quality와
recipe의 export source, recovery의 원 승인·최초 dispatch 경계를 각 변경 범위에서 검토했다.
recovery의 새 effectful 함수는 기존 token 소비와 exclusive journal 생성까지 별도로 확인했다.
이는 실앱 실행이나 native 완료 증거를 대신하지 않는다.

## 미실행·제약

제품 patch 적용, dependency 설치, 제품 import, unit test, 전체 테스트·빌드·E2E·benchmark·CI는
실행하지 않는다(**L4 미실행**). Cascadeur/Windows/native qualification, 새 unbaking leaf,
character writer/exporter, 실제 소비자 import·최종 납품 및 실패 후 native 복구도 실행하지 않는다.

새 native capability는 등록하지 않았다. 이번 packet이 실제 SDK 구현의 누락이나 현재
unknown을 해결했다고 보고하지 않는다. 기존 실앱 성공 기록은 해당 commit의 기록으로 참조하며
로컬 ignored 원 receipt/NPZ/`.casc`를 이 환경에서 재검증하지 않았다.
