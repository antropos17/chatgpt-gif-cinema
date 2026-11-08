# Reproducible Russian and Azerbaijani text

This candidate fixes silent missing-glyph boxes without changing the appearance
of existing supported legacy text. It does not promise universal Unicode support.

## Choosing the font

Set `font_id` on a text layer:

```json
{
  "id": "greeting",
  "type": "text",
  "text": "Привет, Əli! Azərbaycan",
  "font_id": "noto-sans-regular-2.004",
  "font_size": 32,
  "fill": "#ffffff"
}
```

Noto Sans Regular 2.004 is bundled as an unmodified 512,672-byte TTF. Its exact
SHA-256 is `89c3c497f618fdaa0b2d1e98fef93582f28c71debd2c4a8cdf41f190ced2909d`.
No system-font lookup, downloads, arbitrary paths or automatic font fallback occur.
The installed wheel contains the TTF, coverage manifests and complete OFL license.
The font is licensed separately from GIF Cinema under SIL OFL 1.1. See
[third-party notices](../THIRD-PARTY-NOTICES.md).

Russian and modern Azerbaijani Latin uppercase/lowercase alphabets, including
Ё/ё and Ə/ə, Ğ/ğ, I/ı, İ/i, Ş/ş, Ç/ç, Ö/ö, Ü/ü, are checked against real cmap
entries and rendered glyph masks. Both alphabets are covered by the pinned font.

Text is normalized to NFC. Common decomposed spellings such as Е + diaeresis,
И + breve, G + breve and I + dot become their precomposed letters. Unsupported
characters are rejected with their Unicode codepoints before raster allocation,
output creation or encoding. Emoji, CJK, format controls, variation selectors and
remaining combining-mark sequences are not supported by this text renderer.
Russian stress marks that remain combining marks after NFC are therefore rejected.
BASIC layout is selected explicitly; no optional Raqm/HarfBuzz engine changes it.

## Existing scenes and save/reopen

Omitting `font_id` preserves `pillow-default`, the known bundled Aileron font from
Pillow. Supported existing ASCII and punctuation keep identical raster pixels in
the tested environment. The legacy font's actual bytes must match its recorded
SHA-256; an unknown Pillow default is rejected instead of being trusted by name.
Unsupported Russian/Azerbaijani legacy text now produces a clear error telling the
author to select Noto. Switching to Noto is explicit because font metrics differ.

Normalized and saved text layers include `font_id` and `font_sha256`. Saved scenes
also contain `text_renderer`: the Pillow version, FreeType version, BASIC layout
and NFC normalization policy. A version mismatch fails with a migration message
rather than silently rerendering. Keep the recorded versions for a normal reopen.
For an intentional environment migration, work on a copy, remove `text_renderer`,
render a new candidate and review it. Do not replace an accepted export implicitly.

Font bytes and version identifiers are necessary reproducibility evidence, not a
promise of identical pixels across every operating system or FreeType build.
The full-frame verifier compares every reopened PNG pixel and still provides the
actual equality test. Old scenes that never recorded a rasterizer environment
cannot retroactively prove their original environment; the current font choice
is retained and a new save records the environment used now.

The scene bundle relies on the corresponding installed package to provide its
pinned font. It does not look for an installed OS font or fetch anything. A missing
font, changed TTF or changed coverage manifest fails closed. The bundled TTF and
its license travel with the wheel, including installation outside this checkout.

## Run the checks

```sh
python -m gif_cinema.layers render examples/layered-unicode.json --out output/unicode-demo
python tools/verify_layered_scene.py output/unicode-demo
python -m unittest discover -s tests -p test_text_fonts.py -v
python -m unittest discover -s tests -v
python -m compileall -q gif_cinema tools tests
python -m pip wheel . --no-build-isolation --no-deps --no-index --wheel-dir output/wheel
```

The optional maintenance audit `python tools/check_font_coverage.py` requires
fontTools to independently compare both manifests against the actual nonzero
cmap glyph IDs. fontTools is not imported or required by runtime rendering.
Runtime uses pinned coverage manifests whose hashes are tied to the pinned font
bytes. A nonempty text bbox or a nonzero width alone is not evidence of glyph
coverage, because the missing-glyph box also has a bbox and width.
