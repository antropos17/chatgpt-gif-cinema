# Acceptance gates

## 1. Story and source coverage

Read the visible action without captions. Confirm setup, cause, result and payoff.
Audit repeated source hashes in `story-report.json`; a duplicated clip is not evidence
of another action. The helper cannot judge story coherence, identity or contact.
`not-generated` rows are targets, never rendered footage. Do not label planned duration
as delivered duration. Titles are counted separately from character animation.

## 2. Character and contact

For each actual take, inspect every decoded frame, contact transitions and full-speed
playback. Use `scripts/review_gif.py extract TAKE.gif NEW_DIRECTORY` for native PNGs,
optional focus crops and a local frame player. See [the exact review workflow](full-frame-review.md).
The generated record remains pending until inspection; `check` refuses incomplete
or changed packs and does not authenticate the reviewer or obtain user approval. Check face/markings/costume, limb count, held props, ground contact, shadows,
occlusion and intended motion. At each join inspect outgoing and incoming frames
side by side: scale, horizon, camera geography, light, gaze and motion direction.
Pay special attention to a retake's entrance **and** exit. Keep reviews separate from
user approval. Pixel scores and decode success are not visual acceptance.

## 3. Motion design and text

Watch each entrance, trigger, hold and exit. Type must be readable at actual display
size, correct in the requested language, within safe margins and free of missing
glyphs. Local title rendering supplies only text and an accent rule. It does not
animate characters or generate layered scenes. Check motion once-through before
choosing to repeat the story. GIF viewers may ignore a play-once flag.

## 4. Technical evidence

The runtime supplies inspection JSON, endpoint PNGs, contact sheet, continuity report,
SRT, manifest and verified MP4. Inspect them, then watch the exact export. Check:

- Full decode, codec/dimensions, actual duration and frame count.
- Source GIF delays versus playback FPS; repeated export frames are expected.
- Source hashes unchanged; no new provider requests in a source-only edit.
- GIF palette, actual frame delays, loop flag, file size and legibility.
- GIF silence; MP4 audio presence only when audio was actually supplied. Do not
  claim you listened to sound if you only measured its stream.
- Resume is zero-call. Old accepted projects are preserved rather than overwritten.

GIF export resamples existing motion and may merge identical drawings. It does not
provide optical flow or new poses. For long stories prefer an MP4 master and smaller
GIF chapters. The story and chapter exporters reject outputs exceeding the reviewer's
512-frame / 64-Mi-pixel / 32-MiB capacity;
reduce width/FPS or split the story, rather than bypassing that safety limit.

## Delivery note

State: actual runtime, dimensions, character drawing cadence, export FPS, audio/loop
status, source versus newly generated versus locally composed work, acceptance status
and known faults. If contacts or identity fail, say which shots need repair. Keep
private references and prompts out of a public bundle unless authorized to share them.
