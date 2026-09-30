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


def test_press_prefers_focus_free_patterns_over_a_physical_click():
    from cascadeur_complete.uia import _press

    calls = []

    class Invokable:
        def invoke(self):
            calls.append("invoke")

        def click_input(self):
            calls.append("click")

    class Selectable:
        def invoke(self):
            raise RuntimeError("no InvokePattern")

        def select(self):
            calls.append("select")

        def click_input(self):
            calls.append("click")

    class ClickOnly:
        def click_input(self):
            calls.append("click")

    assert _press(Invokable()) == "invoke"
    assert _press(Selectable()) == "select"
    assert _press(ClickOnly()) == "click"
    assert calls == ["invoke", "select", "click"]
