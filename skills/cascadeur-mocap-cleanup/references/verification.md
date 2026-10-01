# Verification and Reporting

## Metrics

| Metric | Source | Meaning | Good |
|---|---|---|---|
| Foot skate (cm/frame) | `motion_cleanup_analyze` → `feet.skate` | Σ over feet of the worst contact point's horizontal speed × `clip(2 − 2^(h/4), 0, 1)` | clip mean < 0.4, p95 < 1.2 |
| Hot spans | `feet.skate.hot_spans` | 10-frame average above 1 cm/frame | none, or explained |
| Double slides | `feet.survey.double_slides` | both feet low (< 5 cm), moving together > 0.5 cm/frame, ≥ 4 frames | 0 |
| Drags | `feet.survey.drags` | one foot < 1.5 cm high moving > 0.8 cm/frame while the other is planted | 0 |
| Leg reach | `cleanup.solve.leg_over_cm` | worst hip-ankle overshoot after the solve | < 0.3 cm |
| Finger spread / twist range | `fingers.joints` | p1–p99 range relative to rest | knuckles ≲ 2 × limit |
| Index–middle gap | `fingers.gaps.<Side>.IndexMiddle` | signed angle between index and middle proximal bones in the palm plane | median 2–6° |
| Arm inside the body | `motion_cleanup_analyze(checks=["arms"], every_frame=true)` → `arms.<Side>` | frames where an arm vertex is behind the body surface deeper than 0.3 cm, and the deepest value | 0 frames (a single frame < 1 cm is tolerable) |
| Wrist bend | `motion_cleanup_analyze(checks=["hands"])` → `hands.<Side>.wrist` | flexion/extension and deviation p1–p99, frames over the limits, largest per-frame change | within ±40° / ±22° unless the reference shows more |
| Finger spikes | `fingers.joints[*].steps_over_spike` | frames jumping > 10° | 0 (fast flicks may stay) |

Foot skating is the standard metric in motion-generation work; use it to confirm a user-reported range is actually flagged before fixing anything.

## Evidence per stage

- snapshot id, committed write count, `max_position_error` / `max_quaternion_error`, `adjusted_by_rig`;
- re-measured metrics after `interpolation_refresh` (not the predicted ones);
- the file name the stage was saved as.

## Report shape

1. What was processed: "all N frames" only when the metric covered every frame.
2. Before/after table: clip mean, p95, the user's ranges.
3. What changed in the choreography (steps inserted, body end position shift).
4. What remains and why (e.g. body travels beyond leg reach → needs an added step).
5. Files: new name(s); the source untouched.
