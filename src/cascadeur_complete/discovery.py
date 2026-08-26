from __future__ import annotations

import ast
import json
import os
import shutil
import warnings
from pathlib import Path
from typing import Any

from .feature_registry import build_registry, registry_json
from .paths import CASCADEUR_EXE, CASCADEUR_SCRIPTS, CSC_SCHEMA_CANDIDATES, RuntimePaths
from .product_catalog import PRODUCT_CATALOG

BASELINE_TOOLS = [
    "DefaultFbxSynchronizationTool",
    "Gui",
    "Hotkeys",
    "GlbSceneLoader",
    "DockingSystem",
    "ControlPicker",
    "Timeline",
    "ManipulatorsTool",
    "AnimationUnbakingTool",
    "DomainStateController",
    "Sf3Loader",
    "CameraOrientationTool",
    "GhostTool",
    "ViewportsTool",
    "OutlinerTool",
    "TopologyController",
    "ViewportModesManager",
    "ViewportSelector",
    "ShowFulcrumPointsTool",
    "ObjectWatchingTool",
    "Audio",
    "MocapTool",
    "Textures",
    "EventSystem",
    "LiveLinkTool",
    "CopierTool",
    "LayersCopier",
    "BallisticTrajectoryTool",
    "AnimationDataCopier",
    "SceneAutosaver",
    "AnimationWithLayersCopier",
    "Retargeting",
    "LayerHierarchyCopier",
    "FbxSceneLoader",
    "Scene",
    "LogDeleter",
    "ViewGridTool",
    "UsdSceneLoader",
    "LinkedScenes",
    "AttractorTool",
    "TrajectoryTool",
    "PythonConsole",
    "MirrorTool",
    "AutoPhysicsTool",
    "NodeEditorTool",
    "FixFootTool",
    "RiggingToolWindowTool",
    "AutoPosingTool",
    "CompositionTool",
    "ViewActionCreatorTool",
    "RiggingModeTool",
    "SelectionGroupsTool",
    "FixCollisionsTool",
    "InbetweeningTool",
    "DataSourceManager",
    "RenderToFile",
]


def discover_installation() -> dict[str, Any]:
    # MCP stdio launchers intentionally pass a reduced environment and may
    # omit PROGRAMFILES. Keep the version-pinned configured executable as the
    # primary candidate so installed-server capability detection matches the
    # interactive development environment.
    candidates = [CASCADEUR_EXE]
    found = shutil.which("cascadeur.exe")
    if found:
        candidates.append(Path(found))
    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(Path(program_files) / "Cascadeur" / "cascadeur.exe")
    executable = next((path.resolve() for path in candidates if path.is_file()), None)
    version = None
    if executable is not None:
        try:
            import win32api

            translations = win32api.GetFileVersionInfo(str(executable), r"\VarFileInfo\Translation")
            for language, codepage in translations:
                key = rf"\StringFileInfo\{language:04X}{codepage:04X}\ProductVersion"
                value = win32api.GetFileVersionInfo(str(executable), key)
                if value:
                    version = str(value)
                    break
        except (ImportError, OSError):
            version = None
    return {
        "executable": str(executable) if executable else None,
        "version": version,
        "adapter": "2026.1",
        "compatible": version == PRODUCT_CATALOG.supported_build,
    }


def load_csc_schema(path: Path | None = None) -> dict[str, Any]:
    candidates = (path,) if path else CSC_SCHEMA_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {}


def _constant_return(function: ast.FunctionDef) -> str | None:
    if len(function.body) != 1 or not isinstance(function.body[0], ast.Return):
        return None
    value = function.body[0].value
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


def discover_commands(root: Path = CASCADEUR_SCRIPTS) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    if not root.is_dir():
        return commands
    for path in root.rglob("*.py"):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, UnicodeError):
            continue
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        name_node = functions.get("command_name")
        if not name_node:
            continue
        name = _constant_return(name_node)
        if not name:
            continue
        description_node = functions.get("command_description")
        commands.append(
            {
                "name": name,
                "description": _constant_return(description_node) if description_node else "",
                "path": str(path),
            }
        )
    return sorted(commands, key=lambda item: item["name"])


def schema_counts(schema: dict[str, Any]) -> dict[str, int]:
    counts = {"modules": 0, "symbols": 0, "classes": 0, "functions": 0, "methods": 0, "values": 0}

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        for value in node.values():
            if not isinstance(value, dict):
                continue
            if "type" in value:
                counts["symbols"] += 1
                kind = value.get("type")
                if kind == "class":
                    counts["classes"] += 1
                elif kind == "function":
                    counts["functions"] += 1
                counts["methods"] += len(value.get("methods", []))
                counts["values"] += len(value.get("values", []))
            else:
                if depth > 0:
                    counts["modules"] += 1
                walk(value, depth + 1)

    walk(schema)
    counts["class_members"] = counts["methods"] + counts["values"]
    return counts


def write_inventory(paths: RuntimePaths | None = None) -> dict[str, Any]:
    runtime = paths or RuntimePaths.discover()
    runtime.ensure()
    schema = load_csc_schema()
    commands = discover_commands()
    records = build_registry(schema, commands, BASELINE_TOOLS)
    tmp = runtime.registry.with_suffix(".tmp")
    tmp.write_text(registry_json(records), encoding="utf-8")
    tmp.replace(runtime.registry)
    return {
        "registry": str(runtime.registry),
        "feature_count": len(records),
        "csc": schema_counts(schema),
        "commands": len(commands),
        "tools": len(BASELINE_TOOLS),
    }


def main() -> None:
    print(json.dumps(write_inventory(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
