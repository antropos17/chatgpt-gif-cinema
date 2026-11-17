# Skip work on exactly black light planes

This local optimization follows e4d9e7d's one-pass verified native assembly. It
changes the native RGB renderer, not GIF timing, drawing selection, camera paths,
encoding, audio, checkpoints or the browser editor.

## Evidence and algorithm

The earlier profile of this unchanged baseline renderer spent 13.326 of 21.676
seconds in 870 Gaussian blurs over 290 frames. The actual five-scene project has
no visible rear-light pixels for 81 frames. A proposed one-entry occlusion cache
was rejected: its ordered drawn-pose keys have zero consecutive hits here.

The renderer checks the actual RGB planes with `getbbox()` after applying rear
light gain. Exactly black glow does not need a Gaussian blur, masking or addition.
Exactly black core does not need masking or addition. If both rear planes are
black, no occlusion mask is needed. Front planes are checked independently.
Nonzero operations retain the original order: rear glow, rear core, front glow,
front core. There is no new cache and no extra retained frame-sized buffer.

This is not an effect-schedule heuristic. Black effect colors can still create a
white center; off-canvas drawings and gain rounding can create black planes.
Even a one-valued blue pixel is nonblack. Grayscale luminance would be an unsafe
empty test, so every RGB channel counts. No pixels are approximated or retimed.

## Measurements

Linux/Python 3.12.14, Pillow 13.0.0, PyAV 16.1.0, FFmpeg 7.1.5. Actual repository project:
5 scenes, 290 frames, 960x540, 25fps, 11.60 seconds. Three alternating before/after pairs:

| Scope | Before | After |
| --- | ---: | ---: |
| Render + RGB hash, median | 20.140s | 17.891s |
| Init + render/hash, median | 21.678s | 19.590s |
| Complete fresh build, one trial each | 36.114s | 33.887s |

Render/hash time was 11.2% lower on this project. Do not apply that percentage to
whole export. All 290 RGB hashes, every decoded scene/movie PTS and 40ms hold,
including the last hold, matched. Both complete MP4 files remain byte-identical
(SHA256 `2fc4afc02ce9abe9b719a901bf50ba6f1fc5504f007c22715f67b31f05b2a46d`),
as do the PCM files. The same MP4 bytes also match the prior assembly optimization;
its independently decoded AAC evidence remains applicable to those identical bytes.

Two shorter paired controls, 40 frames each, demonstrate the tradeoff:
- Empty rear-light window: median 2.750→1.427s.
- Both planes active: median 2.827→2.895s. The scans can add overhead when nothing is
  empty; no speedup is promised on such content. This small timing difference is
  hardware/load-dependent, not a universal regression bound.

The fixture, all individual samples and full output hashes are retained in the
compact package. No paid service, network rendering or new artwork is involved.

## Reproduce and verify

Use a full repository checkout with reviewed original example assets, FFmpeg and
the `lossless` extra. Keep the output path new:

```bash
git show e4d9e7d:gif_cinema/shot_renderer.py > before-renderer.py
python tools/benchmark_native_renderer.py examples/native-shots/project.json \
  --baseline-source before-renderer.py --baseline-commit e4d9e7d \
  --out new-benchmark.json --repeats 3 --build
python -m unittest discover -s tests -p 'test_native*.py' -v
```

The helper accepts only the selected known Git blob. Its default remains eee37ae
for reproducing the older static-cache benchmark. Both full-build variants use
the current assembly pipeline and baseline/current Renderer injection; receipt
engine identities report current installed code for both, as disclosed in the report.

Seven new regression tests compare the previous independent frame method with the
fast path: no lights, each of four planes alone/together, single-valued R/G/B,
saturated colors, zero/fractional gain, white center with black effect color,
off-canvas/quantized black output, effect boundaries, nonmonotonic timestamps and
live parameter edits. Empty scenes really skip all 3 dynamic blurs. These tests
also pass on minimum Pillow 10.1. Existing native decode/audio/recovery tests remain.

Linux tests do not claim Windows/macOS coverage. Identical output demonstrates
preservation, not improved acting, character identity, smoothness or artistic quality.
Different pipeline-stage speed percentages must not be added or multiplied.
