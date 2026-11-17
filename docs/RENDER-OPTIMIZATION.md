# Native renderer: reuse the static shadow stage

Local optimization based on main `eee37ae37e70f59dd87a768306a3dca292a392c4`.
This is not a published release or a face/animation-quality improvement.

## Change and scope

`shot_renderer.Renderer.frame()` used to redraw and Gaussian-blur the same static
shadow layer, convert the background and alpha-composite that stage for every
frame. The renderer now prepares that image once and copies it before painting
actors, light effects and overlays. Original background pixels remain the reference
for sprite masks and rear-light occlusion.

The cache key includes shadow order, positions, radii, RGBA colors and blur. Editing
those recipe values rebuilds the cached image; actor, effect and camera parameters
remain live. The loaded background and decoded clips are renderer-owned images,
not a supported mutable pixel-editing API. Each renderer holds one additional
stage-sized RGB image, never a cache of every output frame.

No FPS, pose selection, source clock, camera calculation, interpolation, color
conversion, encoder setting, audio or source asset is changed. This optimization
only affects native `gif-cinema-shot-project` rendering. It does not accelerate
every GIF Cinema route. Changed renderer code changes engine identity: an old
checkpoint must use a new revision, not resume under a different engine.

## Measured result

Fixture: the repository's `examples/native-shots/project.json`, five authored
scenes, 290 frames at 960x540 and 25 fps, 11.60 seconds of output. Linux, Python
3.12.14, Pillow 13.0.0, FFmpeg 7.1.5, PyAV 16.1.0.

| Measurement | Before | After |
|---|---:|---:|
| Render and RGB hashing, median of 3 alternating pairs | 28.838 s | 24.260 s |
| Initialization plus render/hash, median of 3 | 31.385 s | 26.048 s |
| Complete build including normal verification, one trial each | 51.382 s | 40.110 s |

The repeated render measurement used about **15.9% less time**. The single full
build pair used about 21.9% less time, but is not a stable cross-machine estimate.
The full-build comparison injected the original or optimized Renderer into the
same current build pipeline; both receipts therefore identify the current engine.
Extra post-build verification was outside the timed build interval.

All 290 RGB hashes matched in all six render runs. Actual FFV1 scene outputs and
the MP4 were decoded in both builds: 290 frames each, exact PTS, every 40 ms hold
including the final frame, and 11,600 ms total. Both complete MP4 files and PCM
audio files were also byte-identical. GIF encoding and alpha masters were not
changed or newly benchmarked; this native renderer produces RGB.

The original profile showed Gaussian blur taking 18.30 of 26.87 seconds. Moving
only static-shadow preparation out of the frame loop reduced per-frame blur calls
from four to three. These instrumented profile times are not the repeated timings
in the table.

## Reproduce

In a checkout of this change with the normal Pillow/PyAV/FFmpeg dependencies:

```bash
git show eee37ae:gif_cinema/shot_renderer.py > ../before-renderer.py
python tools/benchmark_native_renderer.py examples/native-shots/project.json \
  --baseline-source ../before-renderer.py --repeats 3 --build \
  --out ../new-render-benchmark.json
python -m unittest discover -s tests -p 'test_native*.py' -v
python -m unittest discover -s tests -v
python -m compileall -q gif_cinema
```

The benchmark accepts only the exact known baseline renderer blob, refuses an
existing report, and checks RGB equality rather than asserting a hardware-dependent
speed threshold. Full-build mode creates two new output directories beside its
report. Allow approximately 450 MiB for the two portable example builds.

Five new regression tests cover original-background occlusion, overlapping and
transparent shadows, crop/gain/time changes, non-monotonic frame requests,
caller-modified output images, in-place recipe edits, and actual lossless export
pixels/timestamps/holds/PCM. Independent review and 33 native tests passed in a
separate copy. Windows/macOS and other Pillow versions were not tested in this
local optimization run. Matching pixels preserve existing artwork defects too;
they do not establish face identity, natural acting or user acceptance.
