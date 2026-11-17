# Audio-only native revisions without unused sprite caches

Native `sequence build --reuse-from ...` reuses verified visual scenes when only
sound changes. Previously, after all scenes had been reused (or resumed), the
build still constructed the full visual `Renderer` solely to call `sound()`.
That prepared all sprite tiles, masks and the stage even though none would be
rendered. These caches stayed alive through final assembly and verification.

The project-only PCM writer is now separate. Fresh and mixed builds retain the
existing `Renderer.sound()` compatibility wrapper. When no compositor was needed,
`write_reused_sound()` validates original images sequentially, then synthesizes
sound without preparing visual caches. It is a memory optimization for that path,
not a claim that all films render faster.

## Validation is retained

- Hash, source type/header/geometry and scene verification remain in the build.
- Each unique background/clip source is fully decoded, **including unused clips**.
  Header/hash/CRC checks alone cannot detect a corrupt compressed pixel stream.
- A one-pixel sample checks required RGB/RGBA conversions without retaining full
  converted atlases. Sources are closed before advancing to the next source.
- The original tile/anchor/recipe bounds remain validated by the project loader.
- Audio sample order, absolute clock, cropped noise recurrence and PCM saturation
  are unchanged. The bounded writer is extracted, not an alternate synthesizer.
- Scene frame counts, RGB digests, PTS, holds, source-drift checks, AAC coverage,
  engine identity and atomic publication remain checked. Failed partial audio is
  not published; a compatible retry writes a new private file.

No source pixels, character poses, anchors, rendering schedule or output settings
are edited. There is no face lock, interpolation, scene repair or new generation.
This change does **not** skip artwork decoding or make decoding memory constant:
peak still includes at least the largest original source image.

## Reproduce the complete revision comparison

Use Python 3.10+, Pillow, PyAV (`lossless` extra), FFmpeg and ffprobe. Create a seed
with the **same installed engine** as the benchmark, then copy its source project
and change sound within the selected time range. Keep visual source files and
recipes identical. Source paths are relative to each project directory.

```sh
python -m gif_cinema sequence build path/to/project.json --out seed
python tools/benchmark_audio_reuse.py path/to/audio-edited-project.json \
  --reuse-from seed \
  --baseline-source evidence/audio-reuse/baseline_shot_renderer.py \
  --out new-audio-comparison --repeats 3
```

`baseline_shot_renderer.py` must be the exact trusted source from local commit
`8d1cc28bcbf8ce17286e6c2ba3a912816a0de282`, Git blob
`a75f461f42fec801510fcefa601f620c035ddb3b`. The benchmark checks the blob before
executing it. This comparison reinstates only the old eager construction/sound
path inside the current engine, with legacy caches retained until build returns.
It is not a comparison of two complete historical engine executables.

Each alternating run uses a fresh process. The timed region covers the complete
revision (including verification and final assembly), not the original seed build.
The script checks all scenes were reused, audio actually changed, and all decoded
scene RGB/PTS/holds, complete PCM WAV and MP4 bytes agree between variants. RSS is
peak parent-process memory, not summed FFmpeg child memory; supported on Linux and
macOS. Pixel hashing used for benchmark comparisons happens after the measured
region. Engine source hashes are recorded; do not force reuse across a changed
engine or remove its resume checks.

## Scope of tests and measurements

On the existing 5-scene, 290-frame, 960×540 / 25 fps effects-heavy project,
three alternating fresh-process revision pairs gave these medians:

| Metric | Previous eager path | Project-only path |
| --- | ---: | ---: |
| Parent-process peak RSS | 400.39 MB | 141.46 MB |
| Complete revision wall time | 31.199 s | 31.104 s |
| Parent CPU time | 63.641 s | 64.231 s |

Memory fell about 65%; wall time was essentially neutral and one pair regressed
31.199 → 32.857 s. No end-to-end speedup is claimed. All six outputs had matching
decoded RGB, PTS/holds and complete PCM WAV/MP4 bytes. Audio differed from the seed.
The delivered raw logs include all runs, not only the favorable pair.

The delivery includes actual repeated measurements and test logs. They are local
Linux results, not cross-platform performance guarantees. Small projects may gain
little. Fresh builds that require a compositor intentionally keep the old path.
Independent review, minimum-Pillow and installed-wheel tests supplement the
regressions but do not establish artistic quality or character identity.
