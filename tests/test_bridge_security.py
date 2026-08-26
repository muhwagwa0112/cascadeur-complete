from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load_log_safety():
    path = ROOT / "cascadeur_side" / "cascadeur_complete" / "log_safety.py"
    spec = importlib.util.spec_from_file_location("cascadeur_bridge_log_safety", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_log_redaction_covers_json_quotes_multiword_and_auth_headers():
    safety = _load_log_safety()
    redact = safety.redact_log_line
    inputs = [
        '{"token":"sekret-123"}',
        '{"access_token":"sekret-access"}',
        '{"refresh_token":"sekret-refresh"}',
        '{"client_secret":"sekret-client"}',
        'password = "two words here"',
        "Authorization: Basic dXNlcjpwYXNz",
        "Authorization=Bearer abc.def.ghi",
        r"scene=C:\Users\Alice\private.casc api_key: xyz trailing metadata",
    ]
    outputs = [
        redact(line, profile=r"C:\Users\Alice", local_app_data=r"C:\Users\Alice\AppData\Local")
        for line in inputs
    ]
    combined = "\n".join(outputs)
    assert "sekret-123" not in combined
    assert "sekret-access" not in combined
    assert "sekret-refresh" not in combined
    assert "sekret-client" not in combined
    assert "two words here" not in combined
    assert "dXNlcjpwYXNz" not in combined
    assert "abc.def.ghi" not in combined
    assert " xyz" not in combined
    assert r"C:\Users\Alice" not in combined
    assert all("<REDACTED>" in item for item in outputs)

    multiline = safety.redact_log_lines(['{"access_token":', '  "sekret-multiline"}'])
    assert "sekret-multiline" not in "\n".join(multiline)
    # Tail limiting must happen after streaming redaction. The final value line
    # remains safe even when the caller requests only that one line.
    assert "sekret-multiline" not in multiline[-1]

    pem = safety.redact_log_lines(
        [
            "-----BEGIN PRIVATE KEY-----",
            "MIIE-SECRET-KEY-MATERIAL",
            "-----END PRIVATE KEY-----",
        ]
    )
    assert "MIIE-SECRET-KEY-MATERIAL" not in "\n".join(pem)

    yaml_block = safety.redact_log_lines(
        ["private_key: |", "  first-secret-line", "  second-secret-line", "next_key: public"]
    )
    assert "first-secret-line" not in "\n".join(yaml_block)
    assert "second-secret-line" not in "\n".join(yaml_block)
    assert yaml_block[-1] == "next_key: public"

    continuation = safety.redact_log_lines(
        ["client_secret:", "first-line", "second-secret-line", "}", "public-after-boundary"]
    )
    assert "first-line" not in "\n".join(continuation)
    assert "second-secret-line" not in "\n".join(continuation)
    assert continuation[-1] == "public-after-boundary"


def test_log_search_filters_only_after_redaction():
    source = (
        ROOT / "cascadeur_side" / "cascadeur_complete" / "handlers" / "system.py"
    ).read_text(encoding="utf-8")
    assert "summarize_log_levels(raw_rows)" in source
    assert '"raw_content_exposed": False' in source
    assert "needle in line.casefold()" not in source


def test_public_log_summary_never_contains_raw_content():
    safety = _load_log_safety()
    hostile = [
        "ERROR client_secret: |2",
        "  first-secret",
        "  second-secret",
        "INFO client_secret = \"\"\"",
        "toml-secret-one",
        "toml-secret-two",
        "\"\"\"",
    ]
    levels = safety.summarize_log_levels(hostile)
    assert levels == ["ERROR", "OTHER", "OTHER", "INFO", "OTHER", "OTHER", "OTHER"]
    assert "secret" not in "\n".join(levels).casefold()


def test_log_tail_read_is_byte_bounded_and_safe_at_truncated_boundary(tmp_path: Path):
    safety = _load_log_safety()
    log = tmp_path / "cascadeur_log.log"
    log.write_bytes(
        b"x" * (safety.MAX_LOG_SCAN_BYTES + safety.MAX_LOG_LINE_BYTES + 100)
        + b"\naccess_token:\n  \"sekret-at-tail\"\n"
    )
    lines, truncated = safety.read_bounded_log_lines(log)
    redacted = list(safety.redact_log_stream(lines))
    assert truncated is True
    assert "sekret-at-tail" not in "\n".join(redacted)
    assert sum(len(line.encode("utf-8")) for line in lines) <= (
        safety.MAX_LOG_SCAN_BYTES + safety.MAX_LOG_LINE_BYTES
    )


def test_production_bridge_contains_no_generic_runtime_executor():
    runtime = (ROOT / "cascadeur_side" / "cascadeur_complete" / "runtime.py").read_text(encoding="utf-8")
    server = (ROOT / "src" / "cascadeur_complete" / "server.py").read_text(encoding="utf-8")
    assert "def call_chain(" not in runtime
    assert "exec(str(args" not in runtime
    assert 'name == "system.csc_query"' not in runtime
    assert 'name == "system.csc_mutate"' not in runtime
    assert 'name == "system.tool_call"' not in runtime
    assert 'name == "system.tool_schema"' not in runtime
    assert '"system.tool_inspect"' not in runtime
    assert '"system.settings_get"' not in runtime
    assert 'name == "system.developer_execute_python"' not in runtime
    assert "def csc_query(" not in server
    assert "def csc_mutate(" not in server
    assert "def tool_call(" not in server
    assert "def developer_execute_python(" not in server
    assert "def cascadeur_tool_inspect(" not in server
    assert "def setting_get(" not in server
