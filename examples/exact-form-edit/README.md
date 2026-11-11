# FORM / 01: exact three-shot edit

This example splits the existing [Blender FORM/01 GIF](../blender-form-01/README.md)
into `[0,40)`, `[40,80)` and `[80,120)`, then rejoins those ranges in script order.
It preserves all 120 original drawings and their 50 ms holds: 640×640, six seconds.
It is an integration proof of the montage, not new artwork or a three-scene story.

```bash
python -m pip install -e '.[lossless]'
python -m gif_cinema master --script examples/exact-form-edit/film.json --edits examples/exact-form-edit/edits.json --out output/exact-form-edit --dry-run
python -m gif_cinema master --script examples/exact-form-edit/film.json --edits examples/exact-form-edit/edits.json --out output/exact-form-edit --preview
```

The new directory contains an exact FFV1/BGRA `master.mkv`, lossy H.264
`preview.mp4` with 600 repeated viewing frames, `captions.srt`, `timeline.json`
and the frame/hash/timing manifest. OPEN, TURN and RETURN are optional external
subtitles spanning 0–2, 2–4 and 4–6 seconds; they do not alter the master pixels.
The original `.blend`, GIF and provenance remain in the FORM/01 example.

The sidecar pins the exact bytes of `film.json` and the source GIF. Editing either
requires a fresh, reviewed sidecar. Use a new output directory for each export.
No provider, paid API or JavaScript animation is used. Software verification is not
an artistic or semantic-continuity approval.
