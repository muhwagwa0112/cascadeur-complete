import json
from dataclasses import replace

from cascadeur_complete import verification
from cascadeur_complete.product_catalog import PRODUCT_CATALOG, SUPPORTED_BUILD
from cascadeur_complete.verification import LiveEvidenceStore

FEATURE_ID = "timeline_set_frame"
ADAPTER_ID = "cascadeur_2026_1.timeline.set_frame"
POSTCONDITION = "frame_equals_requested"
LIVE_TEST_ID = "tests/test_verification.py::test_live_evidence_is_append_only_and_requires_all_postconditions"
FIXTURE_ID = "pytest:tmp_path"


def _enable_test_live_binding(monkeypatch):
    feature = replace(
        PRODUCT_CATALOG.by_id[FEATURE_ID],
        live_test_id=LIVE_TEST_ID,
        fixture_id=FIXTURE_ID,
    )
    catalog = replace(
        PRODUCT_CATALOG,
        features=tuple(feature if item.id == FEATURE_ID else item for item in PRODUCT_CATALOG.features),
    )
    monkeypatch.setattr(verification, "PRODUCT_CATALOG", catalog)


def _record(store: LiveEvidenceStore, **overrides):
    arguments = {
        "version": SUPPORTED_BUILD,
        "adapter_id": ADAPTER_ID,
        "operation": "timeline.set_frame",
        "scene_id": "scene-1",
        "evidence": [{"kind": "postcondition", "detail": POSTCONDITION, "ok": True}],
        "license_name": "Basic",
        "observed_postconditions": {POSTCONDITION: True},
        "test_id": LIVE_TEST_ID,
        "fixture_id": FIXTURE_ID,
    }
    arguments.update(overrides)
    return store.record(FEATURE_ID, **arguments)


def test_live_evidence_is_append_only_and_requires_all_postconditions(tmp_path, monkeypatch):
    _enable_test_live_binding(monkeypatch)
    store = LiveEvidenceStore(tmp_path / "live_evidence.json")
    rejected = _record(store, observed_postconditions={}, evidence=[])
    accepted = _record(store)

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert len(payload["records"]) == 2
    assert rejected["valid"] is False
    assert accepted["valid"] is True
    assert store.verified_features(SUPPORTED_BUILD, license_name="Basic") == {FEATURE_ID}


def test_live_evidence_is_invalidated_by_version_license_dependency_or_binding(tmp_path, monkeypatch):
    _enable_test_live_binding(monkeypatch)
    store = LiveEvidenceStore(tmp_path / "live_evidence.json")
    _record(store)

    assert store.verified_features("2026.1.2.0.other", license_name="Basic") == set()
    assert store.verified_features(SUPPORTED_BUILD, license_name="Pro") == set()
    assert store.verified_features(SUPPORTED_BUILD, license_name="Basic", dependencies={"plugin": True}) == set()

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["records"][0]["binding"]["source_hash"] = "stale"
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    assert store.verified_features(SUPPORTED_BUILD, license_name="Basic") == set()


def test_legacy_or_incomplete_evidence_cannot_mark_feature_supported(tmp_path, monkeypatch):
    _enable_test_live_binding(monkeypatch)
    path = tmp_path / "live_evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "features": {FEATURE_ID: {"ok": True, "version": SUPPORTED_BUILD}},
            }
        ),
        encoding="utf-8",
    )
    store = LiveEvidenceStore(path)
    assert store.verified_features(SUPPORTED_BUILD, license_name="Basic") == set()

    incomplete = _record(store, license_name="unknown")
    assert incomplete["valid"] is False
    assert store.verified_features(SUPPORTED_BUILD) == set()


def test_catalog_without_live_test_and_fixture_cannot_be_supported(tmp_path):
    store = LiveEvidenceStore(tmp_path / "live_evidence.json")
    record = _record(store)
    assert record["valid"] is False
    assert store.verified_features(SUPPORTED_BUILD, license_name="Basic") == set()
