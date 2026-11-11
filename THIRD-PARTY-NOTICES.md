# Third-party font licensing

The unmodified Noto Sans Regular 2.004 font in
`gif_cinema/assets/fonts/NotoSans-Regular.ttf` is licensed under the SIL Open Font
License 1.1, not the GIF Cinema source-available license. Its full license and
copyright notice accompany every package in `gif_cinema/assets/fonts/OFL.txt`.

Copyright 2015 Google LLC. All Rights Reserved.
Font SHA-256: 89c3c497f618fdaa0b2d1e98fef93582f28c71debd2c4a8cdf41f190ced2909d.
The font is copied without subsetting, renaming or other modification from the
preinstalled local Noto font, whose matching copyright file names
https://github.com/googlei18n/noto-fonts as upstream. Its embedded name table
identifies Noto Sans Regular 2.004 and OFL 1.1. Exact local source paths and
checksums are retained in assets/fonts/PROVENANCE.json. An immutable upstream
release or package-manager registration was not independently verified here. It may not
be sold by itself. The OFL permits bundling with software and does not impose its
license on rendered images or documents.

The legacy font remains provided by the user's Pillow installation. No Aileron
font binary is redistributed by this package. Its known embedded bytes are
fingerprinted solely to preserve legacy rendering and reject unknown substitutions.
The generated coverage metadata records Unicode codepoints, not glyph outlines.

## DejaVu Sans in the Blender example

`examples/blender-form-01/assets/DejaVuSans.ttf` is an unmodified DejaVu Sans font copied from the preinstalled DejaVu package. It is licensed under the accompanying Bitstream Vera/DejaVu terms in `examples/blender-form-01/assets/DejaVu-LICENSE.txt`, not the repository evaluation license. Copyright (c) 2003 Bitstream, Inc.; DejaVu changes are in the public domain. The identical font is packed in `examples/blender-form-01/form_01.blend`. Its SHA-256 and source facts are recorded in the example provenance file. No new license is granted to the project by bundling this font.


## GIF Factory workflow influence

The source atlas alignment workflow is independently implemented after reviewing
GIF Factory's `scripts/export_pixel_actions.py`, `references/pixel-actions.md` and
`references/stability.md` at commit
`bea2776100b61563f2beca7a805c1b45bebb192e` (November 11, 2026):
https://github.com/WoYun520/gif-factory/tree/bea2776100b61563f2beca7a805c1b45bebb192e

The adopted ideas are fixed measured column corrections, one common crop/scale,
pixel-preserving sampling and separate technical/visual review. No upstream
exporter code, generated gallery art, character references or fonts are copied
by this feature. The MIT license covers upstream software/documentation, not
third-party character or artwork rights. GIF Cinema's evaluation license remains.
The upstream notice is preserved here for attribution:

MIT License

Copyright (c) 2026 WoYun520

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
