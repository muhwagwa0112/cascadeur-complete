# 설치 profile·qualifier lifecycle 구현 packet

기준 commit: `fc0e98eaa30e819f98880a32dce30c6767a5cc64` (`feat/cascadeur-motion-r3`). 이 디렉터리에는 **적용하지 않은 제안 patch와 변경 후 소스 사본**만 있다. 원 프로젝트/원격 파일, 설치 state, 실제 앱은 수정하지 않았다. 테스트·빌드·설치·실앱 실행은 수행하지 않았다. source snapshot의 SHA-256은 `BASELINE.json`에 기록했다.

## 적용 대상과 순서

| 산출물 | 현행 코드 대상 | 구현 범위 |
|---|---|---|
| `patches/01_exact_installation_profile.proposed.patch` | `scripts/verify-install.ps1` | catalog baseline, 선택한 exact 설치 build, 미관측 native qualification을 별도 출력한다. |
| `patches/02_retain_qualification_fixtures.proposed.patch` | `native_adapters.py`, `native_interpolation_qualification.py`, `native_independent_position.py`; 새 `native_probe_retention.py` | 현재 사용하는 finite qualifier의 남은 자동 탭 제거를 보존으로 바꾸고 동일 epoch의 반복 fixture 생성을 막는다. |
| `proposal_sources/` | 위 patch의 변경 후 전체 텍스트 | 구현자가 함수 본문을 직접 검토할 수 있는 사본이다. 설치 대상 경로가 아니다. |

01과 02의 source hunk는 서로 독립적이다. 02의 실제 실행에는 다른 incident packet의 `incident_admission.assert_setup_admission` 및 authenticated setup dispatcher가 먼저 구현돼 있어야 한다. 해당 모듈이 없는 현재 HEAD에 02만 적용해 실행할 수 있다고 주장하지 않는다. 적용 시에는 incident/완료 판정/이 packet의 bridge 변경을 한 번에 묶어 동결하고 host manifest와 bridge를 함께 설치한다. 두 patch 모두 이번에는 적용하지 않았다.

기존 source installer transaction, `Copy-CascadeurPersistentState`, maintenance lease, `ensure_independent_models()`의 private proof 재사용 원리는 재구현하지 않는다. `guarded_runtime`의 전체 bridge fingerprint, exact source·checkpoint 검사와 원 unknown barrier도 완화하지 않는다.

## 1. exact 설치 profile

### 현행 함수·새 인수

현행 `verify-install.ps1`의 script parameter는 `RuntimeRoot`, `RequireSignature`, `SkipCascadeurVersion`이다. 제안 patch는 다음 **새 공개 인수와 JSON 결과 필드 변경**을 포함하므로 구현 적용 전 승인 대상이다.

```powershell
[ValidateSet('catalog-2026.1', 'independent-2026.2')]
[string] $InstallationProfile = 'catalog-2026.1'
```

| 선택값 | 요구하는 ProductVersion | 뜻 |
|---|---|---|
| `catalog-2026.1` (기본값) | `2026.1.3.0.15619` | 기존 verifier의 기본 exact 조건을 유지한다. |
| `independent-2026.2` | `2026.2.3.0.16863` | 이미 코드에 존재하는 finite native adapter용 설치를 구분한다. operation·rig 지원을 인증하지 않는다. |

prefix·major/minor 비교나 임의 버전 인수를 추가하지 않는다. 두 문자열 이외의 build는 선택한 exact profile과 일치하지 않는다. `SkipCascadeurVersion`의 기존 진단 동작은 유지하며, 이를 지정한 결과는 여전히 버전 검사 생략이다.

출력은 다음 세 사실을 나눈다.

| 필드 | 값과 의미 |
|---|---|
| `CatalogBaseline` | 항상 `2026.1.3.0.15619`. catalog/inventory를 바꾸지 않는다. |
| `InstallationProfile`, `CascadeurVersionRequired`, `CascadeurVersion` | 선택한 profile, 그 exact 요구 build, 실제 executable ProductVersion. |
| `CascadeurCatalogVersionExact` | 실제 build와 catalog baseline의 일치 여부. |
| `CascadeurVersionExact` | 실제 build와 선택한 설치 profile의 일치 여부. 기본 profile에서는 기존 의미와 같다. |
| `InstallationVerificationScope` | `disk_registration_stdio_only`. |
| `NativeQualification.Status` | `not_observed_by_installer`. epoch/fingerprint/qualified operations는 `null`로 둔다. 빈 operation 목록을 실제 관측한 것처럼 쓰지 않는다. |

verifier는 실제 앱을 새로 실행하거나 qualifier를 호출하지 않는다. 기존 smoke는 disposable state에서 실행되므로 실행 중 native process의 qualification 증거가 아니다. hook/installer 인수는 변경하지 않는다.

### host gate는 이미 exact 2026.2 경로가 있다

추가로 확인한 현재 호출 경로는 아래와 같다. 이 packet은 이 파일들을 수정하지 않는다.

1. [`ChangeFlowMixin.prepare_change`와 `commit_change`](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/change_flow.py)는 `_supported_build_error`를 호출한다.
2. [`CascadeurService._supported_build_error`](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/service.py#L413-L425)는 catalog baseline 외에 **exact `2026.2.3.0.16863`**을 이미 admission한다.
3. 같은 파일의 `_rebuild_features()`는 catalog baseline을 유지하면서 2026.2 native feature를 현재 `guarded_capabilities.operations` 및 제한된 read-only 목록으로 제한한다. `_feature_gate_error()`의 narrow 예외도 effect 없는 읽기 또는 현재 등록 operation에 한정되고, 다른 feature/license/dependency/binding 조건은 남는다.
4. [`BridgeClient.execute`](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/bridge_client.py)는 effectful 요청에 host expected fingerprint와 runtime loaded fingerprint 일치를 별도로 요구한다. source/operation의 private native proof는 bridge에서 다시 검사한다.
5. [`product_catalog.py`](https://github.com/muhwagwa0112/cascadeur-complete/blob/fc0e98eaa30e819f98880a32dce30c6767a5cc64/src/cascadeur_complete/product_catalog.py)는 계속 `2026.1.3.0.15619`와 그 inventory를 pin한다.

따라서 verifier profile을 고친 뒤 host가 2026.1만 허용해서 계속 막힌다는 이유로 catalog 전체를 bump할 필요가 없다. 이 정확한 예외 경로는 유지한다. profile 일치만으로 unknown barrier, 미등록 operation, 일반 rig 제한이 해결되는 것은 아니다.

### 명령 구분

**현재 HEAD에 이미 존재하는 명령:**

```powershell
& .\scripts\install.ps1
& .\scripts\verify-install.ps1 -RuntimeRoot $TargetRuntime -SkipCascadeurVersion
```

두 번째는 현재 2026.1 고정 버전 조건을 생략하는 진단용이며 설치/등록이 누락되면 실패한다. `$TargetRuntime`은 installer의 canonical Local AppData 아래 `CascadeurMCP\cascadeur-complete`로 계산해야 한다. `install.ps1`의 유일한 현재 선택 인수는 `-SkipCodexRegistration`이다. installer에 `-SkipCascadeurVersion`을 넘기는 명령은 없다.

**01의 적용 승인을 받고 구현한 뒤에만 존재할 제안 명령:**

```powershell
& .\scripts\verify-install.ps1 -RuntimeRoot $TargetRuntime -InstallationProfile independent-2026.2
```

새 인수는 source installer에 추가하지 않는다. 기존 Start Menu 호출 등 선택 인수를 주지 않는 호출자는 기본 2026.1 profile을 유지한다. 이 packet은 설치 UI나 frozen build를 변경하지 않는다.

## 2. finite qualifier의 자동 제거를 보존으로 바꾸기

### 정확한 수정 함수

| 현행 함수 | 현재 남은 제거 경로 | 제안 본문 |
|---|---|---|
| `native_adapters.qualify_disposable(*, include_scene_adapter=False)` | finally에서 successor/disposable의 `remove_application_scene` | 새 private `RetainedProbe('native_adapter')`로 원 active empty tab과 inventory를 기록하고, 두 새 탭과 기존 다섯 `.casc`를 보존한다. 등록을 retention 관측 뒤로 옮긴다. |
| `native_interpolation_qualification.qualify_independent_models()` | finally의 `release_disposable_scene(scene)` | `create_disposable_scene(retain_on_failure=True)`와 retained 종료를 사용한다. 한 fixture의 정상 경로에서만 전후 파일을 새 경로로 저장한다. |
| `native_independent_position.qualify_independent_position_writer()` | finally의 `release_disposable_scene(scene)` | 같은 방식으로 한 fixture를 보존한다. writer private proof 및 `_PROBE`/thread-local 복원 조건을 유지한다. |
| `native_interpolation_qualification.ensure_independent_models()` | 기존 private proof 재사용 | 기존 동작을 유지한다. 재사용 결과에 원 `retention` 위치만 전달한다. |

`native_fixture.release_disposable_scene()` 자체는 바꾸지 않는다. 다른 소비자까지 일괄 변경하는 refactor가 아니다. qualifier가 직접 사용하는 위 호출부만 바꾼다. 새 helper는 표준 라이브러리와 이미 존재하는 native viewer/save helper를 사용하며 새 dependency를 추가하지 않는다.

### 이미 보존하는 함수와 아직 제거하는 별도 경로

- **이미 보존:** `native_independent_scene.qualify_independent_scene_adapter()` 본문은 fixture/bootstrap source/working 탭을 retained 목록으로 남긴다. `qualify_checkpoint_restore_adapter._observe()`는 restored target을 보존하며 후속 source-idle에서 원/target projection과 inventory를 확인하고 등록한다. 이 두 본문은 이번 patch에서 다시 바꾸지 않는다.
- **이름이 비슷하지만 별도 경로:** `native_scene_adapter.qualify_scene_adapter()`는 HEAD의 finally에서 `for scene in reversed(created): manager.remove_application_scene(scene)`을 여전히 실행한다. `qualify_disposable(include_scene_adapter=True)`가 이 broad 경로를 호출할 수 있다. 이번 finite 실행 계획에서는 이 flag와 broad complete-scene 명령을 사용하지 않으며 그 generic 경로를 해결했다고 주장하지 않는다. 기존 signature를 삭제하거나 일반 scene/character 지원으로 범위를 늘리지 않는다.
- independent-scene wrapper는 본문에 들어가기 전에 `ensure_independent_models()`를 호출한다. 첫 model probe의 제거가 남아 있었으므로 이번 patch가 이 앞부분만 보완한다.

### 보존 규칙

`RetainedProbe(kind)`는 fixture를 만들기 전에 현재 탭이 실제 empty tab인지 확인하고 원 active tab의 instance/path/projection, 원 탭 inventory를 기록한다. 다른 populated 탭의 전체 data를 스캔하지 않는다. **basic native qualifier도 이제 empty current tab을 요구한다.** 이 변경은 숨긴 호환성 조건이 아니라 명시적 제안이다.

새로 만든 탭은 live inventory에 실제 존재함을 확인한 뒤 역할과 runtime-issued scene instance/lineage ID로 식별한다. original inventory에 있던 탭은 새 소유 fixture로 등록할 수 없다. 실패한 native load가 만든 미식별 탭은 `ownership='unverified'`로 남기며 지우거나 소유를 주장하지 않는다.

정상 경로의 model/writer는 `fixture-before.casc`, `fixture-after.casc`를 각각 새 파일로 저장하고 save 전후 full projection 동일성을 검사한다. 기존 `_save_observed`의 completion/manifest 계약을 사용한다. 파일 경로는 승인된 해당 snapshots child에만 속하며 이름 재사용·덮어쓰기·삭제를 하지 않는다. basic native 경로는 이미 생성하는 source, backup/working, successor backup/working의 다섯 파일 manifest를 기록하고 불필요한 추가 save를 하지 않는다.

finally에서는 live inventory로 원 wrapper가 여전히 존재하는지 확인한 뒤 원 empty tab을 다시 활성화하고 그 path/projection과 원 inventory를 검사한다. 남은 생성 탭을 닫거나 제거하지 않는다. 이 관측이 실패하면 새로운 qualification proof를 게시하지 않는다. 다른 user tab의 모든 채널을 검사한 결과로 일반화하지 않는다.

`retention.json`은 새 경로에 `xb`로 쓰고 flush/fsync한다. `retained_tabs`, 역할/ID/경로, 성공적으로 저장된 파일 manifest, 시도한 파일명, original 관측 결과를 포함한다. 이 파일은 진단 자료이며 외부에서 읽어 adapter proof를 재등록하거나 source를 발급하는 입력이 아니다.

### 실패 시 동작

| 실패 시점 | 보존·반환 |
|---|---|
| admission/empty current tab/부족한 사전 예산 | fixture 생성 전에 거절한다. 새 root나 다른 UUID workspace로 재시도하지 않는다. |
| fixture 생성·쓰기·save 중 예외 | 기존 파일과 모든 남은 탭을 유지한다. finally는 새로운 save/close/delete를 호출하지 않는다. 원 active tab 복귀와 inventory/projection 관측만 시도한다. 원 예외를 유지하고 retention 경로·부가 관측 오류를 note로 붙인다. |
| 일부 save 파일만 만들어진 경우 | 성공 manifest가 없는 파일은 완료된 checkpoint라고 부르지 않는다. 부분 파일/실패 탭을 그대로 남긴다. |
| 원 tab/패키지 context를 재확인하지 못한 경우 | 사라진 wrapper를 dereference하지 않는다. original 복귀/보존을 확인했다고 주장하지 않고 retention을 `unverified`로 남긴다. |
| 정상 native probe 후 retention record 저장/원본 관측 실패 | 새 model/writer proof·adapter 등록 단계로 진행하지 않는다. |
| adapter 등록 자체 실패 | 완료 결과를 cache하지 않는다. 부분 등록이 생겼다면 해당 실제 상태를 별도 확인해야 한다. helper가 이를 성공 관측으로 바꾸거나 재probe하지 않는다. |

원본 사용자 파일은 save 대상이 아니다. 실패 시 원본을 덮어쓰거나 native rollback을 자동 수행하지 않는다. Native process 자체가 crash하면 Python finally가 완료된다고 보장할 수 없으며, 그 경우 이미 작성된 파일과 원 기록만 근거로 남는다.

### 반복 호출과 자원 범위

새 helper의 `_ATTEMPTS`는 한 process의 세 내부 qualifier kind만 보관한다. 성공 후 반복 호출은 같은 process에서 반환했던 결과를 조회하고 새 fixture를 만들지 않는다. 실패/미완료 기록이 있으면 해당 관측 경로를 알려주며 자동 재실행하지 않는다. disk의 결과 파일을 읽어 성공 cache를 재구성하지 않는다.

성공 cache도 기존 proof 검사에 종속된다. finite model은 기존 `qualification()`을, writer는 기존 `register_independent_position_writer()`를 거친다. basic native cache는 현재 세 operation의 등록 adapter가 동일한 private `TransformAdapter` instance이고 원 evidence SHA와 같을 때만, 기존 `guards.register_adapter()`로 그 same instance의 loaded bytes/build/persisted evidence를 다시 검사한다. 다른 더 넓은 qualified adapter가 이미 등록돼 있으면 과거 basic 결과로 덮어쓰거나 native probe를 반복하지 않고 `NATIVE_QUALIFICATION_REPLACED`를 보고한다.

| 이 patch가 바꾸는 kind | 한 process에서 요청하는 최대 새 탭 | 정상 경로의 최대 `.casc` 파일 | 기존 실험 범위 |
|---|---:|---:|---|
| native adapter | 2 | 5 (기존 파일) | 기존 key-zero transform/bootstrap/checkpoint 관측 |
| finite models | 1 | 2 | 기존 5-frame fixture와 기존 40 trials 유지 |
| position writer | 1 | 2 | 기존 한 fixture와 기존 16 trials 유지 |

이 숫자는 code-owned 호출/보관 상한이다. native 내부가 예상 밖 탭을 만들거나 메모리를 과다 할당하는 것을 선제 차단하는 OS 한도는 아니다. helper가 예산을 다 채울 수 없는 grant를 받으면 첫 native 생성 전에 거절한다. grant가 더 크더라도 내부 상한은 커지지 않는다. 일반 independent-scene/restore/insertion/export의 별도 fixture 수까지 이 표에 포함한 전체 앱 한도로 주장하지 않는다.

### 사용자 cleanup

자동 cleanup 명령이나 새로운 MCP 삭제 도구를 추가하지 않는다. 반환된 retained tab ID·경로와 `retention.json`을 기준으로 사용자가 해당 진단 탭을 선택해 확인하고, 필요한 경우 **별도 새 경로에** 직접 저장한 다음 UI로 닫는다. 실패 탭의 미저장 내용을 helper가 추가 save로 확정하지 않는다. 파일 삭제는 이 packet의 동작이 아니다.

사용자가 탭을 닫아도 private attempt 기록을 지워 같은 실패를 자동 재시도하지 않는다. 기존 proof가 여전히 유효한 성공 경로는 새 fixture 없이 사용할 수 있다. 실패 경로는 원인을 바꾸거나 입력·코드를 수정한 뒤에만 새 시도를 계획한다. `RetainedProbe`는 fixture-authoring helper의 `_OWNED` 참조만 정리하고 native 탭·파일·guarded source identity를 지우지 않는다.

## 3. unknown admission과의 연결 계약

02는 다음 제안 함수를 호출한다. 이는 현행 HEAD의 API라고 제시하지 않으며 incident packet의 선행 구현 계약이다.

```python
incident_admission.assert_setup_admission(operation_name, setup_invocation_ref)
```

private dispatcher가 원 authenticated immutable setup request의 sidecar를 `claim_setup_invocation(ref)`로 **한 번만** 소비하고 `_LOCAL.setup_invocation_ref/context`를 설치한다. constructor와 정상 save의 assert는 이미 claim된 current helper step·thread·epoch·resource revision을 재검사할 뿐 token을 재소비하지 않는다. dispatcher는 `try/finally`로 이전 context를 복원/제거한다. 다른 thread, 반환 뒤 callback, 임의 dict/ref, 직접 메뉴의 `None`은 native 생성 전에 거절한다.

| 내부 helper | code-owned admission operation |
|---|---|
| `native_adapter` | `setup.qualify_native_adapter` |
| `finite_models` | `setup.qualify_independent_models` |
| `position_writer` | `setup.qualify_independent_position_writer` |

반환값은 incident module이 검증한 내부 `VerifiedSetupStepGrant` mapping으로, `workspace_path`, `maximum_new_tabs`, `maximum_casc_files`를 갖는다. wire에 같은 모양 dict가 있다는 이유로 받지 않는다. constructor는 그 exact snapshots child만 `mkdir()`(기존 경로 거절)한다. 원 계획 경로 충돌 시 UUID를 다시 골라 새 workspace를 발급하지 않는다. 전체 프로그램에 필요한 고정 budget보다 grant가 작으면 native 호출 전에 거절하고, grant가 크면 이 helper의 고정 작은 상한을 유지한다.

independent motion 명령은 model→writer, independent scene 명령은 model→기존 scene 본문을 호출한다. 이 순서와 각 helper budget/resource closure는 원 setup request에 미리 선언돼야 한다. 이미 검증된 current-epoch model은 읽기만 하고 native probe step을 건너뛴다. 한 helper가 unknown/pending/실패하면 다음 helper를 실행하지 않는다. 이 sidecar를 다른 일반 operation의 권한으로 재사용하지 않는다. generic `include_scene_adapter=True`는 finite 승인 sequence에 넣지 않는다.

incident admission 및 dispatcher의 실제 구현/등록은 다른 packet의 책임이며 이 파일들을 적용했다고 자동으로 생기지 않는다. qualifier 내부의 기존 direct fixture creation/writes도 원 claimed scope와 budgets 아래서만 실행돼야 한다. global/isolated 원 unknown, 원 key·receipt·소비 기록은 각각 보존한다. 앱 종료나 새 epoch가 이를 성공/실패로 바꾸지 않는다.

## 4. 설치와 실행 의존 순서

1. 새 profile 인수/JSON 출력과 setup admission의 공개 변경을 승인받고, incident·완료 판정·필요 lifecycle 변경을 같은 bridge bundle로 확정한다.
2. 기존 global/isolated auth domain과 physical resource incident를 원 기록에서 처리한다. 새 root를 만들어 barrier를 피하지 않는다.
3. 이미 존재하는 installer transaction/lease/원 상태 이관을 그대로 사용한다. 실제 설치 대상은 canonical Local AppData의 전역 runtime/bridge/event이다.
4. 현재 작업·retained 파일을 보존하고 Cascadeur 및 installed MCP host를 종료한 뒤 host+bridge를 한 번 설치한다. 설치 중 앱을 hot reload하지 않는다.
5. 정확한 profile로 디스크/등록/stdio 결과를 확인하고 앱을 한 번 새로 실행한다. 실제 loaded fingerprint와 host manifest를 맞춘다.
6. 승인된 setup dispatcher로 필요한 operation의 qualifier만 실행한다. 같은 process의 proof 재사용을 활용하고, generic broad qualifier나 전체 suite를 추가하지 않는다.

## 5. 최소 확인 명세 — 실행하지 않음

이번 agent는 patch artifact를 생성했을 뿐 AST, PowerShell parse, apply-check 또는 테스트를 실행하지 않았다. root가 수행하는 artifact L1 결과는 최종 통합 보고에서 별도로 기록한다. 준비 환경에는 embedded native SDK와 PowerShell이 없으므로 이 packet만으로 실앱/PowerShell 실행을 검증했다고 말할 수 없다.

구현 단계에서 필요한 확인은 다음에 한정한다.

- **L1:** 변경된 Python 네 파일의 syntax/AST와 PowerShell 파일의 Parser 확인. installer/build 전체를 실행하는 검사는 아니다.
- **L2 제안:** 기존 pytest 환경에서 retention helper와 해당 호출부를 SDK-shaped double로 확인하는 작은 파일 하나. `success/error`에서 native remove/close가 호출되지 않고 원 탭·파일이 유지되는 사례, 동일 attempt의 중복 생성/identity 변경 거절, retention 실패가 proof 게시를 막는 사례만 둔다. crash 안정성을 이 double로 증명하지 않는다.
- **version mapping:** 기본값 exact 2026.1, 명시 선택 exact 2026.2.3.0.16863, 다른 2026.2 build의 mismatch, skip 결과의 표시를 확인한다. 실제 native operations는 profile 출력에서 항상 미관측이어야 한다. host catalog/feature support 확대 검사는 기존 narrow gate를 수정하지 않는 정적 확인으로 충분하다.

제안 test 파일을 실제로 추가한 뒤에만 사용할 향후 명령 예시는 `pytest tests/test_native_probe_retention.py -q`이다. 이 파일은 현재 HEAD에 있다고 주장하지 않으며 이번에는 작성하거나 실행하지 않았다. 전체 suite/CI/frozen build/benchmark와 반복 앱 종료 검사는 이 packet의 gate가 아니다.

## 설계상 승인·통합 사항과 실앱 미검증

**적용 전 승인/통합이 필요한 사항:** `InstallationProfile`과 추가 verifier JSON 필드, basic qualifier의 empty-tab 조건, private setup admission/dispatcher의 선행 구현, 독립 command의 사전 helper sequence·정확한 workspace/fixture budget binding. 이들 의존성을 없는 것으로 간주하고 02를 단독 실행하지 않는다.

**설계로 확정하지 못한 native 사실:** `Qt6Core.dll` access violation/bad allocation의 실제 원인, 추가된 finite fixture save의 실제 SDK 동작, retained 탭을 사용자 UI에서 닫을 때의 안정성. 자동 cleanup이 crash 원인이라고 단정하지 않는다. Python이 정한 fixture 수는 native 메모리의 하드 한도가 아니다.

**이번에 미실행:** 실제 설치·등록, 새 프로세스 qualification, unknown retirement/reconciliation, native save/operation, PowerShell 실행, unit tests, 전체 suite/build/CI. 이 제안 patch를 적용 가능한 텍스트로 준비한 것과 실제 앱 성공은 별도다.
