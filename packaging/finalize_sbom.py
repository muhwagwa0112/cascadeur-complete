"""Bind the dependency SBOM to the final frozen application tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path


def tree_digest(root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8") + b"\0" + file_hash.encode("ascii") + b"\n")
        count += 1
    return digest.hexdigest(), count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    payload = json.loads(args.sbom.read_text(encoding="utf-8"))
    artifact_hash, file_count = tree_digest(args.app)
    root_ref = f"pkg:pypi/cascadeur-complete@{args.version}"
    payload.setdefault("metadata", {})["component"] = {
        "type": "application",
        "bom-ref": root_ref,
        "name": "cascadeur-complete",
        "version": args.version,
        "purl": root_ref,
        "properties": [
            {"name": "cascadeur-mcp:frozen-tree-sha256", "value": artifact_hash},
            {"name": "cascadeur-mcp:frozen-file-count", "value": str(file_count)},
        ],
    }
    python_ref = f"pkg:generic/cpython@{platform.python_version()}?os=windows&arch=x86_64"
    components = payload.setdefault("components", [])
    if not any(item.get("bom-ref") == python_ref for item in components):
        components.append(
            {
                "type": "framework",
                "bom-ref": python_ref,
                "name": "CPython runtime",
                "version": platform.python_version(),
                "purl": python_ref,
                "properties": [{"name": "cascadeur-mcp:bundled", "value": "true"}],
            }
        )
    component_refs = sorted(
        item["bom-ref"] for item in components if isinstance(item, dict) and item.get("bom-ref")
    )
    dependencies = [item for item in payload.get("dependencies", []) if item.get("ref") != root_ref]
    dependencies.append({"ref": root_ref, "dependsOn": component_refs})
    payload["dependencies"] = dependencies
    args.sbom.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
