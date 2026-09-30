# Foot Contacts: Whole-Clip Sliding Correction

## Why spot fixes fail

Mocap feet slide because the root keeps moving while a foot is planted, and the foot's own keys drift a little every key. Threshold-based fixes ("pin the foot when it is low and slow") leave three kinds of residue:

- fast slides fall outside the detector (a 12-frame, 22 cm glide on the toes was never classified as contact);
- blending in/out of a pinned span happens while the foot is still on the floor, which creates a new slide at every pin edge;
- sub-threshold creep (0.5–1.5 cm/frame) is never touched, and that is exactly what the user sees last ("still slightly sliding at 600–620 and 960–end").

So solve the whole clip at once.

## The method (`motion_cleanup_prepare(kind="foot_contacts")`)

1. **Soft contact weights.** For each foot's heel (`Foot_Self0Point`), ball (`ToeBase_MainPoint`) and toe (`ToeBase_DirectionPoint`) and each frame transition: `w = clip(2 − 2^(h/4), 0, 1) · exp(−(v/8)²)`, with `h` the height above that point's floor (3rd percentile, cm) and `v` its horizontal speed (cm/frame). No on/off threshold, so nothing falls between the cracks.
2. **One QP over every frame** (OSQP, ~1 s for 1000 frames). Unknowns: a whole-body XZ offset `b(f)` and per-foot XZ offsets `dL(f)`, `dR(f)`. Minimise
   - Σ w · |contact velocity after correction|² (planted points stop moving),
   - acceleration of `b` (weight 2) and of each foot offset (0.5),
   - small anchors on all offsets (0.02) so the result stays close to the capture;

   subject to
   - each leg's hip→ankle distance (`UpLeg_MainPoint`→`Foot_MainPoint`) never exceeding its longest original value (linearised, tightened over up to 6 iterations),
   - per-foot offsets within ±`max_foot_offset_cm` (10).

   Both feet gliding together is absorbed by `b` (root glide); one foot creeping is absorbed by that foot. Transitions migrate to airborne frames by themselves, so no manual blending.
3. **Step pass (`steps=true`).** Re-survey the corrected motion: remaining double slides are cancelled by a carried-forward body offset; a foot still dragging along the floor while the other is planted becomes a short step (sine lift of 3–8 cm, horizontal path unchanged).
4. **Writes.** Every Point of the character gets `b`; points whose names contain `Foot`/`ToeBase` also get their side's offset and lift. Only existing keys are written (per object's own layer). Knees are not written separately — the rig re-derives them; `Leg_AdditionalPoint` ids go into `rig_solved_ids` so the rig's trimming is reported, not treated as failure. Tolerance is 10 cm (IK limb-length trimming).

## Procedure

1. `motion_cleanup_analyze(checks=["feet"], segments=[[600,620],[960,985]])` → baseline `mean_cm_per_frame`, `hot_spans`, `survey`.
2. Confirm the metric sees what the user sees: the reported ranges should have segment means well above the clip mean. If not, stop and discuss before writing.
3. `motion_cleanup_prepare(kind="foot_contacts", segments=[...])`. Inspect `cleanup.predicted.before/after`, `cleanup.solve.leg_over_cm` (< 0.3 good), `foot_offset_max_cm` (≤ 10), `steps.drags_to_steps` (these change the choreography slightly — mention them).
4. Verify the active tab, then `change_commit(token, timeout=900)`. Expect `adjusted_by_rig` entries for leg helper points; a `POSTCONDITION_FAILED` listing non-helper points means the rig refused the pose — roll back (automatic) and lower `max_foot_offset_cm`.
5. `feature_prepare("interpolation_refresh")` → commit, then `motion_cleanup_analyze(checks=["feet"], segments=...)` again. Report the re-measured numbers.

## Reference result (986-frame clip, keys every 3 frames)

| | Before | After solve + steps (re-measured) |
|---|---|---|
| Mean skate (cm/frame) | 0.976 | 0.344 |
| p95 | 3.59 | 1.07 |
| 600–620 | 1.65 | 0.59 |
| 660–690 (pure glide) | 1.45 | 0.24 |
| 960–985 | 1.35 | 0.16 |
| Double slides / drags (survey) | 9 / 13 | 0 / 0 |

Thigh and shin lengths were unchanged; no planted foot rose more than 1.3 cm. What remained (600–620) was the body travelling further than the legs can reach from a fixed foot — fixing that needs a new foot placement (an added step), not a stronger solve.

## Tuning

- `max_foot_offset_cm` (10): lower if the rig trims many foot points; raise only with visual review.
- `body_smoothness` (2): higher = smoother root correction, more residual slide.
- `steps=false` when the user wants choreography untouched (e.g. an intentional foot drag).
- Multi-character scenes: pass `object_ids` for one character; the tool refuses ambiguous names.
