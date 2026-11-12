# Two generated-pose previews

[Back to the moving catalog](../../../README.md#anime-pixel-art)

| Character | Action | GIF | Actual frames | Timing |
| --- | --- | --- | --- | --- |
| Fox knight | Raise shield and sway tail | [Open](fox-knight.gif) | 16 distinct decoded frames | 120 ms each; 1.92 s loop |
| Dragon chef | Offer basket and return | [Open](dragon-chef.gif) | 16 distinct decoded frames | 120 ms each; 1.92 s loop |

These are **new generated drawings**, not a camera bounce on a static concept.
Both canvases are 320 × 344 with an opaque ivory background. Residual face,
outline and background texture changes remain, including at the loop join.
They are previews, not seamless finished performances, 15-second narratives,
or a completed 100-character animation collection. The separate concept collection
must not be counted as animated GIFs.

## Sources and reproduction

Built-in image generation produced the two 4 × 4 source sheets in `sources/`.
`frames/` contains every extracted full-color PNG. `build.py` slices fixed
per-column coordinates, pads to one common canvas, computes one shared 256-color
palette per character, and encodes the frames in original order. It does not
interpolate, reverse, crossfade, recenter each pose or stretch the duration.
GIF palette reduction is lossy; original PNG sources remain available.

```bash
python examples/anime-pixel/character-previews/build.py
```

The script writes GIFs, frame PNGs, decoded contact sheets and `manifest.json`
inside this example directory. Pillow is required. `verification.json` records
hashes, dimensions, measured timing and unique decoded frames for the committed GIFs.
Technical checks and contact-sheet inspection are not a claim of ideal motion.

Original project artwork. No GIF Factory assets are included. Repository license applies.
