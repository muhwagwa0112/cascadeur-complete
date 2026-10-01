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
# An index-middle gap this wide for most of the clip reads as a claw.
FAN_FLAG_DEG = 10.0
# Hand controllers: the wrist point, then the two that orient the hand around it.
HAND_POINTS = ("Hand_MainPoint", "Hand_DirectionPoint", "Hand_AdditionalPoint")
# Arm controllers moved by the arm clearance solve (elbow group, then wrist group).
ARM_POINTS = (
    "ForeArm_MainPoint",
    "ForeArm_AdditionalPoint",
    "Hand_MainPoint",
    "Hand_DirectionPoint",
    "Hand_AdditionalPoint",
)


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

    def sample(
        self, ids: list[str], frames: int, space: str = "global", only: list[int] | None = None
    ) -> dict[str, dict[str, np.ndarray]]:
        """Positions and quaternions (wxyz) per frame (rows of unread frames stay zero).

        Reads every frame, or just ``only``; the first read refreshes interpolation.
        """
        positions = {object_id: np.zeros((frames, 3)) for object_id in ids}
        quaternions = {object_id: np.zeros((frames, 4)) for object_id in ids}
        wanted = list(range(frames)) if only is None else [int(frame) for frame in only]
        for start in range(0, len(wanted), READ_CHUNK):
            chunk = wanted[start : start + READ_CHUNK]
            operations = [
                Operation(
                    name="animation.transform_get",
                    arguments={
                        "ids": ids,
                        "frame": frame,
                        "space": space,
                        **({"refresh": True} if frame == wanted[0] else {}),
                    },
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
        result = {"frames": frames, "joints": rows, "flagged": [row["joint"] for row in flagged]}
        try:
            fan = self._fan_track(object_ids)
        except CleanupError as exc:
            result["gaps_unavailable"] = str(exc)
            return result
        result["gaps"] = {side: mc.gap_summary(mc.finger_gaps(fan[2], side)["gaps"]) for side in mc.SIDES}
        for side, pairs in result["gaps"].items():
            if abs(pairs["IndexMiddle"]["median_deg"]) > FAN_FLAG_DEG:
                result["flagged"].append(f"{side}IndexMiddle gap")
        return result

    # -- finger fan --------------------------------------------------------

    def _fan_track(self, object_ids):
        objects = self.objects(object_ids)
        joint_names = [name for side in mc.SIDES for name in mc.fan_joint_names(side)]
        box_names = [f"{side}{suffix}" for side in mc.SIDES for suffix in ("Hand_Box", "HandIndex1_Box")]
        joints = self.by_name([item for item in objects if item["type"] == "Joint"], joint_names)
        boxes = self.by_name([item for item in objects if item["type"] == "Box"], box_names)
        frames = self.frame_count()
        sampled = self.sample(list(joints.values()) + list(boxes.values()), frames, space="global")
        positions = {name: sampled["position"][object_id] for name, object_id in joints.items()}
        rotations = {name: sampled["quaternion"][object_id] for name, object_id in boxes.items()}
        return boxes, frames, positions, rotations

    def prepare_finger_fan(self, object_ids=None, target_deg: float = 3.0, keep: float = 0.2, ttl: float = 900.0):
        boxes, frames, positions, rotations = self._fan_track(object_ids)
        index_ids = [boxes[f"{side}HandIndex1_Box"] for side in mc.SIDES]
        keys = self.key_frames(index_ids)
        writes = []
        sides = {}
        for side in mc.SIDES:
            closed = mc.close_index_gap(
                positions,
                rotations[f"{side}Hand_Box"],
                rotations[f"{side}HandIndex1_Box"],
                side,
                target_deg,
                keep,
            )
            object_id = boxes[f"{side}HandIndex1_Box"]
            for frame in keys[object_id]:
                if 0 <= frame < frames:
                    writes.append(
                        {
                            "id": object_id,
                            "frame": frame,
                            "rotation_euler_xyz_radians": [float(v) for v in closed["euler_xyz"][frame]],
                        }
                    )
            sides[side] = {
                "index_middle_gap": {
                    "before": mc.gap_summary({"gap": closed["gap_before"]})["gap"],
                    "after": mc.gap_summary({"gap": closed["gap_after"]})["gap"],
                },
                "index_rotation_deg": closed["rotation_deg"],
            }
        prepared = self.service.prepare_change(
            "rotation_keys", "animation.rotation_keys_set", {"writes": writes, "space": "local"}, ttl
        )
        prepared["cleanup"] = {"kind": "finger_fan", "frames": frames, "write_count": len(writes), "sides": sides}
        return prepared

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

    # -- arm clearance -------------------------------------------------------

    def _arm_points(self, object_ids):
        objects = self.objects(object_ids)
        # The shoulder point anchors the solve; only ARM_POINTS are written.
        names = [f"{s}{name}" for s in mc.SIDES for name in ("Arm_MainPoint", *ARM_POINTS)]
        points = self.by_name([item for item in objects if item["type"] == "Point"], names)
        meshes = [item for item in objects if item["type"] == "Mesh Object"]
        if len(meshes) != 1:
            raise CleanupError(f"Expected one character mesh, found {len(meshes)}; pass object_ids including the mesh")
        return points, meshes[0]["id"]

    def _arm_mesh(self, object_ids, name: str, every_frame: bool = False):
        """Arm controller positions and the skinned mesh at the arm controllers' keys (or every frame)."""
        points, mesh_id = self._arm_points(object_ids)
        frames = self.frame_count()
        keys = self.key_frames(list(points.values()))
        written = [points[f"{s}{point}"] for s in mc.SIDES for point in ARM_POINTS]
        common = sorted(set.intersection(*[set(keys[item]) for item in written]))
        common = [frame for frame in common if 0 <= frame < frames]
        if len(common) < 3:
            raise CleanupError("The arm controllers share fewer than three keys; reduce and bake the clip first")
        keys = np.array(common)
        if every_frame:
            common = list(range(frames))
        sampled = self.sample(list(points.values()), frames, only=common)
        track = {name_: sampled["position"][object_id][common] for name_, object_id in points.items()}
        result = self._read(
            "mesh_sample",
            [Operation(name="animation.mesh_sample", arguments={"id": mesh_id, "frames": common, "name": name})],
            timeout=600,
        )
        mesh = np.load(result["path"])
        return points, np.array(common), track, mesh, keys

    def _arm_surface(self, mesh, track, side, params):
        return mc.MeshSurface(
            mesh["positions"],
            mesh["triangles"],
            mesh["dominant"],
            mesh["joints"],
            side,
            track[f"{side}Arm_MainPoint"],
            track[f"{side}ForeArm_MainPoint"],
            track[f"{side}Hand_MainPoint"],
            params,
        )

    def analyze_arms(
        self, object_ids=None, params: mc.ArmParams | None = None, every_frame: bool = False
    ) -> dict[str, Any]:
        """Where each arm's mesh is inside the rest of the body, measured on the skinned mesh.

        Samples the arm controllers' key frames, or every frame to check the
        interpolated frames between keys as well.
        """
        params = params or mc.ArmParams()
        _, frames, track, mesh, _ = self._arm_mesh(object_ids, "arms_analyze", every_frame)
        zero = np.zeros((2, len(frames), 3))
        return {
            "sampled_frames": len(frames),
            **{
                side: mc.depth_summary(self._arm_surface(mesh, track, side, params).depth(zero), frames, params.allow)
                for side in mc.SIDES
            },
        }

    def prepare_arm_clearance(self, object_ids=None, params: mc.ArmParams | None = None, ttl: float = 900.0):
        params = params or mc.ArmParams()
        # The surface covers every frame so a path that cuts through the body
        # between two clear keys is seen; the offsets are solved at the keys.
        points, frames, track, mesh, keys = self._arm_mesh(object_ids, "arms_prepare", every_frame=True)
        at_keys = np.searchsorted(frames, keys)
        spread = mc.linear_interpolation(frames, keys)
        spacing = float(np.median(np.diff(keys)))
        writes = []
        sides = {}
        for side in mc.SIDES:
            solved = mc.solve_arm_offsets(
                track[f"{side}Arm_MainPoint"][at_keys],
                track[f"{side}ForeArm_MainPoint"][at_keys],
                track[f"{side}Hand_MainPoint"][at_keys],
                self._arm_surface(mesh, track, side, params),
                params,
                spacing,
                spread,
            )
            for name in ARM_POINTS:
                offset = solved["elbow"] if name.startswith("ForeArm") else solved["wrist"]
                object_id = points[f"{side}{name}"]
                for index, frame in enumerate(keys):
                    if np.abs(offset[index]).max() > 1e-3:
                        position = track[f"{side}{name}"][at_keys[index]] + offset[index]
                        writes.append({"id": object_id, "frame": int(frame), "position": [float(v) for v in position]})
            sides[side] = {
                "before": mc.depth_summary(solved["depth_before"], frames, params.allow),
                "predicted_after": mc.depth_summary(solved["depth_after"], frames, params.allow),
                "elbow_offset_max_cm": round(float(np.linalg.norm(solved["elbow"], axis=1).max()), 1),
                "wrist_offset_max_cm": round(float(np.linalg.norm(solved["wrist"], axis=1).max()), 1),
                "iterations": solved["iterations"],
            }
        report = {
            "kind": "arm_clearance",
            "sampled_frames": len(frames),
            "write_count": len(writes),
            "sides": sides,
        }
        if not writes:
            report["note"] = "No arm vertex is inside the body beyond the allowed overlap; nothing to write."
            return {"ok": True, "cleanup": report}
        rig_solved = [points[f"{s}ForeArm_AdditionalPoint"] for s in mc.SIDES]
        prepared = self.service.prepare_change(
            "position_keys",
            "animation.position_keys_set",
            {"writes": writes, "space": "global", "tolerance_cm": 10.0, "rig_solved_ids": rig_solved},
            ttl,
        )
        prepared["cleanup"] = report
        return prepared

    # -- hand styling --------------------------------------------------------

    def _hand_track(self, object_ids):
        """Joint positions, box orientations and hand points for both hands on every frame."""
        objects = self.objects(object_ids)
        fingers = ("Thumb", *mc.FOUR_FINGERS)
        joint_names = [
            name
            for side in mc.SIDES
            for name in (
                f"{side}ForeArm",
                f"{side}Hand",
                *[f"{side}Hand{finger}{index}" for finger in fingers for index in (1, 2, 3, 4)],
            )
        ]
        box_names = [
            name
            for side in mc.SIDES
            for name in (
                f"{side}Hand_Box",
                *[f"{side}Hand{finger}{index}_Box" for finger in fingers for index in (1, 2, 3)],
            )
        ]
        point_names = [f"{side}{name}" for side in mc.SIDES for name in HAND_POINTS]
        joints = self.by_name([item for item in objects if item["type"] == "Joint"], joint_names)
        boxes = self.by_name([item for item in objects if item["type"] == "Box"], box_names)
        points = self.by_name([item for item in objects if item["type"] == "Point"], point_names)
        frames = self.frame_count()
        sampled = self.sample([*joints.values(), *boxes.values(), *points.values()], frames)
        return {
            "frames": frames,
            "joints": {name: sampled["position"][object_id] for name, object_id in joints.items()},
            "boxes": {name: sampled["quaternion"][object_id] for name, object_id in boxes.items()},
            "points": {name: sampled["position"][object_id] for name, object_id in points.items()},
            "box_ids": boxes,
            "point_ids": points,
        }

    def analyze_hands(self, object_ids=None) -> dict[str, Any]:
        """Wrist bend ranges and how the hands split between open, half-closed and fist."""
        track = self._hand_track(object_ids)
        out: dict[str, Any] = {"frames": track["frames"]}
        for side in mc.SIDES:
            hand = mc.HandGeometry(track["joints"], track["boxes"], side)
            closure = hand.closure()
            out[side] = {
                "wrist": mc.wrist_summary(hand),
                "closure_deg": [round(float(item)) for item in np.percentile(closure, [5, 50, 95])],
            }
        return out

    def prepare_wrists(self, object_ids=None, params: mc.WristParams | None = None, ttl: float = 900.0):
        track = self._hand_track(object_ids)
        frames = track["frames"]
        rotated = [track["point_ids"][f"{side}{name}"] for side in mc.SIDES for name in HAND_POINTS[1:]]
        keys = self.key_frames(rotated)
        writes = []
        sides = {}
        for side in mc.SIDES:
            softened = mc.soften_wrist(mc.HandGeometry(track["joints"], track["boxes"], side), params)
            wrist = track["points"][f"{side}{HAND_POINTS[0]}"]
            for name in HAND_POINTS[1:]:
                object_id = track["point_ids"][f"{side}{name}"]
                moved = wrist + softened["rotation"].apply(track["points"][f"{side}{name}"] - wrist)
                for frame in keys[object_id]:
                    if 0 <= frame < frames and softened["turned_deg"][frame] > 0.3:
                        writes.append({"id": object_id, "frame": frame, "position": [float(v) for v in moved[frame]]})
            sides[side] = softened["report"]
        report = {"kind": "wrist_soften", "frames": frames, "write_count": len(writes), "sides": sides}
        if not writes:
            report["note"] = "Both wrists already stay inside the limits; nothing to write."
            return {"ok": True, "cleanup": report}
        prepared = self.service.prepare_change(
            "position_keys",
            "animation.position_keys_set",
            {"writes": writes, "space": "global", "tolerance_cm": 1.0},
            ttl,
        )
        prepared["cleanup"] = report
        return prepared

    def prepare_hand_pose(self, object_ids=None, params: mc.HandPoseParams | None = None, ttl: float = 900.0):
        track = self._hand_track(object_ids)
        frames = track["frames"]
        finger_boxes = {
            name: object_id for name, object_id in track["box_ids"].items() if not name.endswith("Hand_Box")
        }
        keys = self.key_frames(list(finger_boxes.values()))
        writes = []
        sides = {}
        for side in mc.SIDES:
            posed = mc.pose_hand(mc.HandGeometry(track["joints"], track["boxes"], side), params)
            for suffix, euler in posed["euler_xyz"].items():
                object_id = finger_boxes[side + suffix]
                for frame in keys[object_id]:
                    if 0 <= frame < frames:
                        writes.append(
                            {
                                "id": object_id,
                                "frame": frame,
                                "rotation_euler_xyz_radians": [float(v) for v in euler[frame]],
                            }
                        )
            sides[side] = posed["report"]
        prepared = self.service.prepare_change(
            "rotation_keys", "animation.rotation_keys_set", {"writes": writes, "space": "local"}, ttl
        )
        prepared["cleanup"] = {
            "kind": "hand_pose",
            "frames": frames,
            "write_count": len(writes),
            "sides": sides,
            "note": "Finger AutoPosing must be off for these controllers (auto_posing_state inactive).",
        }
        return prepared

    # -- resting hands -------------------------------------------------------

    def prepare_hand_rest(self, object_ids=None, near_cm: float = 14.0, touch_cm: float = 0.4, ttl: float = 900.0):
        """Bring hands that hover near the body while holding still into contact with it."""
        points, frames, track, mesh, _ = self._arm_mesh(object_ids, "hand_rest", every_frame=True)
        keys = self.key_frames(list(points.values()))
        writes = []
        sides = {}
        for side in mc.SIDES:
            contact = mc.hand_body_clearance(
                mesh["positions"], mesh["triangles"], mesh["dominant"], mesh["joints"], side
            )
            settled = mc.settle_resting_hand(
                track[f"{side}Arm_MainPoint"],
                track[f"{side}ForeArm_MainPoint"],
                track[f"{side}Hand_MainPoint"],
                contact,
                near_cm,
                touch_cm,
            )
            for name in ARM_POINTS:
                offset = settled["elbow"] if name.startswith("ForeArm") else settled["wrist"]
                object_id = points[f"{side}{name}"]
                for frame in keys[object_id]:
                    if 0 <= frame < len(frames) and np.abs(offset[frame]).max() > 1e-3:
                        position = track[f"{side}{name}"][frame] + offset[frame]
                        writes.append({"id": object_id, "frame": int(frame), "position": [float(v) for v in position]})
            sides[side] = {"resting_spans": settled["spans"]}
        report = {"kind": "hand_rest", "frames": len(frames), "write_count": len(writes), "sides": sides}
        if not writes:
            report["note"] = "No hand rests near the body with a gap to close; nothing to write."
            return {"ok": True, "cleanup": report}
        rig_solved = [points[f"{s}ForeArm_AdditionalPoint"] for s in mc.SIDES]
        prepared = self.service.prepare_change(
            "position_keys",
            "animation.position_keys_set",
            {"writes": writes, "space": "global", "tolerance_cm": 10.0, "rig_solved_ids": rig_solved},
            ttl,
        )
        prepared["cleanup"] = report
        return prepared
