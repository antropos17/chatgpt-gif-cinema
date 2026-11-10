# Animate an existing image or GIF

This installed route adds camera movement and retiming to existing artwork. It
makes no API calls and invents no character poses. For independent text, shapes,
strokes or GIF placement, use [layers.md](layers.md) instead.

The pinned motion command writes **infinitely repeating GIFs**. `pop-in`, `push-in`
and `pan-left` do not return to their starting transforms, so the GIF can visibly
reset. Use the silent MP4 for a once-through entrance, or review the wraparound
deliberately. Matching endpoints does not prove a seamless loop. Some viewers
also apply their own playback policy.

## Start from the installed skill

Run from this skill folder with the pinned runtime installed, or make all input
and helper paths absolute. Output belongs in a fresh project directory outside
the skill. Python/Pillow suffice for dry-runs; actual encoding needs FFmpeg with
H.264 and ffprobe. No repository checkout, API key or model download is needed.

```bash
python -m gif_cinema motion assets/example/shot-01.gif --preset push-in --out ../project/push-in --dry-run
python -m gif_cinema motion assets/example/shot-01.gif --preset push-in --out ../project/push-in
python scripts/review_gif.py extract ../project/push-in/take.gif ../project/review-push-in
```

The bundled astronaut example is 512×512, 2.56 seconds and 16 existing drawings.
The default 25-fps export has 64 PNG samples, not 64 new poses. Dry-run decodes and
validates the source, reports precise timing and budgets, writes nothing, and
does not require the encoders.

For a local still image:

```bash
python -m gif_cinema motion /absolute/path/poster.png --preset pop-in --out ../project/poster --dry-run
python -m gif_cinema motion /absolute/path/poster.png --preset pop-in --out ../project/poster
```

Inputs are GIF or still PNG/JPEG/WebP. Animated PNG/WebP is rejected. A still
defaults to 2 seconds. Its EXIF display orientation is honored, including mirrors;
metadata is stripped and no ICC color conversion is performed. The original file
does not change. Presets are `identity`, `push-in`, `pan-left` and `pop-in`.
These move the entire image, including any background, letters and figures.

## Use the bundled returning-camera recipe

```bash
python -m gif_cinema motion assets/example/shot-01.gif --recipe assets/example/motion-loop.json --out ../project/returning-camera --dry-run
python -m gif_cinema motion assets/example/shot-01.gif --recipe assets/example/motion-loop.json --out ../project/returning-camera
```

The installed recipe fits the source into 256×256 pixels at 25 fps. It plays the
existing action forward and backward with a returning zoom/rotation: 120 PNG
samples over 4.8 seconds. It is not new action or a promise of seamlessness.
Its last source drawing is index 1, not index 0. Reversing contact, jumps or facial
gestures can be narratively wrong even if the camera returns smoothly.

Copy the recipe into your project before editing it. Main fields:

- `schema_version`: integer 1; unknown or duplicate JSON fields are rejected.
- `width`, `height`: even integers 2–2048. Default is the source size rounded up
  to even. `fit` is `contain` or `cover`; fit stays fixed across all drawings.
- `fps`: 25 or 50, giving exact GIF intervals of 40 or 20 ms.
- `background`: explicit `#RRGGBB`, default `#101018`, used for GIF/MP4 compositing.
  PNG frames preserve alpha.
- `still_duration_ms`: integer 40–30000, default 2000, for single-drawing sources.
- `trim_start_ms`, `trim_end_ms`: inclusive start/exclusive end inside the source.
  Defaults cover the complete source; partial drawing holds are allowed.
- `speed`: 0.1–8, default 1, divides the source delays.
- `playback`: `forward`, `reverse` or `ping-pong`. `repeats`: integer 1–16 source
  cycles inside the clip. This is different from the GIF's delivery loop policy.
- `hold_start_ms`, `hold_end_ms`: integer 0–10000 extra source-pose holds before
  and after all repeats. They do not stop camera transforms.
- `spritesheet`: boolean, default false; opt in to an additional RGBA atlas.
- `keyframes`: 2–32 keys with increasing `at` values, including 0 and 1.

Keyframes use normalized center `x`, `y` (default 0.5, range −2 to 3), `zoom`
(default 1, range 0.1–8), clockwise `rotation` in degrees (−3600 to 3600), and
`opacity` (0–1). Missing transforms inherit from the prior key, starting at identity.
Easing belongs to the left key and defaults independently to `linear`: also
`ease-in`, `ease-out`, `ease-in-out`, `smootherstep` and `step`. Rotation uses
numeric interpolation, not automatic shortest-path rotation.

## Timing, outputs and review

The order is trim, speed, direction, repeats, extra holds, then FPS sampling.
Ping-pong appends only reversed interior drawings: A B C D becomes A B C D C B.
Frame count rounds requested duration × FPS to nearest, ties to even. Centered
sample bins retain the first/last selected poses but can omit short source holds.
Read `omitted_source_drawings` and the exact timing/source trace in `receipt.json`.
Transforms span the entire exported duration, including repeats and pose holds.

Every output contains:

- `take.gif`: flattened onto the chosen background with a shared limited palette,
  no dithering and infinite looping. Identical adjacent drawings may merge into
  longer holds. A fully static result may have only one encoded drawing.
- `review.mp4`: silent H.264 from full-color PNGs, not from the quantized GIF.
- `frames/`: RGBA PNG per playback sample, with file/pixel hashes in the receipt.
- `first.png`, `last.png`, `contact-sheet.png`, `loop-seam.png`: endpoint and
  sampled inspection aids. A contact sheet alone is not full-frame review.
- `recipe.json` and `receipt.json`: expanded editable settings and technical
  evidence. **The input artwork is not copied into the output.** Preserve its
  original bytes separately with your project; the receipt records their hash.
- Optional `spritesheet.png`/`.json`: full-canvas RGBA cells and exact timing.

Watch both delivered formats. Step through the GIF with the installed review
helper and record only inspection actually performed. `review_gif.py check`
initially fails because frame decisions, playback and user acceptance are pending.
Export checks and endpoint metrics do not approve continuity or artistic quality.

## Limits and a complete local check

Motion source limits are 32 MiB, 4 Mi pixels per drawing, 512 drawings and 64 Mi
decoded pixel-frames. The output allows 1500 PNG frames and 160 Mi pixel-frames.
An optional atlas is at most 8192 pixels per side and 16 Mi pixels. Recipes are
limited to 64 KiB. Output paths must be new; there is no overwrite or resume.

The GIF review helper is stricter: 32 MiB, 512 decoded drawings and 64 Mi pixels.
Not every legal motion export fits review. Reduce dimensions/duration, or create
shorter candidates, before exporting an oversized animation. Lower output FPS
does not create new poses and may omit existing source drawings.

```bash
python scripts/smoke_motion.py --out ../project/motion-smoke
```

This checks all four preset dry-runs, exports the existing GIF push-in, its first
drawing as a still entrance, and the bundled returning-camera recipe. It reopens
and compares every saved PNG, checks the complete output inventory and source
hashes, and prepares pending full-frame review packs. Python network calls are
blocked during the check. It proves local technical behavior, not new artwork,
seamlessness, human playback inspection or user acceptance.
