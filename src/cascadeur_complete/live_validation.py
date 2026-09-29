"""Live validation harness for the version-pinned product catalog.

Each product feature that can run on this machine has one scenario.  A scenario
opens a pinned fixture, drives the feature through the public service contract
(`execute` for reads, `prepare_change`/`commit_change` for mutations), and the
service records live evidence only when every catalog postcondition is
observed.  Fixtures are opened read-only: the first protected change branches
the scene into a snapshot working copy, so installed samples are never written.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .service import CascadeurService

CASCADEUR_ROOT = Path(os.environ.get("CASCADEUR_ROOT", r"C:\Program Files\Cascadeur"))
FIXTURES: dict[str, Path | None] = {
    "fixture.none": None,
    "fixture.empty_scene": None,
    "fixture.sample.cube": CASCADEUR_ROOT / "samples" / "Cube.casc",
    "fixture.sample.cascy": CASCADEUR_ROOT / "samples" / "Cascy.casc",
    "fixture.sample.backflip": CASCADEUR_ROOT / "samples" / "Backflip_animation.casc",
    "fixture.test.three_joints": CASCADEUR_ROOT / "resources/scripts/test_data/casc/three_joints.casc",
    "fixture.test.minichar_joints": CASCADEUR_ROOT / "resources/scripts/test_data/casc/minichar_joints.casc",
    "fixture.test.proto_additional": CASCADEUR_ROOT
    / "resources/scripts/test_data/casc/proto_joints_with_additional_joints.casc",
    "fixture.test.spine": CASCADEUR_ROOT / "resources/scripts/test_data/casc/spine.casc",
    "fixture.test.one_joint_rigged": CASCADEUR_ROOT / "resources/scripts/test_data/casc/one_joint_rigged.casc",
    "fixture.test.hinge": CASCADEUR_ROOT / "resources/scripts/test_data/casc/hinge_minimal_interpolation.casc",
    "fixture.test.legs": CASCADEUR_ROOT / "resources/scripts/test_data/casc/legs.casc",
}
LIVE_TEST_TEMPLATE = "tests/live/test_live_features.py::test_live_feature[{feature_id}]"


class LiveValidationError(RuntimeError):
    pass


def _dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


class LiveSession:
    def __init__(self, service: CascadeurService | None = None, output_root: Path | None = None):
        self.service = service or CascadeurService()
        self.output_root = output_root or (self.service.paths.root / "live-validation")
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.current_fixture: str | None = None

    # -- primitives -------------------------------------------------------
    def status(self) -> dict[str, Any]:
        result = _dump(self.service.refresh_live(timeout=90))
        if not result.get("ok"):
            raise LiveValidationError(f"status failed: {result.get('error_code')}: {result.get('error_message')}")
        return result["result"]

    def read(self, feature_id: str, operation: str, arguments: dict[str, Any] | None = None, *, timeout=120):
        result = _dump(self.service.execute(feature_id, operation, arguments or {}, timeout=timeout))
        if not result.get("ok"):
            raise LiveValidationError(
                f"{feature_id} {operation} failed: {result.get('error_code')}: {result.get('error_message')}"
            )
        return result["result"]

    def change(self, feature_id: str, operation: str, arguments: dict[str, Any] | None = None, *, timeout=240):
        prepared = _dump(self.service.prepare_change(feature_id, operation, arguments or {}, 900))
        if not prepared.get("ok"):
            raise LiveValidationError(
                f"prepare {feature_id} failed: {prepared.get('error_code')}: {prepared.get('error_message')}"
            )
        committed = _dump(self.service.commit_change(prepared["confirmation_token"], timeout))
        if not committed.get("ok"):
            raise LiveValidationError(
                f"commit {feature_id} failed: {committed.get('error_code')}: {committed.get('error_message')}"
            )
        return committed["result"]

    def output(self, name: str) -> str:
        path = self.output_root / f"{int(time.time() * 1000)}-{name}"
        return str(path)

    # -- fixtures ---------------------------------------------------------
    def use_fixture(self, fixture_id: str) -> dict[str, Any]:
        if fixture_id not in FIXTURES:
            raise LiveValidationError(f"Unknown fixture {fixture_id}")
        if fixture_id == "fixture.none":
            return self.status()
        if fixture_id == "fixture.empty_scene":
            self.change("scene_new", "scene.new", {})
            self.current_fixture = fixture_id
            return self.status()
        path = FIXTURES[fixture_id]
        assert path is not None
        if not path.is_file():
            raise LiveValidationError(f"Fixture file is missing: {path}")
        self.change("scene_open", "scene.open", {"path": str(path)})
        self.current_fixture = fixture_id
        return self.status()

    # -- scene helpers ----------------------------------------------------
    def objects(self) -> list[dict[str, Any]]:
        return self.read("object_search", "scene.objects", {"offset": 0, "limit": 1000})["items"]

    def object_named(self, name: str) -> str:
        matches = [item["id"] for item in self.objects() if item["name"] == name]
        if len(matches) != 1:
            raise LiveValidationError(f"Expected exactly one object named {name!r}, found {len(matches)}")
        return matches[0]

    def layers(self) -> list[dict[str, Any]]:
        return self.read("layer_list", "layer.list")

    def verified(self, feature_id: str) -> bool:
        return feature_id in self.service.evidence_store.verified_features(
            self.service._version_name, license_name=self.service._license_name
        )


@dataclass(frozen=True)
class Scenario:
    feature_id: str
    fixture_id: str
    run: Callable[[LiveSession], Any]

    @property
    def live_test_id(self) -> str:
        return LIVE_TEST_TEMPLATE.format(feature_id=self.feature_id)


SCENARIOS: dict[str, Scenario] = {}


def scenario(feature_id: str, fixture_id: str):
    def register(function: Callable[[LiveSession], Any]) -> Callable[[LiveSession], Any]:
        if feature_id in SCENARIOS:
            raise RuntimeError(f"Duplicate live scenario for {feature_id}")
        SCENARIOS[feature_id] = Scenario(feature_id, fixture_id, function)
        return function

    return register


def run_scenario(session: LiveSession, feature_id: str) -> dict[str, Any]:
    item = SCENARIOS[feature_id]
    started = time.monotonic()
    if session.current_fixture != item.fixture_id or item.fixture_id == "fixture.empty_scene":
        session.use_fixture(item.fixture_id)
    detail = item.run(session)
    verified = session.verified(feature_id)
    return {
        "feature_id": feature_id,
        "fixture_id": item.fixture_id,
        "verified": verified,
        "seconds": round(time.monotonic() - started, 1),
        "detail": detail,
    }


from . import live_scenarios  # noqa: E402,F401  (registers SCENARIOS)
