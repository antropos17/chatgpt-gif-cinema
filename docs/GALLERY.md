# Visual catalog: methods, sources and recipes

[Browse the moving homepage](../README.md) · [Install the skill](../README.md#install-the-skill)

Original API footage, local compositions, reusable source drawings, private finishing and archived Blender artwork use different methods. The homepage labels those routes and links their actual sources. This is a smaller independent collection, not a claim of GIF Factory's style or example count.

## Character stories

- [Original direct GIF](RECIPES.md#one-prompt-one-gif): historical paper-cut astronaut result, 9 drawings at 200 ms, 1.80 seconds. A new request needs supported access, billing and an authorized budget.
- [Three bundled actions](EXAMPLES.md#the-actual-three-shot-story): 16 drawings at 160 ms each, 2.56 seconds per take. Wide → close → wide framing and details still differ. These are not three separate art styles.
- [Titled story](EXAMPLES.md#2-titled-story-a-small-gif-to-share): the same actions plus a 2-second local title. MP4 is 9.68 seconds; the committed play-once GIF is 9.70 seconds at 320 px and 10 fps. Titles do not create new poses.

```bash
python -m gif_cinema render examples/film.json --dry-run --max-api-calls 0
python -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/my-film
```

[Editable storyboard](../.agents/skills/gif-cinema/assets/example/storyboard.json) · [Exact title/GIF recipe](EXAMPLES.md#2-titled-story-a-small-gif-to-share) · [Story pages](STORYTELLING-SKILL.md).

## Local motion

The two new GIFs were actually rendered with the public local layered-scene CLI from unchanged scene JSON in this repository. No model, API, downloaded artwork or Blender render was used.

| Example | Actual GIF | Source and method |
| --- | --- | --- |
| Independent layers | 320 × 180, 25 rendered samples → 24 encoded drawings, 1.00-second loop | [Scene](../examples/layered-shapes.json), [experimental layer format](MULTILAYER-POC.md) |
| Vertical motion | 540 × 960, 160 drawings at 20 ms, 3.20-second loop | [Scene](../examples/vertical-motion.json), [composition and margins](VERTICAL-MOTION-EXAMPLE.md) |

```bash
python -m gif_cinema.layers render examples/layered-shapes.json --out output/my-layers --dry-run
python -m gif_cinema.layers render examples/layered-shapes.json --out output/my-layers
python -m gif_cinema.layers render examples/vertical-motion.json --out output/my-vertical
```

The small shape GIF combines one equal pair into a longer hold; its total timing stays 1.00 second. Use new output directories. These are composition studies, not a general rigging engine. Static text stays editable in the source, and glyph/font limits apply. Exported final frames precede the conceptual endpoint; inspect actual playback. [Whole-image motion](STANDALONE-MOTION.md) transforms a complete existing image rather than articulating its subjects.

## Sprites and review

The [source examples](EXAMPLES.md#the-actual-three-shot-story) show the original takes and an existing first/middle/last storyboard sheet. They are real footage and samples, not newly generated sprite artwork or a complete all-frame review. Run the actual tools for the complete output pack:

```bash
python -m gif_cinema sprites pack .agents/skills/gif-cinema/assets/example/shot-01.gif --columns 4 --out output/my-sprites --dry-run
python -m gif_cinema sprites pack .agents/skills/gif-cinema/assets/example/shot-01.gif --columns 4 --out output/my-sprites
python .agents/skills/gif-cinema/scripts/review_gif.py extract .agents/skills/gif-cinema/assets/example/shot-01.gif output/my-review --focus 80 60 370 330
```

The sprite example uses all 16 existing drawings and produces a shared-coordinate atlas, individual RGBA frames, a palette-limited preview and timing manifest. This opaque source remains opaque; no background removal or pose generation is claimed.

Open the review pack's local index.html. Step through every native frame and the seam, then record what you actually inspected. Its review record starts pending; neither frame counts nor a contact sheet manufacture approval. [Sprite contract](SPRITES.md) · [Review workflow](GIF-REVIEW.md).

GIF previews have palette/binary-alpha limits. Shared trimming preserves source alignment; it cannot repair inconsistent source drawings. Runtime coordinates are explicit, not an engine-compatibility claim. The current source skill includes helper/guidance for these workflows; install its pinned runtime separately.

## Finishing studies

[Cat, dog and astronaut comparisons](SHOWCASE.md) retain their original public media. Each small GIF is a 2.24-second excerpt; the linked comparison covers the full selected sequence. Its thumbnail reset is not a cut in the complete film.

Right-hand panels use private finishing tools outside the public CLI. Cat changes include compositing and framing cleanup as well as selective interpolation. More playback frames cannot repair missing props, bad contact or anatomy. The [57.2-second cat film](assets/showcase/cat-film.mp4) is assembled from short takes and locally finished, not one long model request.

## Archived 3D study

[Chrome Trefoil](MOTION-DESIGN.md) is one original Blender EEVEE study: 512 × 512, 80 unique frames at 40 ms, 3.20 seconds, silent and repeating. Original GIF/MP4 bytes remain unchanged. It is not native API output, a core generator feature or evidence of six completed variations. The public API workflow does not require Blender.

## Asset facts and rights

[New local GIF facts](assets/catalog/manifest.json) pin the exact Git blobs and source recipes, dimensions, frame counts and total timing. Earlier [media hashes](assets/identity/manifest.json), [finishing facts](assets/showcase/asset-manifest.json) and [3D receipt](assets/motion-elements/manifest.json) preserve their provenance.

No upstream artwork, characters, fonts or exporter code is copied. GIF Factory's gallery-first organization and linked methods informed the presentation. The [source-available evaluation license](../LICENSE) is unchanged. New provider generation and sharing private inputs still need appropriate authorization.
