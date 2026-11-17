# One-pass verified native shot assembly

This local backend change follows the static shadow-stage cache and exact GIF
palette indexing changes. It affects `sequence build` native-shot final assembly, not the browser
editor, GIF palette route, face consistency or animation quality.

## What changed

Previously, final assembly called `verify_scene` to decode and verify each FFV1
scene, then reopened and decoded it again to send the same RGB images to FFmpeg.
The second pass also repeated RGB conversion and hashing.

`BuildContext.verified_scene_images` now checks each decoded frame once and yields
that same RGB image. It checks the checkpoint key/file hash, record shape, frame
geometry, timestamp, RGB hash, extra/short frames, and the file hash again at EOF.
`verify_scene` drains this shared validator, retaining its previous path return.
Scene-render verification, resume/reuse verification and final MP4/audio verification
remain enabled; only the redundant assembly decode was removed.

The consumer must exhaust the iterator successfully. Receiving its last image is
not a verification receipt: count, EOF and post-read stability checks still follow.
FFmpeg writes a uniquely named attempt, not `film.mp4`. A late decoder failure,
changed file or mismatched frame prevents successful ready/publication. Completed
scene checkpoints and failed attempts remain for diagnosis and safe resume.

Before final publication, a cheap hash pass also checks all completed scenes again,
catching an earlier scene changed while later scenes or the output were checked.
This is a point-in-time check, not protection against an unrelated process changing
files immediately afterward. The build lock coordinates cooperating builders only.
No verification pass is omitted to make the benchmark faster.

Encoder cleanup explicitly closes a suspended input generator, stops/waits/kills
a still-live failed encoder, then closes its stdin. A buffered stdin must not be
flushed before stopping a stalled encoder: otherwise error cleanup itself can hang.
Successful normal encoding still closes stdin to signal EOF before waiting.

## Reproduce

Use a full checkout with FFmpeg and the `lossless` extra (PyAV 16.1). No provider or
API key is used. Prepare a verified native build using the authored example:

```bash
python -m gif_cinema sequence build examples/native-shots/project.json --out source-build
git show 3849555:gif_cinema/shots.py > before-shots.py
python tools/benchmark_native_assembly.py source-build \
  --baseline-source before-shots.py --out new-benchmark --repeats 3 --full-build
python -m unittest discover -s tests -p 'test_native*.py' -v
```

The helper accepts only the exact previous `shots.py` Git blob. It alternates
implementations, counts decoder openings and decoded frames, compares every RGB
hash, and independently decodes MP4 RGB/PTS/holds and AAC samples. PCM and original
scene bytes must remain unchanged. No numpy dependency is needed for audio checks.

- Stream timings include validation and RGB delivery/hash, without an encoder.
- Assembly timings include the verified scene feed and H.264/AAC encoding, but
  exclude subsequent MP4 verification and the final publication hash pass.
- The optional fresh full builds include rendering, encoding, all verification,
  portable snapshots and publication. One trial per variant is not a universal
  full-build speed guarantee.
- The pinned previous or current shots module is injected into the same checkout
  with the same optimized renderer. Engine receipts report current installed source
  identity in both benchmark variants; the report discloses this explicitly.

## Safety coverage and limitations

Tests cover correct independent artwork, bad key/hash/record length, geometry/PTS,
missing timestamps, RGB mismatch, missing/extra frames, decoder EOF error, in-place
mutation and same-path replacement, premature iterator closure, actual invalid
Matroska, real FFmpeg failure, and late first/last-scene mutation with no successful
publication. Repaired checkpoints resume without rerendering completed scenes.
A Linux-only actual full-pipe/sleeping-encoder probe has an external watchdog.

Fault injection tests are not all actual damaged-container fixtures: where a decoder
is substituted, the test explicitly checks a controlled error path. Linux/Pillow/
PyAV/FFmpeg coverage does not imply a Windows/macOS run. Existing output formats,
CLI and checkpoint schema are unchanged. Engine source identity changes, so use a
new revision rather than forcing a checkpoint from an older engine to resume.

Identical output pixels/audio/timing prove this optimization preserves the tested
render, not that characters, acting, scene joins or art are now improved. H.264/AAC
remain lossy viewing formats; this change does not turn them into lossless masters.

## Measured result on the included repository artwork

Final source SHA256 `f5d2783902ecfa2973a4bef7e8fff15e7ea631cd8237b5cb9b5825c97963b7bc`. Linux, Python 3.12.14,
Pillow 13.0.0, PyAV 16.1.0; 5 scenes, 290 frames, 960x540, 25fps, 11.60s.

| Measured operation | Before | After | Scope |
| --- | ---: | ---: | --- |
| Stream verification + RGB delivery/hash | 8.046s | 4.528s | Median of 3 alternating pairs |
| Verified feed + H.264/AAC encoding | 9.357s | 5.419s | Median of 3 alternating pairs |
| Fresh complete build | 40.562s | 35.994s | One trial per variant |

Assembly time was 42.1% lower in this run.
Do not apply that percentage to the complete render: the measured full build is
a separate, single-trial comparison. Assembly decoder openings fell from 10 to 5,
decoded scene frames from 580 to 290, and all 290 output frames remained unchanged.

Every paired MP4 is byte-identical, SHA256
`2fc4afc02ce9abe9b719a901bf50ba6f1fc5504f007c22715f67b31f05b2a46d`. Every decoded RGB frame, timestamp, hold
(including the final hold), AAC block and original PCM digest matched. Sources
were unchanged. Hardware/load/version dependence remains; no universal speedup
is promised. Reports retain each individual timing, not just the medians.
