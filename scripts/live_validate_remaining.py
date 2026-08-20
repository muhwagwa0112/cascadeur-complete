from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from cascadeur_complete.service import CascadeurService

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs" / "live-validation"
SAMPLES = Path(r"C:\Program Files\Cascadeur\samples")
TEST_DATA = Path(r"C:\Program Files\Cascadeur\resources\scripts\test_data\casc")


def emit(label: str, value: Any) -> Any:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    print(label + "=" + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    return payload


def require(label: str, value: Any) -> dict[str, Any]:
    payload = emit(label, value)
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError(label + " failed")
    return payload


def require_quiet(label: str, value: Any) -> dict[str, Any]:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if not isinstance(payload, dict) or not payload.get("ok"):
        emit(label, payload)
        raise RuntimeError(label + " failed")
    return payload


def status(service: CascadeurService) -> dict[str, Any]:
    return require("status", service.refresh_live(timeout=90))["result"]


def protected(
    service: CascadeurService,
    feature_id: str,
    operation: str,
    arguments: dict[str, Any],
    *,
    timeout: float = 180,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prepared = require("prepare_" + feature_id, service.prepare_change(feature_id, operation, arguments, 900))
    committed = require(
        "commit_" + feature_id,
        service.commit_change(prepared["confirmation_token"], timeout),
    )
    return prepared, committed


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scene_lifecycle(service: CascadeurService) -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    destination = OUTPUTS / f"scene-lifecycle-{int(time.time())}.casc"
    state = status(service)
    if not state.get("scene_id"):
        protected(service, "scene_new", "scene.new", {})
        status(service)
    prepared, _ = protected(
        service,
        "scene_save_as",
        "scene.save_as",
        {"path": str(destination)},
    )
    state = status(service)
    require(
        "scene_save",
        service.execute(
            "scene_save",
            "scene.save",
            scene_id=state["scene_id"],
            expected_revision=state["revision"],
            timeout=60,
        ),
    )
    state = status(service)
    tabs = require("scene_list", service.execute("scene_list", "scene.list"))["result"]
    active = next(item for item in tabs if item["active"])
    protected(service, "scene_close", "scene.close", {"tab_id": active["tab_id"]})
    emit(
        "scene_lifecycle_evidence",
        {
            "output": str(destination),
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
            "save_as_snapshot": prepared.get("snapshot_id"),
        },
    )


def object_lifecycle(service: CascadeurService) -> None:
    sample = SAMPLES / "Cube.casc"
    source_hash = sha256(sample)
    open_prepared, _ = protected(
        service,
        "scene_open",
        "scene.open",
        {"path": str(sample)},
        timeout=180,
    )
    create_snapshot = None
    backup_hashes: list[tuple[str, str]] = []
    try:
        require_quiet("status", service.refresh_live(timeout=90))
        hierarchy = require_quiet(
            "object_hierarchy",
            service.execute("object_hierarchy", "object.hierarchy", timeout=90),
        )["result"]
        parent_id = next(item["id"] for item in hierarchy["items"] if item["name"] == "pCube1")
        create_prepared, created = protected(
            service,
            "object_create",
            "object.create",
            {"name": "CascadeurCompleteValidationCube", "position": [7.0, 0.0, 0.0], "size": 1.0},
        )
        create_snapshot = create_prepared["snapshot_id"]
        for prepared in (open_prepared, create_prepared):
            if prepared.get("backup_path"):
                backup = Path(prepared["backup_path"])
                backup_hashes.append((str(backup), sha256(backup)))
        child_id = created["result"]["id"]
        created_ids = [child_id]
        parent_prepared, _ = protected(
            service,
            "object_parent",
            "object.parent",
            {"ids": [child_id], "parent_id": parent_id},
        )
        unparent_prepared, _ = protected(
            service,
            "object_unparent",
            "object.unparent",
            {"ids": [child_id]},
        )
        delete_gate = service.prepare_change("object_delete", "object.delete", {"ids": created_ids}, 900)
        emit("object_delete_gate", delete_gate)
        if delete_gate.get("ok") or delete_gate.get("error_code") != "UI_LOCKED":
            raise RuntimeError("object_delete did not return its verified UI-only gate")
        for prepared in (parent_prepared, unparent_prepared):
            backup = Path(prepared["backup_path"])
            backup_hashes.append((str(backup), sha256(backup)))
        require("rollback_create", service.rollback(create_snapshot))
        require("rollback_scene_open", service.rollback(open_prepared["snapshot_id"]))
        if sha256(sample) != source_hash:
            raise RuntimeError("installed Cube.casc changed during validation")
        changed_backups = [path for path, digest in backup_hashes if sha256(Path(path)) != digest]
        if changed_backups:
            raise RuntimeError("immutable backups changed: " + ", ".join(changed_backups))
        emit(
            "object_lifecycle_evidence",
            {
                "sample": str(sample),
                "source_sha256": source_hash,
                "parent_id": parent_id,
                "created_ids": created_ids,
                "delete_gate": delete_gate.get("error_message"),
                "snapshots_verified": len(backup_hashes),
            },
        )
    except Exception:
        rollback_id = open_prepared.get("snapshot_id")
        if rollback_id:
            emit("emergency_rollback", service.rollback(rollback_id))
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("scene", "objects"))
    args = parser.parse_args()
    service = CascadeurService()
    if args.mode == "scene":
        scene_lifecycle(service)
    elif args.mode == "objects":
        object_lifecycle(service)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"LIVE_VALIDATION_FAILED={type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
