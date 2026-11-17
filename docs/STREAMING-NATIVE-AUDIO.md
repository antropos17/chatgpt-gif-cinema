# Bounded-memory native soundtrack synthesis

`shot_renderer.Renderer.sound` now mixes stereo PCM in blocks of at most 4096
sample frames instead of retaining two full-length Python float lists and a full
PCM output array. This is for native shot projects, not imported soundtrack
retiming or a new sound generator. The existing 2 Mi-sample input budget stays.

## Exact contract

Each output sample keeps the original event order: all authored tones in order,
then all seeded noise events in order, then saturation and the absolute fade.
Python double-precision arithmetic, `round()` behavior, source sample rate and
stereo panning remain unchanged. Noise RNG and low-pass state continue across
blocks. For a cropped performance, the preceding samples are still synthesized
so a noise event that started earlier retains the same state. The final partial
block is not padded with extra samples. WAV headers describe the selected range.

The buffers are bounded, but CPU work still scales with event duration/count.
It does not make every long source faster or remove existing validation limits.
No dependencies or project fields were added. Frame rendering, poses, timing,
FFV1, AAC encoding and publication checks are untouched. Failed audio writes
remain unselected private build attempts; the existing checkpoint can resume.
A new renderer source identity deliberately prevents resuming an interrupted
build made with a different engine. Keep that build and start a new revision.

## Measurements

Linux/Python 3.12, three alternating before/after runs, each in a separate process.
The reference is exactly `shot_renderer.py` from local commit `4087023`, Git blob
`f8bc9630b88d92de9fc5a7d42c41e1ed3c23ecff`. Process RSS includes interpreter/import
and process-launch overhead; it is not a measurement of only the mixing buffers.
No render/verification suite ran concurrently with these measurements.

| Native audio case | Median peak process RSS before | After | Median synthesis before | After |
|---|---:|---:|---:|---:|
| Existing 11.6-second soundtrack, 24 kHz | 62.9 MB | 34.3 MB | 1.569s | 1.500s |
| Synthetic 260-second stress, 8 kHz, 2,080,000 samples/channel | 204.4 MB | 34.3 MB | 3.711s | 3.556s |

All twelve produced WAVs are **byte-identical within their case**. The roughly 4%
time difference is small and machine-dependent, not a whole-film speed claim.
The long test measures bounded synthesis, not a newly created 260-second film or
high-fidelity sound demonstration. The 8 kHz rate is deliberately a stress fixture.

The current real native project was also fully rebuilt: 290 frames, 960×540,
25 fps, 11.6 seconds. Against the retained verified pre-change build:
- All 290 decoded FFV1 RGB frames, PTS and holds matched exactly.
- Whole WAV and final MP4 files matched byte-for-byte.
- Final native verification passed. The one full acceptance run took 36.426s,
  not a paired or repeated performance benchmark.

## Regression coverage and reproduction

The eleven regressions cover cropped seeded noise, overlapping maximum event
counts, fractional sample boundaries, 4095/4096/4097-sample outputs, rates and
FPS, silence, live recipe edits/repeated calls, bounded writes/allocations, an
unknown benchmark reference, and disk-write failure followed by real resume.
The real small export compares PCM and MP4 bytes and checks video clocks.

```sh
python -m unittest discover -s tests -p test_native_stream_audio.py -v
# From a source checkout, explicitly select its runtime. Or install its wheel
# into an isolated environment before running the copied benchmark tool.
PYTHONPATH=. python tools/benchmark_stream_audio.py examples/native-shots/project.json \
  --baseline-source baseline_shot_renderer.py --out new-audio-benchmark --repeats 3
```

The benchmark requires the validated local native project/assets, rejects any
other reference source, and uses a new non-symlink output directory. The compact
package supplies a tiny validated stage with the same audio recipe for reuse
without shipping the large visual atlas assets. Worker measurements record the
loaded renderer source path/hash. RSS accounting requires Linux/macOS; no native
Windows/macOS or big-endian test is claimed. Independent review and full-suite
results are recorded separately in the delivered evidence.

This is an exact-output memory optimization. It neither improves character
identity nor synthesizes missing animation poses, and it makes no subjective
sound-quality or user-acceptance claim.
