from cascadeur_complete.discovery import (
    BASELINE_TOOLS,
    discover_commands,
    discover_installation,
    load_csc_schema,
    schema_counts,
)
from cascadeur_complete.feature_registry import build_registry, registry_json


def test_installed_inventory_matches_baseline_counts():
    schema = load_csc_schema()
    counts = schema_counts(schema)
    assert counts["symbols"] == 372
    assert counts["classes"] == 223
    assert counts["functions"] == 42
    assert counts["methods"] == 1344
    assert counts["values"] == 118
    assert counts["class_members"] == 1462
    assert len(discover_commands()) == 104
    assert len(BASELINE_TOOLS) == 56


def test_registry_has_no_unclassified_or_untested_features():
    records = build_registry(load_csc_schema(), discover_commands(), BASELINE_TOOLS)
    assert len(records) >= 2100
    assert len({record.id for record in records}) == len(records)
    assert all(record.execution_mode for record in records)
    assert all(record.test_ids for record in records)
    assert all(record.evidence_kind for record in records)
    assert all(record.route for record in records)
    assert {"root_motion", "inbetweening", "retargeting", "unreal_livelink"} <= {record.id for record in records}


def test_basic_license_is_explicitly_gated():
    records = build_registry(load_csc_schema(), [], BASELINE_TOOLS, license_name="Basic", scene_available=True)
    by_id = {record.id: record for record in records}
    assert by_id["inbetweening"].state.value == "license_gated"
    assert by_id["retargeting"].execution_mode.value == "Gated"
    assert by_id["unreal_livelink"].state.value == "missing_dependency"


def test_installed_executable_uses_the_2026_1_adapter():
    installation = discover_installation()
    assert installation["version"] == "2026.1.2.0.15343"
    assert installation["compatible"] is True


def test_installation_detection_does_not_require_programfiles_environment(monkeypatch):
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.setenv("PATH", "")

    installation = discover_installation()

    assert installation["executable"] == r"C:\Program Files\Cascadeur\cascadeur.exe"
    assert installation["version"] == "2026.1.2.0.15343"
    assert installation["compatible"] is True


def test_unimplemented_native_route_is_not_reported_available():
    records = build_registry(
        load_csc_schema(),
        discover_commands(),
        BASELINE_TOOLS,
        license_name="Pro",
        scene_available=True,
    )
    by_id = {record.id: record for record in records}
    assert by_id["timeline_set_frame"].state.value == "unhealthy"
    assert by_id["transform_get"].state.value == "unhealthy"
    assert by_id["transform_set"].state.value == "unhealthy"
    assert by_id["auto_posing"].state.value == "unhealthy"
    assert by_id["auto_posing"].adapter_id == "cascadeur_2026_1.tool.AutoPosingTool"
    assert by_id["gui_tool.autoposingtool"].state.value == "ui_only"
    assert by_id["ui_flow_run"].state.value == "available"
    assert by_id["action_invoke"].state.value == "available"
    assert by_id["developer_execute_python"].state.value == "missing_dependency"
    assert by_id["developer_execute_python"].execution_mode.value == "Gated"


def test_live_evidence_is_required_before_adapter_is_available():
    records = build_registry(
        load_csc_schema(),
        discover_commands(),
        BASELINE_TOOLS,
        license_name="Pro",
        scene_available=True,
        verified_features={"timeline_set_frame", "transform_get"},
    )
    by_id = {record.id: record for record in records}
    assert by_id["timeline_set_frame"].state.value == "available"
    assert by_id["timeline_set_frame"].verification.value == "verified_live"
    assert by_id["transform_get"].last_verified_version == "2026.1.2.0.15343"
    assert by_id["transform_set"].state.value == "unhealthy"


def test_registry_json_uses_schema_v2():
    records = build_registry(load_csc_schema(), discover_commands(), BASELINE_TOOLS)
    payload = __import__("json").loads(registry_json(records))
    assert payload["schema_version"] == 2
    assert payload["unclassified_count"] == 0
