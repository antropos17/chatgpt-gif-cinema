# Animated story pages

Use `scripts/story_pages.py` to put an existing GIF action beside readable text in
landscape, or above it in portrait. This is an offline page-layout compositor,
not a new character generator. No Blender, browser, external service or API key is
needed. The supplied three-page recipe reuses the original astronaut takes.

## Make the example

Run these from the repository root with GIF Cinema installed:

```bash
python .agents/skills/gif-cinema/scripts/story_pages.py .agents/skills/gif-cinema/assets/example/storybook.json --out output/story-pages --dry-run
python .agents/skills/gif-cinema/scripts/story_pages.py .agents/skills/gif-cinema/assets/example/storybook.json --out output/story-pages
python -m gif_cinema render output/story-pages/film.json --execute --max-api-calls 0 --out output/story-pages-film
```

The first two commands need Python and Pillow, but no FFmpeg. The final MP4 command
needs FFmpeg and ffprobe. In an installed skill, use that skill's `scripts` and
`assets/example` paths instead of the repository paths.

You get three actual **960 × 640, 2.56-second GIFs**, each with the original 16 drawings
at 160 ms per drawing. Each page is silent and plays once. The optional film joins
them with hard cuts into a **7.68-second MP4 at 50 fps**, with unchanged action
cadence. There are no extra poses, reading pauses, music or page-turn transitions.
Some viewers override GIF playback/loop metadata. Watch the actual files before
accepting the result; decoding and hashes do not establish artistic quality.

## Author a page project

```json
{
  "schema_version": 1,
  "title": "A small story",
  "layout": "portrait",
  "pages": [
    {
      "id": "first-wave",
      "source": "existing-wave.gif",
      "heading": "Hello, out there.",
      "text": "One small wave into the dark."
    }
  ]
}
```

Only existing animated GIF sources are accepted. Paths are local, relative to the
input JSON, or absolute; URLs are rejected. All input files must be regular files.
No still image is mislabeled as a generated GIF and nothing is sent to a provider.
Source footage is fitted inside the image panel without cropping or stretching.
Transparent source pixels are composited onto an opaque matte. Pages are **not
transparent stickers**. Character consistency and correct action must be reviewed.

- `schema_version`: integer 1. Unknown fields are rejected.
- `title`: 1–200 characters.
- `layout`: `landscape` (default 960 × 640) or `portrait` (default 640 × 960).
- `width`, `height`: optional even integers 256–1280; dimensions must match the
  selected orientation and reduce to a ratio with terms at most 99.
- `background`, `foreground`, `accent`, `image_background`: optional opaque
  `#RRGGBB` colors. Defaults are warm paper, dark green, burnt orange and white.
- `font`: optional local TrueType/OpenType file. `--font` selects a font for a new
  project. Without either, the helper looks for installed DejaVu Sans or Arial on
  Linux, Windows or macOS and gives a clear error if unavailable. No font is
  downloaded or bundled. Different installed fonts can change wrapping; use an
  explicit licensed font for a matching layout on another system.
- `pages`: 1–24 ordered pages. IDs are case-insensitively unique, safe ASCII names
  of up to 40 characters. Each needs `source`, `heading` (up to 100 characters) and
  `text` (up to 800 characters). Text must fit at a readable fixed size; long words
  wrap and explicit newlines are retained. Overflow fails instead of clipping.
- `source_sha256` per page and `font_sha256` at the top level: optional exact
  lowercase SHA-256 pins, automatically added to the portable output project.

A supplied font must cover the requested language. The helper measures text, but
**does not certify glyph coverage, complex-script shaping or accessibility**.
Inspect first/last PNGs, the actual GIF lettering and contrast. Use a font licensed
for your intended use; the helper copies it into the project. Review font rights
and private source/text content before sharing that project. Installed system-font
licenses may restrict redistribution even though the helper can use them locally.

## Preserve, continue and inspect

Every output directory must be new. Input sources are never modified. Encoding
runs in a staging directory; failed exports publish no partial project and cannot
replace an accepted output. The result contains:

- `pages/ID.gif`: opaque, silent, play-once composed pages.
- `review/ID-first.png`, `review/ID-last.png`: actual decoded export endpoints.
- `sources/ID.gif`: byte-for-byte originals, including their original loop flags.
- `font.ttf`: the exact selected font bytes, including when the source is OpenType.
- `storybook.json`: editable portable recipe with relative paths and input hashes.
- `film.json`: zero-call hard-cut assembly input.
- `pages.json`: actual source/encoded frame counts, delays, hashes and limits.

To revise the text or orientation, copy/edit the output `storybook.json` and run the
helper with a **new** output directory. Keep its source/font paths valid relative
to that copy. To deliberately replace footage or a font, update the corresponding
hash in your edited copy after reviewing the change. A pinned font cannot be
silently overridden using `--font`.

Page timing preserves the exact GIF delays and adds no holds. Identical encoded
frames may coalesce without changing total playback duration; the report states
both source and actual encoded counts. If resizing/palette conversion removes all
visible animation, export fails rather than delivering a still as an animation.
`--dry-run` decodes inputs and checks text layout without writing or encoding, so
it cannot prove motion or colors will survive GIF conversion.

The optional film uses 50 fps. Delays divisible by 20 ms are preserved; other GIF
centisecond delays can shift within that 20 ms movie grid, with total page duration
rounded to the nearest frame (ties to even). The GIFs themselves keep their timing.
Per-frame GIF palettes can change color/flicker and reduce gradients. MP4 conversion
is lossy too. No automatic aesthetic approval is implied.

## Bounds

The JSON is limited to 1 MiB, the font to 10 MiB, and combined encoded source files
to 128 MiB. Shared runtime GIF safety checks apply before decoding. Composed pages
are limited to 32 megapixels across all their source drawings, and the whole book
to 128 megapixels. Sources, font, output GIFs and endpoint PNGs together must fit
256 MiB. A new project is refused if it exceeds a bound; no source is silently
trimmed to make it fit. Long books can be built as several separately reviewed
projects. This does not enable automatic paid batches.
