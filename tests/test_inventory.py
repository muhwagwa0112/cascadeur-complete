from cascadeur_complete.discovery import (
    BASELINE_TOOLS,
    discover_commands,
    discover_installation,
    load_csc_schema,
    schema_counts,
)
from cascadeur_complete.feature_registry import build_registry, registry_json
from cascadeur_complete.product_catalog import PRODUCT_CATALOG, SUPPORTED_BUILD


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


def test_product_catalog_core_matches_registry_contract():
    assert PRODUCT_CATALOG.product_version == "2026.1.2"
    assert PRODUCT_CATALOG.supported_build == SUPPORTED_BUILD
    assert len(PRODUCT_CATALOG.core_features) == 153
    assert {item.id for item in PRODUCT_CATALOG.core_features} == {
        spec.feature_id for spec in __import__(
            "cascadeur_complete.feature_registry", fromlist=["CORE_FEATURES"]
        ).CORE_FEATURES
    }
    assert all(item.source_url.startswith("https://cascadeur.com/") for item in PRODUCT_CATALOG.features)
    assert all(
        item.operation and item.route
        for item in PRODUCT_CATALOG.core_features
        if item.implementation_status == "implemented"
    )
    for feature_id in ("tool_inspect", "settings_get"):
        item = PRODUCT_CATALOG.by_id[feature_id]
        assert item.implementation_status == "unsupported"
        assert item.operation is None and item.route is None and item.adapter_id is None


def test_implemented_features_reference_real_test_nodes():
    root = __import__("pathlib").Path(__file__).parents[1]
    implemented = [item for item in PRODUCT_CATALOG.core_features if item.implementation_status == "implemented"]
    assert len(implemented) == 106
    for feature in implemented:
        assert feature.adapter_id
        assert feature.postconditions
        assert feature.contract_test_ids
        for node_id in feature.contract_test_ids:
            relative, test_name = node_id.split("::", 1)
            source = (root / relative).read_text(encoding="utf-8")
            assert f"def {test_name}(" in source


def test_official_documentation_gaps_are_explicit():
    gaps = PRODUCT_CATALOG.official_gaps
    assert len(gaps) == 70
    assert all(item.implementation_status == "not_implemented" for item in gaps)
    assert all(item.route is None and item.adapter_id is None for item in gaps)
    assert {
        "official_gap.silhouette",
        "official_gap.root_constraint",
        "official_gap.node_editor",
        "official_gap.ballistic_ghosts",
        "official_gap.open_autosave",
        "official_gap.rig_json_import",
        "official_gap.filament_environment_map",
    } <= {item.id for item in gaps}


def test_discovered_inventory_is_separate_from_product_catalog():
    records = build_registry(load_csc_schema(), discover_commands(), BASELINE_TOOLS)
    assert len(records) >= 2100
    assert len({record.id for record in records}) == len(records)
    assert all(record.execution_mode for record in records)
    assert all(record.test_ids for record in records)
    assert all(record.route for record in records)
    assert all(
        "::" in test_id and not test_id.startswith(("contract::", "live::"))
        for record in records
        for test_id in record.test_ids
    )
    product_ids = {item.id for item in PRODUCT_CATALOG.features}
    discovered_ids = {item.id for item in records if item.family == "csc_api"}
    assert not (product_ids & discovered_ids)
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


def test_registry_json_uses_schema_v3_and_reports_truth_layer_gaps():
    records = build_registry(load_csc_schema(), discover_commands(), BASELINE_TOOLS)
    payload = __import__("json").loads(registry_json(records))
    assert payload["schema_version"] == 3
    assert payload["product_catalog"] == {
        "product_version": "2026.1.2",
        "supported_build": "2026.1.2.0.15343",
        "feature_count": 223,
        "core_feature_count": 153,
        "official_gap_count": 70,
    }
    # 70 official documentation gaps plus 38 legacy core entries that have
    # neither an adapter nor an explicit gate evidence record.
    assert payload["unclassified_count"] == 108


def test_wrong_build_marks_product_and_discovered_inventory_unsupported():
    records = build_registry(
        load_csc_schema(), discover_commands(), BASELINE_TOOLS, version_name="2026.1.3.0.99999"
    )
    assert records
    assert all(record.state.value == "unsupported_version" for record in records)
    assert all(record.execution_mode.value == "Gated" for record in records)


def test_windows_version_resource_matches_project_version():
    root = __import__("pathlib").Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version_info = (root / "packaging" / "windows_version_info.txt").read_text(encoding="utf-8")
    assert 'version = "0.1.0"' in pyproject
    assert "StringStruct('ProductVersion', '0.1.0')" in version_info
    assert "prodvers=(0, 1, 0, 0)" in version_info
