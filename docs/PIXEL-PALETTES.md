# Keep GIF colors and pixel geometry exact

Inspect an existing GIF, put every visible color into one fixed global palette,
and optionally enlarge it by an **integer nearest-neighbor** scale. This route
never silently quantizes colors, smooths edges, crops, changes timing or inserts
new drawings. If a single GIF palette cannot represent the source exactly, it
refuses the build rather than claiming a lossless result.

This is post-production for a reviewed source GIF, including anime pixel art.
It is not prompt-to-GIF generation, recoloring, identity repair, a new action, or
an artistic acceptance check. If the source already uses one stable palette,
normalization does not fix a palette defect that was never present. It also does
not remove color flicker that is already drawn into the source frames.

## Inspect, build, verify

Use the current checkout with Python 3.10+ and Pillow 10.1+. This workflow does not
need FFmpeg, an API key, JavaScript, Higgsfield, network access or a new dependency.
It is newer than the separately installed skill's immutable runtime pin.

```sh
python -m gif_cinema pixel inspect accepted.gif
python -m gif_cinema pixel inspect accepted.gif --scale 2
python -m gif_cinema pixel build accepted.gif --scale 2 --out output/pixel-2x --dry-run
python -m gif_cinema pixel build accepted.gif --scale 2 --out output/pixel-2x
python -m gif_cinema pixel verify output/pixel-2x
```

`inspect` returns `can_process_exactly`, native timing and loop metadata, source
local-table count, transparency, and a visible-color count or explicit lower
bound. Color collection stops growing at 257, so larger counts are not reported
as exact. Inspection can succeed while reporting that a single exact palette is
impossible. `build` then fails, including in dry-run mode. Dry-run writes nothing.

`--scale` accepts integer 1–8, subject to pixel budgets. Each source pixel becomes
an exact square of that many identical pixels. There is no downscaling,
fractional scale, rotation, dithering, antialiasing or adaptive crop option.
Existing antialiased or dithered source pixels remain unchanged; this does not
turn unsuitable artwork into clean pixel art.

Always choose a new output directory. Originals are never overwritten. The
bundle contains:

- `source.gif`: the exact original bytes, including original metadata.
- `preview.gif`: the verified global-palette GIF, possibly enlarged.
- `frames/0000.png`, etc.: every source display state at output size, with RGBA.
- `palette.json`: reusable opaque colors in their actual palette index order.
- `requested-palette.json`: an unchanged copy of an explicitly supplied palette,
  when used.
- `palette.png`: color swatches in that order, left to right then top to bottom.
  Dark unused cells in its last row are merely padding, not extra palette entries.
- `loop-seam.png`: last displayed frame on the left, first on the right, with
  transparency retained. This is a review aid, not an automatic seam approval.
- `receipt.json`: source identity, timing, palette, PNG and full-GIF evidence,
  complete file inventory and an explicitly unestablished visual-acceptance status.

Move the whole bundle and verify again. Do not deliver only its receipt as proof.

## Reuse one authored palette

The automatic palette is the exact sorted union of visible RGB colors across all
frames, not a palette learned from a small sample or only the first frame. To
keep consistent color indices across several clips, reuse a previously exported
palette or provide a small JSON file:

```json
{
  "format": "gif-cinema-palette",
  "schema_version": 1,
  "colors": ["#121326", "#303958", "#d9857d", "#ffe0b5"]
}
```

The colors above only illustrate the format. An actual palette must contain
**every visible source color**. This is not a nearest-color remapping request.
Removing a source color or replacing it with another shade makes the build fail.
Unused authored colors are allowed and retain their index order.

```sh
python -m gif_cinema pixel build next-accepted.gif --palette output/pixel-2x/palette.json --out output/next-fixed
```

There are at most 256 opaque entries. If any pixel is transparent, one separate
index is reserved after the opaque entries, leaving at most 255. Opaque black
and transparent black are kept separate. Repeated colors and malformed schemas
are rejected. An empty color list is useful only for fully transparent artwork.
The encoded global table has 256 padded slots; these are not 256 used colors.
No frame-local color tables are written.

GIFs with different local palettes can contain more than 256 visible colors over
time. Such an input may be valid GIF, but cannot be converted to this single-table
contract without changing colors. The tool leaves it intact and reports the
limit. Any future intentional color reduction must be a separately described,
reviewed operation; it is not hidden inside this command.

## What “exact” proves

The decoder resolves original local tables and disposal modes into full visible
RGBA frames. Fully transparent RGB is normalized to zero for comparison. It does
not threshold partial alpha; helper inputs with partial alpha are rejected.
The original GIF bytes remain available even though hidden RGB is not a visible
color guarantee.

Verification independently reopens the retained source and output, recompiles the
palette and scale, and checks:

- every source-derived PNG pixel at the specified nearest-neighbor scale;
- the complete decoded GIF display timeline, merging adjacent identical states
  for comparison, including every native delay and loop count;
- the exact global color table and absence of local tables;
- swatches, seam image, source identities, strict receipt metadata and file hashes.

Source and output encoded frame counts are reported separately. Equal drawings
may be represented as longer holds without creating new motion; matching a frame
count alone is not the verification contract. Missing loop metadata, infinite
loop (`0`) and finite repeat counts remain distinct.

Exactness means decoded visible RGBA values and timing, not byte-identical GIF
encoding, anatomical quality or universal appearance in every player. The viewing
copy need not preserve comments, application extensions or original disposal/block
layout. Players can clamp delays, override looping or apply different color
management. Receipt consistency is not authentication of an intentionally rewritten
source and receipt. Automatic visual acceptance is never claimed.

## Failure safety and bounds

Inputs and palette files must be local regular files with no symlinks or URL
schemes. Scale, dimensions and aggregate pixel counts are checked before decoding
or allocating enlarged frames. Sources are limited to 128 MiB, 1–256 encoded
frames, 4,000,000 pixels per source/output frame, 16,000,000 aggregate source/output
pixel-samples, 8,192 pixels per side and 120 seconds total. Delays must be multiples
of 10 ms between 20 and 120,000 ms; invalid timing is not silently rounded. Plain-text GIF graphics, user-input
graphic controls, reserved disposal modes and nonzero pixel-aspect metadata are
rejected before decoding because this route cannot preserve those semantics.
Palette JSON is limited to 16 KiB, receipts to 1 MiB and the complete output to
256 MiB. The first applicable bound wins.

A build stages and verifies its files, then rechecks the original GIF and authored
palette immediately before publication. An edited original prevents publication
under its old identity. Pre-publication failure leaves no output directory.
Publication uses no-clobber file links and puts the receipt last. If publication
itself fails, any partial output is deliberately retained: deleting those public
paths could erase another writer's replacement or edits. Treat the failure as
incomplete, inspect it, and use a new destination for a retry. The tool never
blindly overwrites or deletes those files to “clean up.”

The test suite exercises local palettes, one-pixel accents, adjacent RGB values,
opaque black beside transparency, disappearance/disposal, finite and absent loop
metadata, differing delays, exact palette limits, modified receipts and interrupted
publication. Real 16-frame, 320 × 320 anime artwork was additionally checked at
1× and 2× on both Pillow 10.1 and the development version: 124 opaque colors plus
transparency, 1,920 ms and all decoded states were preserved. Its source already
had one global palette, so that check proves preservation and scaling, not an
artistic improvement or removal of existing palette flicker.

Continue with [authored atlas poses](AUTHORED-POSES.md) or [source-only scene
sequences](SCENE-SEQUENCES.md) only after reviewing the source and actual exports.
