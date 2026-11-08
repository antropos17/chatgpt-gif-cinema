# Vertical layered motion example

`examples/vertical-motion.json` is a small, asset-free 9:16 scene for the
existing offline layers renderer. It contains 12 independent layers: background,
five moving graphics, a static accent rule and five editable text layers.
The public-facing copy is English: **Layered / Motion** and
**Layers · Text · Rhythm**. Russian and Azerbaijani support remains covered by
`tests/test_text_fonts.py` and the separate `examples/layered-unicode.json` fixture.
The example is a short composition study, not a long-form GIF-film workflow.
No images, fonts or other assets are downloaded and no provider/API call is used.

## Resolution and scope

The editable scene and native render are **540×960**, 50 fps and 3.2 seconds
(160 exported frames). The current renderer limits each dimension to 1024 pixels.
This example does not change or bypass that limit or any work/memory budget.

The optional delivery MP4 is **1080×1920 after a 2× Lanczos upscale of the native
PNG sequence**. It is not a native Full HD render and scaling does not add detail.
Using the PNGs avoids scaling an already compressed MP4 or paletted GIF.
The delivery is silent. Repeat playback is a player setting for MP4; the native
GIF has the repeat flag. No universal platform acceptance or visual-quality
certification is implied.

The example was developed against PR7 head
`cf9ee71a20d46e5127e08133468471bd04e61fc9`, whose parent is
`9cebaa889c56efbee907c267069cc05c191e73fb`. Runtime code remains unchanged.

## Composition and reserved interface margins

The chosen foreground-safe rectangle is `(54,120)..(454,750)` in native pixels,
or **(108,240)..(908,1500)** in the upscaled delivery. That reserves 108 pixels on
the left, 172 on the right, 240 at the top and 420 at the bottom of the delivery.
Only the background extends outside it. The asymmetry leaves more room on the
right for controls and below for captions.

These are conservative **author-chosen margins**, not an official Instagram,
TikTok, YouTube or universal device specification. App controls, caption length,
accessibility settings and crops differ. Preview in the intended app before
posting; no upload or platform-specific compatibility test is part of this demo.

The test checks raster-corner bounds at **all 160 export times**, expanded by two
native pixels for resampling fringes. It also checks that moving graphics never
cross any text box. Actual decoded stills were inspected at full delivery size
and at a 360×640 display size. Representative conservative delivery bounds:

| Element | Bounds (left, top, right, bottom) |
| --- | --- |
| First title line | (140, 416, 502, 526) |
| Second title line | (140, 544, 438, 626) |
| Moving ring, union over all samples | (186, 680, 786, 1278) |
| Main caption | (140, 1342, 612, 1404) |
| Small format label | (140, 1446, 456, 1492) |

Titles use native sizes 46 and 42, the main caption 22, and auxiliary labels 18.
At a 360-pixel-wide display their nominal sizes are about 31, 28, 15 and 12 pixels.
The auxiliary labels are deliberately secondary, not essential instructions.
Solid text colors have nominal contrast ratios of **10.72:1 to 16.31:1** against
the static background; this measures the specified colors, not every antialiased
or compressed edge pixel and not a full accessibility assessment.

## Loop behavior

All five moving layers use two `smootherstep` segments with equal start/end
transforms. Velocity and acceleration reach zero at the turn and loop endpoint.
The tests check matching endpoint transforms and near-boundary numerical speed.
Text stays static to remain readable. The conceptual 3200 ms closing endpoint is
not duplicated in the 160-frame export; the last export sample is 3180 ms.

Native first/closing RGBA pixels match exactly. The real encoded first/last
frames also decode successfully. Pixel scores and derivative tests are technical
checks, not a promise of perceptual seamlessness in every player. Inspect the
native `loop-seam.png` and `encoded-loop-seam.png` and watch the repeated result.

## Reproduce locally

Use the already installed Pillow, FFmpeg and ffprobe versions supported by the
project. The packaged Noto Sans 2.004 font is selected explicitly; the renderer
checks font hashes and glyph coverage. See [Unicode text](UNICODE-TEXT.md) and
[third-party notices](../THIRD-PARTY-NOTICES.md). No font fallback is used.
The saved scene records the font/Pillow/FreeType environment for reopening.

All output paths must be new. These commands create only local files:

```sh
python -m gif_cinema.layers render examples/vertical-motion.json \
  --out output/vertical-native --dry-run
python -m gif_cinema.layers render examples/vertical-motion.json \
  --out output/vertical-native
python tools/verify_layered_scene.py output/vertical-native \
  --report output/native-reopen-verification.json
mkdir output/vertical-delivery
ffmpeg -v error -xerror -nostdin -n -threads 2 -filter_threads 1 \
  -framerate 50 -start_number 0 -i output/vertical-native/frames/%04d.png \
  -vf scale=1080:1920:flags=lanczos -frames:v 160 -an \
  -c:v libx264 -threads 2 -crf 18 -pix_fmt yuv420p -movflags +faststart \
  output/vertical-delivery/vertical-1080x1920-upscaled.mp4
ffprobe -v error -count_frames \
  -show_entries stream=codec_name,codec_type,width,height,pix_fmt,r_frame_rate,nb_read_frames,duration:format=duration \
  -of json output/vertical-delivery/vertical-1080x1920-upscaled.mp4
ffmpeg -v error -xerror -nostdin \
  -i output/vertical-delivery/vertical-1080x1920-upscaled.mp4 -f null -
python -m unittest discover -s tests -p test_vertical_motion_example.py -v
```

Expected delivery evidence: H.264, yuv420p, 1080×1920, 50/1 fps, 160 decoded frames,
3.2 seconds, no audio. The native verifier rerenders all 160 PNGs from the portable
saved scene and checks all output hashes. An installed font/rendering version
mismatch must be resolved explicitly rather than silently substituted.

Only the small scene JSON, this document and its tests are source deliverables.
Generated GIFs, videos, decoded stills and receipts stay under ignored `output/`;
they are not included in the source change or published by these commands.
