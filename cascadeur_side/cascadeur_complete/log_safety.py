from __future__ import annotations

import re
from pathlib import Path

MAX_LOG_SCAN_BYTES = 512 * 1024
MAX_LOG_LINE_BYTES = 16 * 1024
LOG_LEVELS = ("CRITICAL", "FATAL", "ERROR", "WARNING", "INFO", "DEBUG", "TRACE", "OTHER")
_LOG_LEVEL = re.compile(r"(?i)\b(CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\b")

_SECRET_KEY = (
    r"(?:access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|"
    r"api[_-]?key|private[_-]?key|signing[_-]?key|session[_-]?(?:id|key|token)|"
    r"token|password|passwd|secret|authorization|cookie)"
)
_SECRET_ASSIGNMENT = re.compile(
    rf"(?im)([\"']?\b{_SECRET_KEY}\b[\"']?\s*[:=]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\r\n]*)"
)
_AUTH_SCHEME = re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_PENDING_SECRET = re.compile(
    rf"(?i)^(?P<indent>\s*)[{{\[]?\s*[\"']?\b{_SECRET_KEY}\b[\"']?\s*[:=]\s*"
    r"(?P<block>[|>][+-]?)?\s*[,]?\s*$"
)
_PEM_PRIVATE_BEGIN = re.compile(r"(?i)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_PRIVATE_END = re.compile(r"(?i)-----END [A-Z0-9 ]*PRIVATE KEY-----")
_STRUCTURE_END = re.compile(r"^\s*[}\]]\s*[,]?\s*$")


def redact_log_text(text: str, *, profile: str = "", local_app_data: str = "") -> str:
    if profile:
        text = re.sub(re.escape(profile), "<USERPROFILE>", text, flags=re.IGNORECASE)
    if local_app_data:
        text = re.sub(re.escape(local_app_data), "<LOCALAPPDATA>", text, flags=re.IGNORECASE)
    text = _AUTH_SCHEME.sub("<AUTH> <REDACTED>", text)
    return _SECRET_ASSIGNMENT.sub(r"\1<REDACTED>", text)


def redact_log_line(line: str, *, profile: str = "", local_app_data: str = "") -> str:
    return redact_log_text(line, profile=profile, local_app_data=local_app_data)


def redact_log_lines(lines, *, profile: str = "", local_app_data: str = ""):
    return list(redact_log_stream(lines, profile=profile, local_app_data=local_app_data))


def redact_log_stream(lines, *, profile: str = "", local_app_data: str = ""):
    pending_secret_value = False
    pending_yaml_block = False
    pending_indent = 0
    pem_private_block = False
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if pem_private_block or _PEM_PRIVATE_BEGIN.search(line):
            indentation = line[: len(line) - len(line.lstrip())]
            line = indentation + "<REDACTED>"
            pem_private_block = not bool(_PEM_PRIVATE_END.search(raw_line))
            yield line
            continue

        current_indent = len(line) - len(line.lstrip())
        if pending_secret_value and pending_yaml_block and line.strip() and current_indent <= pending_indent:
            pending_secret_value = False
            pending_yaml_block = False

        if pending_secret_value:
            if line.strip():
                indentation = line[:current_indent]
                line = indentation + "<REDACTED>"
            if _STRUCTURE_END.match(raw_line):
                pending_secret_value = False
                pending_yaml_block = False
            yield line
            continue

        line = redact_log_line(line, profile=profile, local_app_data=local_app_data)
        pending = _PENDING_SECRET.search(raw_line.rstrip("\r\n"))
        if pending:
            pending_secret_value = True
            pending_yaml_block = bool(pending.group("block"))
            pending_indent = len(pending.group("indent"))
        yield line


def read_bounded_log_lines(path: Path):
    """Return a bounded tail plus whether older input was omitted.

    An artificial pending-secret marker is inserted at a truncated boundary.
    This conservatively redacts the first complete value line if its key was
    outside the read window. Oversized individual lines receive the same
    treatment and are never returned verbatim.
    """

    size = path.stat().st_size
    read_limit = MAX_LOG_SCAN_BYTES + MAX_LOG_LINE_BYTES
    offset = max(0, size - read_limit)
    with path.open("rb") as stream:
        stream.seek(offset)
        payload = stream.read(read_limit + 1)
    truncated = offset > 0 or len(payload) > read_limit
    if len(payload) > read_limit:
        payload = payload[:read_limit]
    if offset > 0:
        boundary = payload.find(b"\n")
        if boundary < 0:
            return ["secret:"], True
        payload = payload[boundary + 1 :]

    lines = []
    if truncated:
        lines.append("secret:")
    for raw_line in payload.splitlines():
        if len(raw_line) > MAX_LOG_LINE_BYTES:
            lines.append("secret:")
            continue
        lines.append(raw_line.decode("utf-8", errors="replace"))
    return lines, truncated


def summarize_log_levels(lines):
    """Convert untrusted log text into a fixed, non-content-bearing schema."""

    levels = []
    for line in lines:
        match = _LOG_LEVEL.search(line)
        level = match.group(1).upper() if match else "OTHER"
        if level == "WARN":
            level = "WARNING"
        levels.append(level)
    return levels
