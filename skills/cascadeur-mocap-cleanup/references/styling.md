# Styling: Matching the Dance, Not Just Cleaning the Capture

Cleanup removes capture errors. Styling decides what the motion is *supposed* to look like, and that comes from the reference, not from the data. Do this after the cleanup passes and only when the user asks for more than cleanup ("make it fit the dance", "hands look wrong").

## 1. Get the reference and read the intent

Ask for the source video when there is one. For a capture made from a video, `duration × fps` equals the clip's frame count, so frame `f` is time `f / fps` — compare frame for frame.

What to look for (take stills at ~0.5 s steps; a browser tab with the video paused and seeked is enough):

- **What the hands are.** In the reference clip the character wears big cat-paw mittens: the hands are paws from the first frame to the last. The capture read the mittens as human fingers and produced half-curled "claws", splayed fingers and open hands that are not in the choreography. Gloves, props and sleeves all do this.
- **Where the hands rest.** A paw on the hip is captured a mitten's thickness away from the body; on a bare-handed character it becomes a hand floating beside the hip.
- **Which bends are choreography.** Wrist "knocks" are part of this dance; a 90° wrist is not.

Timing: measure before touching it. Correlate the video's frame-difference energy with the clip's joint speeds (lag should be 0) and compare the raw capture's joint speeds and 1–3 Hz bounce power with the cleaned clip. On the reference clip the cleanup kept lag 0, hand-speed correlation 0.94 and the same bounce power, so the rhythm was already right and only the hands and wrists needed work. Do not "sharpen the rhythm" without such evidence.

## 2. Look at the motion yourself

`viewport_capture` costs a snapshot per image. For a whole clip, sample the skinned mesh once (`mesh_sample`, every frame) and render it on the host:

```bash
python scripts/mesh_preview.py <state/mesh/name.npz> body  out.png --frames 0:986:14
python scripts/mesh_preview.py <state/mesh/name.npz> hands out.png --frames 10:986:42 --side Left
```

`scripts/mesh_preview.py` (numpy + Pillow) draws ~10 images per second: full-body sheets facing the character and hand close-ups (thumb side, back, palm). Re-sample after every commit and compare before/after sheets; judge the pictures, not only the numbers.

## 3. Wrists (`motion_cleanup_prepare(kind="wrist_soften")`)

`motion_cleanup_analyze(checks=["hands"])` reports flexion/extension and deviation ranges and the frames over the limits. The prepare smooths both angles (σ 1.5 frames) and squeezes them under soft limits (untouched up to 20° flexion / 10° deviation, never beyond `wrist_flex_limit_deg` 40 / `wrist_deviation_limit_deg` 22) by rotating `Hand_DirectionPoint` and `Hand_AdditionalPoint` about `Hand_MainPoint`; the hand box, joints and fingers follow rigidly (verified: a 25° turn of the points turned the box by exactly 25°). Raise the limits when the reference shows deliberate wrist flicks.

Reference clip: left wrist −66°…+68° flexion and up to 71° deviation → ±40° and ±22°.

## 4. Hand shape (`motion_cleanup_prepare(kind="hand_pose")`)

Replaces the captured finger rotations with coordinated poses on the line between a relaxed open hand (MCP 12°, PIP 18°, DIP 10°) and a loose fist (78°, 95°, 55°):

- hinges parallel to the hand's lateral axis, a small cascade from index to pinky, fingers gathered when open;
- the thumb blends from its relaxed pose to one wrapped over the index and middle fingers (a small optimisation places the tip; check `thumb_fit`);
- by default the capture's own open/close timing drives it (smoothed, with `hand_contrast` pushing half-closed hands toward open or fist);
- `hand_fixed_closure` holds one shape for the whole clip — use it when the reference shows one hand shape (0.85 gave the cat-paw fist here).

Finger AutoPosing must be off for the finger controllers. Re-running on an already styled clip is fine but measures the styled fingers; keep the pre-styling snapshot if the timing matters.

## 5. Hands that should touch the body (`motion_cleanup_prepare(kind="hand_rest")`)

A hand that stays within 14 cm of the waist, hips or thighs and barely moves relative to the hips for 12+ frames is treated as resting there (the span extends while it is still calm within 19 cm). Inside the span the wrist group is pushed along the surface normal until 0.4 cm from the skinned mesh, frame by frame, eased over 8 frames; the elbow is re-solved analytically so both bones keep their lengths. Only the waist-down surface counts: a hand held by the chest or face is a pose, not a hand at rest (including the chest pulled a raised paw onto the body).

Reference clip: left hand 11.4 cm off the hip for frames 0–139 → on the hip, matching the video.

## 6. Flicks the capture could not see (`motion_cleanup_prepare(kind="wrist_accent")`)

A mitten hides the wrist: on the reference clip the right wrist sat at a constant −20° through the whole intro while the video shows the paw "knocking" on the beat. Such accents have to be authored, timed from the reference.

1. **Time them from the video.** Pick a pixel signal that follows the gesture and read it per frame from the paused, seeked video (a canvas in the browser tab is enough). Here: the count of pink paw-pad pixels in the region of the raised paw — high when the paw is upright (pads to the camera), low when it is knocked forward. Runs of low values gave nine pulses, ~6–7 frames each, one beat (≈12.9 frames at 140 BPM) apart, grouped in "knock knock" pairs: `[4,10] [16,22] [41,47] [53,58] [66,72] [80,86] [92,98] [118,125] [133,139]`.
2. **Check the hand can do it.** The palm must face the direction the flick should go (`palm·front` ≈ 0.7–0.8 here, fingers up), otherwise fix the hand's orientation first.
3. **Bake the hand's layer over the span.** A 6-frame flick does not survive keys every 3 frames: `feature_prepare("bake", {"layer_ids": [<Hand_R layer>], "first_frame": 0, "last_frame": 147})`. The tool refuses and names the layer when keys are missing.
4. `motion_cleanup_prepare(kind="wrist_accent", side="Right", pulses=[...], accent_deg=55)`: each pulse snaps on over 2 frames, holds, and eases back over 3 (correlation 0.91 with the video signal); the wrist flexes by `accent_deg` but never past 40° of flexion, so a flick that starts from an already flexed wrist does not over-bend.
5. Sample the mesh over the span and render it frame by frame from the side: upright, down, upright, down must be readable. Then check `arms` again.

## Order and checks

1. `hand_pose` (finger shapes do not depend on where the hand is).
2. `hand_rest`, then `arm_clearance`: both move the wrist and the elbow, which changes the forearm direction and therefore the wrist bend.
3. `wrist_soften` **after** the hand positions are final. Softening first and placing the hand afterwards re-bent the left wrist from 40° back to 68° on the reference clip.
4. `motion_cleanup_analyze(checks=["arms"], every_frame=true)` again: turning a hand that rests on the hip pushed its fingers 1.7 cm into the body. One more `arm_clearance` pass fixes that with centimetre-sized moves; re-check the wrists once.
5. `wrist_accent` last, on top of the softened wrist (softening afterwards would flatten the flicks).
6. Re-analyze feet, fingers, hands; sample the mesh, render the same sheets as before and compare with the reference stills.

Tell the user what was a judgement call (hand shape, limits, which spans were treated as contact) so they can ask for a different one.
