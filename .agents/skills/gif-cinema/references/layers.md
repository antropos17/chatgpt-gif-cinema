# Editable layers and draw-on strokes

Use these local tools for independent graphics, typography and existing artwork.
They do not generate character poses or repair continuity. The Python runtime is
installed separately at the commit recorded in `runtime.json`; old runtimes do not
understand stroke or animated GIF layers. Run `python scripts/check_install.py` before using them.

Resolve the paths below from the installed skill folder. Keep all outputs in a
new project directory outside the installed skill. Python 3.10+, Pillow 10.1+,
FFmpeg and ffprobe are required for rendering; dry-run and save need no encoders.
No key, provider or network request is needed after installing the runtime.

```sh
python -m gif_cinema.layers render assets/example/stroke-reveal.json --out ../project/strokes-plan --dry-run
python -m gif_cinema.layers render assets/example/stroke-reveal.json --out ../project/strokes
python scripts/verify_layers.py ../project/strokes
python scripts/review_gif.py extract ../project/strokes/preview.gif ../project/review-strokes
```

The original stroke example draws a heart, an underline and a sparkle in sequence.
It is 4 seconds, 480 × 320, 50 fps, silent and play once, with a final 400 ms hold.
This is authored geometry, not AI-generated handwriting. The GIF encoder may merge
identical held frames; the PNG sequence retains all 200 export samples. MP4 repeat
behavior belongs to its player, and some GIF viewers override play-once metadata.
The other bundled scene, `assets/example/layered-shapes.json`, demonstrates editable
text/shapes and independent transforms. Use the same commands with that source.

`render` produces `preview.gif`, `preview.mp4`, every RGBA timeline PNG, isolated
layer PNGs, diagnostic sheets, `editable/scene.json`, copied image assets and
`receipt.json`. Outputs must be new; original sources are never replaced.
`verify_layers.py` requires the complete output inventory and exact hashes, then
rerenders all timeline pixels from the saved scene. It does not authenticate an
edited receipt, redo the encoder's media-decoding checks, or approve visual quality.
The separate full-frame review starts pending. Inspect its playback and frames.

To edit a portable project, copy `editable/` into the user's project, change a new
scene version and render to another output directory. Referenced assets resolve
relative to the scene, never the shell. Existing snapshots are hash-pinned.

## Core scene contract

A scene has `format: "gif-cinema-layered-scene"`, `schema_version: 1`, even dimensions
2..1024, `fps` 25 or 50, `duration_ms`, `loop`, opaque `matte` and 1..16 ordered layers.
Back-to-front compositing uses source-over alpha. PNG output preserves alpha;
GIF/MP4 flatten against the matte. Scene duration must align with the frame period.
There are 2..1500 exported samples within resource budgets, not unlimited footage.

Each layer has a unique `id`, a `type`, optional `in_ms`/`out_ms`, `anchor` and
2..32 normalized keyframes. Position `x`/`y` is a fraction of scene dimensions;
`zoom`, clockwise `rotation` and `opacity` are independent per layer. The active
interval is `[in_ms, out_ms)`. `at` runs from zero to one over that interval.
Missing transform values inherit. `easing` belongs to the left keyframe of a
segment and does not inherit; it defaults to linear. Use `smootherstep` for a
slowing start and finish when appropriate. The conceptual closing endpoint is not
an additional exported frame. Author a hold before the endpoint if it must be seen.

Layer types are still `image`, animated `gif`, editable `text`, `rect`, `ellipse` and
`stroke`.
Images are local PNG/JPEG/WebP. Text uses pinned packaged fonts, not arbitrary font
files or automatic fallback; `noto-sans-regular-2.004` supports Russian/Azerbaijani.
Unsupported glyphs fail rather than silently becoming replacement boxes.

## Compose an existing GIF

```sh
python -m gif_cinema.layers render assets/example/gif-layer.json --out ../project/gif-plan --dry-run
python -m gif_cinema.layers render assets/example/gif-layer.json --out ../project/gif-composition
python scripts/verify_layers.py ../project/gif-composition
python scripts/review_gif.py extract ../project/gif-composition/preview.gif ../project/review-composition
```

This 3.2-second, 400 × 256, 50 fps, silent, play-once example places the bundled
`shot-01.gif` beside independently animated titles and a drawn accent. The source
has 16 drawings held for 160 ms each: 2.56 seconds of existing action, followed by
a final-drawing hold. The source background remains. The composition does not
create another astronaut action or extra character drawings.

A `gif` layer has `source`, `size`, optional `sha256` and `playback: "once"` or
`"loop"`, plus the usual transforms and active interval. Sources resolve relative
to the scene. Each layer's source clock starts at its own `in_ms`. Once is the
default and holds the final drawing after the native duration; loop wraps it.
The source GIF's loop extension does not override that choice. `out_ms` ends the
layer, even if source action remains. The scene's loop is a separate setting.

At each 25/50 fps export timestamp the source drawing is selected from its native
delay interval. Exact boundaries choose the next drawing. This sampling can omit
a very short source drawing. Inspect the dry-run/receipt `gif_timing`, including
`sampled_source_indices` and `omitted_source_drawings`, before rendering. Increase
export FPS or choose suitable source footage when an important drawing is omitted.
There is no hidden retiming, source trim, reverse, interpolation or new-pose synthesis.

All drawings use one shared fit and anchor. Stored alpha/disposal are decoded;
opaque backgrounds are not removed. Separate GIF layers can share one source with
independent clocks; a portable save keeps one content-addressed asset copy. Use
`image` only for stills, since it deliberately rejects animated inputs.

Each GIF is bounded to 16 MiB, 256 drawings, 4,194,304 pixels per drawing and
120 seconds, with delays 20..60000 ms. Unique sources share a 32 MiB byte and
16,777,216 decoded-pixel ceiling, counting every drawing. GIF raster variants
have a separate 33,554,432-pixel budget across layers. Smaller source drawings and
layer boxes may be needed; these are workload bounds, not total process memory.

## Authored strokes

```json
{
  "id": "underline", "type": "stroke", "size": [260, 32],
  "points": [[12, 24], [90, 15], [175, 12], [246, 20]],
  "stroke": "#86e4f5", "stroke_width": 3,
  "keyframes": [
    {"at": 0, "reveal": 0, "y": 0.83},
    {"at": 0.5, "easing": "ease-out"},
    {"at": 0.8, "reveal": 1},
    {"at": 1}
  ]
}
```

`points` has 2..512 local pixel pairs forming a nonzero-length polyline. Coordinates
are inside the local `size`; leave room for half the line width and antialiasing.
`stroke_width` is an integer 1..128, with round caps/joins. `reveal` is the fraction
of geometric path length, from blank zero to complete one. It defaults to one and
inherits; use separate layers for pen lifts. Reveal can decrease to erase a prefix.
Spatially uneven vertices do not introduce timing jumps. More authored points can
approximate a smooth curve; there is no SVG import, font tracing or pressure model.

Use the original example as a starting point rather than promising automatic
signature tracing. This feature neither signs documents nor creates new actions.
Pixel scores and equal endpoints do not prove that a loop looks smooth.

## Limits and checks

Layer transforms, cached rasters, image decoding, supersampling and compositing
have separate preflight budgets. Stroke work is additionally capped at 268,435,456
supersampled pixel-frames and 1,000,000 segment-frames. Reduce raster size, active
time, FPS, duration or points when a scene is rejected. Limits are not total-process
memory guarantees. Reopening text scenes requires the saved Pillow/FreeType version.

The renderer can produce larger GIFs than full-frame review accepts. For final
review keep each GIF within 512 decoded drawings, 64 Mi pixels and 32 MiB. The bundled
examples fit those limits. Prefer shorter scenes or smaller dimensions;
never silently omit frames from a claimed full review.

Run `python scripts/smoke_layers.py --out ../project/layer-smoke` to render the real
stroke and GIF-composition examples, verify every saved timeline frame and prepare
pending GIF reviews.
The full `smoke_test.py` includes this check. Reports are technical evidence only.
