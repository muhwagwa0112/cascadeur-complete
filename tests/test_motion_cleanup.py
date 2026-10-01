from __future__ import annotations

import numpy as np
import pytest

from cascadeur_complete import motion_cleanup as mc
from cascadeur_complete.cleanup_workflow import CleanupError, CleanupWorkflow
from cascadeur_complete.models import ResultEnvelope

FRAMES = 120
RIG = mc.FootRig()


def _standing_track(slide=(40, 80), speed=0.6):
    """Both feet planted; the whole character glides along X between the slide frames."""
    shift = np.zeros(FRAMES)
    for f in range(1, FRAMES):
        shift[f] = shift[f - 1] + (speed if slide[0] <= f <= slide[1] else 0.0)
    track = {}
    for side, x in (("Left", -10.0), ("Right", 10.0)):
        layout = {
            RIG.heel.format(side=side): (x, 0.0, -5.0),
            RIG.ball.format(side=side): (x, 0.0, 10.0),
            RIG.toe.format(side=side): (x, 0.0, 18.0),
            RIG.ankle.format(side=side): (x, 8.0, 0.0),
            RIG.hip.format(side=side): (x, 90.0, 0.0),
            f"{side}Leg_AdditionalPoint": (x, 50.0, 5.0),
        }
        for name, (px, py, pz) in layout.items():
            positions = np.tile([px, py, pz], (FRAMES, 1)).astype(float)
            positions[:, 0] += shift
            track[name] = positions
    track["Hips_MainPoint"] = np.tile([0.0, 95.0, 0.0], (FRAMES, 1)) + np.c_[shift, np.zeros(FRAMES), np.zeros(FRAMES)]
    return track


def test_skate_is_zero_when_planted_and_positive_while_gliding():
    still, _ = mc.skate_per_frame(_standing_track(speed=0.0), RIG)
    gliding, _ = mc.skate_per_frame(_standing_track(), RIG)
    assert still.max() == 0.0
    assert gliding[50] == pytest.approx(1.2)  # 0.6 cm/frame on each planted foot
    summary = mc.skate_summary(gliding, [(40, 80)], hot_threshold=0.5)
    assert summary["segments"][0]["mean"] > 1.0
    assert summary["hot_spans"] and summary["hot_spans"][0]["first"] <= 45


def test_survey_finds_double_slide():
    found = mc.survey(_standing_track(), RIG)
    assert len(found["double_slides"]) == 1
    assert found["double_slides"][0]["first"] <= 41 and found["double_slides"][0]["last"] >= 79
    assert found["drags"] == []


def test_contact_solve_cancels_a_glide_with_the_body_offset():
    track = _standing_track()
    solved = mc.solve_contacts(track, RIG)
    moved = mc.apply_offsets(track, RIG, solved["body"], solved["feet"])
    before, floor = mc.skate_per_frame(track, RIG)
    after, _ = mc.skate_per_frame(moved, RIG, floor)
    assert after.mean() < 0.2 * before.mean()
    assert solved["leg_over_cm"] < 0.3
    # Legs keep their reach: every hip-ankle distance stays within the original maximum.
    for side in mc.SIDES:
        hip, ankle = moved[RIG.hip.format(side=side)], moved[RIG.ankle.format(side=side)]
        original = np.linalg.norm(track[RIG.ankle.format(side=side)] - track[RIG.hip.format(side=side)], axis=1)
        assert np.linalg.norm(ankle - hip, axis=1).max() <= original.max() + 0.3


def test_apply_offsets_moves_feet_by_their_own_offset_only():
    track = _standing_track(speed=0.0)
    body = np.zeros((FRAMES, 2))
    feet = {"Left": np.tile([1.0, 0.0], (FRAMES, 1)), "Right": np.zeros((FRAMES, 2))}
    lifts = {"Left": np.full(FRAMES, 2.0), "Right": np.zeros(FRAMES)}
    moved = mc.apply_offsets(track, RIG, body, feet, lifts)
    assert moved["LeftFoot_Self0Point"][0, 0] == pytest.approx(-9.0)
    assert moved["LeftFoot_Self0Point"][0, 1] == pytest.approx(2.0)
    assert moved["LeftUpLeg_MainPoint"][0, 0] == pytest.approx(-10.0)
    assert moved["LeftLeg_AdditionalPoint"][0, 0] == pytest.approx(-10.0)
    assert RIG.is_rig_solved("LeftLeg_AdditionalPoint")


def test_step_pass_turns_a_one_foot_drag_into_a_step():
    track = _standing_track(speed=0.0)
    for name in RIG.contacts("Right") + [RIG.ankle.format(side="Right")]:
        for f in range(51, FRAMES):
            track[name][f, 0] += min(f - 50, 10) * 1.5
    result = mc.step_pass(track, RIG)
    assert len(result["drags_to_steps"]) == 1
    step = result["drags_to_steps"][0]
    assert step["side"] == "Right" and step["lift_cm"] >= 3
    assert result["lifts"]["Right"].max() >= 3 and result["lifts"]["Left"].max() == 0


def _finger_track():
    from scipy.spatial.transform import Rotation

    t = np.linspace(0, 4 * np.pi, FRAMES)
    curl = 30 * np.sin(t)
    spread = 40 * np.sin(3 * t)  # far outside the knuckle limit
    spread[60] += 25  # single-frame spike
    rotation = Rotation.from_euler("ZYX", np.radians(np.stack([curl, spread, np.zeros(FRAMES)], 1)))
    xyzw = rotation.as_quat()
    return {"RightHandMiddle1_Box": xyzw[:, [3, 0, 1, 2]], "RightHandMiddle1_Joint": xyzw[:, [3, 0, 1, 2]]}


def test_finger_cleanup_limits_spread_and_removes_spikes_but_keeps_curl():
    result = mc.finger_cleanup(_finger_track())
    assert list(result["euler_xyz"]) == ["RightHandMiddle1_Box"]
    row = result["joints"][0]
    assert row["spread_range_deg"][1] <= 2 * mc.FINGER_SPREAD_LIMIT["Middle"]
    assert row["spread_range_deg"][1] < row["spread_range_deg"][0] / 3
    assert row["steps_over_spike"][1] == 0
    stats = mc.finger_stats(_finger_track())
    assert stats[0]["joint"] == "RightHandMiddle1"


def test_finger_parts():
    assert mc.finger_parts("LeftHandThumb3_Box") == ("Left", "Thumb", 3)
    assert mc.finger_parts("LeftHand_Box") is None


class _FakeClient:
    """Answers the reads CleanupWorkflow issues from a synthetic scene."""

    def __init__(self, track, keys, scene_ids=None):
        self.names = list(track)
        self.ids = {name: f"id-{index}" for index, name in enumerate(self.names)}
        self.track = track
        self.keys = keys
        self.scene_ids = list(scene_ids or [])

    def _scene(self):
        return self.scene_ids.pop(0) if len(self.scene_ids) > 1 else (self.scene_ids[0] if self.scene_ids else "s1")

    def execute(self, feature_id, operations, **_kwargs):
        results = [self._one(item) for item in operations]
        result = results[0] if len(results) == 1 else [{"result": item} for item in results]
        return ResultEnvelope(
            ok=True, feature_id=feature_id, execution_mode="Native", scene_id=self._scene(), result=result
        )

    def _one(self, operation):
        args = operation.arguments
        if operation.name == "timeline.get":
            return {"frames_count": FRAMES}
        if operation.name == "scene.objects":
            return {"items": [{"id": self.ids[name], "name": name, "type": "Point"} for name in self.names]}
        if operation.name == "object.properties":
            return {"items": [{"id": object_id, "layer_id": "layer-1"} for object_id in args["ids"]]}
        if operation.name == "layer.list":
            return [{"id": "layer-1", "keys": self.keys}]
        if operation.name == "animation.transform_get":
            by_id = {self.ids[name]: name for name in self.names}
            return [
                {
                    "id": object_id,
                    "position": self.track[by_id[object_id]][args["frame"]].tolist(),
                    "rotation": None,
                }
                for object_id in args["ids"]
            ]
        raise AssertionError(operation.name)


class _FakeService:
    def __init__(self, client):
        self.client = client
        self.prepared = None

    def prepare_change(self, feature_id, operation_name, arguments, ttl):
        self.prepared = (feature_id, operation_name, arguments)
        return {"ok": True, "confirmation_token": "token"}


def test_prepare_feet_writes_only_existing_keys_and_marks_rig_solved_points():
    keys = list(range(0, FRAMES, 3))
    client = _FakeClient(_standing_track(), keys)
    service = _FakeService(client)
    prepared = CleanupWorkflow(service).prepare_feet()
    feature_id, operation, arguments = service.prepared
    assert (feature_id, operation) == ("position_keys", "animation.position_keys_set")
    assert {item["frame"] for item in arguments["writes"]} <= set(keys)
    assert set(arguments["rig_solved_ids"]) == {
        client.ids[name] for name in client.names if name.endswith("Leg_AdditionalPoint")
    }
    report = prepared["cleanup"]
    assert report["predicted"]["after"]["mean_cm_per_frame"] < report["predicted"]["before"]["mean_cm_per_frame"]


def test_reads_fail_when_the_active_tab_changes():
    client = _FakeClient(_standing_track(), [0], scene_ids=["s1", "s2"])
    with pytest.raises(CleanupError, match="active scene tab changed"):
        CleanupWorkflow(_FakeService(client)).analyze_feet()


def _splayed_hand(splay_deg=20.0):
    """Right hand, palm facing down, fingers along +Z; the index is splayed away from the middle finger."""
    from scipy.spatial.transform import Rotation

    frames = 60
    joints = {"RightHand": np.zeros((frames, 3))}
    for finger, x in (("Index", 0.0), ("Middle", 2.0), ("Ring", 4.0), ("Pinky", 6.0)):
        joints[f"RightHand{finger}1"] = np.tile([x, 0.0, 10.0], (frames, 1))
        joints[f"RightHand{finger}2"] = np.tile([x, 0.0, 14.0], (frames, 1))
    normal = mc.finger_gaps(joints, "Right")["normal"][0]
    wobble = splay_deg + 3 * np.sin(np.linspace(0, 6, frames))
    index_box = Rotation.from_rotvec(normal[None, :] * np.radians(wobble)[:, None])
    bone = np.array([0.0, 0.0, 4.0])
    joints["RightHandIndex2"] = joints["RightHandIndex1"] + index_box.apply(bone)
    identity = np.tile([1.0, 0.0, 0.0, 0.0], (frames, 1))
    return joints, identity, index_box.as_quat()[:, [3, 0, 1, 2]]


def test_finger_gaps_see_a_static_index_splay():
    joints, _, _ = _splayed_hand()
    gaps = mc.gap_summary(mc.finger_gaps(joints, "Right")["gaps"])
    assert 15 < gaps["IndexMiddle"]["median_deg"] < 25
    assert abs(gaps["MiddleRing"]["median_deg"]) < 0.1


def test_close_index_gap_rotates_the_knuckle_to_the_target_gap():
    from scipy.spatial.transform import Rotation

    joints, hand, index = _splayed_hand()
    closed = mc.close_index_gap(joints, hand, index, "Right", target_deg=3.0)
    new_index = Rotation.from_quat(hand[:, [1, 2, 3, 0]]) * Rotation.from_euler("xyz", closed["euler_xyz"])
    old_index = Rotation.from_quat(index[:, [1, 2, 3, 0]])
    moved = dict(joints)
    base = joints["RightHandIndex1"]
    moved["RightHandIndex2"] = base + (new_index * old_index.inv()).apply(joints["RightHandIndex2"] - base)
    after = mc.finger_gaps(moved, "Right")["gaps"]["IndexMiddle"]
    assert np.abs(after - closed["gap_after"]).max() < 1e-6
    assert abs(np.median(after) - 3.0) < 0.5 and after.max() < 5.0


def _arm_through_torso(frames=40):
    """Shoulder beside a vertical torso; the forearm swings through the torso in the middle frames."""
    shoulder = np.tile([20.0, 140.0, 0.0], (frames, 1))
    elbow = np.tile([22.0, 115.0, 0.0], (frames, 1))
    swing = np.clip(1 - np.abs(np.arange(frames) - frames / 2) / 8, 0, 1)
    wrist = np.tile([22.0, 92.0, 0.0], (frames, 1)) + np.outer(swing, [-20.0, 4.0, 0.0])
    return shoulder, elbow, wrist


def test_linear_interpolation_rows_blend_the_two_neighbouring_keys():
    spread = mc.linear_interpolation(np.arange(7), np.array([0, 3, 6]))
    dense = spread.toarray()
    assert np.allclose(dense.sum(1), 1.0)
    assert np.allclose(dense[3], [0, 1, 0])
    assert np.allclose(dense[4], [0, 2 / 3, 1 / 3])


def test_arm_solve_lifts_the_forearm_out_of_a_torso_capsule_and_keeps_bone_lengths():
    shoulder, elbow, wrist = _arm_through_torso()
    frames = len(shoulder)
    body = {"Spine_Rigid": (np.tile([0.0, 90.0, 0.0], (frames, 1)), np.tile([0.0, 120.0, 0.0], (frames, 1)), 9.0)}
    params = mc.ArmParams(margin=0.5, allow=0.1)
    surface = mc.CapsuleSurface(shoulder, elbow, wrist, wrist, (3.5, 3.3), body, params)
    solved = mc.solve_arm_offsets(shoulder, elbow, wrist, surface, params)
    assert solved["depth_before"].max() > 3.0
    assert solved["depth_after"].max() < 0.3
    moved_elbow, moved_wrist = elbow + solved["elbow"], wrist + solved["wrist"]
    upper = np.linalg.norm(moved_elbow - shoulder, axis=1) - np.linalg.norm(elbow - shoulder, axis=1)
    fore = np.linalg.norm(moved_wrist - moved_elbow, axis=1) - np.linalg.norm(wrist - elbow, axis=1)
    assert np.abs(upper).max() < 0.5 and np.abs(fore).max() < 0.5
    # Frames far from the contact stay where they were.
    assert np.linalg.norm(solved["wrist"][0]) < 0.5 and np.linalg.norm(solved["wrist"][-1]) < 0.5
    summary = mc.depth_summary(solved["depth_before"], allow=0.3)
    assert summary["penetrating_samples"] > 0 and summary["spans"]


def _sphere_body(radius=10.0, rings=12, segments=24):
    vertices = [[0.0, radius, 0.0]]
    for ring in range(1, rings):
        phi = np.pi * ring / rings
        for segment in range(segments):
            theta = 2 * np.pi * segment / segments
            vertices.append(
                [radius * np.sin(phi) * np.cos(theta), radius * np.cos(phi), radius * np.sin(phi) * np.sin(theta)]
            )
    vertices.append([0.0, -radius, 0.0])
    triangles = []
    for segment in range(segments):
        triangles.append([0, 1 + (segment + 1) % segments, 1 + segment])
    for ring in range(rings - 2):
        for segment in range(segments):
            a = 1 + ring * segments + segment
            b = 1 + ring * segments + (segment + 1) % segments
            triangles += [[a, b, a + segments], [b, b + segments, a + segments]]
    last = len(vertices) - 1
    base = 1 + (rings - 2) * segments
    for segment in range(segments):
        triangles.append([last, base + segment, base + (segment + 1) % segments])
    return np.array(vertices), np.array(triangles)


def test_mesh_surface_pushes_a_hand_out_of_the_body_mesh():
    body, triangles = _sphere_body()
    frames = 12
    shoulder = np.tile([14.0, 30.0, 0.0], (frames, 1))
    elbow = np.tile([16.0, 12.0, 0.0], (frames, 1))
    dip = np.clip(1 - np.abs(np.arange(frames) - frames / 2) / 3, 0, 1)
    wrist = np.tile([14.0, 0.0, 0.0], (frames, 1)) + np.outer(dip, [-8.0, 0.0, 0.0])
    hand_cloud = np.array([[0.0, 0.0, 0.0], [-1.0, -1.0, 0.5], [-1.0, 1.0, -0.5], [-2.0, 0.0, 0.0]])
    positions = np.zeros((frames, len(body) + len(hand_cloud), 3), dtype=np.float32)
    for f in range(frames):
        positions[f, : len(body)] = body
        positions[f, len(body) :] = wrist[f] + hand_cloud
    dominant = np.array([0] * len(body) + [1] * len(hand_cloud))
    joints = np.array(["Spine", "LeftHand"])
    params = mc.ArmParams()
    surface = mc.MeshSurface(positions, triangles, dominant, joints, "Left", shoulder, elbow, wrist, params)
    zero = np.zeros((2, frames, 3))
    before = surface.depth(zero)
    assert before.max() > 3.0 and before[0] == 0.0
    solved = mc.solve_arm_offsets(shoulder, elbow, wrist, surface, params)
    assert solved["depth_after"].max() <= params.allow + 0.2
    assert np.linalg.norm(solved["wrist"], axis=1).max() < 12.0
