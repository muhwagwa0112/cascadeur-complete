"""Collect a bounded installed-SDK/source evidence bundle without running the SDK.

Only the two code-owned collectors beside this script are imported.
Installed .py/.pyi inputs are read as source; they are never imported or executed.
The bundle is implementation evidence, not a native qualification or approval.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


STUB_MODULES = ("domain", "update", "model", "tools", "app")
SYMBOLS = (
    "Scene", "SceneUpdater", "SkinnedMeshCalcResult", "calc_skinned_mesh",
    "Update", "Node", "NodeAttribute", "Group", "ObjectGroup", "UpdateGroup",
    "RegularData", "RegularFunction", "SettingFunction", "InterfaceAttribute",
    "RegularFunctionAttributeId", "RegularDataAttributeId", "GroupAttributeId",
    "SettingFunctionAttributeId", "ExternalPropertyAttributeId", "InterfaceId",
    "ConstantDataAttributeId", "ConstantSettingAttributeId",
    "Data", "DataViewer", "BehaviourViewer", "ModelViewer",
    "AnimationUnbakingTool", "AutoPosingTool", "ActionManager",
)
DEFAULT_ACTIONS = (
    "View.AutoInterpolation_Keys", "View.Animation unbaking", "AutoPosingTool.AutoUnlock",
)
MAX_BUNDLE_BYTES = 16 * 1024 * 1024


def _collector(path: Path, name: str):
    # A fixed product path, never a path derived from the installed SDK inputs.
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Product collector cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def collect_bundle(stub_root: Path, python_specs: list[str], text_paths: list[Path],
                   entries: tuple[str, ...], actions: tuple[str, ...],
                   build_label: str | None = None, *,
                   stub_paths: tuple[Path, ...] = (), symbols: tuple[str, ...] = SYMBOLS) -> dict:
    if entries and not python_specs:
        raise ValueError("--entry requires at least one explicit --python source")
    if build_label is not None and (not build_label or len(build_label) > 160):
        raise ValueError("The unverified build label must contain 1..160 characters")
    root = stub_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("--stub-root must identify the installed stubs directory")
    collector_root = Path(__file__).resolve().parent
    declaration_path = collector_root / "_native_evidence" / "declarations.py"
    source_path = collector_root / "_native_evidence" / "action_sources.py"
    declarations = _collector(declaration_path, "cascadeur_r6_declaration_collector")
    selected, absent = [], []
    # Explicit files or five named defaults only; never recurse or search inputs.
    candidates = list(stub_paths) or [root / "csc" / module / "__init__.pyi" for module in STUB_MODULES]
    for path in candidates:
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            absent.append({"expected_path": str(path)})
            continue
        if not resolved.is_file() or not resolved.is_relative_to(root):
            raise ValueError(f"Selected stub is not a regular file under the root: {path}")
        selected.append(resolved)
    if not selected:
        raise ValueError("No selected stub files exist under the explicit root")
    declaration_result = declarations.collect(selected, symbols)
    source_result = None
    collector_files = [declaration_path, Path(__file__).resolve()]
    if python_specs or text_paths:
        source_collector = _collector(source_path, "cascadeur_r6_action_source_collector")
        source_result = source_collector.collect(python_specs, text_paths, actions, entries)
        collector_files.append(source_path)
    material = {
        "declarations": declaration_result,
        "action_source": source_result,
        "absent_selected_stub_files": absent,
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("Evidence bundle exceeds the fixed 16 MiB limit")
    return {
        "format": "cascadeur-native-input-evidence-r6",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "collector_python": sys.version.split()[0],
        "stub_root": str(root),
        "build_label": {"value": build_label, "source": "operator_label_only",
                        "executable_version_observed": False},
        "selected_stub_files": [str(path) for path in selected],
        "material_sha256": hashlib.sha256(raw).hexdigest(),
        "material": material,
        "collector_files": [{"name": str(p.relative_to(collector_root)),
                             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                            for p in collector_files],
        "scope": {
            "source_bytes_only": True,
            "sdk_or_installed_source_imported": False,
            "native_executed": False,
            "runtime_qualified": False,
            "incident_changed": False,
            "action_binding_or_completion_proven": False,
            "missing_symbol_proves_sdk_absence": False,
            "native_storage_type_proven_by_python_annotation": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stub-root", required=True, type=Path,
                        help="Exact installed resources/scripts/stubs directory")
    parser.add_argument("--stub", action="append", default=[], type=Path,
                        help="Exact .pyi under stub-root; defaults to five named module files")
    parser.add_argument("--symbol", action="append", default=[],
                        help="Exact selected declaration; defaults to the fixed integration symbols")
    parser.add_argument("--python", action="append", default=[],
                        help="Explicit source MODULE=FILE; never imported or executed")
    parser.add_argument("--text", action="append", default=[], type=Path,
                        help="Explicit action-registration text file")
    parser.add_argument("--entry", action="append", default=[],
                        help="Explicit source entry MODULE:QUALNAME, not a proven binding")
    parser.add_argument("--action", action="append", default=[],
                        help="Exact action ID; defaults to the three unbaking IDs")
    parser.add_argument("--build-label", help="Optional operator hint, not observed version")
    parser.add_argument("--output", required=True, type=Path,
                        help="New bundle JSON path; the parent must already exist")
    args = parser.parse_args()
    try:
        result = collect_bundle(args.stub_root, args.python, args.text,
                                tuple(dict.fromkeys(args.entry)),
                                tuple(dict.fromkeys(args.action)) or DEFAULT_ACTIONS,
                                args.build_label, stub_paths=tuple(args.stub),
                                symbols=tuple(dict.fromkeys(args.symbol)) or SYMBOLS)
        raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2,
                          allow_nan=False) + "\n").encode("utf-8")
        if len(raw) > MAX_BUNDLE_BYTES:
            raise ValueError("Formatted evidence bundle exceeds the fixed 16 MiB limit")
        with args.output.open("xb") as stream:
            stream.write(raw)
        print(str(args.output.resolve()))
        return 0
    except (OSError, UnicodeError, SyntaxError, ValueError, RecursionError) as exc:
        print(f"Native evidence collection failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
