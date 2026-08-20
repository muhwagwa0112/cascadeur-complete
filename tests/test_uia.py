from cascadeur_complete.uia import _is_cascadeur_window_title, _scene_id_from_window_title


def test_cascadeur_window_title_is_exact_and_does_not_match_codex_tasks():
    assert _is_cascadeur_window_title("Cascadeur")
    assert _is_cascadeur_window_title("C:/Scenes/walk.casc - Cascadeur")
    assert not _is_cascadeur_window_title("Implement Cascadeur MCP - Codex")
    assert not _is_cascadeur_window_title("Cascadeur Complete")


def test_window_title_maps_to_bridge_scene_identity():
    assert (
        _scene_id_from_window_title("C:/Program Files/Cascadeur/samples/Cube.casc - Cascadeur")
        == "fe0b06613aaf5156deda2b49"
    )
    assert _scene_id_from_window_title("Cascadeur") is None
