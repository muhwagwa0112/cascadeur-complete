# 수동 legacy 재개: bounded setup과 실제 pair 후속 실행

기준은 `7f1565a0ffad1595b9824cba25443bc581997fb6`이다. 제품 적용 전 제안 소스와
unified diff이며, 기존 R6 `incident/independent_target.py`의 일반 참조 API와 별도로
**한 번의 fresh bounded setup**과 그 실제 성공 결과를 사용하는 별도 유한 후속 route를 구현했다.
Windows, SDK, TTY 승인, 앱 dispatch를 실행하지 않았다.

## 실제로 이어지는 경로

`incident_cli prepare-manual-setup` → 기존 서명된 `system.incident_diagnostic` →
`incident_setup._prepare_metadata_only` → 정확한 두 legacy의 plan 저장 →
`approve-manual-setup`의 로컬 TTY 검토 → setup 서명과 수동 정책 서명 저장 →
`dispatch-manual-setup` → 기존 `BridgeClient.execute`/signed outbox →
`incident_admission.issue` → `admission-v2.json` → native `_validate` →
기존 `dispatch_setup`/`assert_setup_admission`/retained helper이다.

`collect_snapshot_locked`는 현재 원 request/terminal/journal을 그대로 projection한다.
draft 생성 단계만 policy의 실행 후보 판정을 요구하지 않는다. draft와 setup 승인만으로
큐를 실행할 수 없고, 수동 route가 없는 기존 요청은 기존 unresolved 정책을 계속 따른다.

### 파일별 역할

| 제안 product target | 변경 |
|---|---|
| `src/cascadeur_complete/incident_manual_setup.py` 및 native mirror | 실제 plan 발급, TTY 승인, exact request 소비, 한 request에만 claim, 기존 outbox 관측, 실제 BridgeClient 호출 |
| `src/cascadeur_complete/incident_pair_continuation.py` 및 native mirror | 실제 성공 setup의 request/terminal chain·fixture ID에서 새 유한 plan 작성, 한 번의 plan 승인, 요청별 실제 source/receipt lowering, 원 tab 복원 |
| `incident_admission.py` host/native | 잠금 안 projection 공유, 인증된 수동 disposition 소비, route 전용 v2 sidecar와 claim, native epoch/fingerprint 재확인 |
| `incident_policy.py` host/native | 기존 원 request·unsealed·pending retirement·원 run 차단 다음에 exact setup 정책만 허용; 원 사건 상태는 변경하지 않음 |
| `incident_setup.py` host/native | 기존 prepare를 유지하고 새 내부 metadata-only draft 경로 추가; helper sequence·workspace·bytes·budget 검증 재사용 |
| `src/cascadeur_complete/incident_cli.py` | prepare/approve/dispatch 세 로컬 명령을 실제 함수에 연결; MCP 승인 발급 경로 없음 |

host/native module 5개는 byte-for-byte 동일한 제안 소스다. 기존 native dispatcher와
helper를 교체하지 않으며, 새 geometry helper를 추가하는 별도 motion 패치와 합칠 때는
`_HELPERS`, `SETUP_IDS`, semantic limits, dispatcher branch 추가를 그대로 병합한다.

## 한정된 승인 내용

원 `ffb7fc8e-417c-454c-a669-48625a086eda`, `fcf3352a-483c-4f9c-bc18-8b61a58822eb`의
실제 original ref, raw terminal digest, journal head, unresolved-set digest를 기록한다.
두 개 외의 unknown, 미봉인 effect, 진행 중인 retirement는 적용 범위 밖이다.
원 outcome/open 상태를 쓰거나 key·registry·journal을 재생성하는 코드는 없다.

새 epoch·loaded fingerprint·run UUID·workspace UUID·setup plan ID를 고정한다.
baseline은 설치된 helper 파일 전체의 digest와 exact setup plan에 묶인 새 fixture다.
unknown 산출물이나 현재 scene을 입력으로 채택하지 않는다. 각 helper는 기존 원 scene
보존 guard와 scope/budget을 그대로 사용한다.

plan에는 실제 setup sequence, 파일 경로, 생성 상한, 원문 operation과 setup digest가
포함된다. 아직 존재하지 않는 `operator_authorization` 서명은 prepare 단계에 만들지
않는다. TTY 검토 뒤 그 exact setup plan의 서명을 만들고 별도 수동 approval에 담는다.
dispatch의 operation은 그 저장된 서명을 포함한 정확한 값으로 재구성·검증한다.
이 구조는 승인 전 approval을 요구하던 순환을 제거한다.

승인 대기는 registry/admission lock 밖이다. 승인 직후 같은 plan bytes, 원 heads,
expiry, workspace 존재 여부, helper bytes를 lock 안에서 다시 확인한다. native 첫 effect
재검사는 동일 잠금 안 projection을 공유하며, 승인할 때의 setup permit을 일반 source
capture나 scene mutation에 재사용하지 않는다. 최초 claim은 한 signed request digest에만
연결된다. plan을 갱신하거나 요청 nonce를 바꿔 재소비할 수 없다.

## 적용 후 사용 형태 — 이번에는 실행하지 않음

아래는 설치·재로딩을 완료한 동일 host/native package에서 사용할 **제안 CLI**다.
기존 setup plan의 유효기간 300초를 유지하므로 검토·승인·첫 제출은 그 안에 끝나야 한다.
새 명령을 적용하지 않은 설치에서는 사용할 수 없다.

```powershell
python -m cascadeur_complete.incident_cli --root <runtime-root> prepare-manual-setup --step setup.qualify_independent_models --step setup.qualify_independent_position_writer --workspace <runtime-root>\snapshots\<fresh-directory>
python -m cascadeur_complete.incident_cli --root <runtime-root> approve-manual-setup --plan-digest <printed-plan-sha256>
python -m cascadeur_complete.incident_cli --root <runtime-root> dispatch-manual-setup --plan-digest <printed-plan-sha256>
```

첫 명령은 code-owned metadata diagnostic과 draft 저장을 수행하며 scene을 생성하지
않는다. 두 번째 명령은 잔여 불확실성과 전체 plan을 표시한 뒤 operator가 digest 전체를
입력해야 서명을 발급한다. 세 번째 명령만 실제 승인된 setup을 제출한다.

이미 동일 request의 outbox가 있으면 세 번째 명령은 `reconcile_request`만 호출한다.
새 incident가 생기거나 plan이 만료된 뒤에도 원 결과를 관측할 수 있다. 효과를 재전송하지
않으며 실패/unknown을 성공으로 바꾸지 않는다. 최초 제출 직전 runtime이 바뀌면 제출하지
않는다. plan 만료나 준비 중 source 변경은 새 draft와 별도 검토가 필요하며 자동 승인하지 않는다.

## 내부 형식 변경 제안

- 신규 route: `manual_legacy_setup_v1`, reference `{kind, plan_digest}`.
- 신규 목적별 signed store: `manual-setup-plans`, `manual-setup-approvals`, `manual-setup-claims`.
- 실제 pair 후속 route: `manual_legacy_pair_continuation_v1`. 별도 signed store는
  `pair-continuation-plans`, `pair-continuation-approvals`, `pair-continuation-claims`다.
- route 요청만 `admission-v2.json` / `admission-claim-v2.json`을 사용한다. v2 sidecar는
  별도 MAC purpose와 signed `policy_route`를 갖는다. route 없는 요청은 기존 v1을 유지한다.
- request/receipt protocol `3.0`, 원 key, registry v1, incident journal 형식은 변경하지 않는다.
- 이 route는 기존 R6 참조 `manual_legacy_disposition_v1`의 광범위 계획 형식을 암묵적으로
  수용하지 않는다. 실제 구현한 setup 한 요청의 의미만 새 이름에 고정했다.

이 정책·CLI·내부 형식 변경은 이번 **설계/적용 패치 제안**의 일부다. 준비물 push는
사용자 Windows에서 이 위험 수용을 발급하거나 실행한 것이 아니다.

## 실제 setup 성공 이후의 유한 pair 실행

`incident_pair_continuation`은 `setup.qualify_owned_pair_geometry`의 실제 성공을
인증한 경우에만 작성할 수 있는 두 번째 plan이다. setup request의 원 MAC, receipt 전체
sequence와 request/operation/context/result digest, `succeeded` terminal, 그 terminal의
raw bytes digest를 읽는다. motion integration이 반환한 실제 `fixture_scene`,
`original_scene`, 두 tab ID, 두 mesh ID, 두 layer ID, 세 frame, 초기 projection digest,
retention 관측을 사용한다. 존재하지 않는 객체나 완료 상태를 생성하지 않는다.

유한 순서는 다음과 같다.

1. 원 tab에서 실제 `scene.activate`용 source를 읽고 승인된 fixture tab을 활성화한다.
2. 선택적으로 **명시된 실제 mesh 1개·기존 frame 1개·local position 하나**를 쓴다.
3. 실제 새 source를 읽어 interpolation을 평가하고 그 성공 terminal을 얻는다.
4. 그 evaluation의 실제 `post_source_binding`으로 native motion capture를 읽는다.
5. 실제 motion capture와 원 mutation/evaluation receipt에서 geometry arguments를 낮추고,
   geometry source를 새로 읽은 뒤 두 mesh × 세 frame을 계산한다.
6. 실제 terminal 이후 봉인된 geometry manifest를 읽는다.
7. 실제 새 activation source로 원 tab을 복원하고 반환된 successor와 원 scene identity를 대조한다.

총 요청은 기본 **10개**, 선택적 position 쓰기를 포함하면 **12개**다. 실제 geometry 계산
상한은 6회, array 상한은 64 MiB, artifact 상한은 16 MiB다. 좌표계·길이 변환·rational FPS는
사용자가 명시한 기존 MotionContext 형식으로 plan에 포함한다. 이 값은 변환 정책이며 SDK의
물리 metadata를 관측했다고 표시하지 않는다. 입력 frame은 실제 fixture의 `[0,1,2]`로 제한한다.

각 step의 request UUID는 새 run UUID에서 결정되고 한 번만 제출된다. 다음 요청의 객체,
source, capture digest, origin request는 해당 plan의 실제 선행 성공 terminal에서만 얻는다.
설치된 native pair adapter는 private scene 객체와 original setup terminal을 별도로
확인한다. 첫 activation은 setup의 초기 fixture projection과 동일해야 한다. 단순히 같은
ID가 있는 다른 tab이나 caller가 선언한 source는 이 조건을 대체하지 않는다.

effect 단계의 confirmation token은 이미 서명된 전체 유한 plan을 소비하여 기존
`ChangeManager.prepare/consume`으로 발급한다. native의 source·exact operation·request ID·
context·selection·confirmation 검증은 그대로 수행된다. 일반 `ChangeFlow`나 recipe를
우회 가능한 범용 mutation API로 노출하지 않는다. 대상은 setup이 만든 disposable fixture와
두 tab의 선택뿐이고 임의 scene, 파일 경로, export, 원 프로젝트 쓰기는 plan에 없다.
전체 유한 plan 승인 후 단계별 TTY 승인을 다시 받지 않는다.

```powershell
python -m cascadeur_complete.incident_cli --root <runtime-root> prepare-pair-continuation --setup-plan-digest <succeeded-manual-setup-plan-sha256> --context-json <explicit-context.json>
python -m cascadeur_complete.incident_cli --root <runtime-root> approve-pair-continuation --plan-digest <printed-continuation-sha256>
python -m cascadeur_complete.incident_cli --root <runtime-root> run-pair-continuation --plan-digest <printed-continuation-sha256>
```

선택한 position 쓰기가 필요한 경우 첫 명령에 `--mutation-json <exact-position.json>`을
추가한다. 그 파일의 정확한 `{ids,position,frame,space}` 값이 plan 원문에 표시된다.
`ids`는 실제 setup 결과의 mesh ID 한 개여야 하며 새 ID를 가정할 수 없다.

후속 plan은 600초 이내의 새 실행에만 적용된다. 이미 기록된 요청은 만료 후에도 관측만
가능하며, 성공한 prefix 다음의 아직 제출하지 않은 단계만 같은 유효 plan으로 진행한다.
실패·pending·unknown 단계는 재제출하지 않는다. 그 경우 원 tab 복원 완료를 주장하지
않고 중단한 원 request를 반환한다. 완료가 불확실한 SDK 작업 중에 임의 cleanup effect를
추가하지 않는다. 정상 경로는 원 tab 복원까지 끝나야 `complete=True`를 반환한다.

## 남은 연결과 검증 범위

실제 pair setup부터 위 continuation을 실행하려면 motion integration의
`native_installed_update_facts.extract_installed_update_facts`가 설치 SDK에 맞게 구현돼야
한다. 이 SDK 입력이 없으면 setup 성공과 후속 plan의 기반을 발명하지 않는다.
원 작업 복구, 일반 rig, 전체 recipe preflight/context 전달, 실제 모션 품질 평가는 이번
finite continuation의 완료 의미가 아니다. 일반 recipe 코드는 변경하지 않는다.

이 소스 작성 중에는 Windows/SDK/import/pytest를 실행하지 않았다. 부모 작업이 최종
파일에 대해 구문과 패치 문맥만 한 번 확인한다. 제품 적용 후 필요한 직접 확인은
(1) 승인된 정확한 setup 한 요청이 기존 dispatcher에 도달하는지,
(2) 같은 요청은 재제출되지 않고 새 unknown·다른 epoch·다른 plan에는 승인이 재사용되지
않는지, (3) TTY 대기 중 registry 잠금이 유지되지 않고 승인 직후 바뀐 원 head를 거절하는지다.
전체 회귀·E2E·CI 실행 절차를 추가하지 않는다.
