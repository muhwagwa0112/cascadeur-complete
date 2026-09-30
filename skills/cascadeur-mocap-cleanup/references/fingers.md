# Fingers: Spread, Twist and Spikes

Hand mocap errors show up as fingers splaying sideways (spread), knuckles rotating around the bone (twist) and single-frame flicks. Curl is the real hand motion and must survive.

## Method (`motion_cleanup_prepare(kind="fingers")`)

For every `(Left|Right)Hand(Thumb|Index|Middle|Ring|Pinky)(1-3)_Box` controller, in local space:

1. Rest pose = median quaternion over the clip. Express each frame relative to rest as ZYX Euler: Z = curl, Y = spread, X = twist (QRT finger box axes).
2. Curl: light median(3) + Gaussian(σ=1) smoothing only.
3. Spread and twist: median(7) + Gaussian(σ=3), then a soft limit `L·tanh(x/L)`:
   - knuckles (segment 1): spread L = Index 15°, Middle 8°, Ring 10°, Pinky 18°; twist 5°;
   - segments 2–3: spread and twist 3°;
   - thumbs: smoothing only (median 3, σ=1), no limit.
4. Joints still jumping more than `spike_deg` (10°) per frame get median(5) + Gaussian(σ=1.5) on all three angles.
5. Write the result as Cascadeur Euler XYZ radians at each controller's existing keys via `rotation_keys`.

## Procedure

1. `motion_cleanup_analyze(checks=["fingers"])` → `flagged` joints (spikes, non-thumb spread range > 15°, index–middle gap > 10°).
2. Collect the 30 finger `_Box` ids (`scene_objects`), then `feature_prepare("auto_posing_state", {"state": "inactive", "ids": [...]})` → commit. With AutoPosing active on fingers, Cascadeur re-derives them after the write and the settled read-back rolls the change back.
3. `motion_cleanup_prepare(kind="fingers")` (optionally `joints=["RightHandMiddle1", ...]`). Check `cleanup.joints[*]`: spread/twist ranges, `max_step_deg`, `steps_over_spike`, and `change_p95_deg` (should stay a few degrees except on the broken joints).
4. Verify the active tab, `change_commit(token, timeout=600)`. The host re-reads a sample in a separate request; a > 0.2° difference means something overrode the write.
5. Refresh interpolation and analyze again.

Tell the user AutoPosing stays off for those controllers: manual finger edits stick, but Cascadeur no longer auto-adjusts them.

## Finger fan: a claw-like index splay (`kind="finger_fan"`)

The spread limit above works around each joint's **own median pose**, so a finger that is splayed for the whole clip looks "normal" to it. On the reference clip the index finger sat 15.5° (left) / 23.5° (right) away from the middle finger in every frame while middle–ring stayed near 0° — the hand read as a claw even after the spread cleanup.

`motion_cleanup_analyze(checks=["fingers"])` reports `gaps` per hand: signed angles between neighbouring proximal bones (`Hand{Finger}1 → 2` joints) in the palm plane (normal from the knuckle line and the wrist→knuckle direction; positive = apart). An index–middle median above 10° is flagged as `"<Side>IndexMiddle gap"`.

`motion_cleanup_prepare(kind="finger_fan", index_gap_deg=3)` rotates each `HandIndex1_Box` about the palm normal (children follow through the box hierarchy) so the gap becomes `index_gap_deg + 0.2 × (slow spread motion)`; frame noise goes. Written as local rotations relative to `Hand_Box` at existing keys (2 controllers × keys).

Verified: `Hand_Box ⊗ local = global` exactly, the joint direction is rigid in the box frame, and +θ about the palm normal widens the gap by exactly θ — check these three on a new rig before trusting the correction.

| | Before | After (re-measured) |
|---|---|---|
| Left index–middle gap | 15.5° (7.8–25.8) | 3.0° (1.5–5.0) |
| Right index–middle gap | 23.5° (11.0–28.2) | 3.0° (0.5–3.9) |

## Reference result

| Joint | Spread | Twist | Jumps > 10°/frame |
|---|---|---|---|
| Right middle knuckle | 53.9° → 12.8° | 62.5° → 7.5° | 13 → 0 |
| Left middle knuckle | 19.4° → 13.3° | 22.9° → 8.3° | 0 → 0 |
| Right index tip | – | – | 27 → 4 (fast flicks kept) |
| Thumbs | – | – | 3 → 0 |

95 % of frames changed by ≤ 3.7° on healthy joints.
