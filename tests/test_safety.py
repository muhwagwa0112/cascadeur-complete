import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from cascadeur_complete.models import Operation
from cascadeur_complete.paths import RuntimePaths
from cascadeur_complete.safety import ChangeManager, SafetyError, validate_local_input_path, validate_local_path


def test_path_policy_rejects_unc_device_relative_and_overwrite(tmp_path):
    with pytest.raises(SafetyError):
        validate_local_path(r"\\server\share\file.fbx")
    with pytest.raises(SafetyError):
        validate_local_path(r"\\?\C:\file.fbx")
    with pytest.raises(SafetyError):
        validate_local_path("relative.fbx")
    existing = tmp_path / "exists.fbx"
    existing.write_text("x", encoding="utf-8")
    with pytest.raises(SafetyError):
        validate_local_path(str(existing))
    assert validate_local_path(str(existing), allow_overwrite=True) == existing.resolve()


def test_input_path_requires_an_existing_local_file(tmp_path):
    existing = tmp_path / "scene.casc"
    existing.write_bytes(b"CASC")
    assert validate_local_input_path(str(existing)) == existing.resolve()
    with pytest.raises(SafetyError):
        validate_local_input_path(str(tmp_path / "missing.casc"))
    with pytest.raises(SafetyError):
        validate_local_input_path(r"\\server\share\scene.casc")


def test_confirmation_token_is_bound_to_scene_revision_and_selection(tmp_path):
    manager = ChangeManager(RuntimePaths.discover(tmp_path / "runtime"), secret=b"x" * 32)
    token = manager.prepare(
        feature_id="object_delete",
        scene_id="scene-1",
        scene_revision="rev-1",
        selection_fingerprint="sel-1",
        operation=Operation(name="object.delete", arguments={"ids": ["1"]}),
        impact={"count": 1},
        backup_path="snapshot.casc",
    )
    with pytest.raises(SafetyError):
        manager.consume(token.token, scene_id="scene-1", scene_revision="rev-2", selection_fingerprint="sel-1")
    consumed = manager.consume(token.token, scene_id="scene-1", scene_revision="rev-1", selection_fingerprint="sel-1")
    assert consumed.used
    with pytest.raises(SafetyError):
        manager.load(token.token)


def test_expired_token_is_rejected(tmp_path):
    manager = ChangeManager(RuntimePaths.discover(tmp_path / "runtime"), secret=b"y" * 32)
    token = manager.prepare(
        feature_id="x",
        scene_id=None,
        scene_revision=None,
        selection_fingerprint=None,
        operation=Operation(name="x"),
        impact={},
        backup_path=None,
        ttl=30,
    )
    path = manager.paths.tokens / f"{token.token.split('.', 1)[0]}.json"
    payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    payload["expires_at"] = time.time() - 1
    # Signature no longer matches, which is also a mandatory rejection.
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")
    with pytest.raises(SafetyError):
        manager.load(token.token)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("feature_id", "status"),
        ("scene_id", "scene-2"),
        ("scene_revision", "rev-2"),
        ("selection_fingerprint", "sel-2"),
        ("operation", {"name": "system.developer_execute_python", "arguments": {"code": "x"}}),
        ("impact", {"count": 999}),
        ("backup_path", "other.casc"),
        ("expires_at", 9_999_999_999.0),
    ],
)
def test_confirmation_token_rejects_any_approval_payload_tampering(tmp_path, field, replacement):
    manager = ChangeManager(RuntimePaths.discover(tmp_path / "runtime"), secret=b"z" * 32)
    token = manager.prepare(
        feature_id="object_delete",
        scene_id="scene-1",
        scene_revision="rev-1",
        selection_fingerprint="sel-1",
        operation=Operation(name="object.delete", arguments={"ids": ["1"]}),
        impact={"count": 1},
        backup_path="snapshot.casc",
    )
    nonce = token.token.split(".", 1)[0]
    path = manager.paths.tokens / f"{nonce}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SafetyError):
        manager.load(token.token)


def test_confirmation_token_can_be_consumed_exactly_once_concurrently(tmp_path):
    manager = ChangeManager(RuntimePaths.discover(tmp_path / "runtime"), secret=b"r" * 32)
    token = manager.prepare(
        feature_id="object_delete",
        scene_id="scene-1",
        scene_revision="rev-1",
        selection_fingerprint="sel-1",
        operation=Operation(name="object.delete", arguments={"ids": ["1"]}),
        impact={"count": 1},
        backup_path="snapshot.casc",
    )

    def consume():
        try:
            manager.consume(
                token.token,
                scene_id="scene-1",
                scene_revision="rev-1",
                selection_fingerprint="sel-1",
            )
            return True
        except SafetyError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: consume(), range(2)))
    assert sorted(outcomes) == [False, True]
