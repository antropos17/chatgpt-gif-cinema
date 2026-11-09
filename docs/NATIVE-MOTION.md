# Native motion GIF presets

The product path is **prompt → native animated GIF → inspection**. No Blender,
video intermediate or animated-still fallback. This module prepares requests and
inspects media; it does not itself generate GIFs or call a paid provider.

## Six distinct directions

- Chrome Trefoil: slender constant-section silver knot, rigid sway up to ±6°, black.
- Copper Folded Ribbon: six satin pleats, small phase-offset hinge wave up to ±4°, warm off-white.
- Pearl Gyroscopic Orbits: three ceramic rings, phase-offset rocking up to ±5°, silver/ivory/lavender on indigo.
- Cobalt Kinetic Bloom: twelve constant-sized tiles, restrained hinge wave up to ±5°, pale blue.
- Amber Liquid Torus: tiny traveling surface bulge up to 2% of tube radius, stable open hole, warm ivory.
- Coral Braided Helices: two fixed-pitch strands swaying together rigidly up to ±4°, dark navy.

All use a locked camera, fixed broad softbox lights, stable center and scale,
constant topology/count, generous framing and no green, characters or text.
Angular bounds are excursions from the resting pose, not full spins. Copper and
cobalt motion is confined to hinges; amber's very small surface motion is intentional.
The other subjects retain rigid geometry. Loops request continuous forward phase
progression, not reverse playback or a duplicated final endpoint.

`motion_intent` records requested family, amplitude, unit and cycle count separately
from API parameters. The amplitude is inserted into the actual prompt. Compilation
rejects angular excursions above 6° and surface excursions above 2% of tube radius
for this restrained preset set, so a full-turn request cannot enter through that
structured setting. Free-form art direction still requires human review.
These are requested model behaviors, **not measured amplitudes or guarantees**.
The inspector does not estimate 3D movement or enforce geometric consistency.

Timing stays **16 drawings × 200 ms = 3.2 seconds, or 5 drawings per second**.
Smaller excursions aim to reduce pose jumps, but do not add temporal detail or make
5 fps inherently smooth. Judge the actual GIF's pacing, silhouette, constant tube
thickness, ring/strand separation and highlight stability at playback speed.
Technical format matching is not aesthetic acceptance.

## Offline preparation

Run in a checkout with Python 3.10+ and Pillow installed:

```bash
python -m gif_cinema motion list
python -m gif_cinema motion compile --out output/motion-plan
# Optional explicit spelling of the same, sole route:
python -m gif_cinema motion compile --route openai-direct-16 --out output/direct-motion-plan
```

`--preset chrome-trefoil` prepares one instead of all six. Output folders must be
new. JSON serialization is deterministic; requests include exact prompts, parameters,
a parameter SHA-256 and route information. The direct route preserves both its
source prompt and the effective render-normalized provider prompt; tests compare
the compiled film script payload with the recorded parameters. The manifest hashes each request's bytes.
No timestamps, credentials or keys are embedded. Preparation makes zero network calls.
Request changes are explicit source edits followed by compilation into a new folder.
Keep the source revision with customized projects; inspection rejects requests that
no longer match this runtime's presets rather than silently misattributing them.

## Direct OpenAI API contract

The sole route, `openai-direct-16`, requests 512×512, maximum quality and
16 × 200 ms (3.2 seconds) through the existing `gpt-image-2.6-flare` direct adapter.
It generates one `.film.json` per preset compatible with the existing render CLI.
The adapter retains its conservative 16-frame ceiling. Actual account/model access
must be checked separately: offline tests do not establish live availability.
The compiler does not add a third-party integration or a paid-execution command.

Requests also contain `artifact_requirements.background: opaque`, a local acceptance
criterion. It is deliberately separate from API `parameters`: no unsupported
background field is sent to the API. The inspector reports a warning if the returned
GIF contains actual transparent pixels. A prompt or local requirement cannot
force a provider to meet it.

Direct execution requires `OPENAI_API_KEY` in the environment and explicit
user authorization with a bounded call budget. Never print or save the key.
Start with one approved pilot, retain the runtime receipt and original GIF, and
resolve pending/unknown outcomes before any retry. No price is baked into this package.
In ChatGPT, use native GIF generation only when the current chat's available tools
actually support it and the user authorizes execution; text instructions do not
establish that capability. This package does not automate the ChatGPT interface.

For a separately authorized direct request, use the runtime's guarded execution:

```bash
python -m gif_cinema render output/direct-motion-plan/chrome-trefoil.film.json --dry-run
python -m gif_cinema render output/direct-motion-plan/chrome-trefoil.film.json --execute --max-api-calls 1 --retries 0 --out output/chrome-direct
```

The latter requires API access and FFmpeg because the existing render route also
assembles an MP4. The source GIF is returned natively by the generation service;
it is not extracted from that movie. Use the accepted shot GIF for native inspection.
The standalone `motion` module does not add a paid-execution command.

## Inspect returned bytes

```bash
python -m gif_cinema motion inspect actual.gif --request output/motion-plan/chrome-trefoil.request.json --out output/chrome-review
```

Creates `inspection.json`, `first.png`, `last.png` and `contact-sheet.png` in a new
folder. The original GIF is untouched. Inspection reuses the runtime's bounded GIF
scanner and full decoder, with encoded byte, frame, per-frame pixel and cumulative
pixel budgets. A still image, invalid/truncated GIF or unsafe input is rejected.

The receipt retains the exact request, its file hash and actual GIF hash. It reports
every composited frame's dimensions, actual transparent-frame indices, frame count,
all delays, duration, loop metadata, exact unique
composited-frame count, adjacent-frame pixel differences and the last-to-first
pixel difference. The contact sheet includes start, quarter, half, three-quarter
and final frames, with exact indices in the receipt. Infinite loop metadata is
`0`; a missing extension or finite repeat count is flagged. Any frame with dimensions
other than 512×512 is flagged, including later canvas expansion. For the local opaque
artifact requirement, actual transparent pixels in composited RGBA frames are flagged;
an unused palette transparency index alone is not a mismatch. Alpha inspection
streams one frame at a time after the shared bounded scanner and decoder accept
the same immutable input bytes.

A technically decodable mismatch produces warnings and `decoded-with-warnings`,
not an invented success. A format match produces `requested-format-matched`.
Both remain `human-review-required`. No seam score threshold asserts quality:
small pixel changes might just be a still, and good motion can have large changes.
The request association is caller supplied, not cryptographic provider provenance.
A matching receipt cannot prove how a GIF was generated; retain the provider job
record. Record visual acceptance separately after real playback and seam review.

## Verification

```bash
python -m unittest discover -s tests -v
python -m compileall -q gif_cinema
```

Motion tests are offline and use synthetic fixtures solely for technical validation.
They do not prove paid generation, premium visual quality, or model availability.
