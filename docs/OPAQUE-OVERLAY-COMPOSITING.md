# Exact opaque overlay compositing

The native shot renderer keeps its working frame in RGB, with transparent
particles drawn into a same-sized RGBA overlay. Previously every output frame
converted the RGB canvas to RGBA, allocated a source-over result, then converted
that result back to RGB. `_composite_overlay` instead uses the overlay's alpha
as the paste mask on the owned RGB frame. Camera cropping/resampling still happens
afterward, with the same coordinates and order. If the recipe contains no overlays,
the renderer skips allocating and compositing an empty RGBA plane entirely.

## Why the restriction matters

For an opaque destination, source-over reduces to channel interpolation by the
source alpha. Pillow supports RGBA alpha masks in `Image.paste`; using the overlay
as both source and mask does not multiply its alpha twice. This equivalence does
**not** hold for a translucent RGBA destination. See the official
[paste documentation](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.paste).

Pillow's [source-over implementation](https://github.com/python-pillow/Pillow/blob/13.0.0/src/libImaging/AlphaComposite.c)
uses integer coefficients. With destination alpha 255, its coefficients reduce
to the same weighted sum used by masked paste, with equal rounding for every
possible 8-bit sum. The independent review also checked the
[integer blending definitions](https://github.com/python-pillow/Pillow/blob/13.0.0/src/libImaging/ImagingUtils.h).
No Pillow implementation was copied into this project: both paths call Pillow.

The fast path requires RGB destination, RGBA source and equal sizes. It also
rejects **any `transparency` metadata on the RGB image**: an RGB PNG color key can
make `convert('RGBA')` transparent even though its mode says RGB. Other cases keep
the original composite/conversion path, including its errors on incompatible
inputs. The normal native renderer already produces an opaque stage, but this
guard prevents accidentally extending the optimization to a future transparent
canvas.

## Ownership and compatibility

Only the current owned working frame is modified. The cached stage, decoded
sprite tiles/masks, overlay pixels, source assets and project recipe are not
changed. An empty overlay list allocates no RGBA overlay plane at all; adding particles
again on a subsequent call immediately restores overlay rendering. There is no
frame cache or precomputed overlay: live changes to alpha,
color, particles and camera settings are evaluated on each call. Particle draw
order and overlap behavior remain unchanged. No dependency, schema, encoder or
timing setting changes.

Test coverage includes every 256 x 256 x 256 source-channel / destination-channel
/ alpha combination; random mixed RGB channels; invisible RGB, alpha 1 and alpha
255; RGB color keys and transparent destinations; tiny/non-square canvases;
fractional cameras; live edits; source ownership; and actual FFmpeg export with
decoded RGB, PTS, hold, WAV and MP4 comparison. Minimum Pillow 10.1 and Pillow 13.0
are checked separately. This is not a claim that every future Pillow build has
been tested.

## Reproduce measurements

From a checkout containing this change, save the exact previous renderer:

```sh
git show 3ace165:gif_cinema/shot_renderer.py > baseline_shot_renderer.py
PYTHONPATH=. python tools/benchmark_opaque_overlay.py examples/native-shots/project.json \
  --baseline-source baseline_shot_renderer.py --out new-overlay-benchmark --repeats 3 --export
python -m unittest discover -s tests -p test_native_opaque_overlay.py -v
```

The benchmark checks the reference's Git blob hash before executing it. Each
sample runs in a fresh process. Alternating render-loop measurements include RGB
hashing and exclude renderer initialization; initialization is recorded separately.
Peak process RSS is not an allocation counter. Optional full exports are one
before/after pair and include their existing verification. Actual FFV1 samples,
PTS and holds are decoded again for comparison outside the measured interval;
full PCM and MP4 hashes must agree. FFmpeg/ffprobe and the lossless extra are
required. RSS measurement requires Linux/macOS.

Performance depends on canvas and workload. A primitive paste speedup is not the
same as a complete export speedup. This change does not create poses, interpolate
frames, repair cuts, lock faces or establish visual acceptance. It preserves
already-authored samples and their timing.

## Observed measurements (local Linux, Pillow 13.0)

Three fresh-process alternating render/hash pairs per 960 x 540 project:

| Workload | Frames | Median before | Median after |
| --- | ---: | ---: | ---: |
| Independent no-overlay control | 150 | 1.315 s | 0.858 s |
| Independent dense-overlay control | 150 | 1.859 s | 1.212 s |
| Existing effects-heavy native example | 290 | 16.891 s | 16.996 s |

The controls isolate this operation, not representative character animation. The
large example's frame loop is essentially neutral. Its one final full export pair
was **37.046 -> 41.031 s (slower)**, while an earlier overlay-only candidate pair
was 37.208 -> 35.682 s. These variable single pairs do not establish a general
end-to-end improvement. No universal speedup or absence of timing regression is
promised. Sparse overlays can have a different cost balance from dense ones,
since the original source-over implementation skips work at alpha zero.

Each final project pair matched all decoded RGB samples, timestamps, holds, PCM
and MP4 hashes: 590 decoded frames per variant across the three projects. Source
creation time is excluded. Initial and final measurements are both retained in
the delivery evidence rather than reporting only the fastest favorable pair.
