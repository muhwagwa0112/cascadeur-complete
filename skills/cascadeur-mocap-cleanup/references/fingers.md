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

1. `motion_cleanup_analyze(checks=["fingers"])` → `flagged` joints (spikes or spread range > 15°).
2. Collect the 30 finger `_Box` ids (`scene_objects`), then `feature_prepare("auto_posing_state", {"state": "inactive", "ids": [...]})` → commit. With AutoPosing active on fingers, Cascadeur re-derives them after the write and the settled read-back rolls the change back.
3. `motion_cleanup_prepare(kind="fingers")` (optionally `joints=["RightHandMiddle1", ...]`). Check `cleanup.joints[*]`: spread/twist ranges, `max_step_deg`, `steps_over_spike`, and `change_p95_deg` (should stay a few degrees except on the broken joints).
4. Verify the active tab, `change_commit(token, timeout=600)`. The host re-reads a sample in a separate request; a > 0.2° difference means something overrode the write.
5. Refresh interpolation and analyze again.

Tell the user AutoPosing stays off for those controllers: manual finger edits stick, but Cascadeur no longer auto-adjusts them.

## Reference result

| Joint | Spread | Twist | Jumps > 10°/frame |
|---|---|---|---|
| Right middle knuckle | 53.9° → 12.8° | 62.5° → 7.5° | 13 → 0 |
| Left middle knuckle | 19.4° → 13.3° | 22.9° → 8.3° | 0 → 0 |
| Right index tip | – | – | 27 → 4 (fast flicks kept) |
| Thumbs | – | – | 3 → 0 |

95 % of frames changed by ≤ 3.7° on healthy joints.
