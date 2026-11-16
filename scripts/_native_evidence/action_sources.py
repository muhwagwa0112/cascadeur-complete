"""Collect bounded, explicitly selected action source evidence without imports.

The report records source bytes and syntactic references. A literal, a call-graph
candidate, or an absence of async indicators does not prove a runtime binding or
completion. No selected source is imported or executed, and no paths are scanned.
"""
from __future__ import annotations

import argparse
import ast
from collections import deque
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import tokenize


DEFAULT_ACTIONS = (
    "View.AutoInterpolation_Keys",
    "View.Animation unbaking",
    "AutoPosingTool.AutoUnlock",
)
MAX_FILES = 16
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_AST_NODES = 100_000
MAX_OCCURRENCES = 256
MAX_DEFINITIONS = 4096
MAX_REACHED_DEFINITIONS = 128
MAX_GRAPH_DEPTH = 8
MAX_CALLS = 2048
MAX_INDICATORS = 1024
MAX_SNIPPET_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MODULE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*\Z")
TEXT_SUFFIXES = {".json", ".xml", ".qml", ".ini", ".cfg", ".txt", ".cpp", ".cc", ".h", ".hpp"}
DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass
class Definition:
    file: "PythonSource"
    node: ast.AST
    qualname: str
    parent_qualname: str
    kind: str

    @property
    def key(self) -> str:
        return f"{self.file.module}:{self.qualname}@{self.node.lineno}"


class PythonSource:
    def __init__(self, module: str, path: Path, source: str):
        self.module, self.path, self.source = module, path, source
        self.lines = source.splitlines(keepends=True)
        self.tree = ast.parse(source, filename=str(path), type_comments=True)
        self.parents: dict[ast.AST, ast.AST] = {}
        self.owner: dict[ast.AST, Definition | None] = {}
        self.definitions: list[Definition] = []
        self.nodes: list[ast.AST] = []
        self.import_cache: dict[str | None, dict[str, set[str]]] = {}
        self._index(self.tree, None, "")

    def _index(self, node: ast.AST, owner: Definition | None, qualname: str) -> None:
        self.nodes.append(node)
        if len(self.nodes) > MAX_AST_NODES:
            raise ValueError("Selected Python file exceeds AST node budget")
        if isinstance(node, DEF_TYPES):
            current = ".".join(filter(None, (qualname, node.name)))
            owner = Definition(self, node, current, qualname, type(node).__name__)
            self.definitions.append(owner)
            qualname = current
        self.owner[node] = owner
        for child in ast.iter_child_nodes(node):
            self.parents[child] = node
            self._index(child, owner, qualname)

    def snippet(self, node: ast.AST, *, decorators: bool = False) -> dict:
        start = node.lineno
        if decorators:
            start = min([start, *(item.lineno for item in getattr(node, "decorator_list", ()))])
        end = node.end_lineno
        text = "".join(self.lines[start - 1:end])
        if len(text.encode("utf-8")) > MAX_SNIPPET_BYTES:
            raise ValueError("Selected definition/statement exceeds excerpt budget; narrow the input")
        return {"start_line": start, "end_line": end, "source": text}

    def statement(self, node: ast.AST) -> ast.AST:
        while not isinstance(node, ast.stmt) and node in self.parents:
            node = self.parents[node]
        return node


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        return parent + "." + node.attr if parent else None
    return None


def _location(file: PythonSource, node: ast.AST) -> dict:
    return {"module": file.module, "path": str(file.path),
            "line": node.lineno, "end_line": node.end_lineno,
            "utf8_column": node.col_offset, "end_utf8_column": node.end_col_offset}


def _read(path: Path, python: bool) -> tuple[bytes, str]:
    if not path.is_file():
        raise ValueError(f"Selected input must be a regular file: {path}")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"Selected file exceeds byte budget: {path}")
    if python:
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig"
    return raw, raw.decode(encoding)


def _relative_module(file: PythonSource, node: ast.ImportFrom) -> str | None:
    if not node.level:
        return node.module or ""
    package = file.module if file.path.name == "__init__.py" else file.module.rpartition(".")[0]
    parts = package.split(".") if package else []
    if node.level > len(parts):
        return None
    base = parts[:len(parts) - node.level + 1]
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports(file: PythonSource, owner: Definition | None) -> dict[str, set[str]]:
    # Imports are lexical hints, not a model of execution order or rebinding.
    cache_key = owner.key if owner else None
    if cache_key in file.import_cache:
        return file.import_cache[cache_key]
    scopes = {None}
    if owner:
        scopes.update(d.key for d in file.definitions
                      if owner.qualname == d.qualname or owner.qualname.startswith(d.qualname + "."))
    out: dict[str, set[str]] = {}
    for node in file.nodes:
        node_owner = file.owner[node]
        if (node_owner.key if node_owner else None) not in scopes:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else alias.name.split(".")[0]
                out.setdefault(name, set()).add(target)
        elif isinstance(node, ast.ImportFrom):
            parent = _relative_module(file, node)
            if parent is not None:
                for alias in node.names:
                    if alias.name != "*":
                        out.setdefault(alias.asname or alias.name, set()).add(parent + "." + alias.name)
    file.import_cache[cache_key] = out
    return out


def _candidates(file: PythonSource, node: ast.AST, definitions: dict,
                selected_modules: tuple[str, ...]) -> list[str]:
    name = _dotted(node)
    if not name:
        return []
    owner = file.owner[node]
    keys: set[tuple[str, str]] = {(file.module, name)}
    scope = owner.qualname if owner else ""
    while scope:
        keys.add((file.module, scope + "." + name))
        scope = scope.rpartition(".")[0]
    if owner and name.startswith(("self.", "cls.")):
        classes = [d.qualname for d in file.definitions if d.kind == "ClassDef"
                   and owner.qualname.startswith(d.qualname + ".")]
        for cls in classes:
            keys.add((file.module, cls + "." + name.split(".", 1)[1]))
    first, _, rest = name.partition(".")
    expanded = {name}
    for target in _imports(file, owner).get(first, ()):
        expanded.add(target + ("." + rest if rest else ""))
    for expression in expanded:
        for module in selected_modules:
            if expression.startswith(module + "."):
                keys.add((module, expression[len(module) + 1:]))
    return sorted({d.key for key in keys for d in definitions.get(key, ())})


def _indicators(file: PythonSource, definition: Definition) -> list[dict]:
    rows = []
    for node in ast.walk(definition.node):
        # Nested definitions have their own graph records. Their bodies are not
        # attributed to execution of their enclosing function.
        if file.owner.get(node) is not definition:
            continue
        labels = []
        if isinstance(node, (ast.Await, ast.Yield, ast.YieldFrom, ast.AsyncFor, ast.AsyncWith, ast.AsyncFunctionDef)):
            labels.append("async_or_generator_syntax")
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            labels.append("nonlocal_binding_syntax")
        if isinstance(node, ast.ExceptHandler):
            labels.append("exception_handler_requires_control_flow_review")
        if isinstance(node, ast.Return):
            labels.append("return_syntax_not_completion_evidence")
        if isinstance(node, ast.Call):
            name = _dotted(node.func) or "<dynamic callable expression>"
            lowered = name.casefold()
            if any(part in lowered for part in ("dialog", "messagebox")):
                labels.append("dialog_name_indicator")
            if any(part in lowered for part in ("defer", "singleshot", "call_soon", "call_later", "schedule", "post_event", "create_task", "ensure_future", "add_done_callback")):
                labels.append("deferred_or_task_name_indicator")
            if any(part in lowered for part in ("current_scene", "selection", "selected_layer", "selected_object")):
                labels.append("current_scene_or_selection_name_indicator")
            if name in {"getattr", "setattr", "eval", "exec", "__import__"} or name == "<dynamic callable expression>":
                labels.append("dynamic_resolution_indicator")
        if labels:
            rows.append({**_location(file, node), "indicators": labels,
                         "statement": file.snippet(file.statement(node))})
    return rows


def collect(python_specs: list[str], text_paths: list[Path], actions: tuple[str, ...],
            entries: tuple[str, ...]) -> dict:
    if not 1 <= len(python_specs) + len(text_paths) <= MAX_FILES:
        raise ValueError(f"Select between 1 and {MAX_FILES} exact files")
    if not 1 <= len(actions) <= 16 or any(not a or len(a) > 160 for a in actions):
        raise ValueError("Select between 1 and 16 nonempty action IDs, at most 160 characters each")
    if len(entries) > 16:
        raise ValueError("Select at most 16 exact entry definitions")
    selected: list[tuple[str | None, Path]] = []
    for spec in python_specs:
        module, sep, path = spec.partition("=")
        if not sep or not MODULE.fullmatch(module) or not path:
            raise ValueError("--python requires MODULE=EXACT_PATH")
        selected.append((module, Path(path).resolve(strict=True)))
    selected.extend((None, path.resolve(strict=True)) for path in text_paths)
    if len({path for _, path in selected}) != len(selected):
        raise ValueError("Duplicate selected file")
    modules = [module for module, _ in selected if module]
    if len(set(modules)) != len(modules):
        raise ValueError("Duplicate Python module name")
    files, python_files, occurrences, total, total_nodes = [], [], [], 0, 0
    for module, path in sorted(selected, key=lambda item: str(item[1])):
        if (module and path.suffix != ".py") or (not module and path.suffix.casefold() not in TEXT_SUFFIXES):
            raise ValueError("Use --python for .py or --text for an explicit supported text file")
        raw, source = _read(path, bool(module))
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Selected files exceed total byte budget")
        file_record = {"path": str(path), "module": module, "bytes": len(raw),
                       "sha256": hashlib.sha256(raw).hexdigest(),
                       "analysis": "python_ast" if module else "text_mentions_only"}
        files.append(file_record)
        file = PythonSource(module, path, source) if module else None
        if file:
            total_nodes += len(file.nodes)
            if total_nodes > MAX_AST_NODES:
                raise ValueError("Selected Python files exceed total AST node budget")
            python_files.append(file)
            for node in file.nodes:
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in actions:
                    owner = file.owner[node]
                    statement = file.statement(node)
                    occurrences.append({"action_id": node.value, "kind": "exact_python_string_literal",
                        **_location(file, node), "enclosing_definition": owner.key if owner else None,
                        "statement": file.snippet(statement), "binding_proven": False})
        else:
            for number, line in enumerate(source.splitlines(keepends=True), 1):
                for action in actions:
                    if action in line:
                        if len(line.encode("utf-8")) > MAX_SNIPPET_BYTES:
                            raise ValueError("Action text line exceeds excerpt budget")
                        occurrences.append({"action_id": action, "kind": "text_mention",
                            "path": str(path), "line": number, "source_line": line, "binding_proven": False})
        if len(occurrences) > MAX_OCCURRENCES:
            raise ValueError("Too many action occurrences; narrow selected files")

    definitions: dict[tuple[str, str], list[Definition]] = {}
    by_key: dict[str, Definition] = {}
    for file in python_files:
        for definition in file.definitions:
            definitions.setdefault((file.module, definition.qualname), []).append(definition)
            by_key[definition.key] = definition
    if len(by_key) > MAX_DEFINITIONS or sum(len(f.nodes) for f in python_files) > MAX_AST_NODES:
        raise ValueError("Selected files exceed definition or AST node budget")
    seed_reasons: dict[str, set[str]] = {}
    for entry in entries:
        module, sep, qualname = entry.partition(":")
        matches = definitions.get((module, qualname), ())
        if not sep or not matches:
            raise ValueError(f"Entry absent from selected Python files: {entry}")
        for match in matches:
            seed_reasons.setdefault(match.key, set()).add("explicit_entry_not_proven_action_binding")
    for file in python_files:
        for node in file.nodes:
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in actions):
                continue
            owner = file.owner[node]
            if owner:
                seed_reasons.setdefault(owner.key, set()).add("contains_action_literal")
            # Name references in the same statement include callbacks passed to a
            # registration API. They are candidates even when never called here.
            for item in ast.walk(file.statement(node)):
                if isinstance(item, (ast.Name, ast.Attribute)):
                    for key in _candidates(file, item, definitions, tuple(modules)):
                        seed_reasons.setdefault(key, set()).add("same_statement_callable_reference_candidate")
    if len(seed_reasons) > MAX_REACHED_DEFINITIONS:
        raise ValueError("Too many candidate entry definitions; narrow selected files")
    queue = deque((key, 0) for key in sorted(seed_reasons))
    queued = set(seed_reasons)
    reached, graph, indicators, total_calls, cutoff = set(), [], [], 0, []
    while queue:
        key, depth = queue.popleft()
        if key in reached:
            continue
        if len(reached) >= MAX_REACHED_DEFINITIONS:
            raise ValueError("Candidate call graph exceeds definition budget; narrow inputs")
        reached.add(key)
        definition = by_key[key]
        file = definition.file
        calls = []
        for node in ast.walk(definition.node):
            if not isinstance(node, ast.Call) or file.owner.get(node) is not definition:
                continue
            candidate_keys = _candidates(file, node.func, definitions, tuple(modules))
            callbacks = set()
            for argument in [*node.args, *(item.value for item in node.keywords)]:
                if isinstance(argument, (ast.Name, ast.Attribute)):
                    callbacks.update(_candidates(file, argument, definitions, tuple(modules)))
            calls.append({**_location(file, node), "expression": ast.get_source_segment(file.source, node.func),
                "candidate_definitions": candidate_keys, "callback_reference_candidates": sorted(callbacks),
                "resolution": "syntactic_candidates_only" if candidate_keys else "unresolved_external_or_dynamic",
                "statement": file.snippet(file.statement(node))})
            targets = sorted(set(candidate_keys) | callbacks)
            if depth < MAX_GRAPH_DEPTH:
                new_targets = [target for target in targets if target not in queued]
                if len(queued) + len(new_targets) > MAX_REACHED_DEFINITIONS:
                    raise ValueError("Candidate call graph exceeds definition budget; narrow inputs")
                queue.extend((target, depth + 1) for target in new_targets)
                queued.update(new_targets)
            else:
                if len(cutoff) + len(targets) > MAX_CALLS:
                    raise ValueError("Too many depth-cutoff edges; select fewer definitions")
                cutoff.extend({"from": key, "candidate": target, "reason": "depth_limit"}
                              for target in targets if target not in reached)
        total_calls += len(calls)
        if total_calls > MAX_CALLS:
            raise ValueError("Candidate call graph exceeds call budget; narrow inputs")
        indicators.extend(_indicators(file, definition))
        if len(indicators) > MAX_INDICATORS:
            raise ValueError("Too many source indicators; narrow inputs")
        graph.append({"definition": key, "kind": definition.kind, "depth": depth,
            "seed_reasons": sorted(seed_reasons.get(key, ())),
            "source": file.snippet(definition.node, decorators=True), "calls": calls})
    found = {row["action_id"] for row in occurrences}
    return {"format": "cascadeur-action-source-evidence-r6", "collector_python": sys.version.split()[0],
        "requested_action_ids": list(actions), "explicit_entries": list(entries), "files": files,
        "action_occurrences": occurrences, "not_found_in_selected_files": sorted(set(actions) - found),
        "candidate_call_graph": graph, "graph_cutoffs": cutoff, "source_indicators": indicators,
        "limits": {"max_depth": MAX_GRAPH_DEPTH, "max_definitions": MAX_REACHED_DEFINITIONS,
                   "max_calls": MAX_CALLS, "selected_bytes": total},
        "scope": {"source_imported": False, "action_executed": False, "paths_scanned": False,
                  "binding_proven": False, "runtime_qualified": False,
                  "completion_observed": False, "call_graph_is_exhaustive": False,
                  "dynamic_binding_or_rebinding_resolved": False,
                  "negative_match_proves_installation_absence": False},
        "interpretation": "Lexical candidates only. Imports, decorators, aliases, rebinding, conditionals, "
                          "native code and callbacks may change runtime targets. No indicator is a qualification verdict."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", action="append", default=[], metavar="MODULE=FILE",
                        help="Exact .py file and its installed module name; repeat, no directory scans")
    parser.add_argument("--text", action="append", default=[], type=Path,
                        help="Exact registration/config/C++ text file; mentions only")
    parser.add_argument("--action", action="append", help="Exact action ID; defaults to the three documented steps")
    parser.add_argument("--entry", action="append", default=[], metavar="MODULE:QUALNAME",
                        help="Explicit function/class to inspect when its source has no action literal")
    parser.add_argument("--output", required=True, type=Path,
                        help="New JSON file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        report = collect(args.python, args.text, tuple(dict.fromkeys(args.action or DEFAULT_ACTIONS)),
                         tuple(dict.fromkeys(args.entry)))
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(raw) > MAX_OUTPUT_BYTES:
            raise ValueError("Report exceeds output budget; narrow selected files")
        with args.output.open("xb") as stream:
            stream.write(raw)
        print(str(args.output.resolve()))
        return 0
    except (OSError, UnicodeError, SyntaxError, ValueError, RecursionError) as exc:
        print(f"Action source collection failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
