"""Read selected installed Python stubs without importing or contacting Cascadeur.

This is an operator-run evidence collection utility, not an MCP operation or a
native qualification issuer. Its output proves only which bytes/declarations were
read. A declaration cannot establish synchronous completion or graph freshness.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import tokenize
from io import BytesIO


MAX_FILES = 8
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_MATCHES = 256
MAX_DECLARATION_BYTES = 128 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024


def _read_stub(path: Path) -> tuple[bytes, str]:
    if path.suffix != ".pyi":
        raise ValueError(f"Expected an explicitly selected .pyi file: {path}")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"Stub exceeds {MAX_FILE_BYTES} bytes: {path}")
    encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
    return raw, raw.decode(encoding)


class Declarations(ast.NodeVisitor):
    def __init__(self, source: str, symbols: tuple[str, ...]):
        self.lines = source.splitlines(keepends=True)
        self.symbols = symbols
        self.parents: list[str] = []
        self.rows: list[dict] = []

    def _add(self, node: ast.AST, kind: str, name: str) -> None:
        qualified = ".".join((*self.parents, name))
        matched = [s for s in self.symbols if qualified == s or qualified.endswith("." + s)]
        if not matched:
            return
        start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", ()))])
        end = node.end_lineno
        declaration = "".join(self.lines[start - 1:end])
        if len(declaration.encode("utf-8")) > MAX_DECLARATION_BYTES:
            raise ValueError(f"Declaration too large; select a specific member: {qualified}")
        self.rows.append({"kind": kind, "qualified_name": qualified,
                          "start_line": start, "end_line": end,
                          "matched_symbols": matched, "declaration": declaration})
        if len(self.rows) > MAX_MATCHES:
            raise ValueError("Too many declarations; select fewer/more specific symbols")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add(node, "class", node.name)
        self.parents.append(node.name)
        for item in node.body:
            self.visit(item)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add(node, "function", node.name)
        # A stub function body is not an SDK namespace.

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add(node, "async_function", node.name)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._add(node, "annotated_attribute", node.target.id)


def collect(stubs: list[Path], symbols: tuple[str, ...]) -> dict:
    if not 1 <= len(stubs) <= MAX_FILES:
        raise ValueError(f"Select between 1 and {MAX_FILES} stub files")
    if not symbols or len(symbols) > 32 or any(not s or len(s) > 160 for s in symbols):
        raise ValueError("Select between 1 and 32 nonempty symbol names")
    paths = [p.resolve(strict=True) for p in stubs]
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate stub path")
    files, found, total = [], set(), 0
    for path in sorted(paths, key=str):
        raw, source = _read_stub(path)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Selected stubs exceed the total byte limit")
        tree = ast.parse(source, filename=str(path), type_comments=True)
        reader = Declarations(source, symbols)
        reader.visit(tree)
        for row in reader.rows:
            found.update(row["matched_symbols"])
        files.append({"path": str(path), "bytes": len(raw),
                      "sha256": hashlib.sha256(raw).hexdigest(),
                      "declarations": reader.rows})
    return {"format": "cascadeur-sdk-declarations-r6", "collector_python": sys.version.split()[0],
            "requested_symbols": list(symbols),
            "not_found_in_selected_files": sorted(set(symbols) - found),
            "files": files,
            "scope": {"stub_bytes_only": True, "native_imported": False,
                      "native_executed": False, "runtime_qualified": False,
                      "missing_symbol_proves_sdk_absence": False}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stub", action="append", required=True, type=Path,
                        help="Exact installed .pyi path; repeat for at most 8 files")
    parser.add_argument("--symbol", action="append", required=True,
                        help="Exact name or class-qualified name; repeat as needed")
    parser.add_argument("--output", required=True, type=Path,
                        help="New JSON file; existing files are never overwritten")
    args = parser.parse_args()
    try:
        result = collect(args.stub, tuple(dict.fromkeys(args.symbol)))
        raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(raw) > MAX_OUTPUT_BYTES:
            raise ValueError("Output exceeds limit; select fewer symbols")
        # Open only after all source reads/parsing succeed. No partial semantic
        # report is presented as successful if a selected input is invalid.
        with args.output.open("xb") as stream:
            stream.write(raw)
        print(str(args.output.resolve()))
        return 0
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        print(f"SDK declaration collection failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
