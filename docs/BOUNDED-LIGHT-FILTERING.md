# Exact bounded-area native light filtering

The native renderer can now filter a small light plane or occlusion mask without
blurring every canvas pixel. It still calls the same Pillow `GaussianBlur` with
the same radius. This is an exact-output optimization, not reduced-resolution
bloom, approximated light, animation interpolation or a face-lock feature.

## Conservative eligibility

Only RGB/L planes, finite scalar radii 0…64, and explicitly checked Pillow
**10.1.0 or 13.0.0** qualify. Any other version, mode or radius retains the previous
full-image filter. This deliberately favors compatibility over speed until another
implementation is checked. The package does not force a Pillow downgrade.

The actual nonzero bounding box is measured after gain. It is expanded by
`3 * (ceil(radius) + 1)` in each direction and clipped to the original canvas.
The crop contains exact zeros, not guessed transparent/low-brightness pixels.
Original canvas-edge clamping is retained. No threshold discards faint blue light.
The checked Pillow implementations use three extended-box passes whose finite
per-pass support fits that conservative margin. A new crop edge stays zero until
its last relevant pass; it cannot feed a changed clamp value back into the output.
This reasoning comes from the official
[Pillow 10.1 implementation](https://github.com/python-pillow/Pillow/blob/10.1.0/src/libImaging/BoxBlur.c)
and [Pillow 13.0 implementation](https://github.com/python-pillow/Pillow/blob/13.0.0/src/libImaging/BoxBlur.c).
No Pillow implementation code is copied into GIF Cinema.

If the expanded rectangle covers at least 75% of the canvas, the full filter is
used instead. The result always has the original full dimensions, mode and copied
metadata. Input pixels remain untouched. There is no region/image cache; live
source, brightness and radius edits cannot leave a stale light boundary.
The operation order (gain, blur, occlusion, additive composition) stays unchanged.
Initialization-time sprite masks and cached static shadows are not changed.

## Actual measurements

Three alternating before/after render+RGB-hash runs of the existing native shot
project (290 frames, 960×540, 25 fps, 11.6 seconds) gave medians:
**21.042 → 17.522 seconds**, about 16.7% less frame-loop time. Initialization was
outside that timing. The reference was exact `shot_renderer.py` from local
`4b193d7`, Git blob `57c3f7ae1a8fc9c93db99401b4853946e6d84bec`.

Gaussian work kept the same call counts, but processed fewer pixel-filter pairs:
- RGB glow: 258,681,600 → 204,579,215 across 499 calls.
- L occlusion: 108,345,600 → 42,166,160 across 209 calls.

One complete export pair took **37.147 → 34.866 seconds** (about 6.1% less).
That is a single build pair, not a repeated universal promise. All 290 decoded
FFV1 RGB frames, timestamps and holds match; complete WAV and MP4 bytes match.
The checks remain enabled. No provider/generation work is included.

**Dense images do not benefit from cropping.** A separate 40-call dense L-mask
control measured 0.247 → 0.279s (about 13% overhead for the extra bounds scan).
The dense RGB control used already available bounds and showed noisy
1.114 → 1.022s; its full-filter path performs no intended filtering reduction.
These are primitive controls, not whole-frame slowdown/speedup estimates.
Gains depend on actual effect area, radius, canvas and Pillow version.

## Verification and use

Regression checks compare complete image bytes against the ordinary full filter:
random sparse planes, tiny/narrow canvases, every edge/corner, fractional radii,
one-valued RGB channels, true cropping, dense fallback, unsupported versions/modes,
metadata, source mutations and real FFmpeg export. Technical equivalence is not
perceptual acceptance. It does not assess anatomy, motion continuity or identity.

```sh
python -m unittest discover -s tests -p test_native_bounded_blur.py -v
PYTHONPATH=. python tools/benchmark_bounded_blur.py examples/native-shots/project.json \
  --baseline-source baseline_shot_renderer.py --out new-blur-benchmark --repeats 3 --export
```

Use the selected source checkout or install its wheel in an isolated environment.
The benchmark rejects any other reference source before execution and records the
loaded renderer path/hash. Outputs must be new non-symlink directories. A tiny
validated native fixture is supplied in the compact package for reproducing the
workflow without large source atlases; its timings are not the table above.

No new dependency or project field is introduced. Engine identity changes still
prevent unsafe resume across renderer revisions; preserve an interrupted build
and use a new destination. Independent review, installed-wheel checks and full
repository status are recorded in the delivered evidence. No Windows/macOS or
subjective visual-quality claim is made.
