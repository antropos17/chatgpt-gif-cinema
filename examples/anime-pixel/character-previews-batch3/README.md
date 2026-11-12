# Violinist and blacksmith previews

[Moving catalog](../../../README.md#anime-pixel-art)

- [Violinist](violinist.gif): stylized bow gesture, not mechanically accurate playing; instrument drift remains.
- [Blacksmith](blacksmith.gif): raising and inspecting a hammer; ponytail movement.

Each is 320 × 344, 16 different decoded drawings, 120 ms per frame, 1.92 seconds,
looping. These are new generated-pose previews, with residual face, outline and
background texture drift. They are not seamless finished performances or 15-second narratives.
The ivory background is opaque. Source images are original project artwork, not GIF Factory assets.

` sources/ ` contains generated 4 × 4 sheets; `frames/` contains 32 extracted PNGs.
Run `python examples/anime-pixel/character-previews-batch3/build.py` to reproduce
fixed-cell extraction and shared-palette encoding, requiring Pillow. The script
writes frames, GIFs, decoded contact sheets and manifest locally. No interpolation,
reverse playback, per-pose recentering or duration padding is used. GIF quantization
can reduce colors; original PNGs remain available. See [measured facts](../character-previews/verification.json).

Repository license applies. Contact-sheet inspection and technical checks do not certify ideal motion.
