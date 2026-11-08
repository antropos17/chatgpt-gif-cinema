# Offline motion design

`motion` adds repeatable camera/graphic movement and timing control around existing
artwork. It makes **zero API calls**, downloads no model, and never selects, accepts
or replaces a take. This is a development-preview feature, not a new versioned skill release.

## Start with a preset

```bash
python -m gif_cinema motion poster.png --preset pop-in --out output/poster --dry-run
python -m gif_cinema motion poster.png --preset pop-in --out output/poster
python -m gif_cinema motion shot.gif --preset push-in --out output/push-in
```

Inputs are local GIFs, or still PNG/JPEG/WebP. Transparent PNGs keep their alpha in
the output PNG sequence and atlas. Presets: `identity`, `push-in`, `pan-left`,
`pop-in`. Still images default to two seconds. The preset transforms the **whole
image**: it does not isolate letters, articulate limbs, or repair generated poses.

Still PNG/JPEG/WebP inputs honor their EXIF display orientation before default
canvas sizing, fitting and keyframe transforms, including mirrored orientations.
The original file and its hash stay unchanged. Decoded PNG frames retain alpha;
metadata is stripped as before. No ICC color-profile conversion is performed.

`--dry-run` validates the complete recipe and decoded input, reports exact output
timing and budgets, requires no FFmpeg, and writes nothing. Rendering needs Pillow,
FFmpeg with H.264, and ffprobe. Use a new output folder for every candidate, including
after a failed attempt. Originals are read-only and checked again before publishing.

## Direct the motion with keyframes

```bash
python -m gif_cinema motion shot.gif --recipe examples/motion-loop.json --out output/loop --dry-run
python -m gif_cinema motion shot.gif --recipe examples/motion-loop.json --out output/loop
```

```json
{
  "schema_version": 1,
  "width": 512,
  "height": 512,
  "fps": 25,
  "background": "#101018",
  "fit": "cover",
  "speed": 1,
  "playback": "ping-pong",
  "repeats": 1,
  "keyframes": [
    {"at": 0, "zoom": 1, "easing": "ease-in-out"},
    {"at": 0.5, "zoom": 1.12, "rotation": 2, "easing": "ease-in-out"},
    {"at": 1, "zoom": 1, "rotation": 0}
  ]
}
```

The example runs the source forward and backward while adding a gentle, returning
camera move. Review the actual action: reversing a jump, contact or facial gesture
may be narratively wrong. A matching first/last transform is not proof of a seamless
loop. Use `loop-seam.png`, full playback and the source-index trace in the receipt.

### Recipe contract (version 1)

Unknown fields, duplicate JSON fields, nonfinite numbers and numeric booleans are
rejected. Recipe files are limited to 64 KiB.

| Field | Default and meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `width`, `height` | Source dimensions rounded up to even; even integers 2..2048 |
| `fps` | 25 or 50; exact GIF intervals of 40 or 20 ms |
| `fit` | `contain` or `cover`; one fixed source-to-canvas fit for all drawings |
| `background` | `#101018`; explicit `#RRGGBB` compositing color for GIF/MP4 |
| `still_duration_ms` | 2000; integer 40..30000; used only for single-frame sources |
| `trim_start_ms` | 0; inclusive source time in integer milliseconds |
| `trim_end_ms` | End of source; exclusive source time; partial frame holds allowed |
| `speed` | 1; 0.1..8; divides every trimmed source hold duration |
| `playback` | `forward`, `reverse` or `ping-pong` |
| `repeats` | 1; integer 1..16; repeats the source cycle before applying keyframes |
| `hold_start_ms`, `hold_end_ms` | 0; integer 0..10000; extra source-pose holds, once before/after all repeats |
| `spritesheet` | false; opt-in RGBA atlas plus explicit frame rectangles/timing JSON |
| `keyframes` | Identity at 0 and 1; 2..32 keys, strictly increasing `at`, includes both 0 and 1 |

Keyframes support `x`, `y` (source center in normalized canvas coordinates, default
0.5, range -2..3), `zoom` (relative to fit, default 1, 0.1..8), `rotation` (clockwise
degrees, default 0, -3600..3600), and `opacity` (default 1, 0..1). Missing transform
values inherit the preceding key, with identity defaults for the first key. Position
and scale use the same canvas throughout the sequence; no automatic per-pose crop.

`easing` belongs to the **left** key of each segment and defaults to `linear` at
every key; it does not inherit. Options: `linear`, `ease-in` (quadratic), `ease-out`
(quadratic), `ease-in-out` (smoothstep), `smootherstep` (quintic, zero velocity and acceleration at both ends), and
`step` (hold until the next key).
Rotation is numeric interpolation, not automatic shortest-path rotation. Keyframe
progress spans the **entire output**, including repeats and pose holds. Source pose
holds do not pause the transform. Split into separate candidates if you want camera
motion to stop during a hold.

### Timing is explicit

Trim → speed → playback direction → repeats → extra source-pose holds → FPS sampling.
Ping-pong appends reversed interior drawings only, avoiding duplicated endpoint holds:
`A B C D` becomes `A B C D C B`; two drawings become `A B`. This is a cyclic sequence,
not a promise that the final stored drawing equals the first.

Output frame count is requested duration × FPS, rounded to nearest with ties to
even. Fewer than two output frames are rejected. Drawing selection uses centered
time bins across the exact requested duration, with first and last source poses
retained. This distributes unavoidable subframe timing quantization over the clip;
it does **not** synthesize intermediate subject poses. The receipt reports requested
and actual duration, quantization error, every sampled source drawing and any skipped
drawings. Fast motion can omit short source holds. Inspect that list before accepting.
Sampling uses rational integer-tick boundaries, retained in the timeline's
`exact_timing`, rather than the rounded decimal durations used for readability.
A frame center exactly on a boundary belongs to the following source drawing.

## Deliverables and verification

- `frames/0000.png…`: full-canvas straight-alpha RGBA PNG sequence, one file per
  playback frame. Per-file and pixel hashes are in `receipt.json`.
- `review.mp4`: silent H.264 from full-color frames composited onto `background`.
  Codec, dimensions, FPS, frame count and duration are checked with ffprobe, followed
  by a full decode. It is not a preview of GIF palette loss.
- `take.gif`: same timing, infinite loop, one shared palette and no dithering for
  stable flat graphics. Identical adjacent frames may merge into longer holds. GIF
  is flattened, not transparent, and its colors can differ from MP4/PNG.
  Palette training uses up to 256 representative colors from each full-resolution
  composited frame, not averaged thumbnails. A clip using at most 256 distinct RGB
  colors retains those colors exactly, including thin white marks and isolated
  accents. More colorful artwork still requires lossy palette reduction; inspect
  the GIF separately from the full-color MP4.
- `first.png`, `last.png`, `contact-sheet.png`, `loop-seam.png`: review endpoints,
  sampled playback, and the actual final-to-first wraparound. Pixel MAE is a diagnostic,
  never an automatic visual pass.
- `recipe.json`: expanded editable settings; `receipt.json`: input/output hashes,
  complete frame-to-source trace, encoder commands and verification evidence. The
  receipt is written last as the completion marker; status stays `human-review-required`.
- Optional `spritesheet.png` and `spritesheet.json`: transparent full-canvas atlas,
  with exact rectangles and frame durations. No trimming or rotation of packed cells.

Limits protect local memory and disk: source ≤32 MiB/4 megapixels, ≤512 source
drawings and 64 million decoded source pixel-frames; output ≤1500 frames and 160
million pixel-frames. Atlas ≤8192 pixels per side and 16 megapixels. Reduce output
dimensions/duration or leave `spritesheet` off when its plan exceeds the atlas limit.
GIF descriptors are scanned before Pillow decoding to enforce the source frame and
pixel budgets, including later-frame disposal allocations. GIFs that expand their
logical canvas are refused instead of changing the fit partway through a clip.
The shared parser also rejects malformed extension framing before Pillow opens
the file; stricter motion budgets do not replace those protections.
Spritesheet packing searches the feasible integer grids, minimizing unused cells
before preferring a compact shape; a feasible rectangular grid is not rejected
just because a near-square layout exceeds the pixel budget.
No arbitrary network paths, shell expressions, plugins or external commands can be
specified in a recipe.

## Source-only preview scope

This branch provides the standalone `motion` command and the generic JSON recipe.
Use your own local still image or existing footage. It does not include a packaged
demo, the Silk orbit artwork/media or demo generator, or the separate editor and
finishing commands. No media assets are needed to import or install the package.

A completely static result can encode to one GIF drawing with a longer hold.
Inspect full playback and `loop-seam.png`. Matching endpoints, pixel metrics and
successful decoding do not automatically establish smoothness, continuity or
visual acceptance. This command never selects or replaces an accepted take.
