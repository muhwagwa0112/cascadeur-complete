"""SDK-shaped raw mesh reads; these doubles do not qualify native geometry."""
import hashlib
import importlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tests.bridge_support import loaded_bridge


def mesh_boundary(tmp_path, monkeypatch, sample):
    behaviours = SimpleNamespace(get_behaviour_by_name=lambda obj, name: "mesh-behaviour",
        get_behaviour_asset=lambda behaviour, name: name,
        get_behaviour_objects_range=lambda behaviour, name: ["joint-0", "joint-1"])
    viewer = SimpleNamespace(behaviour_viewer=lambda: behaviours, get_object_name=lambda obj: obj)
    mesh = SimpleNamespace(vertices_in_polygon=3,
        vertices=[SimpleNamespace(position_index=i) for i in range(3)])
    dependency = SimpleNamespace(vertices_weights=[
        [SimpleNamespace(index=0, weight=1.)],
        [SimpleNamespace(index=0, weight=.25), SimpleNamespace(index=1, weight=.75)],
        [SimpleNamespace(index=1, weight=1.)]])
    assets = {"mesh": mesh, "mesh_dependency": dependency}
    domain = SimpleNamespace(model_viewer=lambda: viewer,
        layers_viewer=lambda: SimpleNamespace(frames_count=lambda: 3),
        assets_manager=lambda: SimpleNamespace(at=assets.__getitem__))
    calls = []
    def calculate(scene, object_id, frame):
        assert scene is domain and object_id == "mesh-id"
        calls.append(frame)
        return SimpleNamespace(positions=sample(frame))
    # Only the actual installed typed namespace is exposed. The old
    # csc.domain.assets.calc_skinned_mesh path must fail in this boundary.
    csc = SimpleNamespace(domain=SimpleNamespace(calc_skinned_mesh=calculate, assets=SimpleNamespace()))
    context = {"csc": csc, "domain_scene": lambda scene: domain, "object_id": lambda value: value}
    return context, calls


@pytest.mark.parametrize("column_vectors", [False, True])
def test_mesh_sample_uses_typed_namespace_and_keeps_exact_npz_contract(tmp_path, monkeypatch, column_vectors):
    expected = np.asarray([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]],
                           [[0., 0., 2.], [1., 0., 2.], [0., 1., 2.]]], dtype=np.float32)
    def sample(frame):
        values = expected[frame // 2]
        return values[:, :, None] if column_vectors else values
    context, calls = mesh_boundary(tmp_path, monkeypatch, sample)
    with loaded_bridge("mesh_sample_boundary") as (runtime, _):
        monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path)
        handler = importlib.import_module("mesh_sample_boundary.handlers.mesh")
        result, warnings = handler.mesh_sample(object(), {"id": "mesh-id", "frames": [0, 2], "name": "surface"}, {}, context)
    assert calls == [0, 2] and warnings == []
    path = Path(result["path"])
    assert path.parent == tmp_path / "state" / "mesh"
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (result["frame_count"], result["vertex_count"], result["triangle_count"], result["joint_count"]) == (2, 3, 1, 2)
    with np.load(path, allow_pickle=False) as saved:
        np.testing.assert_array_equal(saved["positions"], expected)
        np.testing.assert_array_equal(saved["triangles"], [[0, 1, 2]])
        np.testing.assert_array_equal(saved["frames"], [0, 2])
        np.testing.assert_array_equal(saved["dominant"], [0, 1, 1])
        np.testing.assert_array_equal(saved["weight_offsets"], [0, 1, 3, 4])
        np.testing.assert_array_equal(saved["weight_indices"], [0, 0, 1, 1])
        np.testing.assert_array_equal(saved["weight_values"], [1., .25, .75, 1.])
    assert "native_completion" not in result and "geometry_digest" not in result


@pytest.mark.parametrize("sample", [np.zeros((3, 1, 3)), np.zeros((2, 3, 1)), np.full((3, 3, 1), np.nan)])
def test_mesh_sample_rejects_wrong_layout_coverage_and_nonfinite_without_an_artifact(tmp_path, monkeypatch, sample):
    context, calls = mesh_boundary(tmp_path, monkeypatch, lambda frame: sample)
    with loaded_bridge("mesh_sample_rejection") as (runtime, _):
        monkeypatch.setattr(runtime, "runtime_root", lambda: tmp_path)
        handler = importlib.import_module("mesh_sample_rejection.handlers.mesh")
        with pytest.raises(ValueError, match="INCOMPLETE_CAPTURE"):
            handler.mesh_sample(object(), {"id": "mesh-id", "frames": [0]}, {}, context)
    assert calls == [0]
    assert not (tmp_path / "state" / "mesh").exists()
