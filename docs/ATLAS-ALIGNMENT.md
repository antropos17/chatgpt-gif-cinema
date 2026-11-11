# Correct measured column drift without recentering every pose

A regular atlas can contain a repeated layout error: the same column is displaced
in several rows, so playback jumps when it returns from the last column to the
first. A moving hand also changes the silhouette bounds, so independently
centering each pose can make an otherwise steady head and planted feet shake.

The `sprites slice` importer supports **authored integer column corrections**.
Measure a stable landmark across multiple rows, then apply one `[dx, dy]` to all
cells in that column. This moves the complete existing drawing; it does not guess
anchors, deform limbs, generate intermediate poses, or approve the animation.
Use it only when the repeated shift is a layout defect, not intentional acting.

## A small explicit change to the slice spec

```json
{
  "schema_version": 1,
  "atlas": "poses.png",
  "grid": [4, 4],
  "column_offsets": [[0, 0], [-3, 0], [-5, 1], [-7, 0]],
  "duration_ms": 120,
  "loop": 0,
  "trim": true,
  "scale": 2,
  "sampling": "pixel",
  "require_margin": 1
}
```

These numbers are illustrative, not a preset for every character. Positive `dx`
moves right; positive `dy` moves down, in original cell pixels. Supply exactly one
pair per **source grid column**, even when `cells` selects only part of the grid or
reorders/repeats frames. The same correction applies in every row. Omitting
`column_offsets` keeps the existing behavior unchanged; no automatic correction
is inferred from the image.

```sh
python -m gif_cinema sprites slice poses.json --out output/aligned --dry-run
python -m gif_cinema sprites slice poses.json --out output/aligned
```

All selected cells enter one common transparent canvas, large enough to retain
all original cell pixels after their integer shifts. Its padding is computed from
all source columns, not separately from each silhouette or selected pose. This
keeps a stable coordinate system before cropping when the selection changes.
A selected-pose union trim can still change if the selection changes; use a common
explicit crop when multiple exports need identical final coordinates. An unmasked copy
preserves RGBA values, including partial alpha; there is no alpha threshold or
color remapping in this alignment stage.

Only afterward does the ordinary shared transform run:

- `trim: true` uses one union of the selected poses' alpha bounds, never a separate
  crop for each frame.
- Explicit `crop` coordinates refer to the **padded canvas**, not the original
  atlas or unshifted cell. A corrected export refuses a crop that would remove
  any pixel with alpha greater than zero. Transparent margins, including their
  invisible RGB, may be removed by an explicitly selected trim/crop.
- Integer `scale` 1–4 with nearest-neighbor sampling remains available. Smooth
  enlargement is rejected for corrected pixel artwork.
- `require_margin` still examines each original cell before padding. Added
  transparency cannot make an edge-touching source pass that check.

Timing, cell order, repeated poses and loop metadata keep their original meaning.
Offsets do not add motion. The manifest keeps `source.rectangles` in original atlas coordinates. Its
`transform.column_alignment` records `column_offsets`, `source_size`, `origin`,
`padding` in left/top/right/bottom order, `padded_size` and per-selected-frame
`frame_translations`. A cell pixel `[x, y]` lands at `[x + tx, y + ty]` before the
recorded common crop and scale. Frame hashes and timings describe the final
output. The original atlas is never modified.

Each offset component is an integer in −16384..16384, subject to the tighter
frame, aggregate-pixel and packed-atlas budgets. Dimensions and correction
parameters are checked before PNG decoding. For shared automatic trim, budgets
conservatively use the full padded canvas and requested scale: trim cannot rescue
an over-budget allocation. Explicit all-zero offsets therefore preserve pixels but
can reject an oversized trim/scale case previously accepted without the correction
field. Dry-run applies the same bounds without writing files.

## Review the complete result

Compare every corrected PNG at native size and every row boundary, then inspect
normal-speed playback and last → first. Check head/foot landmarks *and* intended
body motion. A deliberate lean, step or jump must not be canceled just to make
one measurement constant. If columns behave differently in different rows, this
single-correction model is not sufficient.

The correction is applied **after nominal cell extraction**. It cannot recover a
hand or hair already cut off by the source grid, separate overlapping neighboring
characters, remove a baked-in background or repair changing anatomy. Prepare a
better sheet or generate a targeted replacement span for those defects. A stable
palette or an unchanged pose count does not prove that acting is coherent.

The PNG frames and atlas are the pixel authorities. `animation.gif` remains the
existing **lossy sprite preview** with binary alpha; this option does not silently
upgrade its color guarantee. Import the verified PNG atlas with
[`layers import-sprites`](SPRITE-LAYERS.md) for composition. Use the separate
[exact palette workflow](PIXEL-PALETTES.md) only when its input/format contract fits;
it cannot restore colors already lost during a lossy preview export.

## Reproduce the preservation check

The repository includes `tools/check_atlas_alignment.py`. Given an existing GIF,
it adds a **known synthetic column displacement** to a test atlas, reverses only
that displacement through the public sprite importer, and compares every recovered
canonical RGBA frame and native delay with the retained source. Its before/after
GIFs use the exact fixed-palette encoder, not the lossy sprite preview.

```sh
mkdir -p output
python tools/check_atlas_alignment.py accepted.gif --out output/alignment-proof
```

This is a controlled regression demonstration, not a claim that an actual art
source had that defect or that the operation improved its anatomy. It keeps the
source bytes and reports the source identity, fixture changes and checks. It does
not generate new drawings or establish user acceptance. Inputs that cannot fit
one exact GIF palette fail rather than silently reducing colors.

## What was learned from GIF Factory

At the inspected immutable revision
[`bea2776100b61563f2beca7a805c1b45bebb192e`](https://github.com/WoYun520/gif-factory/tree/bea2776100b61563f2beca7a805c1b45bebb192e),
[`export_pixel_actions.py`](https://github.com/WoYun520/gif-factory/blob/bea2776100b61563f2beca7a805c1b45bebb192e/scripts/export_pixel_actions.py)
uses fixed column corrections before a shared crop and scale.
[`pixel-actions.md`](https://github.com/WoYun520/gif-factory/blob/bea2776100b61563f2beca7a805c1b45bebb192e/references/pixel-actions.md)
and [`stability.md`](https://github.com/WoYun520/gif-factory/blob/bea2776100b61563f2beca7a805c1b45bebb192e/references/stability.md)
explain why moving silhouettes are unsuitable automatic alignment anchors.
Their broader workflow starts from reviewed character/key-pose references, plans
anticipation → action → recovery, and reviews decoded frames and actual playback.
More frames or higher FPS alone are not a substitute for missing action stages.

This is an independent implementation of that practical alignment rule. Our
`[dx, dy]` pairs are **not** the upstream manifest's scalar x-offset format or sign
convention. We do not copy its alpha threshold, arbitrary fit scale, captions,
provider integration or sample artwork. Its MIT software/documentation notice is
preserved in [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md); character and gallery
art rights are not conveyed by the software license. GIF Cinema retains its own
source-available evaluation license.
