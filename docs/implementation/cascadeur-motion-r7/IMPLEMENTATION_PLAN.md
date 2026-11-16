# R7: 캐릭터 모션·최종 납품·복구의 남은 구현

작성: 2026-11-17, Asia/Seoul. 기준 제품 commit:
`99b85163c4125a621ef7e2deeabe22270032c60b`.

## 목적과 산출물 지위

최종 목표는 실제 캐릭터의 모션을 입력받아 원래 의도를 유지하면서 필요한 보정을 수행하고,
실제 평가 결과와 소비자 앱의 최종 파일을 확인해 납품하는 것이다. 그 과정의 미확정 실패를
중복 실행하거나 원본 상태를 훼손하지 않아야 한다.

이 packet은 **제품에 아직 적용하지 않은 구체적 구현안과 실제 적용 가능한 diff**다.
코드 후보로 작성한 부분, 설치된 Cascadeur 자료가 필요한 native 구현, 실앱에서만 확인할 수
있는 부분을 구분한다. 새 Python 의존성·버전 변경·CI·전체 테스트 체계는 추가하지 않는다.

기존 R6의 소유 pair setup, 12단계 continuation과 immutable-P0 roundtrip은 구현되어 있고
로컬 성공 기록도 있다. R7에서 그 성공을 다시 만들거나 준비 상태로 되돌리지 않는다.
이전 packet의 `native_installed_update_facts.py` 부재도 현재 제품에서 이미 해소됐다.

## 남은 네 영역과 코드 위치

| 영역 | 이번 packet의 변경 단위 | 이어서 필요한 실제 구현 |
|---|---|---|
| unbaking | `unbaking/product-integration.patch`, `unbaking/IMPLEMENTATION.md` | 세 action의 설치된 실제 callable, 인수 변환, 작업과 대응하는 완료 신호 |
| 캐릭터 모션 | `character/product-integration.patch`, `character/IMPLEMENTATION.md` | 관측된 RigInfo/부모/rest/controller에 기반한 native rotation writer, 이후 root·회전·접촉 결합 |
| 최종 납품 | `delivery/product-integration.patch`, `delivery/IMPLEMENTATION.md` | character/skin을 포함하는 실제 exporter와 소비자에서의 원본 의도·최종 mesh 동작 확인 |
| 실패 복구 | `recovery/product-integration.patch`, `recovery/IMPLEMENTATION.md` | 실제 partial-write 실패의 원 terminal에서 복구까지 연결한 native 관찰, 캐릭터 writer별 실패 완료 계약 |

`product-integration.patch`는 위 네 영역을 함께 적용할 때 사용할 통합 diff다. 개별 diff는
영역별 검토·선택 적용용이며, 통합 diff 적용 뒤 다시 적용하지 않는다. 기준 제품 source와
최종 source의 Git blob·SHA256은 `integration-source-metadata.json`에 고정한다.

## 1. Unbaking 실행 연결

현재 제품의 세 step은 `UNBAKING_STEP_UNQUALIFIED`로 끝난다. 필요한 변경은 오류 문구를
지우는 것이 아니라 `native_unbaking` 상태 조회와 **실제 runtime adapter dispatch**를
같은 설치 구현에 연결하는 것이다. guarded runtime은 등록 adapter의 `execute()`를 호출하므로
legacy handler에만 함수를 추가하면 실제 보호된 경로에 연결되지 않는다.

단계는 다음 세 개다.

1. `prepare_keys_by_fulcrums` / `View.AutoInterpolation_Keys`
2. `adjust_keys_and_interpolation` / `View.Animation unbaking`
3. `adjust_autoposing_lock_state` / `AutoPosingTool.AutoUnlock`

호스트의 명시 topology 권한·키 추가/삭제/모드 변경 예산과 기존 scene/source/attempt를 그대로
전달한다. 실행 전 관측한 layer/key/lock, 실제 실행한 설치 함수와 인수, 실행 뒤 전체
projection·key delta·lock 변화가 같은 원 요청에 결합되어야 한다. native 함수가 반환한
값이나 현재 화면만 보고 완료를 추정하지 않는다. 이후 evaluation/capture도 별도 실제 요청의
terminal에 연결한다.

설치 leaf 구현에는 실제 command 등록 source, callback의 인수/선택 상태, 동기 반환 또는
operation-specific 완료 event가 필요하다. 기존 수집기는 요청한 SDK 선언 29개를 이미
찾았으므로 전체 SDK 수집을 반복하는 것이 작업은 아니다. **미발견인 세 등록/실행 source와
완료 계약**만 추가로 확인해야 한다. 자료 없는 함수 이름과 성공 event는 코드에 만들지 않는다.

현재 runtime의 synchronous/no-yield 계약에 맞는 low-level API가 없다면 opaque UI action을
곧바로 지원 등록하지 않는다. 실제 비동기 job의 correlation·취소·terminal을 보존하는 별도
executor 변경이 필요하며, 그때는 public protocol 변경안으로 검토한다. polling 시간 초과를
성공으로 바꾸거나 단순한 action dispatch를 완료로 표현하지 않는다.

## 2. 캐릭터 모션과 실제 품질

기존 host에는 FK/IK·retarget·contact·sparse fitting 수학이 이미 있다. 현재 실제 controller
lowering과 native writer가 parentless position에 묶여 있는 지점을 확장한다. 새 solver를
별도로 복제하지 않는다.

첫 구현 단위는 **단일 RigInfo가 소유하고 부모 closure와 rest가 실제로 관측된 FK skeleton의
기존 키 local rotation**이다. host 후보는 quaternion·부모 변환·기존 local translation을
명시적으로 사용하고, 실제 native writer가 지원 등록되기 전에는 실행 가능하다고 반환하지
않는다. 모델 이름이나 현재 애니메이션 자세를 rest로 추정하지 않는다.

그다음 구현은 root position과 joint rotation을 같은 후보로 묶는 lowering이다. contact/IK
목표를 기존 solver에 전달하고 같은 프레임의 전체 후보를 한 write 계획으로 만들며, 둘 중
일부만 성공하면 나머지를 성공으로 표시하지 않는다. controller로 작성할 대상인지 bone
channel로 직접 작성할 대상인지 실제 소유권·제약 관측으로 구분한다.

품질 비교는 입력 원본과 의도에 고정한다. 보정 뒤 motion을 새 원본으로 바꿔 오차를 0으로
만들지 않는다. 원본의 key pose·비대상 채널·접촉 구간·손가락 회전·support motion과 필요한
mesh 항목은 기존 quality 계약에 연결한다. sampled 관측 결과가 연속 구간 충돌 없음이나
모든 rig 지원을 의미하지 않는다.

실제 완료 단위는 host 후보 생성만이 아니다. native writer의 실제 인수 → 현재 요청의
write 완료 → 별도 evaluation terminal → 실제 motion/geometry readback → 원본과 후보의
품질 판정까지 연결해야 한다. 캐릭터 상세 명세에 입력 채널·native leaf·실패 경계를 고정한다.

## 3. 최종 FBX와 소비자 왕복

기존 seal → consumer import/capture → 원본 intent/quality 비교 → publish는 재사용한다.
현재 native export는 독립 Transform 하나로 제한되며 skin/mesh/일반 character를 허용하는
구현이 아니다. 허용 ID 수만 늘리면 character export가 되는 것으로 취급하지 않는다.

character exporter는 실제 selection closure(root/bone/mesh/controller), animation 범위,
take, axes/units, skin/bind 입력과 설치 exporter의 실제 설정·완료를 함께 관측해야 한다.
그 뒤 immutable export bytes를 소비자에서 실제로 읽고 정확한 profile 및 import 설정으로
관측한 skeleton·mesh를 비교한다. 외부 파일·다른 take·다른 실행 결과를 결과로 붙이지 않는다.

이번 delivery 코드 후보는 bone motion이 맞아도 잘못 skin된 mesh가 통과할 수 있는 간극을
직접 겨냥한다. 최종 native geometry와 소비자 geometry의 명시 mapping, 같은 sample time과
canonical 단위/basis를 사용해 표면 위치 차이를 계산한다. vertex 순서 변경을 고려하고,
shape 오차를 숨기는 별도 정렬은 적용하지 않는다. full N×M 메모리를 만들지 않고 기존
geometry window와 계산 예산을 재사용한다. 세부 알고리즘과 실제 caller는 delivery 문서에 있다.

이 영역에서 제안하는 import profile/품질 입력 필드가 있으면 public schema 변경이다.
**이번 commit은 그 변경안을 문서와 미적용 patch로 보관한다.** 제품 반영 시 기존 사용자
profile의 호환성과 적용 범위를 검토해야 한다. mesh 없는 독립 객체 경로를 이유 없이 막거나
새 기준을 과거 성공 결과에 소급 적용하지 않는다.

## 4. 실패 복구와 중단 뒤 이어가기

기존 independent writer에는 실제 bounded failure observer가 있고 실제 새 탭 restore도 있다.
이 두 구현을 일반 캐릭터의 성공 증거로 확대하지 않는다. 새로운 writer도 자신의 실제
native transaction·완료 prefix·현재 projection에 결합한 failure observation이 필요하다.

이번 host diff는 signed `prepared.json`과 미사용 confirmation token을 보관한 뒤 최초
dispatch 전에 종료된 구간을 이어간다. 같은 원 실패·permit·source·token·request ID를
검증하고 최초 dispatch 한 번만 수행한다. 이미 dispatch intent가 있거나 token이 소비됐으면
원 request만 조회한다. 새 permit, TTL 연장, unknown 재실행, 재귀 rollback은 추가하지 않는다.

기존 열한 unknown은 원 증거를 보존한다. 이 packet은 producer/process/resource가 실제로
종료됐다는 증거를 만들지 않는다. `observed_partial_v1`은 부분 관측으로 유지한다. 미래의
자동 격리/종료를 추가하려면 원 producer의 실제 descendant/resource 소유권과 종료 증거가
필요하며 PID 추정이나 state 폴더 교체로 대신하지 않는다.

## 실제 작업 순서와 완료 판단

1. 설치 source가 필요한 unbaking 및 native character writer/exporter leaf를 각 명세의
   정확한 callable·scope·완료 계약으로 채운다. 동일 정보가 이미 제품 코드에 있으면 재수집하지 않는다.
2. native reader/rotation writer가 확보된 범위에서 FK 후보 → 실제 write/evaluation/readback을
   연결한다. 이후 root·회전 결합과 접촉 보정을 같은 경로로 확장한다.
3. character exporter를 실제 최종 source에 결합하고 consumer skeleton/mesh 비교와 기존
   publication을 연결한다. required quality가 unverified이면 납품 성공을 반환하지 않는다.
4. 실제 실패가 발생한 별도 소유 작업본에서 해당 writer의 failure evidence와 기존 restore를
   연결한다. 원 작업 실패와 복구 결과를 별도로 유지한다.

이 순서는 구현 의존 관계다. 전체 회귀·반복 감사·벤치마크·CI를 자동으로 추가하는 gate가
아니다. 이번 packet 확인은 변경 파일의 구문과 diff 문맥에 한정하며 실제 native 성공을
대신하지 않는다. 적용 뒤 확인할 사례도 각 변경 지점과 직접 대응하는 사례만 명시한다.

## 기준 자료

- [최신 구현 commit](https://github.com/muhwagwa0112/cascadeur-complete/commit/99b85163c4125a621ef7e2deeabe22270032c60b)
- [최신 제품 상태와 실제 로컬 실행 기록](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/docs/KNOWN_ISSUES_2026-11-15.md)
- [현재 지원 범위](https://github.com/muhwagwa0112/cascadeur-complete/blob/99b85163c4125a621ef7e2deeabe22270032c60b/README.md)

위 실행 기록의 원 raw receipt·NPZ·`.casc` 파일은 로컬 ignored artifact이며 이 환경에서
독립적으로 재검증하지 않았다. 각 영역 문서의 소스 링크는 모두 같은 기준 commit에 고정한다.
