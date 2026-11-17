# Exact integer-translation compositing

This local optimization speeds up the existing **layered-scene** renderer when a
layer is only translated by whole pixels. It does not change scene schemas,
source drawings, selected poses, animation clocks, interpolation policy, audio or
export encoders. It is not a face-lock or new-animation feature and does not
accelerate the separate native camera/light shot renderer.

## Why this path mattered

Profiling the repository's `examples/sprite-layer/scene.json` found 1024 affine
transforms over 128 output frames. One render loop spent 2.741 of 3.201 seconds in
Pillow transforms, including stationary layers that needed no resampling.

`layers._integer_translation` now requires all of the following exactly:
- Identity linear matrix: no rotation, scale or shear.
- Integral translations, with **no epsilon or near-integer rounding**.
- Premultiplied `RGBa` input, or straight `RGBA` with nearest-neighbor sampling.

It clips the source to the visible canvas intersection before converting to RGBA,
applies opacity to that new image and alpha-composites only that rectangle.
Entirely off-canvas layers have no visible work. No rendered images are cached,
so live raster/recipe edits cannot become stale. At most the visible canvas area
is converted, even when the source raster is larger.

All other cases keep the original affine path. In particular, straight RGBA with
bicubic resampling must **not** bypass Pillow's implicit premultiply/unpremultiply:
even an identity transform can round its colors. Odd centered raster sizes can
produce half-pixel placement and therefore correctly use the fallback. A 360°
rotation with tiny trigonometric error is not rounded into eligibility.

Layer previews retain full-canvas coordinates, hidden RGB behavior, alpha bounds,
midpoint selection and tie ordering. They are not cropped user-visible artifacts.

## Actual measurements

Linux, Python 3.12, Pillow 13.0.0. Before is exact `layers.py` from local commit
`2ec4d091eb40392fbd35a3702604f699ac7464e9`, Git blob
`c1be9b2e8ad5b14a345c60ec5f6d6bee10f0947e`.
The table is the median of three alternating before/after render+RGBA-hash+state
runs, with each scene prepared before the timed frame loop:

| Existing scene | Frames | Before | After |
|---|---:|---:|---:|
| Sprite atlas, two stages | 128 | 3.582s | 1.847s |
| GIF layer composition | 160 | 3.235s | 2.104s |
| Independent shapes PoC | 25 | 0.193s | 0.098s |

All **313 frame RGBA hashes and source states match**. This does not establish
perceptual quality; it proves that this optimization did not alter those samples.

One full sprite-scene export pair took **12.781→10.003s** including preview
collection, PNG/GIF/MP4 encoding and normal checks. All output file bytes match,
including 128 PNGs, isolated layers, GIF and MP4. Both MP4s were additionally
decoded: all 128 PTS and holds per file match the 50fps grid, including the final
20ms hold. GIF duration remains 2560ms. The route remains silent.

This is not a repeated full-build speed guarantee. Gains depend on how many layers
qualify and their visible area; zoomed/rotated/subpixel layers get no resampling
savings. A separate all-zoom fallback control measured 3.493→3.603s (about 3.1% overhead)
with no changed RGBA. No universal speedup is claimed.
Do not multiply these timings by earlier optimization results or apply them to
all GIF Cinema routes. Initialization and provider generation are not accelerated.

## Reproduce

```sh
python -m unittest discover -s tests -p test_integer_composite.py -v
# Save the exact reference source from the named local revision, or use the
# pinned baseline_layers.py supplied in the compact evidence package.
python tools/benchmark_integer_composite.py examples/sprite-layer/scene.json \
  --baseline-source baseline_layers.py --out new-integer-benchmark --repeats 3 --export
```

The benchmark rejects any other reference source before executing it. Output must
be a new non-symlink directory. It verifies all compared RGBA samples/states and
input hashes; `--export` also requires FFmpeg/ffprobe and PyAV to inspect actual
MP4 timestamps. No provider or network call is used. Fonts can differ between
Pillow versions: the paired comparison always uses one installed renderer, not a
cross-version image-equality promise.

The 12 tests cover randomized alpha/clipping differentials, exact guards, large
source clipping, opacity, live raster edits, native pose/anchor clocks, preview
selection and a real before/after export. The same 12 passed on Pillow 10.1.
A broader independent review and full-suite status belong in the delivered log.
