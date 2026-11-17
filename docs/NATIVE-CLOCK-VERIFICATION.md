# Verify native frame holds and sound coverage

The native shot renderer already accepts integer frame rates from 1 to 60. Its
old verifier compared decoded timestamps to ideal seconds within one microsecond.
That incorrectly rejected its own FFV1/Matroska output at rates such as 24, 30 and
60fps: Matroska stores timestamps on a millisecond grid. Separately, the verifier
did not check frame holds and accepted any nonempty stereo audio decode.

This change fixes **verification and compatible frame-rate support**, not drawing
quality, identity, interpolation or performance. Rendering, encoder arguments,
source art, sound synthesis, output format and authored frame count are unchanged.

## Video clock checks

`verify_video_clock` uses exact rational arithmetic:
- A timestamp must equal the ideal `index/fps` rounded half-up to the decoded
  time base. There is no accumulating float tolerance.
- Each positive hold, including the final frame, must be the floor or ceiling
  of the ideal frame period in those ticks. If exactly representable, only the
  exact value passes: at 25fps and 1ms ticks, 40ms passes but 41ms does not.
- Fractional clocks coarser than 1ms are rejected. Coarser clocks are allowed
  only when the frame period is an exact integer number of ticks.
- Missing timestamps/time bases, zero/negative holds, wrong dimensions, one-tick
  timestamp errors and extra/missing frames remain failures.

For 30fps Matroska, PTS can be `0,33,67,100ms` and holds can be `33ms`.
That is container quantization, **not exact 1/30-second storage**. The final stored
endpoint can differ from the ideal by less than 1.5ms (half a tick for PTS plus
less than one tick for a hold). MP4 uses its own finer time base. No original
frames are dropped, invented or retimed by this verifier.

Scene verification remains single-pass. Every RGB hash and pre/post file hash is
still checked. Final assembly remains private until checks complete; a failure
leaves accepted checkpoints available for unchanged-input resume. Decoder generators
are explicitly closed on failure. A new engine identity requires a new revision;
old completed outputs can still be verified without overwriting them.

## Audio clock checks

A valid AAC decode can include codec padding beyond the effective stream endpoint.
Counting decoded samples alone is not proof that sound covers the film.
The verifier now checks both:
1. Effective stream start/end against the video timeline, with a bounded allowance
   of 1ms plus one input and one output sample for metadata/slicing/resampling.
2. Every decoded block's timestamps, sample rate, channels, positive sample count
   and contiguous sample clock, starting at zero. Gaps and overlaps are rejected.
3. Decoded coverage reaches the effective/video endpoint. Padding is capped at the next 1024-sample AAC block boundary of the effective
   endpoint. An extra complete block or an oversized decoded block is rejected.

The encoded sample rate need not equal the input rate: FFmpeg can resample an
unsupported rate, e.g. 8001Hz input to 8000Hz AAC. These checks do not evaluate
loudness, musical quality, speech meaning, perceptual sync or compare decoded AAC
samples to lossless PCM. AAC is still lossy.

## Verified regression cases

```sh
python -m unittest discover -s tests -p test_native_clock.py -v
```

Requires Pillow; integration cases additionally need FFmpeg and PyAV. The 13 tests
cover rational clocks across all 1–60fps, long frame indices, real build/verify/
resume at ten representative rates, five additional audio input rates, resampling,
invalid metadata, final holds, short/gapped AAC and atomic failure recovery.

Three real malformed-input cases that previously passed are now rejected:
- Four FFV1 frames with identical RGB/PTS, but final hold **40→140ms**.
- Eight video frames/320ms, but effective AAC duration only **40ms**. Decoder
  padding does not hide the missing coverage.
- Fifty video frames/2s, matching 2s effective AAC metadata, but a decoded gap
  **512→768ms**. Correct endpoints alone do not prove continuous audio.

The regular 25fps route remains compatible. A real 290-frame, 11.6s native project
is checked separately against its retained verified output: all source RGB hashes,
movie timestamps/holds, PCM hash and final MP4 hash must match. This is an acceptance
check, not a speed benchmark. See the accompanying evidence for actual results.
No API/provider calls or perceptual/face-lock claims are involved.
