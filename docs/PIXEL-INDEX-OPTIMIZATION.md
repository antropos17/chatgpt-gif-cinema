# Exact GIF indexing before integer scaling

Local optimization on top of `5d26cd72a61c783d1d04fdf77c64bde153849b47`.
It retains the previous native shadow-stage optimization and changes only the
exact-palette GIF encoder's indexing order. No verification or resource limit is
removed, and no source drawings, colors, frame delays or audio are synthesized.

## Algorithm and proof boundary

Previously, `pixel_palette.encode()` canonicalized and enlarged each RGBA frame,
then performed a Python color-to-palette-index lookup for every enlarged pixel.
Now it maps original pixels to the same palette indices and enlarges the P-mode
image with integer `NEAREST`. At scale 2, that changes 4 lookups per original pixel
into 1. At scale 1, there is no lookup reduction or promised speedup.

Only binary alpha is supported, as before. Opaque RGB values are copied exactly;
RGB under zero alpha is ignored and mapped to the existing transparent index.
`P + NEAREST` duplicates indices without quantization or palette remapping.
The independent, canonicalized, enlarged RGBA frames are still retained for the
existing full decoded-output verification. The requested global palette, all
frame/byte/pixel/time budgets, loop checks and publication safeguards remain.

This is a GIF `pixel build` optimization, not a general MP4/native-shot rendering
speedup. It creates no intermediate poses and does not improve face consistency,
anatomy, perceived smoothness or artistic quality. A stable original palette is
not evidence that a palette defect was repaired.

## Repeated measurement on actual repository artwork

Source: `examples/anime-pixel/anime-pixel-wave-and-bow-v2.gif`, SHA256
`07977d10de4c01f2982e54399fd27c71dbe3a3bfa7d303ced26b0f32d1f8b1ba`.
32 frames, 320x320, 124 visible colors plus transparency, 3,840 ms, infinite loop.
Linux, Python 3.12.14, Pillow 13.0.0. All values below are seconds on one machine.

| Scope | Before median | After median | Trials per variant |
|---|---:|---:|---:|
| 2x encode including all built-in checks | 2.3275 | 0.9986 | 5 |
| 2x full pixel build including PNGs, checks and publication | 3.0296 | 2.6166 | 3 |
| 1x encode including all built-in checks | 0.4185 | 0.4405 | 5 |
| 1x full pixel build | 1.2880 | 1.1495 | 3 |

Trials alternate before/after order. At 2x, measured encoding used **57.1% less
time** and the full build used **13.6% less time**. Do not substitute the encode
improvement for end-to-end performance. At 1x, measurements fluctuate and encoding
was about 22 ms slower; no 1x benefit is claimed. These are observations, not
hardware-independent guarantees, and do not add to another route's speedup.

Every baseline/candidate GIF was byte-identical at each scale. All 32 decoded
RGBA frames, individual delays and loop metadata matched source-derived truth,
including the final hold. Full builds were independently verified after timing,
and original source bytes remained unchanged. GIF has no audio; the native
renderer and its audio code were unchanged in this second optimization.

The profile reduced lookup-generator iterations from 13,107,232 to 3,276,832
(including generator termination) at 2x. Profile timings are not used for the
table above. Actual encoding, decoding and verification still scale with output
pixels; the whole workflow is not expected to become four times faster.

## Regression and compatibility checks

Five new tests compare output bytes with an independent implementation of the
old writer order and check decoded RGBA separately. They cover all scales 1..8,
odd canvas sizes, hidden RGB, opaque black, transparent indices 0 and 255, all 256
opaque colors, authored palette order/unused colors, duplicate holds, 120-second
holds, finite/infinite/absent loop metadata, local source palettes and disposal
2/3, input immutability, source-pixel lookup count, and pre-allocation budgets.

All 48 pixel tests passed on Pillow 13.0.0, independently in a separate copy, and
on the declared minimum Pillow 10.1.0. The real source GIF at 1x and 2x was also
checked against the original writer on Pillow 10.1.0, with identical bytes and
decoded pixels/delays. Windows/macOS were not tested in this local run.

## Reproduce

```bash
git show 5d26cd:gif_cinema/pixel_palette.py > ../before-palette.py
python tools/benchmark_pixel_index_scaling.py \
  examples/anime-pixel/anime-pixel-wave-and-bow-v2.gif \
  --baseline-source ../before-palette.py --out ../new-pixel-benchmark \
  --scales 1 2 --repeats 5 --build-repeats 3
python -m unittest discover -s tests -p 'test_pixel*.py' -v
python -m unittest discover -s tests -v
```

The helper checks the exact baseline code blob before executing it, uses bounded
local reads, refuses an existing report directory and preserves all trial values.
Encode timing includes normal encoder self-verification. Full-build timing
includes normal verification and publication; the additional external verify is
outside timing. Its output directory contains the actual compared GIFs and builds.
