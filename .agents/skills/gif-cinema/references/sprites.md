# Offline sprites and runtime atlases

Turn existing drawings into reusable assets without calling a model:

```bash
# Existing OpenAI GIF, local drawing animation, or other authorized source.
python -m gif_cinema sprites pack assets/example/shot-01.gif --columns 8 --out ../project/sprites --dry-run
python -m gif_cinema sprites pack assets/example/shot-01.gif --columns 8 --out ../project/sprites
```

These commands use the repository's bundled no-key sample. Replace the source path
with another GIF you have permission to use.
Python 3.10+ and Pillow are sufficient. No FFmpeg, API key, provider, network access,
subscription or paid call is used by these commands. Existing OpenAI GIF generation
is a separate, explicitly authorized step. This feature does not use Higgsfield,
Grok, video generation, background-removal models or hidden credentials.

`--dry-run` decodes and validates the input, computes the same shared coordinates
and prints a plan. It writes nothing and does not encode or claim to verify a GIF.
Execution requires a **new** output directory. There is no overwrite switch.

## Outputs

- `frames/0000.png`, etc.: full RGBA drawings in source order, including repeats.
- `atlas.png`: the same drawings packed into equal-size cells with transparent
  padding. PNGs preserve the decoded pixels, including partial alpha.
- `animation.gif`: a **lossy preview**, with one shared 255-color palette plus a
  transparent palette entry. Alpha below 128 becomes transparent; other alpha
  becomes opaque. An animated preview can be a film-script source after visual
  review. Single-pose or fully merged previews are static and cannot be imported
  by the film renderer, which requires at least two decoded GIF frames.
- `manifest.json`: versioned runtime coordinates, individual delays, loop metadata,
  source checksum, crop/scale, RGBA pixel checksums, output file checksums, warnings
  and actual preview timing. Published last as the completion marker.

The files are staged and the encoded GIF is decoded to verify total duration and
loop metadata before publication. Files publish without clobbering existing paths.
A failure during publication can leave a partial directory without a manifest.
Already published files are retained, not deleted, because another process could
have replaced or started using them. Inspect that directory and choose a new output
path for a retry. Directory identities are checked between publication steps to
stop when another process replaces the output or frames directory. Original media
are never changed.

Each `frame_layout` entry uses an absolute pixel rectangle `[x, y, width, height]`
inside `atlas.png`. Coordinates exclude padding. `duration_ms` belongs to that
source drawing, not to a uniform playback FPS. This is a small explicit runtime
format, **not** an Aseprite, Phaser, Unity or sprite-gen compatibility claim.

GIF encoders can combine consecutive identical drawings into one longer hold.
The manifest preserves every input drawing and records the actual decoded preview
frame count and delays separately. `loop: null` means no loop extension (play once),
`0` means infinite, and a positive integer is the GIF repeat count after the first
play. Some viewers impose their own playback policy.

## Slice a reviewed PNG grid

Save `poses.json` beside `poses.png`:

```json
{
  "schema_version": 1,
  "atlas": "poses.png",
  "grid": [3, 2],
  "cells": [[0, 0], [1, 0], [2, 0], [0, 1]],
  "duration_ms": [100, 100, 100, 300],
  "loop": 0,
  "trim": true,
  "scale": 2,
  "sampling": "pixel",
  "columns": 4,
  "padding": 2,
  "require_margin": 1
}
```

```bash
python -m gif_cinema sprites slice poses.json --out ../project/poses --dry-run
python -m gif_cinema sprites slice poses.json --out ../project/poses
```

An image-model prompt asking for a grid does **not** prove that a PNG follows one.
Review the source: faces, proportions and pose origins may drift; characters can
cross gutters or overlap their neighbors. `grid` only describes equal-sized cells.
The command requires exact divisibility and never guesses cells, repairs anatomy,
recenters characters or erases a background. Use a correctly prepared sheet if
poses do not fit that grid. Any input source must be yours to use.

### Spec contract (version 1)

Unknown fields and duplicate JSON keys are rejected. Booleans do not count as
integers. All paths are local; `atlas` resolves relative to the spec file.

| Field | Meaning and default |
| --- | --- |
| `schema_version` | Required integer `1` |
| `atlas` | Required local still PNG; APNG and other formats are rejected |
| `grid` | Required `[columns, rows]`, each 1..256, at most 256 cells total |
| `cells` | Ordered zero-based `[column, row]` selections; 1..256 entries; default all cells, row-major; repeats allowed |
| `duration_ms` | Integer delay for all selections, or a list matching `cells`; default 120; each 20..60000 in multiples of 10 |
| `loop` | Absent or `null`: play once; `0`: forever; 1..65535: repeat count |
| `crop` | Optional common `[x, y, width, height]` inside every cell; warns if visible pixels are removed |
| `trim` | Default `false`; one union of all selected alpha bounds; mutually exclusive with explicit `crop` |
| `scale` | Integer 1..4; default 1; applied equally to all frames |
| `sampling` | `pixel` (nearest neighbor, default), or `smooth` (Lanczos) |
| `columns` | Packed output columns, 1..256; default 8, capped to selected frame count |
| `padding` | Transparent pixels on each side of each packed cell, 0..64; default 1; no edge extrusion |
| `require_margin` | Default 0; 0..256 transparent pixels required at **every original cell edge** for every selected pose, before crop/trim |

For GIF packing, `--columns`, `--padding`, `--trim`, `--scale` and `--sampling` have
the same meanings. Source delays and loop metadata are retained; there is no FPS
override or invented tweening. Use `--sampling pixel` for pixel art.

## Why a shared crop matters

Independent tight crops make a character's head, feet and apparent scale jump
between poses. Shared trimming takes the union of every selected pose's alpha
bounds and applies **that same rectangle to all drawings**. Their relative motion
and empty space remain intact. Scaling is then shared, too. This preserves input
alignment; it cannot fix source poses that were already misaligned.

Do not interpret a transparent margin as visual approval. It detects visible pixels
touching an edge, not missing fingers, inconsistent identity or a wrong facing
direction. The full margin strips are checked, including partially transparent
pixels. Entirely transparent frames, opaque backgrounds and consecutive duplicate
drawings produce explicit warnings. All exports remain `human-review-required`.

Inspect the PNG frames on light and dark backgrounds and play the **decoded** GIF.
Check all poses, every boundary, actual timing and first-to-last loop continuity.
Transparent PNGs can keep soft edges that GIF cannot reproduce. `smooth` scaling
does not create extra action drawings; duplicated poses remain holds.

## Import into a film

After reviewing `animation.gif`, use it as a local `source` in a normal v1 film
script if it contains at least two decoded frames. A single pose still exports
useful PNG assets, but does not count as an animated film source. Preserve
`first_frame_target` and `last_frame_target` descriptions and check
the neighboring cuts. Use `render ... --execute --max-api-calls 0` for a guaranteed
source-only film. See [the pinned script contract](https://github.com/antropos17/chatgpt-gif-cinema/blob/c4cc9a095ab55ee9618f1dd0c3150743b047c1ac/docs/SCRIPT-FORMAT.md).

Sprite export retains alpha. The existing film assembler uses opaque video frames;
exporting a transparent atlas does not add transparent-video or layered scene
composition to that assembler. Keep the PNG assets for a compositor that supports
them and choose the background explicitly there.

## Resource limits

- 1 MiB JSON spec, 32 MiB encoded PNG/GIF input.
- 16 megapixels per input PNG atlas; 4 megapixels per extracted or scaled drawing.
- 256 selected/decoded frames; 32 megapixels across all retained drawings.
- 120 seconds total animation duration.
- 16 megapixels and 16384 pixels per dimension in the packed output atlas.
- GIF input must stay inside its fixed logical canvas. Existing GIF block-framing
  preflight runs before decoding; malformed extensions or oversized descriptors fail.
- Inputs must be regular local files. Devices and FIFOs are rejected without
  waiting for a writer; Windows reads explicitly preserve binary control bytes.

The limits apply before the corresponding bulk frame or atlas allocation. Exceeding
one fails explicitly; the tool does not silently downsample, truncate or discard poses.
The palette is trained from bounded samples of every frame, so GIF color remains an
approximation even when the PNG atlas is lossless. Keep the source and manifest.

## Workflow influences and rights

This is an independent implementation, without copied upstream code or media:

- [GIF Factory](https://github.com/WoYun520/gif-factory) (MIT code/documentation):
  shared pose bounds, deliberate timing, separate pixel/HD scaling, decoded-output
  review. Its gallery and character assets do not become ours to redistribute.
- [aldegad/sprite-gen](https://github.com/aldegad/sprite-gen) (Apache-2.0): explicit
  runtime frame rectangles, transparent source frames, state-by-state curation and
  honest motion QA. No provider authentication, external video pipeline, source
  package, code or artwork from that project is bundled here.

Only the general workflow ideas are adopted. GIF Cinema's existing source-available
license remains unchanged. Background removal, arbitrary irregular-sheet segmentation,
state generation, automatic loop repair and engine-specific exporters are not included.
