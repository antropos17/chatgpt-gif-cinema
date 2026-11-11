# Exact script montage

Use an existing source-only `film.json` to assemble the actual GIF drawings, their
original delays, shot order, captions and one soundtrack into a verified film master.
This joins the script workflow to the lossless master introduced in `GIF-MASTER.md`.
It does not generate missing scenes, poses or transitions, and does not prove character
identity or good cuts. Author review remains required.

Install the runtime's `lossless` extra. PyAV/FFV1 is needed for the silent master;
FFmpeg/libx264 and ffprobe are also needed for the optional H.264/AAC viewing copy.

```bash
python -m gif_cinema master --script film.json --out output/master --dry-run
python -m gif_cinema master --script film.json --out output/master --preview
```

The existing v1 script remains authoritative. Paths are relative to the script,
not the shell directory. All shots must have a local `source` GIF; prompt shots
are rejected without generation. Only hard cuts are supported. There are no API
calls, no JavaScript animation and no dependency on a generation service.

## Select original drawings at a cut

```bash
python -m gif_cinema master --script film.json --write-edits edits.json
# Review/edit the in_frame and out_frame values, then:
python -m gif_cinema master --script film.json --edits edits.json --out output/edit --dry-run
python -m gif_cinema master --script film.json --edits edits.json --out output/edit --preview
```

`--write-edits` writes a new file only. Its full ranges are a starting point, not
an approval that an untrimmed export meets duration/canvas budgets. It never replaces
an existing selection. A sidecar has this strict shape:

```json
{
  "format": "gif-cinema-exact-edit",
  "schema_version": 1,
  "script_sha256": "the exact script byte hash",
  "shots": [
    {"id": "shot-01", "source_sha256": "the exact GIF byte hash", "in_frame": 2, "out_frame": 9}
  ]
}
```

Ranges are **zero-based and half-open**, `[in_frame, out_frame)`, in the original
GIF's stored drawing indices. `[2,9)` retains drawings 2 through 8 with each one's
original delay. No frame is split, no selected drawing is dropped or invented,
and no GIF is saved again to perform the cut. A deliberate selection excludes
unselected drawings; “lossless” does not mean that a trimmed edit keeps those.

Every shot must appear once in the sidecar, in script order, with its exact ID and
source hash. The sidecar cannot substitute sources, reorder the script or override
captions/audio. Duplicate JSON fields, unknown fields, changed inputs, invalid
ranges and boolean/fractional frame indices fail explicitly. After changing a
script or source, generate and review a new template; do not blindly replace hashes.

GIF disposal may depend on earlier drawings. The decoder reconstructs that prefix
before the in point. Both selected canvas pixels and prefix decoding have aggregate
limits: at most 6,000 drawings and 512 Mi pixel-frames. A late one-frame selection
cannot bypass the work needed to reconstruct its composited pixels. Total encoded
inputs are limited to 256 MiB. Existing per-GIF limits and strict control/delay
validation still apply. Selected output is limited to ten minutes; the optional
100 Hz preview has its separate 4 Gi pixel-frame ceiling.

## Timing, composition and sound

- The master uses exact declared GIF delays, including 10 ms drawings and the final
  hold. The script's FPS is recorded but **does not resample** the exact master.
- By default the script's width/height are used as a transparent centered canvas.
  There is no scaling or cropping. Oversized source canvases fail. Either author a
  larger script canvas or explicitly choose `--native-canvas`, which uses the maximum
  native source dimensions and records that choice. It may differ from script ratio.
- `captions.srt` and `timeline.json` use exact selected durations in integer milliseconds,
  not rounding to the script FPS. Captions are sidecars, not burned into preserved
  artwork. Blank cue separators, control characters and `-->` in caption text fail
  rather than producing ambiguous SRT. Both sidecar hashes are in `manifest.json`.
- Script `audio` is the one soundtrack starting at zero. It requires `--preview`.
  The existing strict audio reader snapshots and decodes it, then pads/trims to the
  selected film duration before lossy AAC encoding. `--audio` cannot silently override
  script audio. Music mixing, per-shot offsets and crossfades are not implemented.
- The optional `preview.mp4` repeats source drawings on a 100 Hz grid and composites
  transparency on black. H.264/AAC is a lossy viewing copy, not the preserved master.

The new output directory is staged and published without overwriting files. Source
GIF hashes are checked again before snapshots. Exact master verification reopens
all output frames and compares decoded RGBA, PTS and each hold duration. A successful
verification leaves visual acceptance pending. This fixes the assembly contract;
it does not repair a semantically wrong action or manufacture smooth intermediate poses.

## Reproducible Blender proof

[The FORM/01 edit](../examples/exact-form-edit/README.md) uses the existing Blender
artwork in three sequential ranges. Together they retain all original 120 drawings
and six seconds. This is a split-and-rejoin integration proof, not three newly
created scenes. Its example script, sidecar and original GIF are all in the repository.
