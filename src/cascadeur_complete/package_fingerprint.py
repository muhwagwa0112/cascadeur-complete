"""Bind a host package to bridge bytes shipped with that same package."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def bridge_manifest(root: Path) -> dict:
    files = {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(root.rglob("*.py"))}
    if not files or "runtime.py" not in files or "guarded_runtime.py" not in files:
        raise ValueError("Bridge package is incomplete")
    return {"schema_version": 1, "files": files, "fingerprint": digest(files)}


def expected_bridge_manifest() -> dict | None:
    package_root = Path(__file__).resolve().parents[2]
    source = package_root / "cascadeur_side" / "cascadeur_complete"
    if source.is_dir():
        return bridge_manifest(source)
    manifest_path = (Path(sys.executable).parent if getattr(sys, "frozen", False) else package_root) / "bridge-package.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("fingerprint") != digest(manifest.get("files", {})):
        raise ValueError("Installed bridge package manifest differs")
    return manifest


def expected_bridge_fingerprint() -> str | None:
    manifest = expected_bridge_manifest()
    return manifest["fingerprint"] if manifest else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(bridge_manifest(args.bridge_root), sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
