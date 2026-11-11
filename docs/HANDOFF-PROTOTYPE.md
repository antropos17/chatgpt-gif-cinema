# One Small Light: an offline continuity prototype

An original eight-second cutout study: a courier offers a lantern, a keeper takes
its handle, and the keeper hangs it in the garden. Three real state changes, one
prop, a fixed camera, and no generation calls or JavaScript animation.

[View the actual GIF and preserved sources](../examples/handoff/README.md).
The checked-in source bundle includes all 80 PNG ticks, working layers, scene GIFs,
anchor ledger and byte-hash verification. It is separate from skill package 0.4.0.

This is a **fixed, authored procedural animation example**, not a Blender scene or a general rigging
editor, an AI-generated cartoon, or a new capability of the core renderer. Its
flat robot artwork is drawn locally with Pillow. Arms follow authored curves;
heads, bodies and facial expressions stay fixed. It tests a practical continuity
method without claiming to reproduce the illustrative quality of the reference.

## Rebuild

From a checkout, with Python 3.10+, Pillow 10.1+, FFmpeg and ffprobe:

```sh
python tools/build_handoff_prototype.py --out output/one-small-light
python -m unittest discover -s tests -p test_handoff_prototype.py -v
```

The output must be a new path and cannot contain symlink ancestors. The script
never overwrites an earlier accepted render. It uses the existing public GIF
validator and invokes the existing renderer with `--execute --max-api-calls 0`.
It repeats that render once to verify reuse of all three imported source GIFs.
No API key, external artwork, browser animation, Higgsfield, music or paid API is
used. The helper requires Pillow 10.1 for scalable default lettering; that does not
change the core package's Pillow requirement. Pixel/byte reproducibility depends
on the recorded Pillow and media-tool versions.

Open `one-small-light.mp4` or `one-small-light.gif` in the output folder. Both are
**960 × 540, 8.00 seconds, silent, 10 fps**. The GIF omits a loop extension, meaning
play-once in conforming viewers; some viewers override that behavior.

To reassemble the preserved sources in a new render folder:

```sh
python -m gif_cinema render output/one-small-light/film.json --execute --max-api-calls 0 --out output/another-assembly
```

## What the prototype actually proves

- The same original character cutouts, fixed background and lantern drawing are
  used throughout. Nothing is independently regenerated between scenes.
- Lantern ownership is explicit: courier → shared grip → keeper → hook.
- Five 100 ms ticks show shared grip before the courier releases. At the ownership
  change both hands still touch their corresponding handle anchors.
- During lifting, the keeper's palm is attached to the handle. The lantern reaches
  the fixed hook before release. The keeper moves outward, then down, so the palm
  does not pass through the lantern's glass.
- Scene 1's last frame and scene 2's first frame are pixel-identical, as are the
  second and third scene endpoints, in both original PNGs and decoded scene GIFs.
- Every authored 100 ms frame is kept as a PNG with a hash and a corresponding
  anchor-ledger record. Decoded GIF playback is compared with the quantized
  originals at every tick, proving frame order and time were preserved.
- The MP4 is assembled from those scene GIFs by GIF Cinema, verified as H.264 with
  80 decoded frames and an 8-second duration, then fully decoded again for review.
- No reverse, replay or scene repetition pads the story. Short anticipation,
  shared-contact, endpoint and result holds are part of its authored timing.

There are 80 authoring ticks, not necessarily 80 separate encoded GIF drawings.
A GIF encoder combines identical adjacent drawings into a longer frame delay.
The validator expands those delays for comparison. This preserves timing and does
not claim new character motion during a hold. The source PNGs retain all 80 ticks.
H.264 is lossy; the MP4 is not claimed to be pixel-identical to those PNGs.

## Preserved deliverables

- `one-small-light.mp4`, `one-small-light.gif`: actual final media.
- `film.json`: normal, editable v1 GIF Cinema script with three local sources.
- `media/`: the three scene GIFs, never replaced during assembly.
- `frames/`: all 80 original full-resolution PNG authoring frames.
- `layers/`: transparent courier and keeper body cutouts plus fixed background,
  at the 2× working resolution. Arm/prop geometry remains editable in the builder.
- `anchor-ledger.json`: prop position, both palms, both grasp anchors, hook anchor,
  ownership, phase, tick, original frame filename and hash.
- `receipt.json`: source hashes, output hashes, GIF timing preservation, join
  equality, zero-call result and actual ffprobe output.
- `contact-sheet.png`, `gif-contact-sheet.png`, `join-sheet.png`,
  `all-exported-frames.png`: review images decoded from actual delivered media.
- `decoded-mp4/`: all 80 decoded movie frames for full inspection.
- `render/` and render logs: existing GIF Cinema inspection/continuity reports and
  the two zero-call render runs. Historical logs retain temporary build paths;
  use the relative paths in `film.json` to reassemble the portable sources.

Fresh rebuilds stay under ignored `output/`. A reviewed source/export snapshot is
committed under `examples/handoff/` and `docs/assets/handoff/`. This is a checkout-only example,
not a wheel-packaged asset set. No new repository-wide API or schema is added.

## Visual review and limits

Technical equality is a guardrail, not visual acceptance. Inspect the full movie,
then the first/middle/last frames and both contact events. Check handle contact,
prop count, release clearance, layering, character silhouette and cause/effect.
The builder keeps its automated visual status as `human-review-required`.

The movement is deliberately simple: flexible cutout arms, static faces and a
locked camera. It demonstrates an inspectable handoff, not anatomical realism or
a complete narrative-animation engine. It does not prove generated footage can
meet the same constraints. To use generated cutouts later, inspect and approve the
actual assets and keep their source drawings; don't infer continuity from prompts.

## Reference and attribution

The [GIF Factory Tea Party README](https://github.com/WoYun520/gif-factory/blob/main/examples/storybooks/tea-party/README.md)
was read at content blob `fca1dfd9d9bf4998d3114794c86f81302bde02a4`. Its method
separates fixed backgrounds, transparent character poses, object trajectories and
palm anchors, with explicit endpoint/contact inspection. Those production ideas
informed this study. No reference artwork, music, code, private input or animation
was copied. The new source remains under this repository's existing evaluation
license.
