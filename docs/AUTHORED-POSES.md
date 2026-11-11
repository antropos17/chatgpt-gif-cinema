# Edit accepted drawings, without inventing new poses

Use `pose_keys` to choose **existing** PNG-atlas drawings at explicit times, keep
clear result holds, and carry the final drawing into the next scene. This is a
post-production tool for reviewed source artwork. It does not generate a GIF from
a prompt, create missing action, repair anatomy, or establish artistic acceptance.

For anime pixel art, first obtain and review the actual source GIF or transparent
pose atlas. Keep the character's appearance, pixel grid, silhouette and palette
consistent before extending the edit. Do not replace that first step with a rigid
cutout, repeated clip, camera move, procedural stand-in, or a claim of generation.
No new art is presented as an accepted example of that style in this change.

## Keep the source-first workflow

1. Generate or supply the source using an available, authorized tool. Preview its
   real frames, especially hands, feet, silhouettes and contact. A prompt is not
   proof that any image or GIF was generated.
2. Use [sprites pack/slice](SPRITES.md) on the accepted GIF or PNG atlas, then
   [import-sprites](SPRITE-LAYERS.md). A 4 × 4 atlas can hold sixteen source records;
   the format does not require sixteen, and records may duplicate a drawing.
3. Choose the required existing drawings and their holds. Inspect every changed
   boundary before extending the scene. Missing new actions need new source art.
4. Export and inspect the actual GIF/MP4, cut triples and final loop seam. No
   crossfade or spatial deformation is inserted by a pose change.

Example source preparation, **after** a real accepted 320 × 320 GIF exists:

```sh
python -m gif_cinema sprites pack accepted.gif --columns 4 --out output/accepted-atlas
python -m gif_cinema.layers import-sprites output/accepted-atlas/manifest.json --out output/accepted-stage --width 320 --height 320 --fps 50
```

Use the exact manifest path printed by the pack command. These commands decode
and copy existing drawings; they do not call a model or create new artwork.
For a supplied atlas, use `sprites slice` with an explicit layout manifest instead.
Preserve source hashes and attribution. No GIF Factory artwork is copied here.

## An explicit pose track

The optional field is supported only on a `sprites` layer:

```json
"pose_keys": [
  {"at": 0, "frame": 0},
  {"at": 0.2, "frame": 1},
  {"at": 0.4, "frame": 2},
  {"at": 0.7, "frame": 3},
  {"at": 1, "frame": 3}
]
```

This is an excerpt, not a complete source atlas. Indices are zero-based entries
in the existing `frames` list, not coordinates inferred from the image. In a
row-major 4 × 4 atlas, the first row is normally 0–3 and the final row 12–15;
the authored frame list, rather than that convention, remains authoritative.

There must be 2–256 records with exactly `at` and `frame`. Times strictly increase
from 0 to 1 relative to the layer's active interval. Every event must fall on its
25/50 fps output grid, allowing only 1e-7 ms floating-point arithmetic noise.
The selected record is held until the next key. There are no interpolated poses,
crossfades, automatic reversal, inferred in-betweens or native clock resets.

The key at 1 is the **conceptual endpoint**. It is not appended as an extra output
sample. For a visible final hold, select that drawing before 1 and repeat its index
at 1. An endpoint-only change first becomes visible at the following scene.

Native `frames[].duration_ms` values remain validated source metadata, but are
unused as playback timing when `pose_keys` is present. Combining pose keys with
`source_range_ms` or `playback: "loop"` fails rather than choosing an ambiguous
clock. Legacy sprite scenes without pose keys retain their existing timing.
An explicitly looping scene still requires inspection of its exported seam.

## Preserve pixel geometry

Use `sampling: "pixel"`, aligned placement and an integer scale for pixel artwork.
All cells share one size and coordinate system. For an unchanged full-frame GIF,
use matching cell/canvas dimensions, center placement, zoom 1 and rotation 0.
Do not crop or recenter each pose separately. Smooth sampling, rotation, fractional
placement or noninteger scaling can alter pixel clusters even with a good source.
Those existing transform controls remain available; they are not quality fixes.

Pose changes only select a raster. An attachment point is still an authored
coordinate in the common cell, not a tracked hand or beak. A depicted contact
point that moves inside a cell must be authored and checked separately; selecting
another pose does not automatically move a held prop to that depicted point.

Source PNG colors and alpha remain authoritative. GIF previews are flattened and
palette-quantized, and MP4 is lossy. This feature does **not** add a palette lock,
color remapping or a new GIF quantizer. Review actual palette output separately.

## Carry a selected drawing through scene sequences

The [sequence compiler](SCENE-SEQUENCES.md) accepts a sprite stage only when it has
an explicit static starting pose: every seed `pose_keys` entry selects the same
record. Native GIF/sprite clocks remain unsupported in shared-stage sequences.

A shot track can supply pose keys in addition to transforms and attachments:

```json
"tracks": {
  "actor": {
    "pose_keys": [{"at": 0}, {"at": 0.5, "frame": 3}, {"at": 1, "frame": 3}]
  }
}
```

Only the first record may omit `frame`; it inherits the preceding conceptual
endpoint. Later records must state the index. Omitting the entire pose track
holds the preceding drawing for the next action. Explicitly resetting the first
index is rejected even if transforms match. The atlas, cell list and source bytes
stay fixed across the sequence. This does not claim that an extended hold or a
reused drawing is a new character action.

## Reproducible source-only check

The automated fixture is deliberately simple colored atlas cells, **not anime
art or a finished-film sample**. It proves drawing selection independently of
whole-image transforms, prop-coordinate carry, endpoint timing, portable export,
and rejection of changed source pixels and fictional timing reports:

```sh
python -m unittest discover -s tests -p test_pose_tracks.py -v
python -m unittest discover -s tests -p test_pose_sequences.py -v
```

With Pillow, FFmpeg and ffprobe installed, these include real all-frame GIF/MP4
exports and reopening a moved bundle, without network or provider calls. The
normal CLI remains `python -m gif_cinema sequence build PROJECT --out NEW_DIRECTORY`
and `python -m gif_cinema sequence verify DIRECTORY`.

The `sprite_timing` receipt distinguishes selected records, actual exported
indices and holds, omitted source records, transitions and the nonexported
endpoint. Per-frame `source_index` and RGBA pixels are independently rerendered.
Sequence verification also recomputes the sprite timing metadata. Matching
indices do not prove distinct drawings, visible poses, physical contact or story
quality. Receipt consistency is not cryptographic authentication, and encoded
GIF/MP4 pixels are not compared against every source PNG.

This is a current-checkout feature, not an update to the installed skill's pinned
runtime. No JavaScript, Higgsfield, paid API or additional dependency is involved.
