"""Read a character's motion from the live scene and prepare whole-clip cleanup writes.

The math lives in ``motion_cleanup``; this module samples every frame through
the bridge (pinned to one scene so a tab switch fails the read instead of
mixing scenes), keeps writes on each object's existing keys, and hands the
result to the protected ``position_keys`` / ``rotation_keys`` changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from . import motion_cleanup as mc
from .models import Operation

if TYPE_CHECKING:
    from .service import CascadeurService

READ_CHUNK = 25


class CleanupError(RuntimeError):
    pass


class CleanupWorkflow:
    def __init__(self, service: CascadeurService, rig: mc.FootRig | None = None):
        self.service = service
        self.client = service.client
        self.rig = rig or mc.FootRig()
        self.scene_id: str | None = None

    # -- bridge reads -----------------------------------------------------

    def _read(self, feature_id: str, operations: list[Operation], timeout: float = 120.0) -> Any:
        # Not pinned through the request's scene_id: a pinned request for an
        # inactive tab makes the host activate tabs. Every read is compared
        # against the first one instead.
        result = self.client.execute(feature_id, operations, timeout=timeout)
        if not result.ok:
            raise CleanupError(f"{operations[0].name} failed: {result.error_code}: {result.error_message}")
        if self.scene_id is None:
            self.scene_id = result.scene_id
        elif result.scene_id != self.scene_id:
            raise CleanupError("The active scene tab changed while the motion was being read; nothing was prepared")
        return result.result

    def frame_count(self) -> int:
        timeline = self._read("timeline_get", [Operation(name="timeline.get")])
        return int(timeline["frames_count"])

    def objects(self, object_ids: list[str] | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._read(
                "object_search", [Operation(name="scene.objects", arguments={"offset": offset, "limit": 400})]
            )
            batch = page["items"] if isinstance(page, dict) else page
            items += batch
            if len(batch) < 400:
                break
            offset += 400
        if object_ids:
            wanted = {str(item) for item in object_ids}
            items = [item for item in items if item["id"] in wanted]
        return items

    def by_name(self, objects: list[dict[str, Any]], names: list[str]) -> dict[str, str]:
        found: dict[str, list[str]] = {}
        for item in objects:
            if item["name"] in names:
                found.setdefault(item["name"], []).append(item["id"])
        missing = sorted(set(names) - set(found))
        if missing:
            raise CleanupError("Rig points not found: " + ", ".join(missing))
        ambiguous = sorted(name for name, ids in found.items() if len(ids) > 1)
        if ambiguous:
            raise CleanupError(
                "Several characters share these names; pass object_ids for one character: " + ", ".join(ambiguous)
            )
        return {name: ids[0] for name, ids in found.items()}

    def key_frames(self, ids: list[str]) -> dict[str, list[int]]:
        details = self._read("object_properties", [Operation(name="object.properties", arguments={"ids": ids})])
        layers = self._read("layer_list", [Operation(name="layer.list")])
        keys_by_layer = {layer["id"]: [int(frame) for frame in layer["keys"]] for layer in layers}
        out = {}
        for row in details["items"]:
            layer_id = row.get("layer_id")
            if layer_id is None or layer_id not in keys_by_layer:
                raise CleanupError(f"{row['id']} is not on an animation layer")
            out[row["id"]] = keys_by_layer[layer_id]
        return out

    def sample(self, ids: list[str], frames: int, space: str = "global") -> dict[str, dict[str, np.ndarray]]:
        """Positions and quaternions (wxyz) for every frame; the first read refreshes interpolation."""
        positions = {object_id: np.zeros((frames, 3)) for object_id in ids}
        quaternions = {object_id: np.zeros((frames, 4)) for object_id in ids}
        for start in range(0, frames, READ_CHUNK):
            chunk = list(range(start, min(frames, start + READ_CHUNK)))
            operations = [
                Operation(
                    name="animation.transform_get",
                    arguments={"ids": ids, "frame": frame, "space": space, **({"refresh": True} if frame == 0 else {})},
                )
                for frame in chunk
            ]
            rows = self._read("transform_get", operations, timeout=240)
            rows = rows if len(operations) > 1 else [{"result": rows}]
            for frame, row in zip(chunk, rows, strict=True):
                for item in row["result"]:
                    positions[item["id"]][frame] = item["position"]
                    # Points carry a position only; rotation is null for them.
                    if item.get("rotation"):
                        quaternions[item["id"]][frame] = item["rotation"]["quaternion_wxyz"]
        return {"position": positions, "quaternion": quaternions}

    # -- feet ---------------------------------------------------------------

    def _points(self, object_ids):
        objects = self.objects(object_ids)
        points = [item for item in objects if item["type"] == "Point"]
        self.by_name(points, self.rig.required())
        names = [item["name"] for item in points]
        duplicated = sorted({name for name in names if names.count(name) > 1})
        if duplicated:
            raise CleanupError(
                "Several characters share point names; pass object_ids for one character: " + ", ".join(duplicated[:5])
            )
        return {item["name"]: item["id"] for item in points}

    def _feet_track(self, object_ids):
        points = self._points(object_ids)
        frames = self.frame_count()
        sampled = self.sample(list(points.values()), frames)
        track = {name: sampled["position"][object_id] for name, object_id in points.items()}
        return points, frames, track

    def analyze_feet(self, object_ids=None, segments=None) -> dict[str, Any]:
        _, frames, track = self._feet_track(object_ids)
        skate, _ = mc.skate_per_frame(track, self.rig)
        found = mc.survey(track, self.rig)
        found.pop("_info")
        return {"frames": frames, "skate": mc.skate_summary(skate, segments), "survey": found}

    def prepare_feet(
        self,
        object_ids=None,
        params: mc.ContactParams | None = None,
        steps: bool = True,
        segments=None,
        ttl: float = 900.0,
    ) -> dict[str, Any]:
        points, frames, track = self._feet_track(object_ids)
        skate_before, floor = mc.skate_per_frame(track, self.rig)
        solved = mc.solve_contacts(track, self.rig, params)
        moved = mc.apply_offsets(track, self.rig, solved["body"], solved["feet"])
        stage2 = None
        if steps:
            stage2 = mc.step_pass(moved, self.rig)
            moved = mc.apply_offsets(moved, self.rig, stage2["body"], None, stage2["lifts"])
        skate_after, _ = mc.skate_per_frame(moved, self.rig, floor)
        keys = self.key_frames(list(points.values()))
        writes = []
        for name, object_id in points.items():
            delta = np.abs(moved[name] - track[name]).max(axis=1)
            for frame in keys[object_id]:
                if 0 <= frame < frames and delta[frame] > 1e-4:
                    writes.append({"id": object_id, "frame": frame, "position": [float(v) for v in moved[name][frame]]})
        if not writes:
            raise CleanupError("Nothing to correct: the solve left every key where it was")
        rig_solved = [object_id for name, object_id in points.items() if self.rig.is_rig_solved(name)]
        report = {
            "kind": "foot_contacts",
            "frames": frames,
            "write_count": len(writes),
            "object_count": len({item["id"] for item in writes}),
            "predicted": {
                "before": mc.skate_summary(skate_before, segments),
                "after": mc.skate_summary(skate_after, segments),
            },
            "solve": {
                "leg_over_cm": solved["leg_over_cm"],
                "iterations": solved["iterations"],
                "body_offset_max_cm": round(float(np.linalg.norm(solved["body"], axis=1).max()), 1),
                "foot_offset_max_cm": {
                    side: round(float(np.linalg.norm(solved["feet"][side], axis=1).max()), 1) for side in mc.SIDES
                },
            },
            "steps": None
            if stage2 is None
            else {
                "double_slides_cancelled": stage2["double_slides_cancelled"],
                "drags_to_steps": stage2["drags_to_steps"],
            },
            "rig_solved_ids": rig_solved,
        }
        prepared = self.service.prepare_change(
            "position_keys",
            "animation.position_keys_set",
            {"writes": writes, "space": "global", "tolerance_cm": 10.0, "rig_solved_ids": rig_solved},
            ttl,
        )
        prepared["cleanup"] = report
        return prepared

    # -- fingers -----------------------------------------------------------

    def _finger_boxes(self, object_ids, joints):
        objects = self.objects(object_ids)
        boxes = {item["name"]: item["id"] for item in objects if mc.finger_parts(item["name"])}
        names = [item["name"] for item in objects if mc.finger_parts(item["name"])]
        if len(names) != len(set(names)):
            raise CleanupError("Several characters share finger names; pass object_ids for one character")
        if joints:
            wanted = {joint if joint.endswith("_Box") else joint + "_Box" for joint in joints}
            boxes = {name: object_id for name, object_id in boxes.items() if name in wanted}
        if not boxes:
            raise CleanupError("No finger controllers (e.g. RightHandIndex1_Box) found")
        return boxes

    def _finger_quaternions(self, object_ids, joints):
        boxes = self._finger_boxes(object_ids, joints)
        frames = self.frame_count()
        sampled = self.sample(list(boxes.values()), frames, space="local")
        return boxes, frames, {name: sampled["quaternion"][object_id] for name, object_id in boxes.items()}

    def analyze_fingers(self, object_ids=None, spike_deg: float = 10.0) -> dict[str, Any]:
        _, frames, quaternions = self._finger_quaternions(object_ids, None)
        rows = mc.finger_stats(quaternions, spike_deg)
        # Thumbs swing wide by design; only spikes flag them.
        flagged = [
            row
            for row in rows
            if row["steps_over_spike"] or (row["spread_range_deg"] > 15 and "Thumb" not in row["joint"])
        ]
        return {"frames": frames, "joints": rows, "flagged": [row["joint"] for row in flagged]}

    def prepare_fingers(self, object_ids=None, joints=None, spike_deg: float = 10.0, ttl: float = 900.0):
        boxes, frames, quaternions = self._finger_quaternions(object_ids, joints)
        cleaned = mc.finger_cleanup(quaternions, spike_deg)
        keys = self.key_frames(list(boxes.values()))
        writes = []
        for name, euler in cleaned["euler_xyz"].items():
            object_id = boxes[name]
            for frame in keys[object_id]:
                if 0 <= frame < frames:
                    writes.append(
                        {
                            "id": object_id,
                            "frame": frame,
                            "rotation_euler_xyz_radians": [float(v) for v in euler[frame]],
                        }
                    )
        prepared = self.service.prepare_change(
            "rotation_keys", "animation.rotation_keys_set", {"writes": writes, "space": "local"}, ttl
        )
        prepared["cleanup"] = {
            "kind": "fingers",
            "frames": frames,
            "write_count": len(writes),
            "joints": cleaned["joints"],
            "note": "Switch AutoPosing off for these controllers first (auto_posing_state inactive); "
            "otherwise the rig re-derives the fingers and the settled read-back rolls the change back.",
        }
        return prepared
