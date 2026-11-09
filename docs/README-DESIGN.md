# README design and provenance

[Back to GIF Cinema](../README.md)

## Typography and hierarchy

The README uses GitHub's native text styling for headings, prose, links and code.
There is no custom CSS, hidden text or remote-font dependency in the README.
The page opens with one project heading, a concise purpose and useful action links.
Section headings describe the content rather than using decorative numbering.
Historical section anchors remain available for existing links.

The shorter static cover and optional three-shot diagram use **Open Sans Regular
and Semibold**, matching the website's type direction. Lettering is converted to
vector outlines so the cover renders consistently without Arial/Helvetica fallback.
The warm paper, charcoal and brown palette is quieter beside the actual footage.
The former silver-ring artwork and oversized all-caps display have been removed.
The artwork does not depict or demonstrate 3D animation.

- `assets/identity/cover.svg`: 1200 × 354 wide cover.
- `assets/identity/cover-mobile.svg`: 600 × 342 narrow composition, selected by a
  standard HTML `picture` source at viewport widths up to 600 px.
- `assets/identity/story-strip.svg`: 1000 × 210 static three-beat diagram, shown
  inside an optional disclosure after the actual film.

These SVGs contain no scripts, embedded HTML, animation, external images or web fonts.
Each has a descriptive title and description. Essential project information is also
normal README text; the artwork is not required to operate or understand the toolkit.

## Reproduce the artwork

`tools/build_readme_identity.py` contains the layouts and checks the exact hashes of
the original Open Sans 1.10 Regular and Semibold TTFs. It needs optional design tools
Pillow and fonttools; these are not added to the filmmaking runtime requirements.
No font program is bundled. [Font notice](assets/identity/FONT-NOTICE.txt) and
[Apache 2.0 license](assets/identity/FONT-LICENSE.txt) cover the source typography.

```bash
python tools/build_readme_identity.py --font-dir /path/to/open-sans
python tools/build_readme_identity.py --font-dir /path/to/open-sans --check
```

## Actual motion

This typography change adds no generated GIF, video, 3D scene or character action.
Every existing direct GIF, source take, public-toolkit export and finishing study is
preserved byte-for-byte. The cover and diagram are static; they must not be presented
as Blender output, native model animation or proof of a 3D engine.

The direct sample has 9 drawings at 200 ms each, totaling 1.80 seconds. The public
film uses three different reference-conditioned sources, each 16 drawings at 160 ms.
It lasts 7.68 seconds. The title recipe adds 2 seconds of local typography to those
same actions. The long-story example remains an unrendered production plan.

The [identity/media manifest](assets/identity/manifest.json) records exact files,
hashes and source-font identifiers. The [showcase manifest](assets/showcase/asset-manifest.json)
records comparisons. Private finishing limitations stay directly above the visible
previews. GIF embeds and video links are separate to avoid GitHub replacing the
looping previews with full video players.

## Verify

```bash
python -m unittest discover -s tests -p 'test_readme.py' -v
python -m unittest discover -s tests -v
python -m compileall -q gif_cinema
```

The checks validate local links/anchors, original media hashes and timings, static
SVG safety, reviewed sizes, outlined typography and visible gallery placement.
They do not certify aesthetics or continuity. Inspect the live GitHub README,
wide/narrow artwork, actual playback and zero-call render receipts separately.
