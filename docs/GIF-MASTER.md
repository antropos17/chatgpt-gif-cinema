# Preserve GIF drawings and timing in a film master

The ordinary `film` and `render` commands make a fixed-FPS H.264 movie. This is
useful for delivery, but resampling can drop short GIF drawings or change holds.
Increasing the output FPS does not create missing poses or repair a bad story cut.

The optional `master` route provides a different, measurable contract:

- **master.mkv:** FFV1/BGRA, one decoded video frame for every stored GIF drawing,
  with exact RGBA pixels, presentation timestamps and declared frame durations.
- **preview.mp4**, when requested: a broadly usable H.264 viewing copy, repeating
  original drawings on a 100 Hz / 10 ms grid. It is lossy, has no alpha, and does
  not invent intermediate movement. Optional sound belongs to this viewing copy.
- **manifest.json:** source hashes, decoder/encoder versions, every drawing's
  timing and pixel hashes, source-to-canvas placement, output hashes and checks.

“Lossless” applies to the named Pillow decoder's full **RGBA canvases**, not the
original compressed GIF bytes, browser-specific playback rules, prompt identity,
anatomy, semantic continuity or artistic acceptance. The master is a silent
preservation file, not a promise that every mobile player supports FFV1.

## Install and run

Use the current checkout with Python 3.10+, Pillow and the optional PyAV dependency:

```bash
python -m pip install -e ".[lossless]"
python -m gif_cinema master first.gif second.gif --out output/exact-film --dry-run
python -m gif_cinema master first.gif second.gif --out output/exact-film --preview
```

FFmpeg with libx264 and ffprobe are required only for the viewing copy and audio.
The master encoder is the FFmpeg library bundled with the installed PyAV wheel;
its exact versions are recorded. NumPy is not required by this implementation.

Pass the accepted shots in their intended order. These can be saved render takes,
Blender GIFs, editable-layer exports or titles. Inputs are never overwritten.
The destination must be new. Maintained source package 0.4.0 includes the master
and script-edit guides plus an installed smoke. Its immutable runtime pin is in
the skill folder. The older GitHub Release `skill-v0.1.1` predates these workflows;
building a current source ZIP does not publish a new GitHub Release.

For sound starting at the beginning of the viewing movie:

```bash
python -m gif_cinema master first.gif second.gif --out output/exact-with-sound --preview --audio soundtrack.wav
```

The imported audio is snapshotted and strictly decoded before encoding. It is
resampled to 48 kHz, padded or trimmed to exactly `duration_cs × 480` target samples,
and starts at zero. Explicit trimming avoids the short/long-stream problems of
using `-shortest` alone. AAC is lossy and can expose codec padding when decoded to
raw PCM; it is not sample-for-sample preservation of the original audio. The silent
master is unaffected. This is one soundtrack, not event-based SFX editing or mixing.

## Exact timing and pixels

GIF delays are stored as integer centiseconds. The strict master profile accepts
positive declared delays, including 10 ms, without changing them to a browser's
minimum playback delay. Zero/missing delays and interactive GIFs need an explicit
policy and are rejected rather than guessed.

Each source is played **once**, regardless of loop metadata. Different canvas sizes
are centered in a transparent canvas large enough for every source. There is no
resizing or cropping. Source ROIs and hashes are recorded, including RGB under
transparent pixels. Disposal 0/1/2/3 follows the recorded Pillow decoder; undefined
disposal, plain-text graphics and non-square pixel-aspect metadata are rejected.

Frames receive exact cumulative PTS and delay values on a 1/100-second time base.
Crucially, the corresponding **encoded packet duration is set before muxing**.
Setting only `frame.duration` does not preserve the final hold with this FFV1 encoder.
Matroska may use a 1/1000-second time base; every centisecond remains exactly
representable. FFV1 level 3 with slice CRC is used normally; one-pixel-wide/tall
canvases use verified level 1 for compatibility. Chosen options are recorded.

Before publication, the entire master is decoded again and checked against every
source-derived frame record:

1. No missing, coalesced, reordered or extra stored drawings.
2. Full padded RGBA hash and original source ROI hash.
3. Exact PTS and duration for each frame.
4. Exact final frame hold and total duration.

The MP4 viewing copy has one encoded frame per centisecond, repeating existing
artwork without interpolation. Transparency is explicitly composited on black;
odd dimensions get at most one black pixel of right/bottom padding. There is no
source-art scaling. Video frame count/duration and full decode are checked. AAC
track duration is checked separately when audio is present. Pixel hashes apply to
the master, **not** to lossy H.264.

## Reproduce the difference

```bash
python tools/demo_preserved_timing.py --out output/timing-comparison
```

Open `comparison.png` and the three MP4s. The script generates only a tiny colored
timing fixture, then measures actual decoded exports. It makes no provider calls.

The seven declared drawings last 260 ms. In the tested ordinary 25 fps export,
two short color phases disappear and the movie lasts 280 ms. The 5 fps export
contains only two displayed phases and lasts 400 ms. The master keeps seven frames
and 260 ms with zero RGBA/PTS/duration mismatches; the new viewing copy repeats them
into 26 frames while keeping the same 260 ms timeline. Frame count alone is not
coverage: the old 25 fps result also has seven video frames, but repeats some
artwork while omitting other drawings.

The JSON comparison includes the actual sampled pixels and timestamps. This is a
reproducible engineering demonstration, not commissioned animation or visual approval.
Direct VFR H.264 delivery is also possible with carefully controlled demuxing,
time bases, encoder settings and verification. It is not what this viewing mode
claims to implement; naive concat-filter/PNG-sentinel approaches were not reliable
for all final holds in experiments.

## Bounds and failure behavior

- 1–64 ordered local GIFs; at most 256 MiB encoded input total.
- Existing structural GIF limits apply per input, including 1,500 stored frames.
  Fixed logical canvases are required; dimensions may not exceed 4096 × 4096.
- At most 6,000 drawings, 512 Mi padded pixel-frames, and 10 minutes per master.
- Master writes are bounded to 512 MiB before growth. Viewing files must remain
  within 128 MiB after encoding; packet/trailer overshoot is rejected.
- The 100 Hz viewing expansion is limited to 4 Gi pixel-frames. A large, slowly
  changing master can fit while its expanded viewing copy does not. Build only the
  VFR master in that case; the tool never silently drops drawings to fit.
- Existing audio byte/rate/channel limits and media subprocess timeouts apply.
  Dry-run checks structure, declared timing and budgets without outputs, encoders,
  audio decoding or optional PyAV loading. Full GIF decode remains pending until build.

Source bytes are checked again when copied into private staging. All encoding and
verification finish before a new output directory is claimed. No-clobber publication
writes `manifest.json` last and cleans up files created by a failed publication.
Only complete verified output is delivered; original files and accepted exports
remain intact. Receipts are not cryptographic signatures or visual acceptance.

## What this cannot fix

A cut can still be wrong even when every pixel and delay is preserved. Review actual
playback for identity, pose/contact, eyelines, lighting, intent and pacing. Use aligned
accepted shots, trims or authored transitions where appropriate. This route does not
create unseen actions, improve source drawing cadence or make a discontinuity disappear.

## Script-controlled edits

`master --script film.json` adds source-only script order, optional exact frame-range
selections, exact SRT/timeline sidecars and script audio. See
[Exact script montage](EXACT-SCRIPT-EDIT.md) for the strict sidecar contract and limits.
