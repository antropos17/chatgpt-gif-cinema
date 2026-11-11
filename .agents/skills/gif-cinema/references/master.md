# Preserve native GIF pixels and timing

The pinned runtime's `master` command decodes ordered local GIFs into a silent
FFV1/Matroska master. It preserves Pillow-decoded RGBA8 canvases and declared
centisecond delays, including the final hold. This is not preservation of the
original compressed GIF bytes or a guarantee of every browser's timing policy.

Install the exact `gif-cinema[lossless]` pin in [the skill guide](../SKILL.md).
Lossless export needs `av>=16.1,<17` with FFV1 support. The optional viewing MP4
also needs FFmpeg/ffprobe; it is lossy H.264, with alpha composited on black.
Optional local audio goes only into the viewing MP4 as lossy AAC, not the master.

```bash
python scripts/check_install.py --require-master
python -m gif_cinema master assets/example/shot-01.gif --out ../project/master --dry-run
python -m gif_cinema master assets/example/shot-01.gif --out ../project/master --preview
python scripts/smoke_master.py --out ../project/master-smoke
```

To include an existing local track, add `--preview --audio /path/to/audio.wav`.
The master uses one iteration of each input in order. Different canvas sizes are
center-padded transparently without scaling or cropping. Every source drawing has
its own exact timestamp and duration. The viewing copy repeats those drawings on
a 100 fps/10 ms grid; this creates no new poses or motion interpolation.

Inputs require a defined nonzero delay for every drawing, supported disposal and
square pixels. Ambiguous controls, interactive graphics and plain-text graphics
are rejected. Budgets are 1–64 GIFs, 256 MiB combined bytes, ten minutes, 6,000
drawings and 512 Mi padded pixel-frames. The output directory must be new.

The optional 100 fps viewing copy has a separate **4 Gi pixel-frame** limit
(4,294,967,296 output pixel-frames): about 164 seconds at 512×512 or 20.7 seconds
at 1920×1080. A native-timing master can fit while its viewing copy is rejected.
Build only the VFR master in that case; selected drawings are never silently
omitted to satisfy the preview budget.

`manifest.json` records input/output hashes, source/canvas RGBA hashes, source
rectangles, timestamps, durations, decoder/encoder versions and re-open results.
Every master drawing is decoded again and checked. The optional preview is fully
decoded and checked for frame count, duration and requested audio coverage. AAC
can include codec padding; `target_samples` is the intended timeline, not a claim
that raw AAC decode has no padding.

The installed smoke uses three synthetic 24×24 drawings at 10/20/150 ms and a
50 ms local PCM fixture. It plans the positional route, writes a public edit
template and exports two script selections `[0,2)` and `[2,3)` in one build.
Together they retain the same three drawings, not two new actions. It reopens
all RGBA drawings and exact timestamps/durations, checks the final 150 ms hold,
18 viewing frames, the 8,640-sample audio target and exact SRT ranges 0–30–180 ms,
and verifies all four output hashes including both sidecars.
Network is blocked and provider calls are zero. Synthetic fixtures are not an
artwork-quality demonstration. Visual review and user acceptance remain pending.

The default install check reports lossless support as optional and still permits
Pillow-only review/sprites when it is absent. `--require-master`, the master smoke
and full smoke fail before creating their output when lossless support is missing.

## Edit an existing source-only script

Use the v1 `film.json` produced by the story helper after all shots have actual
local source GIFs. Prompt-only shots are rejected without generation. Script order,
source paths, captions and optional audio are authoritative; only hard cuts are
supported. For the bundled source-only example:

```bash
python -m gif_cinema master --script assets/example/film.json --write-edits ../project/edits.json
# Review/edit the two integer drawing indices for each shot, then:
python -m gif_cinema master --script assets/example/film.json --edits ../project/edits.json --out ../project/edit --dry-run
python -m gif_cinema master --script assets/example/film.json --edits ../project/edits.json --out ../project/edit --preview
```

`--write-edits` creates a new file, never replaces an existing edit, and does not
render. Its full ranges are a starting point, not approval. You may omit `--edits`
to keep each complete source GIF in script order. Input paths resolve relative to
the script. Output and edit-template paths are the paths you pass on the command line.

The sidecar is strict JSON with `format: gif-cinema-exact-edit`, `schema_version: 1`,
the exact `script_sha256`, and a `shots` list. Every entry contains `id`,
`source_sha256`, `in_frame` and `out_frame`. Keep every shot once in script order.
Ranges are zero-based, half-open original drawing indices: `[2,9)` keeps drawings
2 through 8 with their original delays. No drawing is split or re-encoded as a GIF.
Changed script/source hashes, duplicate or unknown fields, reordered IDs and
boolean/fractional/out-of-bounds indices fail. After intentional input edits,
create and review a new template rather than blindly replacing hashes.

Disposal compositing may need drawings before the selected range. Prefix decoding
and selected output each obey the 6,000-drawing/512 Mi-pixel bounds; a tiny late
selection cannot bypass decoding limits. The script's FPS is recorded and does
not resample the exact master. Its width/height are a centered transparent canvas;
oversized sources fail instead of scaling or cropping. `--native-canvas` explicitly
chooses the largest source dimensions and can differ from the script ratio.

Script export adds `captions.srt` and `timeline.json` with exact selected millisecond
boundaries and hashes in `manifest.json`. Captions remain sidecars, not burned into
preserved artwork. Ambiguous SRT cue delimiters, blank separator lines and control
characters in captions fail. Source and edit hashes remain in the manifest.

For sound, set the script's `audio` path and request `--preview`. The positional
`--audio` option cannot override script audio. The track starts at zero and is
padded/trimmed to the selected duration before lossy AAC encoding. There is no
per-shot audio mixing, new drawing generation, interpolation or automatic cut
approval. Inspect the final playback and every join yourself.
