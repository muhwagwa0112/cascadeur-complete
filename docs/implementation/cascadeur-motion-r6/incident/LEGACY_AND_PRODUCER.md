# R6: legacy 기록을 보존하는 독립 target과 실제 증거 발급 경로

기준 HEAD `7f1565a0ffad1595b9824cba25443bc581997fb6`. 이 packet은 제품 적용 전 준비물이다. 새 public control API, registry/coverage/producer schema, supervisor 권한은 **별도 적용·실행 승인 대상**이다. OS 명령·SDK·테스트는 실행하지 않았다. packet 정적 확인은 상위 검증 기록을 따른다.

## 결정

원 `ffb7fc8e-417c-454c-a669-48625a086eda`, `fcf3352a-483c-4f9c-bc18-8b61a58822eb`의 terminal과 incident는 `outcome_unknown/open` 그대로 둔다. 없어졌거나 처음부터 남기지 않은 원 PID/creation/image·consumer 전체 목록을 새 PID로 채우지 않는다. 기존 `windows_exact_retirement`는 그 원 증거가 있는 사건에만 사용한다.

두 운영 선택지를 구분한다. **수동 legacy disposition**은 사용자가 미증명인 잔여 위험을 확인하고 두 기존 작업을 포기한 뒤 구체적인 새 run만 허용하는 정책 변경이다. **독립 target coverage**는 실제 독립 환경의 현재 측정으로 그 환경에 한정한 비간섭을 뒷받침한다. 어느 쪽도 원 incident를 해결했다고 표시하거나 원 run resume/retry·기존 output publication을 허가하지 않는다. 같은 source/key/registry를 다른 root에 복사하는 방식도 사용하지 않는다.

독립 coverage의 concrete backend는 **legacy 실행 권한과 관리 권한을 공유하지 않는 별도 신뢰 Hyper-V host의 전용 VM**이다. 기존 host의 같은 사용자·관리자 권한으로 VM 설정/VHD/supervisor key에 접근할 수 있다면 이 backend의 전제가 성립하지 않는다. host-process만 분리하거나 같은 사용자 ACL만 추가한 상태를 OS 격리라고 인증하지 않는다. 별도 host·지원 Windows/Hyper-V·guest OS·Cascadeur 라이선스·GPU/GUI 실행 가능 여부는 현재 미확인이다. 이 backend는 수동 disposition의 전제조건이 아니다.

## 파일의 역할

- `hyperv_realm_evidence.ps1`: 실제 `Get-VM`/Hyper-V WMI/장치·디스크·integration 조회, request/baseline bytes 관측, Windows .NET RSA 서명·검증. 측정 없이 closed flag를 서명하는 API가 아니다.
- `independent_target.py`: 독립 coverage는 위 script의 **실제 표준 crypto verifier 호출**로 검증한다. 별도 `prepare_manual_legacy → approve_manual_legacy_local → consume_manual_step_locked`는 수동 정책 선택을 발급·소비한다. 수동 승인을 OS/과거결과 증거로 변환하지 않는다. baseline bytes를 실제 읽고 hash를 확인한다. Python RSA 구현이나 `verified=true` 입력은 없다.
- `future_producer_issuer.py`: launch/dispatch 이전 측정과 원 signed request를 durable 보존하고, 원 terminal이 생긴 뒤 정확한 original ref에 결합하여 `producer-closures`를 발급한다. 실제 callback 본문과 기존 등록 위치를 연결한다. realm scope를 기존 finite process/file scope로 위장하지 않는다.

## 운영상 먼저 선택할 수 있는 수동 legacy disposition

새 Hyper-V 환경이 없어도 제안할 수 있는 **정책 변경안**이다. 이 packet을 push하는 승인은 이 disposition의 발급/실행 승인이 아니다. 적용 후 로컬 operator가 구체적인 새 작업과 잔여 위험을 별도로 승인해야 한다. 사용자에게 보여 줄 문구는 "원 결과·producer/consumer 종료·영향 범위는 미증명이며 새 작업에 간섭하지 않는다고 보장하지 않음"이다.

`prepare_manual_legacy()`는 현재 canonical registry의 모든 원 key로 두 original ref/head를 읽는다. 두 UUID만 고정된 legacy 대상이며 raw digest/head도 실제 기록과 결합한다. 새 unknown이나 unsealed request가 있으면 이 경로를 사용할 수 없다. 새 runtime epoch·loaded fingerprint·run UUID·workspace UUID/절대 경로·fresh fixture generator의 실제 bytes와 설치 manifest hash·승인할 **operations 원문**·단계별 digest를 immutable plan에 저장한다. 코드가 현재 장면이나 unknown output을 baseline으로 선택하지 않는다.

`approve_manual_legacy_local()`은 MCP에서 노출하지 않는 로컬 TTY entry다. lock에서 plan을 읽고 **lock을 풀어** 원문/잔여 위험을 표시한다. operator가 plan digest를 직접 입력한 뒤 lock을 다시 잡아 같은 plan·원 heads·unknown set·expiry를 확인하고 별도 목적 MAC의 approval을 append한다. 원 terminal/incident journal은 쓰지 않는다.

`consume_manual_step_locked()`는 이미 보유한 registry/admission lock을 재획득하지 않는다. 실제 signed request, 현재 native epoch/fingerprint, exact run/workspace/baseline, operations 원문, 최신 원 heads를 확인하고 해당 step을 **한 request digest에만** 결합한다. native 재검사는 같은 claim을 확인하며 다른 request로의 재소비·원 request 재실행·새 unknown 적용을 거절한다. workspace parent와 baseline의 물리 identity/hash도 재확인한다. 별도 disposition 결과의 assurance는 `operator_accepted_unproven_legacy_interference`이며 `retirement`/`native_closure`가 아니다.

초기 참조 경로는 설치 bytes로 결정되는 bounded setup와 **이미 구체화된 operations**에 한정한다. 새 fixture에서 생성될 object ID를 가짜로 채우지 않는다. 후속 motion은 실제 성공한 새 run source를 얻은 다음 기존 recipe의 역할/객체 lowering 및 source authorization을 통과해야 한다. 그 결과를 아직 얻지 못했다면 임의 concrete request를 발급하지 않는다. `previous_succeeded_new_run_step`은 기존 recipe ancestry 검사가 실제 원 성공 receipt/source binding을 확인할 때만 소비한다. 이 조건을 구현하지 않고 source-rule 문자열만 신뢰하면 안 된다.

첫 setup을 준비하는 순환은 `incident_setup.prepare()`를 **코드/ledger만 읽는 draft 작성**으로 분리해 푼다. 아직 source capture·native create/save는 없다. 정확한 helper sequence/budgets와 setup approval payload를 준비한 뒤 manual plan에 실제 setup operations를 넣고 operator에게 한 번에 보여 줄 수 있다. draft나 setup approval 자체는 admission sidecar가 아니며 실제 큐 dispatch는 아래 검증 경로가 완성된 뒤에만 가능하다.

## 독립 coverage의 최초 신뢰 이전

1. legacy host에서 기존 `IncidentStore`/`incident_inspect`로 두 original ref와 authenticated journal head/raw-terminal digest를 얻는다. 여기서는 원 key를 읽는 기존 verifier만 사용한다. 원 결과를 재분류하지 않는다.
2. 독립 supervisor의 공개 인증서 fingerprint, 실제 별도 host identity, 허용 VM ID·저장 영역, 사용할 확정 baseline, 새 출력 namespace를 구체적으로 승인한다. 다른 machine UUID라는 사실만으로 관리 권한의 독립성을 증명하지 않는다. trusted-host provisioning/관리권한 분리의 확인은 최초 trust bootstrap의 전제이며 자동으로 만들어 내지 않는다.
3. supervisor는 이 export digest를 migration plan에 고정하고 **현재 VM 측정**을 붙인 target coverage anchor를 서명한다. 목적은 `independent_target_coverage_v1`; 원 incident가 해결됐다는 서명이 아니다. 원 두 domain key는 guest로 반입하지 않는다.
4. guest에는 supervisor의 **공개 인증서 pin**, original ref/head/raw digest의 최소 목록, coverage anchor, baseline manifest와 새 target domain identity만 넣는다. 새 target key는 새 작업 domain용이며, old unknown을 지우기 위해 새 key를 쓰는 것이 아니다.

host의 신뢰 provisioning을 애초 확인하지 못하면 계획은 여기서 멈춘다. 반대로 이 전제가 성립하고 concrete collector가 통과하면, 원 역사적 producer closure를 기다리지 않고 새 VM의 bounded setup으로 이어질 positive path가 있다. 최초 trust bootstrap 이후의 같은 승인 범위 작업은 supervisor가 자동으로 lease/증거를 발급할 수 있다.

## 현재 환경을 증명하는 범위

collector profile은 VM ID/Generation 2, hypervisor 상태, VM worker PID+creation time+image, attached VHDX, checkpoint/replication, NIC, DDA/GPU partition, Fibre Channel, named COM pipe, DVD mount, integration service, Enhanced Session 설정을 실제로 읽는다. 이 profile에서는 network adapter·passthrough device·shared storage/parent differencing disk·checkpoint·mounted DVD·COM pipe·enabled integration service를 허용하지 않는다. 누락 cmdlet/API/권한은 빈 목록으로 대체하지 않고 실패한다.

PowerShell Direct는 독립 host의 승인된 제어/반입/회수 채널로 **명시적으로 남긴다**. 이 채널은 NIC가 없어도 동작하므로 'NIC 0 = IPC 0'이라고 주장하지 않는다. host administrator와 guest credential이 필요한 trusted controller만 사용하고 legacy host에서 이 credential/session에 접근할 수 없어야 한다. 임의 `Invoke-Command`를 사용자 입력으로 받아 실행하는 MCP API는 추가하지 않는다. 승인된 파일 반입과 고정 bootstrap/dispatch 명령만 transport에 매핑한다.

측정 snapshot 하나가 향후 관리자 reconfiguration을 막는 것은 아니다. 독립 supervisor가 VM control 권한을 소유하고 startup/dispatch/첫 effect 전에 nonce-bound 측정을 갱신하며, 설정 변경은 realm generation을 폐기한다. 같은 host의 임의 관리자·malicious hypervisor까지 방어했다고 주장하지 않는다. 해당 권한 독립성이 없으면 이 profile을 사용할 수 없다.

이번 executable reference profile의 baseline은 **승인된 설치 package bytes에 묶인 새 immutable fixture generator**로 제한한다. original authenticated request의 preincident snapshot/input hash로 고정된 실제 프로젝트 bytes가 별도로 확보되면 lineage 연결을 확장할 수 있으나 이 참조 코드가 그 증거를 만들어 내지는 않는다. unknown output/자동저장/현재 장면을 '비슷한 원본'으로 채택하지 않는다. fresh fixture는 원 작업 복구가 아니다. 프로젝트 baseline이 없으면 qualification fixture까지만 진행하며 원 애니메이션 내용을 발명하지 않는다.

## 새 상태와 target registry v2

원 journal의 `open`을 변경하지 않는다. target registry에 별도 record를 둔다.

```text
foreign_incidents: [original_ref, original_head, source_export_digest]
independent_target_coverage:
  supervisor_certificate_sha256
  coverage_anchor_digest
  target_auth_domain_id / target_store_instance_id
  realm_id / realm_generation / vm_id
  baseline_manifest_digest / workspace_generation_id
  allowed_operations / approved_output_namespace
  measured_profile_digest / control_transport / expiry
```

기존 `incident_store.locked_registry()`가 모든 원 physical store를 직접 여는 v1 동작은 **유지**한다. v2에서만 `local_store`와 `foreign_incident_anchor`를 명시적으로 구분한다. old root를 조용히 생략하는 fallback은 없다. foreign record는 최소 원 digest/head를 공개 인증서로 검증한 coverage anchor를 통해 포함한다. registry v1/지원하지 않는 native는 계속 closed한다.

`incident_policy.decide()`는 local 새 unknown에 대한 종전 차단을 유지한다. foreign open incident에 대해서만 정확한 **현재 target/realm/request scope**의 coverage가 있으면 그 대상의 blocker에서 제외한다. 역사 상태는 여전히 open이다. 다른 realm·workspace·output·run에는 coverage를 재사용할 수 없다. 모든 원 domain을 포괄하지 않은 anchor, mutable target manifest, 기존 run ID는 거절한다.

## 실제 startup→setup→dispatch 연결

| 순서 | 현재/신규 위치 | 정확한 연결 |
|---|---|---|
| 1 | supervisor bootstrap | collector `Capture`로 VM 상태와 baseline을 측정하고 signed coverage anchor를 저장. guest에 공개 pin·coverage·최소 original refs만 전달. |
| 2 | target `IncidentStore` startup | registry v2를 읽고 `independent_target.load_coverage()`로 OS crypto 서명/target binding 확인. old key/root가 없다는 이유로 old incident를 삭제하지 않음. |
| 3 | native discovery/status | effect 없는 metadata만 제공. loaded fingerprint와 `independent_target_coverage_v1` capability를 알림. SDK source/fixture 생성은 아직 안 함. |
| 4 | `incident_setup.prepare()` | ledger projection 수집과 실행 admission 결정을 분리해 SDK 없는 draft를 먼저 만든다. `prepare_target_context()`의 **prepare-scope lease**는 확정된 helper sequence/budget/baseline/workspace를 결합하되 실행권한은 아니다. 원 receipt snapshot을 삭제하거나 unknown을 성공 처리하지 않는다. |
| 5 | `incident_admission.issue()` | signed outbox의 nonce/MAC까지 결정된 뒤 request digest를 supervisor로 전달. `record_dispatch()`가 실제 현재 realm capture와 request digest를 먼저 durable 저장하고 **dispatch lease**를 발급. 기존 sidecar에 coverage/lease digest를 결합. |
| 6 | native snapshot/claim/first effect | signed sidecar의 안정된 route/anchor/scope reference와 현재 request-bound lease를 검증. current local unknown, 기존 source/confirmation, setup helper step/budget, OS profile 변경도 검사. claim은 한 번, assertion은 재소비 없음. |
| 7 | terminal 전후 | 원 terminal을 원 코드대로 seal. supervisor에 raw request/terminal bytes를 전달하고 `finalize_original()`이 원 MAC·digest를 검증해 predispatch record와 결합한 producer closure를 durable 저장. 결과 반환은 durable receipt 이후. |

prepare lease를 dispatch lease로 재사용하지 않는다. recipe/ordinary source capture에도 같은 target context가 전달돼야 한다. request-specific challenge는 서명 밖의 caller JSON으로 덮어쓸 수 없다. 중간에 새로운 local unknown이 생기면 같은 VM의 신규 effect는 다시 멈추며, 그것이 새 VM으로 무제한 도망가는 권한은 아니다.

## 현행 함수에 넣을 호출 연결 — 제품 미적용

HEAD의 `src/cascadeur_complete/models.py`에서 `BridgeRequest.execution_context`는 `dict[str, Any] | None`이다. top-level extra는 금지하지만 `run_id/step_id/workspace_generation_id/baseline_digest/incident_route`는 이 dict에 넣을 수 있다. protocol `3.0`과 원 request/receipt MAC 식을 유지한다. **registry v2, admission sidecar v2, 내부 snapshot 인자, 새 local operator control API**는 승인 대상이다.

### 수동 경로의 실제 소비 지점

현재 `snapshot()`의 projection 수집 부분을 `collect_snapshot_locked()`로 추출하고, 아래 내부 resolver를 그 뒤에서 호출한다. `collect_snapshot_locked`는 신규 이름이며 현재 실존하는 API라고 주장하지 않는다. 본문은 현재 `original_snapshot → journal → project_domain`의 그대로인 로직이다. 원 projection을 수정하거나 raw unknown을 필터링하지 않는다.

```python
# 제안: incident_admission.py. caller가 이미 registry/admission lock을 보유.
def manual_context_locked(registry, stores, request, active, *, native):
    reference = (request.get("execution_context") or {}).get("incident_route")
    if reference is None:
        return None
    store.exact(reference, {"kind", "plan_sha256"})
    if reference["kind"] != "manual_legacy_disposition_v1":
        raise p.PolicyError("MANUAL_ROUTE_KIND_DIFFERS")
    if native:
        from . import guarded_runtime as guards
        epoch, fingerprint = guards.RUNTIME_EPOCH, guards.LOADED_FINGERPRINT
    else:
        # Host request was built from its authenticated runtime handshake.
        # Native checks actual loaded values again before any effect.
        epoch, fingerprint = request["runtime_epoch"], request["adapter_fingerprint"]
    from .independent_target import consume_manual_step_locked
    return consume_manual_step_locked(active.root, registry, stores,
        plan_sha256=reference["plan_sha256"], request=request,
        actual_runtime_epoch=epoch, actual_loaded_fingerprint=fingerprint)

# snapshot(..., native=False)에서 기존 collect/projection 뒤:
manual = manual_context_locked(registry, stores, request, active, native=native)
decision = p.decide(intent=intent, registry=registry_snapshot, domains=projections,
    evidence=evidence, manual_disposition=manual,
    diagnostic_evidence_digest=existing_diagnostic_digest,
    separation_evidence_digest=existing_separation_digest)
# 기존 candidate 검사/heads 반환에 policy context digest를 추가한다.
```

`existing_diagnostic_digest/existing_separation_digest`는 현행 snapshot에 이미 계산식이 있는 값의 설명용 이름이다. external callback/사용자 JSON을 proof로 바꾸는 함수가 아니다. 다른 route resolver는 `kind`로 분기한 후 그 route 전용 exact schema를 사용한다. manual resolver에 independent coverage reference를 넘기지 않는다.

`p.decide()`는 원 request 충돌/observe-only, 기존 diagnostic, unsealed/pending retirement 차단, 원 run 금지를 **먼저** 적용한다. 그 뒤 unresolved 분기에 아래 후보를 추가한다. `manual_disposition`은 위의 인증된 resolver 결과만 받을 수 있고 wire 입력으로 받지 않는다.

```python
# 제안: incident_policy.decide. 원 incidents/journal은 불변.
if manual_disposition is not None:
    exact_open = [asdict(i.original) for i in incidents
                  if i.observation is None and i.retirement is None]
    if sorted(map(digest, exact_open)) != sorted(map(digest, manual_disposition["originals"])):
        return Decision(Verdict.DENY, "MANUAL_LEGACY_SET_DIFFERS")
    return Decision(Verdict.NEW_WORK_CANDIDATE,
        "MANUAL_LEGACY_RISK_ACCEPTED_EXISTING_SOURCE_AND_OPERATION_GUARDS_REQUIRED")
```

이 후보는 기존 mutation confirmation/source/native guards를 생략하는 실행권한이 아니다. `fresh_fixture`는 `incident_setup.validate_setup_plan()`의 같은 helper/workspace/budget 검사로 직접 연결한다. 일반 source capture/read/effect에는 기존 recipe의 실제 성공 predecessor/source binding 검사가 먼저 필요하며, 그 ancestry 경로가 없으면 거절한다. 최초 positive path를 setup으로 제한한 이유다. source-rule 문자열만으로 새 scene을 신뢰하는 구현은 승인 대상 설계와 다르다.

| 현재 함수 | 적용 지점 / 정확한 반환 조건 |
|---|---|
| `incident_setup.prepare` | `collect_snapshot_locked`로 metadata만 수집해 exact draft 작성. 실행 `snapshot` 후보 승인은 호출하지 않음. `admission_required=True`와 현재 blocker를 반환하며 ticket 없음. |
| `incident_admission.issue` | 기존 signed immutable outbox 확인 뒤 위 snapshot 호출. `{policy_route, policy_context_digest}`를 별도 목적 MAC의 `admission-v2.json`에 포함. setup helper plan은 기존 `_setup_plan`으로 확인. |
| `incident_admission._validate` | v2 sidecar MAC/request digest를 읽고 저장된 route reference와 `native=True`로 snapshot 재검증. `_body`/`store.exact`도 v2 필드를 명시적으로 검증. v1 ticket은 새 route를 허용하지 않음. |
| `admitted_request`, `assert_request_admission` | 기존 `_validate` 호출 유지. 같은 step claim은 재검사, 다른 request digest는 거절. 첫 effect 전에 policy/source/plan을 확인. |
| `dispatch_setup`, `assert_setup_admission` | 기존 `VerifiedSetupStepGrant`와 thread-local helper sequence/budget 유지. 승인 workspace를 임의 새 UUID 경로로 바꾸지 않음. |
| `incident_admission.capability` | 지원 route·registry version·loaded fingerprint를 명시. host/native 한쪽 미지원이면 해당 route로 dispatch하지 않음. |

수동 route reference는 `{kind: "manual_legacy_disposition_v1", plan_sha256}`다. 이 참조를 signed request의 기존 execution_context에 넣는다. 실제 plan/approval은 same canonical domain의 durable store에서 인증한다. 원 두 domain을 새 root에서 누락시키지 않는다. **승인 plan의 `scope.operation_plan_digest`는 후속 recipe plan과도 결합해야 하며, 아직 생성되지 않은 객체를 대상으로 한 임의 operation은 이 packet의 발급 범위 밖이다.**

### 독립 target과 미래 producer의 연결

독립 route reference는 `{kind: "independent_target_coverage_v1", coverage_anchor_sha256, scope_digest}`다. `load_coverage()`는 최초 supervisor 서명/완전한 원 export를 확인하고, `prepare_target_context()`는 실제 현재 측정의 request/challenge/scope를 확인한다. signed request 내부에 자기 자신을 포함하는 lease digest를 넣지 않는다. request 완성 → `RealmSupervisor.record_dispatch()` → durable lease → sidecar 순서다. native `_validate`는 같은 request-bound lease와 현재 epoch를 재검사한다. fresh lease가 필요하면 append된 새 관측을 같은 원 request/claim에 연결하며 terminal/기존 sidecar를 덮어쓰지 않는다.

registry v2 reader는 local entry만 `IncidentStore`로 열고, foreign entry는 `load_coverage()`로 검증한 최소 original/head record로 유지한다. 새 local unknown에는 기존 차단이 그대로 적용된다. foreign open만 exact target context로 평가하므로 과거 auth key나 physical store를 guest로 복사하지 않는다. `install_target_registry()`는 `load_coverage()` 직후의 bootstrap 전용 호출이며 외부에서 받은 dict를 그대로 seal하는 public endpoint로 노출하면 안 된다.

supervisor `approved_plan`은 실제 값이 준비된 뒤 아래 필드를 가진다. 이 packet에는 UUID/PID/hash/인증서 값을 창작해 넣지 않았다.

| 필드 | 실제 입력의 출처 |
|---|---|
| `schema_version=1`, `purpose=independent_target_plan_v1`, `profile=dedicated_hyperv_no_external_devices_v1` | 승인된 새 schema의 고정 코드 값 |
| `source_export_sha256`, `target.{auth_domain_id,store_instance_id}` | 원 host의 `export_legacy_snapshot()` + 새 target의 실제 store enrollment |
| `realm.{id,generation,host_uuid,vm_id,storage_directory,vhd_paths}` | 독립 host provisioning과 `Get-VM`/실제 VHD identity; `id/generation`은 supervisor가 발급·관리 |
| `baseline.{origin_kind,path,sha256,size,installed_package_digest}` | 승인된 설치 package의 실제 fixture-generator bytes |
| `workspace_generation_id`, `operation_plan_digest`, `setup_steps` | 구체적으로 준비한 새 작업/helper sequence와 budget |
| `controller_sid`, `control_transport=powershell_direct_fixed_files_v1`, `expires_at_ms` | 독립 supervisor의 실제 Windows SID, 고정 transport, 승인 기간 |

scope에는 `target/runtime_epoch/loaded_fingerprint/run_id/workspace_generation_id/workspace_path/baseline_digest/operation_plan_digest/helper_sequence_digest`를 넣는다. baseline/helper digest는 위 plan의 실제 객체에서 계산한다. guest 반입 시 host path를 guest 파일 경로처럼 사용하지 않는다. target에 설치된 같은 generator bytes를 다시 확인하고 그 로컬 경로를 별도 workspace/source manifest에 결합한다.

생산 순서는 다음과 같다. 이 순서가 제품에 연결되어야 reference가 실제 경로가 되며, 이번에는 연결/실행하지 않았다.

1. supervisor startup에서 보호된 `SupervisorConfig`를 읽고 `install_authority()`로 실제 verifier를 등록한다. 현재 `_enroll_authority`에 `scope_kind`가 없으면 명시적으로 거절한다. 원 key와 새 key의 혼용은 거절한다.
2. guest는 공개 cert pin·최소 원 refs·signed coverage만 bootstrap한다. host 전용 파일 경로/Hyper-V collector를 guest에서 실행하지 않는다. native startup/discovery는 v2 registry와 actual loaded fingerprint가 맞아야 route capability를 공개한다. native의 resource-control facade에는 반입한 **새 domain의** signed evidence와 guest의 실제 baseline 경로를 연결해야 하며, supervisor용 `SupervisorConfig`를 경로만 바꿔 복사하지 않는다.
3. guest에서 signed request가 완성되면 fixed transport가 raw bytes를 supervisor로 전달한다. `record_dispatch()`는 원 MAC·scope를 확인하고 현재 `Capture`를 수행해 `dispatches/<request_id>/committed.json`을 durable 저장한 뒤 반환한다. 이 반환 전에는 기존 `BridgeClient` queue write/trigger를 하지 않는다.
4. native `runtime._drain_once`/`execute_request`의 dispatch_started 이전에 `record_local_dispatch_metadata()`가 **지금 실제 실행할** native PID/creation/image를 보존한다. 이것은 `observed_partial_v1`이며 child/consumer/resource 전체 closure가 아니다.
5. 기존 native terminal seal 이후 receipt bytes를 supervisor로 전달한다. `finalize_original()`이 실제 전체 ordered event chain의 MAC/request/operation/session/run/result digest를 검증하고 VM 밖에 저장한다. unknown이면 original ref에 결합한 `producer-closures/<request_id>.json`을 발급한다. host 결과 반환은 이 durable archive 이후다.
6. 해당 미래 원 VM을 종료한 뒤 `observe_original_realm_off()`가 원 predispatch manifest와 현재 **같은 VM/VHD의 Off**를 실제 측정해 `realm-off/<digest>.json`을 발급한다. 기존 legacy에 없는 predispatch 자료는 지금 만들지 않는다. 과거 SDK 결과는 판정하지 않는다.
7. 다음 새 realm의 `record_dispatch(... off_observations=...)`가 `verify_realm_off()`를 실행하고 VM/VHD identity 분리를 확인하여 그 관측을 실제 committed record에 보존한다. `verify_workspace()`는 별도 미발급 파일을 기다리지 않고 이 실제 record와 signed request의 `intent_for()` 결과를 읽는다. 제안 realm backend는 실제 Off receipt digest를 `RetirementClosure.termination_evidence_digest`로 반환해야 한다.

PowerShell Direct transport는 공식 `New-PSSession -VMId ... -Credential ...`, `Copy-Item -ToSession/-FromSession`, `Remove-PSSession`으로 **정해진 bytes 경로만** 옮기는 제어기로 구현한다. 임의 scriptblock/guest path/외부 output consumer를 사용자 요청에서 받지 않는다. bootstrap trust 입력, credential provisioning, VM 생성/종료/GUI 실행 및 native resource facade 배선은 제품 적용 작업이며 이 packet이 실행 완료했다고 주장하지 않는다. supervisor는 같은 realm의 configuration/dispatch를 직렬화하고 active epoch 동안 reconfiguration을 금지해야 한다. 현재 snapshot만으로 임의 host admin의 미래 변경을 막았다고 주장하지 않는다.

## 미래 요청의 scope issuer와 retirement backend

현재 `_enroll_authority()`는 이름만 있고 production caller가 없으며, `_scope()`는 flat finite files/process lists만 수용한다. R6는 두 타입을 구분한다.

- `finite_windows_v1`: 기존 executor 유지. 실제 native capability가 closure를 증명한 경우에만 원 process·files를 사용한다.
- `hyperv_realm_v1`: **guest 전체가 effect boundary**다. guest 자식 process/SDK worker의 목록을 알지 못해도 이 경계를 넘을 수 없는 profile을 현재 측정한다. worker PID만으로 VM이 끝났다고 하지 않는다. guest process 목록을 빈 리스트로 만들어 finite executor를 통과시키지 않는다.

`future_producer_issuer.install_authority()`는 실제 archive와 host 경로를 소유한 supervisor startup에서 해당 **새 target** domain key/공개 supervisor pin을 결합하여 verifier callbacks를 등록한다. guest의 native facade는 공개 서명 자료와 guest 로컬 baseline을 사용하며 supervisor의 host 경로를 직접 열지 않는다. 기존 `_enroll_authority()`에 `scope_kind`와 backend dispatch를 명시적으로 추가하는 승인된 schema 변경이 필요하다. `inspect_retirement_scope()`는 realm manifest를 기존 `_process()`에 넘기지 않고 supervisor의 VM lifecycle backend로 전달한다. 원 `producer-closures/<request_id>.json` 목적 MAC과 exact original ref 결합은 그대로 사용한다.

realm retirement는 승인된 전용 VM에 대해 Hyper-V의 `Stop-VM -VM $vm -TurnOff`를 호출하는 별도 executor 계약이다. 이 packet은 임의 OS stop를 자동 실행하지 않는다. executor가 실제 실행할 때는 exact approval/VM/generation을 먼저 durable 기록하고, 실제 `Get-VM`의 `Off` 관찰과 signed current profile/result를 **VM 밖 supervisor store**에 먼저 저장한다. `Save`/`Paused`는 종료 증거로 사용하지 않는다. VM worker process kill만으로 guest cessation을 증명하지 않는다.

종료 호출 뒤 host가 끊기면 '다시 Stop'부터 하지 않는다. 같은 VM ID/generation의 현재 `Off`와 설정 custody를 읽어 **미래 간섭 차단의 새 관찰**을 발급할 수 있다. 그 관찰은 원 SDK 성공/실패나 과거 stop 호출 성공을 소급 판정하지 않는다. 원 request는 unknown이고 새 domain별 coverage/realm-retirement receipt만 추가된다. VM 또는 VHD identity/realm generation이 바뀌면 재관측을 원 instance의 종료로 연결하지 않는다.

## 내구성·동시성·인증 경계

- 원 request/terminal/MAC/journal은 그대로 읽는다. 새 manual approval, step claim, supervisor measurement, dispatch commit, producer closure, 현재 Off 관찰은 별도 파일에 append한다. `CreateNew` 또는 no-replace hard-link publication을 사용하고 bytes flush/fsync를 먼저 수행한다. 이전 파일을 새 상태로 재서명하거나 덮어쓰지 않는다.
- manual plan 읽기/approval/claim은 기존 registry/admission lock을 이용한다. `*_locked`는 보유한 lock 안에서 사용하고 TTY 대기는 lock 밖이다. supervisor realm-control lock은 실제 OS 잠금이며 PID 존재/TTL로 소유권을 추측하지 않는다. 다중 설정 변경과 dispatch의 직렬화는 같은 supervisor 제어 경계에 연결해야 한다.
- dispatch record가 없거나 commit 전 crash이면 execution permit을 발급하지 않는다. commit 이후 전달 여부가 불명확하면 같은 request를 재실행하지 않고 원 receipt/claim만 관측한다. terminal archive가 일부만 남았으면 동일 prefix만 이어 저장할 수 있고 다른 bytes는 거절한다. `.pending` 파일은 권한 증거가 아니다.
- 표준 .NET RSA가 **정확한 payload bytes**를 서명/검증한다. Python은 pinned script/cert와 실제 verifier stdout bytes를 비교하므로 caller `verified=true`가 없다. Python/PowerShell의 JSON 정렬이 같다고 가정하지 않는다. plan/binding은 원 bytes SHA-256에 결합하고 signed payload는 base64의 원 bytes로 검증한다.
- 기존 original-domain HMAC 파생식은 `incident_store`와 같은 목적 분리식이다. 서명은 기록 출처를 증명하고 collector는 현재 VM 상태를 관측한다. operator 승인·MAC 자체를 역사적 완료/미래간섭부재의 의미 증거로 취급하지 않는다.
- v1 설치는 새 schema/route를 거절한다. v2 마이그레이션은 parent packet의 실제 store identity 이관 절차와 결합한다. unknown/root/key를 reset하여 old reader를 통과시키지 않는다. 같은 realm의 설정 변경/재시작은 generation을 폐기하고 새 측정·loaded epoch binding이 필요하다.

## 검증 경계와 미확인 항목

코드는 실제 collector/OS verifier/bytes hashing/append serializer와 manual 발급/소비 본문을 포함한다. 환경 정보를 제공하지 않았으므로 실제 UUID·PID·hash·baseline·인증서를 예제로 생성하지 않았다. OS cmdlet/서명·guest transport·Hyper-V/Cascadeur 설치·license·GPU·native recipe는 미실행이다. 코드의 실제 제품 호출 연결, native resource facade, realm subtype executor는 위에서 지정한 **적용 작업**이며 이 참조 파일만 복사하여 전체 기능이 생기지는 않는다. 참조 코드가 positive evidence를 만들 수 있는 경로를 정의한 것과 사용자 환경에서 실행 가능함은 다르다. Hyper-V 지원이 미확인인 이유로 별도 manual 경로의 draft 작성까지 차단하지 않는다.

원 footprint를 모르므로 과거 파일/외부시스템 영향 소거·복구는 보장하지 않는다. 새 output을 원 publication target에 자동 연결하지 않는다. 명시된 독립 target 안에서만 새 작업을 허용한다. 이 조건이 맞는 실제 환경이 없으면 '설계 준비, 실행 가능성 미확인'으로 보고한다.

## 공식 API 근거

- [Get-VM: `-Id`, VM object](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vm?view=windowsserver2025-ps)
- [Get-VMNetworkAdapter](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vmnetworkadapter?view=windowsserver2025-ps), [Get-VMHardDiskDrive](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vmharddiskdrive?view=windowsserver2025-ps), [Get-VHD](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vhd?view=windowsserver2025-ps)
- [Get-VMAssignableDevice](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vmassignabledevice?view=windowsserver2025-ps), [Get-VMGpuPartitionAdapter](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vmgpupartitionadapter?view=windowsserver2025-ps), [Get-VMFibreChannelHba](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vmfibrechannelhba?view=windowsserver2025-ps)
- [Integration services](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/manage/manage-hyper-v-integration-services), [Enhanced Session setting](https://learn.microsoft.com/en-us/powershell/module/hyper-v/set-vmhost?view=windowsserver2025-ps)
- [Msvm_ComputerSystem.ProcessID](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/msvm-computersystem), [Stop-VM `-TurnOff`](https://learn.microsoft.com/en-us/powershell/module/hyper-v/stop-vm)
- [PowerShell Direct의 host/guest·권한·credential 요구](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/powershell-direct)
- [.NET RSA.SignData](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.rsa.signdata), [.NET RSA.VerifyData](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.rsa.verifydata?view=netframework-4.8.1), [GetRSAPrivateKey](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.x509certificates.rsacertificateextensions.getrsaprivatekey)

## 이번 연결이 필요한 코드 근거

- [원 key/MAC 및 physical store를 모두 여는 registry v1](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_store.py#L254-L322)
- [현재 projection과 모든 unresolved 차단으로 이어지는 snapshot/issue/native validate](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_admission.py#L141-L228)
- [기존 decision의 unresolved 및 원 run 차단](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_policy.py#L455-L491)
- [없으면 blocked인 producer-closure reader](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_control.py#L93-L155)
- [기존 authority callback 계약](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_resources.py#L86-L133)
- [실제 BridgeRequest 모델과 execution_context](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/models.py#L121-L143)
- [현재 setup.prepare의 context=None snapshot 순환과 exact helper plan](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_setup.py#L54-L97)
