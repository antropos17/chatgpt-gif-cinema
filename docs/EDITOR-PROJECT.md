# Browser project → verified backend film

The Python backend now accepts the existing Browser Studio `.gfc` format directly:

```sh
python -m gif_cinema.editor_project saved-project.gfc --out NEW_OUTPUT
# Optional: omit the lossy viewing derivative.
python -m gif_cinema.editor_project saved-project.gfc --out NEW_OUTPUT --no-preview
```

Use Python 3.10+, the checked local runtime with its `lossless` extra (PyAV 16.1),
and FFmpeg/ffprobe for the viewing derivative. This command runs locally, makes no
provider requests and does not start a server, publish a site or change access.
The unchanged upstream version number is not enough to identify this local build.

## What is preserved

GFC1 projects contain the editor's current **256×256 straight RGBA working frames**,
scene labels/order and frame holds, not the original GIF files. The backend stores
one FFV1 frame per working drawing with an exact centisecond timestamp and hold.
It reopens the actual Matroska output and checks every RGBA byte, timestamp, duration
and final hold using the existing master verifier. Identical consecutive drawings
remain separate frames. No GIF quantization round-trip is involved. Hidden RGB in
transparent working pixels is preserved in the exact master.

This does **not** reverse scaling, black background compositing or source-decoder
choices already performed by Browser Studio. It does not preserve the original
GIF dimensions or recover source transparency that the browser flattened. Existing
source-only GIF master export remains the route for original decoded GIF canvases.
No new drawings, interpolation, smoother motion, character identity or artistic
acceptance is established by this bridge.

## Delivered files

- `project.gfc`: the unchanged input snapshot.
- `master.mkv`: exact silent FFV1 working-frame film.
- `preview.mp4`: optional silent, lossy 100 fps H.264 viewing copy. Holds repeat on
  the 10 ms grid; transparency is composited onto black. Player support varies.
- `manifest.json`: source hash, scene boundaries, per-frame RGBA hashes and timing,
  codec information, verification results and file hashes.

A completed result requires `manifest.json`. All encoding/verification is staged
first. Final files are published without replacement and the manifest is last;
publication failure rolls back files created by this attempt. This is **not** a
power-loss-durable transaction or a portable atomic whole-directory replacement.
An interrupted publication can leave a directory without the completion manifest;
retain it for inspection, do not treat it as successful or overwrite it automatically.
Existing output paths and input/output symlinks are rejected. Input changes detected
before publication reject the result. Scene names are metadata, never path components.

## Bounds and validation

The project must have the GFC1 magic and little-endian header length, a UTF-8 JSON
object with version 1 and width/height 256, and exactly the declared RGBA payload.
Header keys are `version`, `width`, `height`, `scenes`; scene keys are `name`, `delays`.
Unknown/duplicate fields, booleans in numeric fields, non-finite values and invalid
Unicode labels are rejected. Limits: 64,000,000 input bytes, 100,000 header bytes,
1–8 scenes, 1–240 total drawings, 30 seconds total. Delays are integer 10–30,000 ms
multiples of 10. Empty projects/scenes, truncated and trailing payloads are rejected.
The existing 512 MiB master and 128 MiB preview output budgets still apply.

The backend reads one immutable bounded project snapshot. It does not accept URLs,
commands, embedded assets, arbitrary media paths or audio tracks in project metadata.
The optional HTTP adapter is a separate component with its own admission, origin,
authentication and process-lifetime controls. This module is not a multi-user service.

## Verification scope

`tests/test_editor_project.py` covers real FFV1 round-trips for every working RGBA
byte, duplicate drawings, alpha/hidden RGB, 10 ms intervals and long final holds;
real MP4 frame-count/duration checks; metadata/payload bounds; source mutation;
corrupted packing; derivative failure; no-clobber and manifest-last rollback.
Python-only fixtures are not a browser acceptance test. Cross-runtime/browser and
HTTP integration checks belong to the adapter tests. Native Windows/macOS behavior
and broad player compatibility are not claimed by a Linux run.
