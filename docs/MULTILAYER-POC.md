# Layered scene format: experimental version 1

This source-only proof of concept extends the *idea* of the existing offline
motion recipes. It does not change their format, accepted assets, CLI or renderer.
The standalone entry point is `python -m gif_cinema.layers`. It is experimental,
not a Lottie player, importer or exporter. Pillow 10.1 or newer is required for
editable text, together with FFmpeg and ffprobe for media export.

## Run the asset-free example

The included scene uses only editable shapes and text, with independent layer
motion. No media download, bundled artwork or API key is needed.
The card uses explicit `smootherstep` on both outgoing segments, so its angular
velocity and acceleration reach zero at the midpoint turn and loop seam. The
example tests check near-boundary angular speed and symmetric rendered card poses;
these checks do not replace visual review of the encoded loop.

```sh
python -m gif_cinema.layers render examples/layered-shapes.json --out output/layers-plan --dry-run
python -m gif_cinema.layers save examples/layered-shapes.json --out output/layers-saved
python -m gif_cinema.layers render output/layers-saved/scene.json --out output/layers-render
python tools/verify_layered_scene.py output/layers-render
```

The dry-run writes nothing. The final command reopens and rerenders every frame,
compares RGBA pixels, requires the complete export inventory and verifies its hashes.
All output directories must be new. The separate showcase artwork, media and demo generator are not included.

## Contract

A scene has `format: "gif-cinema-layered-scene"`, `schema_version: 1`, a title,
even `width`/`height` (2..1024), `fps` (25 or 50), `duration_ms`, `loop`, opaque
`matte: "#RRGGBB"`, and an ordered `layers` array. Rendering follows the array
from back to front. Missing optional values are normalized on save.

There are 1..16 layers, 2..1500 export frames and a bounded compositing workload.
Duration must be 40..30000 ms and exactly divisible by the frame period. This
avoids silently changing timing to fit GIF's 10 ms delay units.

Raster budgets are checked before decoding assets or allocating text/shape pixel
surfaces. Each layer is limited to 1,048,576 raster pixels, the whole scene to
4,194,304 cached raster pixels, and the sum of each layer's raster area multiplied
by its active frame count to 268,435,456 pixel-frames. Supersampling is separately
limited to 9,437,184 pixels per temporary surface. Image boxes are conservative
upper bounds; text bounds are measured from font metrics without making an image.
A tiny output canvas therefore cannot hide enormous input-layer work. Prepared
rasters are premultiplied once and reused for every frame.

Every layer has a unique `id`, `type`, optional human-readable `name`, optional
`anchor: [0.5, 0.5]`, `in_ms` and `out_ms`, and 2..32 `keyframes`.

Types:

- `image`: local still PNG/JPEG/WebP `source`, desired pixel `size: [w,h]`.
  Images fit within that box without changing aspect ratio. Animated sources are
  rejected for this still-image type. Source EXIF display orientation
  is normalized before compositing. Portable saves include a verified `sha256`.
- `gif`: existing local GIF `source`, desired pixel `size`, and explicit `playback`
  (`once` with final hold, or `loop`). Native delays, independent layer clocks,
  alpha/disposal and actual source indices are retained. See [GIF layers](GIF-LAYERS.md)
  for the no-key example, cache limits, skipped-drawing diagnostics and precise scope.
- `text`: editable single-line `text`, `font_size`, `fill`, and optional `font_id`.
  The default `pillow-default` preserves the known bundled Aileron font. Explicit
  `noto-sans-regular-2.004` loads the packaged OFL font for Russian/Azerbaijani.
  Font bytes and glyph-coverage manifests are hash-pinned. No arbitrary font paths,
  web-font downloads or automatic fallback are allowed. Saves record `font_sha256`
  and the Pillow/FreeType environment; unsupported glyphs fail preflight.
- `rect`: `size`, `fill`, optional `radius`, `stroke` and integer `stroke_width`.
- `ellipse`: `size`, `fill`, optional `stroke` and integer `stroke_width`.
- `stroke`: `size`, authored polyline `points`, `stroke`, integer `stroke_width`,
  and keyframed `reveal` by geometric distance. See [draw-on motion](STROKE-REVEAL.md)
  for bounds, original example, timing and additional dynamic-work budgets.

Layer colors accept `#RRGGBB` or `#RRGGBBAA`. Opacity is multiplied with source
alpha. Compositing is ordinary source-over. There are no masks, groups, parenting,
blend modes, general SVG paths, repeaters, arbitrary attributes, expressions or plugins.
Supersampled text/shapes and premultiplied-alpha transforms reduce edge fringes.

Example keyframes:

```json
[
  {"at": 0, "x": 0.45, "y": 0.5, "zoom": 0.96, "rotation": -5, "opacity": 1, "easing": "smootherstep"},
  {"at": 0.5, "x": 0.55, "zoom": 1.02, "rotation": 5, "easing": [0.42, 0, 0.58, 1]},
  {"at": 1, "x": 0.45, "zoom": 0.96, "rotation": -5}
]
```

`at` is normalized local layer time, from 0 to 1 over the layer's `in_ms..out_ms`.
Times are strictly increasing and must include both endpoints. Missing transform
properties inherit the preceding keyframe, initially center position, zoom 1,
rotation 0 and opacity 1. `easing` does not inherit: the default for each segment
is linear. Easing belongs to the **left** keyframe of each segment.
Stroke layers additionally inherit `reveal`, initially 1. Other layer types reject
that property; existing scenes and their transform defaults are unchanged.

Position is a fraction of scene dimensions. Zoom is a uniform factor relative to
the layer's declared raster size. Rotation is clockwise in degrees. The anchor
is a normalized point in the layer raster and is placed at x/y in the scene.

Easing names: `linear`, `ease-in`, `ease-out`, `ease-in-out`, `smootherstep`, `step`.
An array `[x1,y1,x2,y2]` is a temporal cubic-bezier curve. All four values must be
0..1. The renderer solves the x coordinate rather than using input time as the
Bezier parameter. Overshoot curves are intentionally excluded in this version.

## Time and loop evidence

Export frame `i` is sampled at `i/fps`, so a 4.8 s / 50 fps loop contains 240
frames at 0, 20, ... 4780 ms. The conceptual 4800 ms endpoint is inspected but
not duplicated as a final export frame. This avoids an extra seam hold. The same
sampling applies to non-repeating scenes; if an end pose must hold, author that
hold before the final keyframe rather than expecting a zero-duration endpoint
to consume a frame.

Layer visibility is `[in_ms, out_ms)`. For the conceptual closing diagnostic,
layers whose out time equals scene duration are evaluated at their final keyframe.
The exported GIF uses a repeat extension only if `loop` is true. MP4 has no
inherent repeat flag: the player must repeat it.

`loop-seam.png` shows last exported frame, first frame and conceptual closing
endpoint. `encoded-loop-seam.png` compares the actual decoded GIF/MP4 last and
first frames. The receipt includes lossless, decoded-GIF and decoded-MP4 seam
pixel errors plus adjacent-frame errors. These are diagnostics, not automatic
visual acceptance. Matching positions need not imply matching velocity, and an
arbitrary authored scene may intentionally cut at its loop boundary.

## Isolated layer previews

`layers/<id>.png` remains a canvas-sized RGBA image for every layer. Its sample is
now the **visible exported frame nearest the midpoint of that layer's active
interval**, with equal-distance ties choosing the earlier frame. Only actual
export samples inside `[in_ms, out_ms)` qualify, never an unsampled time or the
conceptual closing endpoint. This avoids empty previews for short early/late
layers and skips transparent or off-canvas samples near the interval midpoint.

Here, visible means that the isolated layer has at least one nonzero-alpha pixel
on the canvas. It does not mean perceptual visibility or visibility through other
layers. If no export sample qualifies (including fully transparent/off-canvas
layers or motion visible only between samples), the PNG remains fully transparent.
The receipt records `status: "no-visible-export-frame"` and null `frame`, `time_ms`
and `alpha_bbox` instead of presenting that placeholder as a selected frame.

The additive `layer_previews` receipt map records each layer's existing PNG
`filename`, active `in_ms`/`out_ms`, `status`, zero-based `frame`, integer `time_ms`
and Pillow-style exclusive-right/bottom `alpha_bbox`. Selected images have
`status: "visible"`. `layer_preview_sampling` describes the selection rule.
Existing receipt schema version, fields, output paths, playback samples and media
timing are unchanged; old receipts without these extra fields remain verifiable.

Candidates are retained during the existing compositing pass, not by rerendering
each layer at every time. At most one existing canvas-sized RGBA image is retained
per layer (at most 64 MiB under the scene limits), without an extra pixel copy.
When writing each PNG, a blank canvas applies the same source-over composition
as isolated rendering, including RGB values hidden under zero alpha. The explicit
canvas is at most 4 MiB; Pillow's composite result adds another temporary RGBA
buffer, up to 8 MiB combined beyond the retained candidates. These are pixel-buffer
bounds, not total process memory. This happens once per layer, not on every
timeline frame. All retained images are released before GIF frame buffering begins.

## Save and reopen

`save` makes a new directory containing `scene.json` and content-addressed local
assets. Asset filenames are intentionally opaque; the JSON preserves editable
layer names, text, geometry and keyframes. Paths resolve relative to the scene,
never the shell's current working directory. No absolute paths, URLs, traversal
components or symlinks escaping the scene directory are accepted.

`render` includes the same portable scene under `editable/`, tests five reopened
frames, and records all exported PNG hashes. `tools/verify_layered_scene.py`
rerenders every frame from that saved scene, compares its RGBA bytes with the PNG
and receipt, and checks every required output file hash. The inventory is derived
from the saved scene, never from whatever subset the receipt chooses to list:
GIF and MP4 previews, every timeline PNG, every isolated layer PNG, the portable
scene and its distinct image assets, contact sheet, first/last/closing stills and
both seam sheets are mandatory. Missing or unexpected inventory entries, duplicate
JSON fields and malformed SHA-256 values fail verification. Historical receipts
without the additive layer-preview metadata remain supported. Unlisted auxiliary
review reports are allowed on disk and are outside this export check.

Pixel reproducibility is scoped to the same Pillow/font version. Encoded MP4 bytes
may vary across FFmpeg builds. This verifier checks media hashes against the saved
receipt; it does not independently repeat the renderer's GIF/MP4 decoding checks
or authenticate a receipt someone has edited together with its files. It does
not establish artistic quality, loop continuity or human acceptance.

All inputs are read-only. Changed hashes fail export or reopen instead of silently
substituting another image. Rendering stages files beside a fresh output directory,
checks both encoders and source hashes, and writes the receipt last as its completion
marker. A failed encode/probe leaves no completed output. Existing destinations are
refused. `save` is a simple new-directory operation, not crash-resumable storage.

Scene input and saved JSON share a 512 KiB limit, including normalized/inherited
keyframe fields. `save` validates the serialized scene before creating its destination.
Receipt writing and verification share a 16 MiB limit, checked before completing an
export; valid 1500-frame/16-layer receipts can exceed 4 MiB. Local inputs must be
regular files: FIFOs, sockets and devices are rejected. On POSIX, nonblocking open
plus a descriptor type check also handles a file being replaced by a FIFO between
the initial path check and opening. Final-component symlinks are not followed by
that file-opening helper; confined image aliases are resolved before it is called.

## Tests

```sh
python -m unittest discover -s tests -p test_layers.py -v
python -m unittest discover -s tests -p test_layered_verifier.py -v
python -m unittest discover -s tests -v
python -m compileall -q gif_cinema tools
```

Focused tests cover strict/duplicate JSON, numeric bounds, URL/traversal rejection,
escaping symlinks, byte/pixel budgets, unsupported animated assets and expressions,
source immutability, order, separate animation, anchors/rotation, alpha/opacity,
editable text, local layer timing, cubic-bezier timing, saved-scene relocation,
tamper detection, real GIF/MP4 export, loop metadata, reopen equality and failed
encoding. Network calls are explicitly forbidden in these tests.
Regression tests also cover raster-budget rejection before allocation, cached
premultiplication, large receipts, dense normalized scenes, failed saves, named
pipes and a regular-file-to-FIFO replacement race.
`test_layer_previews.py` covers short intervals, single-frame layers, midpoint
ties at both frame rates, transparent/off-canvas samples, invisible layers,
unsampled/closing-only visibility, unchanged composites, zero-alpha RGB parity,
retained-image release,
real export and historical receipt compatibility.
`test_layered_verifier.py` covers empty/incomplete inventories, absent files,
unexpected paths, duplicate fields, malformed hashes, media/PNG tampering, shared
image assets, relocation and complete real exports without encoder or network use
during verification.

## Not a Lottie implementation

The [Lottie specification](https://lottie.github.io/lottie-spec/latest/single-page/)
is a conceptual reference for independent layers, transform properties and
keyframed easing, not an imported dependency or executed artifact. This PoC's
field names and time model are its own. No spec conformance, browser runtime,
cross-player parity or expression support is claimed. The reference page was
not fetched during this offline task.

## Explicit Unicode text fonts

Text layers may set `font_id: "noto-sans-regular-2.004"` for packaged Noto Sans.
Legacy layers without this field keep Pillow's known bundled Aileron font.
Missing glyphs are rejected before export, not substituted with boxes. Saves
record font hashes and Pillow/FreeType versions. See [Unicode text](UNICODE-TEXT.md)
for the supported scope, wheel licensing and deliberate migration procedure.
