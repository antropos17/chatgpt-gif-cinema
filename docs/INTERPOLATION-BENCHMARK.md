# Offline interpolation benchmark

Run from the repository root with the package installed and FFmpeg on PATH:

```bash
python tools/benchmark_interpolation.py --out output/held-out-benchmark
```

The output directory must be new. No provider requests, downloaded models or extra
dependencies are used. Original GIFs remain unchanged. This is not a RIFE test.
Inputs must have uniform frame delays and fully opaque decoded frames. Transparent
footage must first be composited onto an explicitly chosen background; arbitrary
palette values behind transparent pixels are not a valid comparison target.

## What is measured

For each bundled 16-drawing shot, retain only native drawings 0, 2, ..., 14.
Hide drawings 1, 3, ..., 13 and reconstruct their timestamps. Drawing 15 is not
scored because it has no visible right neighbor. This gives 21 held-out samples
across three independent shots. No hidden drawing enters motion estimation.

Compare three baselines:

- Hold: repeat the visible left drawing.
- Blend: average visible neighbors 50/50 in RGB.
- Motion: FFmpeg minterpolate, aobmc/bidir/vsbmc, using visible even drawings as context.

Report RGB MAE, PSNR from mean squared error, grayscale edge MAE, and MAE within
moving regions. The moving-region mask is defined only by differences between the
visible endpoints (>12/255, dilated 7x7), not by the withheld target. Each sample
has equal weight; full-frame averages can be dominated by static background.
This endpoint-change mask is not complete motion segmentation: an object can move
away and return to the same endpoint position, leaving no mask at that location.

For timestamp calibration, every known output drawing must match the corresponding
visible input with MAE <=1/255. Small RGB/YUV conversion errors are expected. PNG
inputs have normalized RGB pixels and no inherited GIF transparency metadata, which
could otherwise change decoder pixel format and reset the FFmpeg filter graph.

Outputs include exact commands, versions, input hashes, per-frame measurements,
all-frame comparison sheets and one deterministically selected hard case per shot
(largest hold-baseline moving-region error). This avoids selecting images based on
which interpolation method wins. The test never interpolates across scene cuts.

## First measured result

Python 3.12.14 / Pillow 13.0.0 / FFmpeg 7.1.5, three bundled astronaut GIFs:

| Method | Full RGB MAE | Moving-region MAE | PSNR from mean MSE |
| --- | ---: | ---: | ---: |
| Hold | 3.123 | 7.854 | 26.79 dB |
| Blend | 2.936 | 7.177 | 28.84 dB |
| Motion | 2.686 | 6.122 | 30.65 dB |

Motion had lower moving-region error than hold in 18/21 samples, but the close-up
second shot slightly favored blend on that metric (4.960 vs 5.002). In inspected
hard cases, blend visibly doubles the hand; motion can still produce a malformed,
blurred or doubled glove. A better score is not visual acceptance.

## Limits and practical use

The visible gap is doubled from 160 to 320 ms. Reconstruction of an actual withheld
native drawing is a useful stress test, not the same task as filling a 160 ms gap
where no ground-truth middle image exists. Generated native drawings may themselves
contain flicker, geometry changes and discontinuities. More than one intermediate
trajectory may be plausible, while pixel metrics reward agreement and sometimes blur.

Use this to catch regressions, timestamp errors and plainly weak methods, then
inspect hands, object contacts, silhouettes and playback. It cannot measure smooth
motion, character continuity, a coherent story or the quality of an entire film.

The [showcase](SHOWCASE.md) identifies private RIFE/local finishing, not a reproducible
model/version/settings recipe. The cat comparison also uses compositing and framing
cleanup; the astronaut third shot was retimed and excluded from its matched comparison.
Do not score these finished videos as a controlled RIFE benchmark or attribute their
entire improvement to interpolation. Once a RIFE runtime is separately authorized,
its predictions can be evaluated on this same hidden-input split, alongside visual
review, without needing new paid GIF generation.
