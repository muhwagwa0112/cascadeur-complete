# Runtime physical identity를 유지하는 설치 transaction 제안

기준 commit은 `7f1565a0ffad1595b9824cba25443bc581997fb6`이다. 이 디렉터리의
`installer-runtime-identity.patch`와 `proposed_sources/`는 **제품에 적용하지 않은 준비물**이다.
제품 파일, 설치, Cascadeur/MCP 실행, 테스트, 빌드, CI는 이 작업에서 수행하지 않았다.

## 바꾸는 동작

현재 source installer는 runtime 디렉터리 자체를 backup으로 옮기고 새 stage 디렉터리로
대체한다. `IncidentStore`는 기존 signed marker의 `physical_root`와 실제 디렉터리의
`device/file_id/path`를 비교하므로, 내용이 같은 `state`를 복사해도 이 경계가 유지되지 않는다.
이것은 **다음 설치에서 발생할 수 있는 코드상 결함**이다. 이번 Windows 환경에서 실제로
이 실패가 발생했다거나, 그 상태를 직접 관측했다는 뜻은 아니다.

제안은 기존 runtime 디렉터리와 `state`, `snapshots`, `logs`, 기존 `policy.json`을
제자리에 두고 코드만 교체한다. signed marker, registry, incident journal, bridge key,
receipt, unknown outcome을 복사·삭제·재발급하거나 재분류하지 않는다.

| 변경 파일 | 직접 바꾸는 지점 |
|---|---|
| `scripts/install.ps1` | lease를 잡은 뒤 code preimage를 확보하고, 기존 root 아래 code child만 교체한다. 실패 시 같은 root에 code와 installer metadata를 복구한다. |
| `packaging/upgrade-state.ps1` | source/frozen에 공통인 `Get/Backup/Clear/Restore-CascadeurRuntimeCode`를 추가한다. 기존 maintenance lease, busy 검사, legacy persistent-copy 함수는 유지한다. |
| `packaging/backup-existing.ps1` | frozen pre-upgrade backup에서 runtime 전체 복사를 code backup + installer metadata preimage로 바꾼다. bridge/events 및 settings/Codex backup은 유지한다. |
| `packaging/restore-existing.ps1` | frozen 실패 복구가 runtime root를 삭제하지 않도록 공통 restore를 호출한다. bridge/events와 settings/Codex 복구는 기존 경로를 사용한다. |
| `packaging/install-hooks.ps1` | 실패 전 없었던 settings/Codex config는 실패 복구 시 제거한다. 기존 파일은 backup으로 복구하며, Codex에 손대기 전 실패한 경우 그 config를 건드리지 않는다. transaction_manifest가 없는 기존 ownership에는 `Add-Member`로 필드를 추가한다. |

### 교체하는 code child의 범위

공통 helper의 목록은 현재 source installer의 복사 목록과 `build-release.ps1`의 frozen
payload 생성 경로에 맞춘 **13개 이름**이다.

```text
.venv  src  inventory  support  _internal
pyproject.toml  uv.lock  README.md  LICENSE  THIRD_PARTY_NOTICES.md
policy.default.json  bridge-package.json  cascadeur-complete.exe
```

새 payload root 항목을 추가하는 변경에는 이 관리 목록의 갱신도 필요하다. 이 목록 밖의
사용자 추가 root 파일과 Inno uninstall metadata는 code transaction이 삭제하지 않는다.
source의 stage 복사 목록, frozen의 `--onedir` 출력 및 app-stage 복사 목록이 현재 근거이며,
미래의 임의 package layout까지 지원한다고 가정하지 않는다.

## Transaction과 rollback

외부 PowerShell 인수는 추가하지 않는다. **내부 transaction manifest schema 2가 제안된
호환성 변경**이며, 제품에 적용하기 전 승인 대상이다. 기존 ownership 문서의 `schema = 2`와는
별개의 `transaction_manifest.schema`이다.

```text
schema: 2
runtime_mode: code-in-place
backup_root: <이번 transaction backup>
targets.runtime:
  path, existed, code_entries
  state_existed, state_acl_sddl, ownership_existed, policy_existed
targets.bridge / targets.events:
  path, existed
```

code preimage는 `backup_root/runtime-code/<code child>`에 저장한다.
`state/install-ownership.json`의 preimage만 `runtime-install-ownership.json`으로 저장한다.
이 파일과 `state`의 DACL은 install hook이 실제로 바꾸므로 실패 시 원래 값으로 돌린다.
`state`의 나머지 내용과 `snapshots`, `logs`, 기존 `policy.json`은 backup 대상으로도 삼지 않는다.

source는 모든 code backup이 끝난 뒤 activation을 시작한다. 기존 code child를 지우고
stage의 code child를 같은 root로 옮긴 뒤, `.venv`를 최종 경로에서 다시 생성한다.
stage smoke와 activated smoke의 disposable `CASCADEUR_MCP_ROOT`는 기존 방식 그대로다.
smoke 통과는 persistent identity, incident 해결 또는 native qualification의 증명이 아니다.

실패 시 bridge/events 복구와 runtime code 복구를 각각 시도한다. 복구 자체가 실패하면
원래 설치 오류와 rollback 오류를 함께 보고하고 backup을 남긴다. 기존 root 또는 원래 있던
state 디렉터리가 사라진 경우에는 이를 새로 만들어 기존 identity인 것처럼 처리하지 않는다.
code preimage는 성공적인 복구 후에도 보존되므로 실패 원인을 확인할 수 있다.

초기 설치에서는 root를 한 번 만든다. 실패 복구 시 새 ownership 기록을 제거하고, 새로 만든
state/root는 **비어 있을 때만** 제거한다. 새 evidence나 사용자 데이터가 생겼다면 남긴다.
원래 policy가 없었다면 현재 policy가 이번 설치의 default와 여전히 같을 때만 제거한다.
기존 policy 또는 설치 도중 달라진 policy는 유지한다.

schema 1의 whole-root backup은 새 `restore-existing.ps1`로 자동 복구하지 않는다.
그 파일의 복사로 signed identity를 다시 만드는 것은 이 제안에 포함되지 않는다. 과거 설치의
ownership에 남아 있는 schema-1 transaction은 다시 쓰지 않는다. 현재
`post-uninstall-restore.ps1`은 그 transaction의 bridge/events만 읽으므로, 새 schema 2에서도
해당 필드는 같은 구조로 유지했다.

## Source와 frozen의 실제 호출 경로

source는 `scripts/install.ps1`이 공통 helper를 dot-source하고 직접 backup/restore를 호출한다.
기존 sibling maintenance lease와 Win32 process busy 검사는 유지한다. 전역 unknown은
이 검사에서 성공으로 바뀌지 않으며, 설치 성공도 incident retirement를 뜻하지 않는다.

frozen은 Inno의 `PrepareToInstall`이 기존 exclusive maintenance handle을 보유한 채
temporary `backup-existing.ps1`을 실행한다. hook 또는 설치 확인이 실패하면 같은 temporary
디렉터리에 추출된 `restore-existing.ps1`과 `upgrade-state.ps1`이 복구한다. 정상 frozen
설치는 원래부터 code child를 갱신했지만, 기존 실패 복구는 runtime 전체를 삭제했다.
이번 patch는 그 실패 복구도 같은 code-only 경로로 연결한다.

`installer/cascadeur-mcp.iss`, `build-release.ps1`, uninstall scripts의 수정은 필요하지 않다.
기존 빌드가 새 `upgrade-state.ps1`/`install-hooks.ps1`을 support에 복사하고, Inno가 새
backup/restore/helper를 temporary 파일로 포함하는 호출 경로를 그대로 사용한다.
나중에 frozen bundle을 만들 때는 수정 전 support를 포함한 stage를 재사용하지 않아야 한다.
현재 frozen의 unmanaged-runtime 거절 조건도 유지한다. 이 제안은 source/frozen 간 모든
uninstall 등록 전환까지 새로 설계하지 않는다.

## 적용 순서와 의존성

1. 기준 HEAD의 5개 파일에 patch 전체를 함께 적용한다. 일부 helper나 schema writer만
   따로 배포하면 안 된다. 이번 산출물은 문서 branch에 준비물을 올리는 범위다.
2. incident/legacy containment 개선과 host-only 진단 순서는 R6 상위 계획을 따른다.
   기존 unknown을 삭제하거나 새 key/marker로 바꾸어 설치를 통과시키는 절차는 없다.
3. bridge와 host의 최종 bundle을 한 번 확정한 뒤, 실제 설치 승인이 있을 때만 설치한다.
   실제 설치 전 앱/host reader가 종료되어야 한다는 기존 조건은 유지된다.
4. 설치 후 current source와 loaded bundle의 일치, registry의 기존 identity, 필요한 setup
   operation의 admission을 구분해 확인한다. 설치 또는 restart만으로 unknown을 해결했다고
   처리하지 않는다. native setup/retirement는 이 patch가 새 권한을 발급하는 작업이 아니다.

기존 source 명령의 인수는 그대로이며, 다음은 **향후 승인된 Windows 실행에서만** 사용할
수 있는 현행 명령 형식이다. 이 작업에서는 실행하지 않았다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -SkipCodexRegistration
```

## 필요한 Windows L2 범위

새 테스트 체계나 제품용 failure flag는 만들지 않는다. 아래는 설치 fixture 또는 외부 호출
경계에서 실패를 주입하는 최소 사례 명세이며, 이번 작업에서는 실행하지 않았다.

| 사례 | 필요한 관측 |
|---|---|
| 기존 signed store의 source 정상 upgrade 1회 | root/state/snapshots/logs의 Windows physical ID 전후 동일, 기존 marker/registry/key/journal/policy bytes 동일, 새 code 및 최종 `.venv` 활성화. 여전히 unresolved인 요청은 그대로 남음. |
| source final-path `uv sync` 실패 1회 | 코드 preimage 복구, 원래 root/persistent ID 유지, bridge/events 원복, 원래 오류 보존. |
| install-hook 실패 1회씩: 기존 파일 있음/없음 | hook의 Codex 등록 호출 경계에서 실패 주입. 기존 ownership·state DACL·settings·Codex config는 원복하고, 처음 만든 config/ownership만 제거. incident 상태는 그대로 유지. |
| 처음 설치의 성공 및 activation 뒤 실패 | 성공은 최종 root의 실행 파일/기본 policy/ownership 생성. 실패는 빈 새 디렉터리만 제거하며 새 evidence가 있다면 보존. |
| frozen의 hook 또는 verify 실패 중 1개 | 기존 Inno rollback 호출이 schema-2 helper를 사용하여 root/persistent ID를 유지하고 code·ownership·settings·Codex를 원복. Inno 자체 rollback과의 상호작용도 이 사례에서 관측. |

이 환경에는 `pwsh`가 없으므로 PowerShell parser, DACL 복구, Windows file ID 보존,
native/frozen installer 동작은 미검증이다. root가 수행할 한 번의 `git apply --check`는
patch 문맥만 확인하며 이 Windows 동작을 검증하지 않는다. 전체 테스트/빌드/CI는 범위 밖이다.

## 기준 소스 근거

- [source 설치의 runtime 전체 교체 및 rollback](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/scripts/install.ps1#L72-L134)
- [signed physical identity 비교](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/src/cascadeur_complete/incident_store.py#L111-L152)
- [공유 lease / busy 검사 / 기존 state copy](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/packaging/upgrade-state.ps1)
- [frozen backup](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/packaging/backup-existing.ps1) · [전체 runtime을 삭제하던 restore](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/packaging/restore-existing.ps1)
- [hook의 ownership·DACL·등록 변경](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/packaging/install-hooks.ps1)
- [Inno의 임시 helper와 실패 복구 호출](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/installer/cascadeur-mcp.iss)
- [frozen payload/support 구성](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/scripts/build-release.ps1#L105-L126)
- [uninstall의 bridge/events 한정 복구](https://github.com/muhwagwa0112/cascadeur-complete/blob/7f1565a0ffad1595b9824cba25443bc581997fb6/packaging/post-uninstall-restore.ps1)
