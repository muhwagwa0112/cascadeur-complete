"""Narrow Windows reproductions: no installer, SDK, app or termination calls."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from unittest.mock import patch

import pytest

from cascadeur_complete import incident_store as store
from cascadeur_complete import producer_observation as producer


pytestmark = pytest.mark.skipif(os.name != "nt", reason="actual Windows handle identities required")


def test_prospective_process_records_preserve_actual_terminal_bytes(tmp_path):
    root = tmp_path / "runtime"
    state = root / "state"
    state.mkdir(parents=True)
    secret = os.urandom(32)
    (state / "bridge.key").write_bytes(secret)
    request = {"request_id": str(uuid.uuid4()), "created_at": time.time(), "expires_at": time.time()+120,
        "operations": [{"name": "fixture.effect", "arguments": {}}], "execution_context": {},
        "session_id": "test-session", "host_instance_id": str(uuid.uuid4()),
        "runtime_epoch": str(uuid.uuid4()), "adapter_fingerprint": "a"*64}
    request["mac"] = hmac.new(secret, store.canonical(request), hashlib.sha256).hexdigest()
    outbox = state / "request_records" / request["request_id"]
    outbox.mkdir(parents=True)
    raw_request = store.canonical(request)
    (outbox / "request.json").write_bytes(raw_request)
    assert producer.record_native_claim_if_prospective(root, request) is None
    assert not (state / "producer-observations").exists()
    host = producer.record_host_dispatch(root, request)
    assert host["host_dispatcher"]["pid"] == os.getpid()
    assert len(host["host_dispatcher"]["image"]["file_id"]) == 32
    native_runtime = {"runtime_epoch": request["runtime_epoch"], "loaded_fingerprint": request["adapter_fingerprint"]}
    # SDK runtime attestation is outside this reproduction. Process identity is
    # nevertheless obtained by the real query-only Win32 implementation.
    with patch.object(producer, "_native_runtime", return_value=native_runtime):
        claim = producer.record_native_claim(root, request)
        assert producer.record_native_claim(root, request) == claim
        assert producer.assert_native_first_effect(root, request)["native_process"] == claim["native_process"]
        producer._CLAIMS.clear()
        with pytest.raises(producer.ObservationUnavailable, match="PRIVATE_PROSPECTIVE"):
            producer.assert_native_first_effect(root, request)
        with pytest.raises(producer.ObservationUnavailable, match="RETROSPECTIVE_OR_REPLAYED"):
            producer.record_native_claim(root, request)
    result = {"ok": False, "outcome": "outcome_unknown"}
    event = {"seq": 1, "phase": "terminal", "outcome": "outcome_unknown", "request_id": request["request_id"],
        "request_digest": producer._digest(request), "operation_digest": producer._digest(request["operations"]),
        "session_id": request["session_id"], "host_instance_id": request["host_instance_id"],
        "runtime_epoch": request["runtime_epoch"], "terminal_result": result, "result_digest": producer._digest(result)}
    event["mac"] = hmac.new(secret, store.canonical(event), hashlib.sha256).hexdigest()
    # Deliberately noncanonical whitespace verifies that raw bytes are retained.
    raw_event = json.dumps(event, indent=2).encode()
    (outbox / "runtime_events").mkdir()
    (outbox / "runtime_events" / "0001-terminal.json").write_bytes(raw_event)
    index = producer.archive_terminal(root, request["request_id"])
    assert index == producer.archive_terminal(root, request["request_id"])
    observed = producer.read_producer_observation(root, request["request_id"])
    assert observed["closure_authority"] == "none"
    assert index["terminal_bytes_sha256"] == hashlib.sha256(raw_event).hexdigest()
    assert (outbox / "request.json").read_bytes() == raw_request
    assert (outbox / "runtime_events" / "0001-terminal.json").read_bytes() == raw_event
    assert not (state / "incidents" / "producer-closures").exists()
    # A fresh process/old outbox cannot manufacture a host dispatch retrospectively.
    old = dict(request, request_id=str(uuid.uuid4()), created_at=producer._LOADED_AT-1)
    old.pop("mac")
    old["mac"] = hmac.new(secret, store.canonical(old), hashlib.sha256).hexdigest()
    old_outbox = state / "request_records" / old["request_id"]
    old_outbox.mkdir()
    (old_outbox / "request.json").write_bytes(store.canonical(old))
    with pytest.raises(producer.ObservationUnavailable, match="RETROSPECTIVE_HOST"):
        producer.record_host_dispatch(root, old)
    assert not (state / "producer-observations" / old["request_id"]).exists()


def test_in_place_code_rollback_retains_real_store_identity(tmp_path):
    root = tmp_path / "runtime"
    for name in ("src", "state/incidents", "snapshots", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    (root / "state/bridge.key").write_bytes(secret)
    marker = store.seal({"schema_version": 1, "auth_domain_id": store.policy.auth_domain_id(secret),
        "store_instance_id": str(uuid.uuid4()), "physical_root": store.physical_identity(root)}, secret, store.STORE_PURPOSE)
    (root / "state/incidents/store-v1.json").write_bytes(store.canonical(marker))
    retained = {"state/install-ownership.json": b'{"installed":true}',
        "state/original-unknown.json": b'{"outcome":"outcome_unknown"}',
        "snapshots/retained.casc": b"retained fixture", "logs/retained.log": b"retained log",
        "policy.json": b'{"retained":true}'}
    for name, raw in retained.items():
        (root / name).write_bytes(raw)
    (root / "src/module.py").write_text("original_code = True\n")
    before = store.IncidentStore(root).identity
    check = tmp_path / "check.ps1"
    check.write_text(r'''param([string]$Workspace,[string]$Helpers)
$ErrorActionPreference = 'Stop'
. $Helpers
$workspaceFull = [IO.Path]::GetFullPath($Workspace)
$runtime = Join-Path $workspaceFull 'runtime'
$backup = Join-Path $workspaceFull 'backup'
if (-not $runtime.StartsWith($workspaceFull + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture escaped' }
New-Item -ItemType Directory -Path $backup | Out-Null
$saved = Backup-CascadeurRuntimeCode $runtime $backup
$saved = $saved | ConvertTo-Json -Depth 12 | ConvertFrom-Json
Clear-CascadeurRuntimeCode $runtime
New-Item -ItemType Directory -Path (Join-Path $runtime 'src') | Out-Null
Set-Content -LiteralPath (Join-Path $runtime 'src/module.py') -Value 'replacement'
Set-Content -LiteralPath (Join-Path $runtime 'state/install-ownership.json') -Value '{"installed":"new"}'
Set-Content -LiteralPath (Join-Path $runtime 'state/new-evidence.bin') -Value 'keep new evidence'
Restore-CascadeurRuntimeCode $saved $backup
Assert-CascadeurRuntimeIdentity $saved
# A corrupt rollback preimage must reject BEFORE removing active code.
Set-Content -LiteralPath (Join-Path $backup 'runtime-code/src/module.py') -Value 'corrupt backup'
$rejected = $false
try { Restore-CascadeurRuntimeCode $saved $backup } catch {
  if ($_.Exception.Message -notmatch 'preimage bytes or file set differ') { throw }
  $rejected = $true
}
if (-not $rejected) { throw 'Corrupt code backup accepted' }
'in_place_identity_and_rollback_observed'
''', encoding="utf-8")
    helpers = Path(__file__).resolve().parents[1] / "packaging/upgrade-state.ps1"
    checked = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(check),
        "-Workspace", str(tmp_path), "-Helpers", str(helpers)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "in_place_identity_and_rollback_observed" in checked.stdout
    assert store.IncidentStore(root).identity == before
    assert (root / "state/incidents/store-v1.json").read_bytes() == store.canonical(marker)
    for name, raw in retained.items():
        assert (root / name).read_bytes() == raw
    assert (root / "src/module.py").read_text() == "original_code = True\n"
    assert (root / "state/new-evidence.bin").exists()
