# Find the actual outfit discontinuities

Review each outfit separately; never average different costumes into one score.
This offline diagnostic ranks **every native adjacent transition**, plus the loop
seam. It does not alter artwork, create poses, retime or approve smoothness.
It complements the existing cut-context review and the opt-in atlas column
alignment in PR #57; neither registration nor a higher playback FPS repairs
changes in face, head shape, sleeve outline or limb proportions.

## Run and reopen

```bash
python -m gif_cinema.motion_review build casual-32-poses.gif --out review/casual
python -m gif_cinema.motion_review verify review/casual
# Optional authored region, measured in original pixels:
python -m gif_cinema.motion_review build casual-32-poses.gif --focus 80 20 240 180 --out review/casual-head
```

Run again with the traveler and festival source files, using separate new output
folders. Inputs must be regular local GIF files; existing output is not overwritten.
The existing exact-pixel decoder enforces binary alpha, structural budgets and
native delays (20 ms minimum). No API, external tool or JavaScript is used.

Each bundle retains original GIF bytes, every decoded native RGBA frame,
`priority-edges.png`, and `receipt.json`. Reopening recomputes metrics from the
retained source, compares all hashes, and compares decoded PNG pixels against the
source and regenerated sheet. This is consistency checking, not authentication.
The source is checked again before publication. A failed publication may leave an
inspectable incomplete directory; do not reuse it as a verified result.

The sheet includes the top five edges and always the loop seam, with a preceding
frame for direction/hold context. Its thumbnails use nearest-neighbor sampling,
**not** a native-resolution proof: inspect the numbered PNGs for individual pixels.
A play-once source's loop seam is marked hypothetical, and first-edge context does
not wrap to the final frame. No scores establish human visual acceptance.

## Metric definitions

- Frames are decoded/composited at their original resolution; RGB under zero alpha
  is canonicalized. No downsampling is used for metrics.
- `changed_pixels` counts pixels with any changed canonical RGBA channel.
- The denominator is the union of visible pixels in the two frames. Transparent
  padding cannot hide a changed character; an opaque background can dilute scores.
  Use the same explicit `--focus` rectangle for a meaningful before/after comparison.
- `visible_mae_0_255` is the larger of the **two aggregate RGB errors**, composited
  separately on black and white, divided by visible-union pixels. It is not the
  sum of per-pixel maxima, optical flow, joint velocity or perceptual distance.
- Rate is that error times 1000 divided by the effective preceding visible hold.
  Consecutive identical focus drawings are combined for this denominator while
  original frame indexes and delays remain intact. Looping takes include identical
  holds straddling the seam; play-once takes do not.
- Ratios use the median rate of changing **internal** edges, excluding unchanged
  holds and the loop seam. A zero baseline gives null, never an automatic pass.
  Rankings prioritize inspection; there is deliberately no universal threshold.

## Evidence from the real separate outfit takes

The exact inputs are identified in [the machine-readable measurements](evidence/outfit-motion-review.json).
All three have 32 decoded drawings at 80 ms each, 2,560 ms duration. No frames were
invented or reordered. Full-canvas measurements found the same two trouble spots:

| Outfit | Worst edge | Rate / internal median | Loop 31→0 ratio |
| --- | --- | ---: | ---: |
| Cream / casual | 15→16 | 2.5383 | 1.7313 |
| Traveler | 15→16 | 2.4494 | 1.9790 |
| Festival | 15→16 | 2.4191 | 1.5438 |

Zero-based 15→16 is the join between the two 16-drawing source halves, at 1,280 ms.
The loop closes at 2,560 ms. In inspected three-frame sheets, this internal join
changes head/hair proportions and arm/sleeve contours; the costume-specific edges
remain visible even with feet aligned. The original GIFs remain untouched.
This is evidence of where review and new authoring are needed, **not** evidence
that the motion has now been repaired. Real-time playback and user acceptance
remain pending.

### Concrete next authoring pass

For **each** costume, preserve its existing drawings and create a reviewed repair
take around frames 14–17 with a consistent head/face and a continuous hand path.
Use the exact preceding and following original PNGs as boundary references. Review
both neighboring joins, not only the replacement's endpoints. Then repair 30–31→0–1
if a loop is intended. Do not hide the defect by duplicating frames, dissolving,
reversing the action, selecting arbitrary low-distance poses, or shifting each
silhouette independently. Repeat this diagnostic on the candidate, inspect every
native frame and actual playback, and retain both original and candidate receipts.
No repaired take or new source drawings are supplied by this change.

## Silhouette anchor diagnostics (receipt schema 2)

New receipts include `anchor_motion`: the bottom-center of each visible alpha
bounding box in the selected focus rectangle, and changes between successive
hold-to-hold displacement rates (pixels per second). Consecutive identical
decoded RGBA drawings are merged before timing calculations, so encoder-split
holds do not produce false acceleration. `holds` preserves the original source
frame ranges and summed durations. Existing schema-1 receipts still verify;
unknown schema versions are rejected.

This is a **report-only silhouette diagnostic**, not tracked anatomy, identity
validation, physical acceleration, or an art-quality score. Costume changes,
pose changes, detached effects and cropped limbs can move the anchor even when
the character is correctly registered. Fully opaque or empty frames produce
`null` anchors instead of a misleading zero. This version does not measure loop
closure or stitch velocity across takes. Inspect decoded playback before fixing
anything; do not pin all frames to a single anchor or smooth intentional motion.
No pixels, delays or motion tracks are changed.

Technique reference: [SpriteForge registration](https://github.com/Ping13with14/spriteforge/blob/e174b3911b791e257f1e2b38c80f9e85d24a2cdd/packages/core/src/register.ts)
distinguishes fixed registration from motion-preserving anchor trajectories.
Our bounded diagnostic is independently implemented; no source was copied.
