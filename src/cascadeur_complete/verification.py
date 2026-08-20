from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .atomic_queue import atomic_write_json, read_json


class LiveEvidenceStore:
    """Persist successful adapter postconditions by installed Cascadeur version."""

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema_version": 1, "features": {}}
        try:
            payload = read_json(self.path)
        except (OSError, ValueError):
            return {"schema_version": 1, "features": {}}
        if not isinstance(payload.get("features"), dict):
            payload["features"] = {}
        return payload

    def verified_features(self, version: str) -> set[str]:
        payload = self._load()
        return {
            feature_id
            for feature_id, record in payload["features"].items()
            if isinstance(record, dict) and record.get("version") == version and record.get("ok") is True
        }

    def record(
        self,
        feature_id: str,
        *,
        version: str,
        adapter_id: str,
        operation: str,
        scene_id: str | None,
        evidence: list[dict[str, Any]],
    ) -> None:
        payload = self._load()
        payload["features"][feature_id] = {
            "ok": True,
            "version": version,
            "adapter_id": adapter_id,
            "operation": operation,
            "scene_id": scene_id,
            "evidence": evidence,
            "verified_at": time.time(),
        }
        atomic_write_json(self.path, payload)
