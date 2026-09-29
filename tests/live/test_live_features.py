"""Live product-feature scenarios; opt in with CASCADEUR_LIVE=1 and a running Cascadeur."""

from __future__ import annotations

import os

import pytest

from cascadeur_complete.live_validation import SCENARIOS, LiveSession, run_scenario

pytestmark = pytest.mark.skipif(os.environ.get("CASCADEUR_LIVE") != "1", reason="requires live Cascadeur")


@pytest.fixture(scope="module")
def session():
    return LiveSession()


@pytest.mark.parametrize("feature_id", sorted(SCENARIOS))
def test_live_feature(session, feature_id):
    row = run_scenario(session, feature_id)
    assert row["verified"], row
