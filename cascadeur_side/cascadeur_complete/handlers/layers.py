from __future__ import annotations

from ..handler_registry import handler


def _folder_rows(domain, context):
    viewer = domain.layers_viewer()
    rows = []
    for folder_id, _folder in viewer.folders_map().items():
        header = viewer.header(folder_id)
        rows.append(
            {
                "id": context["id_string"](folder_id),
                "name": str(context["read_member"](header, "name")),
                "parent": context["id_string"](context["read_member"](header, "parent")),
            }
        )
    return sorted(rows, key=lambda item: item["id"])


@handler("layer.folder")
def edit_folder(scene, arguments, _request, context):
    domain = context["domain_scene"](scene)
    action = str(arguments["action"])
    changed = []

    def edit(model, _update, scene_updater):
        editor = model.layers_editor()
        viewer = scene_updater.layers_viewer()
        if action == "create":
            if not bool(arguments.get("with_default_layer", True)):
                raise ValueError(
                    "Cascadeur 2026.1.2 does not persist an empty folder; "
                    "with_default_layer must be true"
                )
            parent = context["guid"](arguments["parent_id"]) if arguments.get("parent_id") else viewer.root_id()
            changed.append(
                editor.create_folder(
                    str(arguments["name"]),
                    parent,
                    True,
                    arguments.get("position"),
                )
            )
        elif action == "move":
            item_id = context["guid"](arguments["item_id"])
            parent = context["guid"](arguments["parent_id"]) if arguments.get("parent_id") else viewer.root_id()
            editor.move_item(item_id, parent, arguments.get("position"))
            changed.append(item_id)
        elif action == "rename":
            item_id = context["guid"](arguments["item_id"])
            editor.set_name(str(arguments["name"]), item_id)
            changed.append(item_id)
        else:
            raise ValueError("Unsupported folder action: " + action)

    domain.modify("Cascadeur Complete: layer folder " + action, edit)
    folders = _folder_rows(domain, context)
    changed_id = context["id_string"](changed[0])
    observed = next((item for item in folders if item["id"] == changed_id), None)
    if observed is None:
        raise AssertionError("POSTCONDITION_FAILED: folder/item was not observed")
    if action == "rename" and observed["name"] != str(arguments["name"]):
        raise AssertionError("POSTCONDITION_FAILED: folder name differs")
    if action == "move" and arguments.get("parent_id") and observed["parent"] != str(arguments["parent_id"]):
        raise AssertionError("POSTCONDITION_FAILED: folder parent differs")
    return observed, []
