from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer lifecycle")


def _run(script: str, *arguments: str, env: dict[str, str]) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell
    completed = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / script), *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, (completed.stdout or "") + (completed.stderr or "")


def _transaction(
    path: Path,
    backup: Path,
    runtime: Path,
    *,
    runtime_existed: bool,
    external_existed: bool = False,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "backup_root": str(backup),
                "targets": {
                    "runtime": {"path": str(runtime), "existed": runtime_existed},
                    "bridge": {"path": "bridge", "existed": external_existed},
                    "events": {"path": "events", "existed": external_existed},
                },
            }
        ),
        encoding="utf-8",
    )


def test_install_uninstall_reinstall_and_source_migration_use_fresh_transaction(tmp_path: Path):
    local = tmp_path / "local"
    profile = tmp_path / "profile"
    runtime = local / "CascadeurMCP" / "cascadeur-complete"
    backup1 = local / "CascadeurMCP" / "backups" / "first"
    backup2 = local / "CascadeurMCP" / "backups" / "second"
    for path in (runtime, backup1, backup2, profile):
        path.mkdir(parents=True)
    tx1, tx2 = tmp_path / "tx1.json", tmp_path / "tx2.json"
    _transaction(tx1, backup1, runtime, runtime_existed=False, external_existed=True)
    _transaction(tx2, backup2, runtime, runtime_existed=True)
    for name in ("bridge", "events"):
        source = backup1 / name
        source.mkdir()
        (source / "baseline.txt").write_text(f"original-{name}", encoding="utf-8")
    env = os.environ.copy()
    env.update({"LOCALAPPDATA": str(local), "USERPROFILE": str(profile)})
    install = ["-RuntimeRoot", str(runtime), "-SkipCodexRegistration"]

    _run("packaging/install-hooks.ps1", *install, "-TransactionManifest", str(tx1), env=env)
    ownership_path = runtime / "state" / "install-ownership.json"
    first = json.loads(ownership_path.read_text(encoding="utf-8-sig"))
    assert first["installed"] is True
    assert first["transaction_manifest"]["backup_root"] == str(backup1)

    copied_ownership = tmp_path / "ownership-copy.json"
    shutil.copy2(ownership_path, copied_ownership)
    bridge = local / "Nekki Limited" / "Cascadeur" / "user_scripts" / "cascadeur_complete"
    events = local / "Nekki Limited" / "Cascadeur" / "user_scripts" / "cascadeur_complete_events"
    for installed in (bridge, events):
        installed.mkdir(parents=True)
        (installed / "installed.txt").write_text("managed", encoding="utf-8")
    _run(
        "packaging/post-uninstall-restore.ps1",
        "-OwnershipPath",
        str(copied_ownership),
        "-RuntimeOwnershipPath",
        str(ownership_path),
        env=env,
    )
    assert json.loads(ownership_path.read_text(encoding="utf-8-sig"))["installed"] is False
    assert (bridge / "baseline.txt").read_text(encoding="utf-8") == "original-bridge"
    assert (events / "baseline.txt").read_text(encoding="utf-8") == "original-events"
    assert not (bridge / "installed.txt").exists()
    assert not (events / "installed.txt").exists()

    _run("packaging/install-hooks.ps1", *install, "-TransactionManifest", str(tx2), env=env)
    second = json.loads(ownership_path.read_text(encoding="utf-8-sig"))
    assert second["installed"] is True
    assert second["transaction_manifest"]["backup_root"] == str(backup2)

    # Schema-1 source installs had active ownership but no transaction. An Inno
    # upgrade must adopt its fresh transaction without losing the old settings baseline.
    second["installed"] = True
    second["transaction_manifest"] = None
    second["command_preexisting"] = True
    ownership_path.write_text(json.dumps(second), encoding="utf-8")
    _run("packaging/install-hooks.ps1", *install, "-TransactionManifest", str(tx1), env=env)
    migrated = json.loads(ownership_path.read_text(encoding="utf-8-sig"))
    assert migrated["transaction_manifest"]["backup_root"] == str(backup1)
    assert migrated["command_preexisting"] is True
