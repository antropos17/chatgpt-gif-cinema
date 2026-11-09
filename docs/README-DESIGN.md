# README design and provenance

[Back to GIF Cinema](../README.md)

## Original visual identity

The graphite, cream and orange cover, silver orbital ribbons and three story-beat
symbols are original, hand-authored SVG graphics made for this repository. They are
**static editorial artwork**, not generated GIF samples, video frames or evidence of
a motion engine. No third-party illustration or font file is bundled. Text uses the
viewer's Arial/Helvetica/sans-serif fallback.

- `assets/identity/cover.svg`: wide 1200 × 610 cover.
- `assets/identity/cover-mobile.svg`: narrow 600 × 710 composition, selected by a
  standard HTML `picture` source at viewport widths up to 600 px.
- `assets/identity/story-strip.svg`: static diagram of the bundled film's three beats.

The SVGs contain no script, embedded HTML, animation, external image or remote font
references. Their source is editable in the repository. If a Markdown client ignores
`picture`, the wide image is the fallback. Essential content also appears in normal
README text and alternative text; the artwork is not the only way to read the page.

## What changed in the page

The first screen has a new identity rather than the existing beige cat comparison.
The main sequence is **one direct GIF → one repeatable film → finishing studies → copyable recipes**.
All examples occupy one column. This follow-up keeps the original identity and
recipes, adds watch/make/inspect entry routes, and makes all three existing animated
finishing studies visible before the setup instructions. Their shared private-tool
scope appears above the first preview; individual captions explain the method and
link to full videos and actual frame pairs. There is no side-by-side table that
squeezes characters and labels on a phone. Earlier watch/demo/install anchors are
preserved so existing links keep working.

The earlier redesign remains a separate draft. This follow-up is stacked on that
branch so it can be reviewed without duplicating or merging its work. No website
capability or additional native-generation sample is implied by the README gallery.

## Actual media

No new model-generated GIF, video or character artwork is introduced by this README
revision. The historical direct-GIF sample, its prompt record, the three bundled
source takes, the public-toolkit MP4 and the finishing comparisons remain unchanged.

The direct sample is 9 drawings at 200 ms each, 1.80 seconds total. The film uses
three different reference-conditioned sources, each 16 drawings at 160 ms. It is
7.68 seconds, not a longer version of the first sample. The title recipe adds a
locally rendered 2-second opening; it does not create new character actions.

The [asset manifest](assets/identity/manifest.json) identifies exact files and hashes.
The original [showcase manifest](assets/showcase/asset-manifest.json) records the
finishing comparisons. [Recipes](RECIPES.md) distinguish historical API parameters,
offline reconstruction, model-access limits and technical output from visual quality.

The static identity implies no additional native-generation or smooth-motion
capability. The included long-story plan is still an unrendered plan.

## Recheck the page

```bash
python -m unittest discover -s tests -p 'test_readme.py' -v
python -m unittest discover -s tests -v
python -m compileall -q gif_cinema
```

The README tests validate relative files and section anchors, manifest byte hashes,
actual GIF dimensions/timing, visible gallery placement and SVG safety/sizing. The
three preview GIFs are also checked against their original showcase hashes and
2.24-second timing. They do not certify aesthetic
quality or remote media availability. To verify actual media, run the zero-call
recipes, inspect their receipts, and watch the delivered files. To verify presentation,
inspect GitHub's rendered README and the narrow-screen cover separately.
