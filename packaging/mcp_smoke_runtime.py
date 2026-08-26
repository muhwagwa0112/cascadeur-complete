"""Dependency-free MCP stdio smoke test used by source and frozen builds."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class SmokeFailure(RuntimeError):
    pass


class JsonRpcProcess:
    def __init__(self, command: list[str], timeout: float) -> None:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self.timeout = timeout
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                self.messages.put(message)

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())
            if len(self.stderr) > 40:
                del self.stderr[0]

    def send(self, message: dict[str, Any]) -> None:
        if self.process.poll() is not None:
            raise SmokeFailure(f"server exited with {self.process.returncode}: {' | '.join(self.stderr)}")
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, request_id: int, method: str, params: dict[str, Any] | None = None) -> Any:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        deadline = time.monotonic() + self.timeout
        deferred: list[dict[str, Any]] = []
        try:
            while time.monotonic() < deadline:
                try:
                    response = self.messages.get(timeout=min(0.25, deadline - time.monotonic()))
                except queue.Empty:
                    if self.process.poll() is not None:
                        raise SmokeFailure(
                            f"server exited with {self.process.returncode}: {' | '.join(self.stderr)}"
                        ) from None
                    continue
                if response.get("id") != request_id:
                    deferred.append(response)
                    continue
                if "error" in response:
                    raise SmokeFailure(f"{method} returned JSON-RPC error: {response['error']}")
                return response.get("result")
        finally:
            for response in deferred:
                self.messages.put(response)
        raise SmokeFailure(f"timed out waiting for {method}: {' | '.join(self.stderr)}")

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


def _content_payload(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    for content in result.get("content", []):
        if isinstance(content, dict) and content.get("type") == "text":
            try:
                return json.loads(content.get("text", ""))
            except json.JSONDecodeError:
                return content.get("text")
    return result


def run_smoke(server: Path, timeout: float, *, refresh: bool = False) -> dict[str, Any]:
    if not server.is_file():
        raise SmokeFailure(f"server executable does not exist: {server}")
    rpc = JsonRpcProcess([str(server)], timeout)
    try:
        initialized = rpc.request(
            1,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "cascadeur-mcp-smoke", "version": "1"},
            },
        )
        rpc.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = rpc.request(2, "tools/list", {})
        tools = listed.get("tools", []) if isinstance(listed, dict) else []
        names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        if "cascadeur_status" not in names:
            raise SmokeFailure("tools/list did not expose cascadeur_status")
        called = rpc.request(
            3,
            "tools/call",
            {"name": "cascadeur_status", "arguments": {"refresh": refresh}},
        )
        if isinstance(called, dict) and called.get("isError") is True:
            raise SmokeFailure(f"cascadeur_status returned isError: {called}")
        return {
            "ok": True,
            "protocol_version": initialized.get("protocolVersion") if isinstance(initialized, dict) else None,
            "tool_count": len(tools),
            "cascadeur_status": _content_payload(called),
        }
    finally:
        rpc.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test a Cascadeur MCP stdio executable")
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="perform a live read-only bridge status call against a running Cascadeur instance",
    )
    args = parser.parse_args()
    try:
        result = run_smoke(args.server.resolve(), args.timeout, refresh=args.refresh)
    except SmokeFailure as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
