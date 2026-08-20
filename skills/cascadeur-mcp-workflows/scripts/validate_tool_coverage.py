from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

START = "<!-- MCP-TOOLS-START -->"
END = "<!-- MCP-TOOLS-END -->"


def public_mcp_tools(server_path: Path) -> set[str]:
    tree = ast.parse(server_path.read_text(encoding="utf-8"), filename=str(server_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "tool"
                and isinstance(target.value, ast.Name)
                and target.value.id == "mcp"
            ):
                names.add(node.name)
                break
    return names


def catalog_tools(catalog_path: Path) -> set[str]:
    text = catalog_path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise ValueError("tool catalog coverage markers are missing")
    body = text.split(START, 1)[1].split(END, 1)[0]
    return set(re.findall(r"`([a-z][a-z0-9_]*)`", body))


def main() -> int:
    skill_dir = Path(__file__).resolve().parents[1]
    repo_root = skill_dir.parents[1]
    parser = argparse.ArgumentParser(description="Compare the skill tool catalog with the MCP server contract.")
    parser.add_argument(
        "--server",
        type=Path,
        default=repo_root / "src" / "cascadeur_complete" / "server.py",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=skill_dir / "references" / "tool-routing.md",
    )
    args = parser.parse_args()

    contract = public_mcp_tools(args.server.resolve())
    catalog = catalog_tools(args.catalog.resolve())
    result = {
        "contract_count": len(contract),
        "catalog_count": len(catalog),
        "missing_from_catalog": sorted(contract - catalog),
        "unknown_in_catalog": sorted(catalog - contract),
        "ok": contract == catalog,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
