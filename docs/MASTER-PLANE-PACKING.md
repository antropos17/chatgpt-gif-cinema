# Exact RGBA master preparation without redundant row/canvas copies

The FFV1 master still preserves each named decoder's RGBA sample and declared hold,
including hidden RGB under alpha zero. This change only prepares the same pixels
more directly. It neither converts straight alpha to premultiplied alpha nor alters
packet PTS/duration, frame counts, source ordering, preview/audio policy or checks.

## Two narrow paths

`master.video_frame()` previously obtained packed BGRA bytes, allocated another
zero-filled bytearray, then copied every row in Python into the AVFrame plane.

- A fully packed plane with exact buffer size now accepts the same original BGRA
  byte string directly. This path does not depend on new Pillow encoder options.
- For Pillow **10.1.0 and 13.0.0**, a padded plane can use the raw encoder's explicit
  stride and top-down orientation. Its entire size must equal stride × height,
  stride must fit at least width × 4 bytes, and stride must fit the raw encoder's
  buffer `max(ImageFile.MAXBLOCK, width × 4)`. The last guard matters: a small
  MAXBLOCK can make padded raw encoding fail even though packed encoding works.
- Unknown versions, extra-tail allocations or ineligible layouts keep the original
  zero-filled row-copy fallback. No approximation is used to qualify a fast path.

Pillow's versioned raw encoders explicitly zero each row's padding, including the
last row: [10.1 implementation](https://github.com/python-pillow/Pillow/blob/10.1.0/src/libImaging/RawEncode.c)
and [13.0 implementation](https://github.com/python-pillow/Pillow/blob/13.0.0/src/libImaging/RawEncode.c).
No upstream implementation was copied into this project.

For GIF-to-master assembly, a decoded RGBA frame already matching the target size
is also its canvas. `convert('RGBA')` supplied an owned image, and packing only
reads it. This avoids allocating/pasting an identical transparent canvas and
hashing the same RGBA bytes twice. Different source dimensions retain the previous
center-padding, no-mask paste and independent canvas digest. Final decoded master
and ROI verification remain mandatory in both cases.

## Measurements and limits

Three alternating fresh-process pairs per workload, current Pillow 13 / PyAV 16.1
on Linux. Timed scope is the **whole silent master build including verification**,
not merely packing, and not H.264/audio generation. Comparison decoding follows
measurement. RSS is the Python process peak, not summed child memory.

| Input | Master build, median | Process RSS, median |
| --- | ---: | ---: |
| Existing FORM/01, 640×640, 120 frames / 6 s | 4.616 → 4.282 s | 110.28 → 105.37 MB |
| Original HD control, 1920×1080, 60 frames / 2.08 s | 6.337 → 6.340 s | 312.49 → 303.03 MB |
| Original odd-size control, 641×639, 60 frames / 2.08 s | 1.263 → 1.198 s | 101.18 → 97.92 MB |

The HD case is effectively neutral in wall time. These are modest workload-specific
gains, not a universal film-speed promise. Packing-only probes were faster, but
tracemalloc peaks were essentially unchanged because Pillow's own byte production
also allocates buffers. Do not claim that removing the Python row bytearray halves
allocation peaks. Raw runs, including unfavorable timings, are retained.

All actual RGBA samples, PTS, holds, source hashes and per-frame manifest facts
match within each workload across 18 builds. Matroska container bytes need not be
identical (container metadata can vary). Preview/audio equality is separately
covered by real export regressions; no new lossy-copy quality claim is made.

## Reproduce

Use Python 3.10+, Pillow and the optional `lossless` extra. FFmpeg/ffprobe are needed
for preview/audio tests. The benchmark validates its frozen source before executing
it: local `e4853eb` `master.py`, Git blob `afa8ba20bd138307f586dbdc535eb447d1f5d83a`.
Only the old `encode_master()`/`video_frame()` are reinstated for the baseline;
current verification remains in both variants.

```sh
# Set PYTHONPATH=. in a checkout, or use the installed wheel externally.
python tools/benchmark_master_packing.py input.gif \
  --baseline-source baseline_master.py --out new-master-comparison --repeats 3
python tools/benchmark_master_packing.py --packing 641 639 300 \
  --baseline-source baseline_master.py --out new-packing-comparison --repeats 3
```

Existing resource limits, immutable source snapshots, failed-build cleanup and
no-clobber publication are unchanged. No new poses, interpolation, face lock,
semantic continuity or artistic approval is implied. Tests exercise the minimum
and current Pillow versions; no native Windows/macOS performance run is claimed.
