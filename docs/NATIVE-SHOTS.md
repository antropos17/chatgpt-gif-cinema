# Native camera, performance and light projects

`python -m gif_cinema sequence build PROJECT --out NEW` accepts
`format: "gif-cinema-shot-project"`, `schema_version: 1`. The local engine reads
authored data and invokes no provider, code plugin or example Python compositor.
Start with the [complete project](../examples/native-shots/project.json) and
[build/recovery instructions](../examples/native-shots/README.md).

## Clock and artwork

`width`, `height`, `fps` define stage/output. `scenes` partition a contiguous
integer `start_frame` / `end_frame` interval. A project may start after frame zero:
actor phases, effects and sound retain source time, while output timestamps start
at zero. Each scene has a unique portable `id`, four-coordinate `camera` crop and
`effects.gain` (0–2) for rear lighting. `camera_push` sets amplitude and speed.

`files` maps stable IDs to relative local paths, SHA256 and byte sizes. `background`
names an ID. Each `clips` entry defines source ID, frames, columns, integer tile
size, stage position, mask (`alpha` or `background-difference`), threshold and blur.

Each actor has ordered nonoverlapping `tracks`: clip, active start/end seconds,
phase origin, duration, boolean loop, first/last atlas indices. A nonlooping track
clamps at its end pose; gaps draw no actor. Cuts do not restart performance clocks.

## Lighting and sound

Effects have a `type`, a `plane` (`front` / `behind`) and explicit parameters:

| Type | Behavior |
| --- | --- |
| `ambient` | Fixed particles with drift and flicker |
| `path-light` | Linear/quadratic/orbit paths, fades, trails and satellites |
| `burst` | Expanding ring and radial particles |
| `ribbons` | Sine ribbons spreading from an origin |
| `swarm` | Particle arcs to explicit targets, wobble and stars |
| `arrival` | Quadratic descent, persistent light and impact ring |

Path segments may carry explicit `duration` matching end minus start. This
preserves authored floating-point calculations where raster rounding matters.
Rear lights use character/background occlusion. Front lights remain above actors.
The project controls glow/occlusion blur, threshold, ellipse shadows and `petals`
overlays. Coordinates are authored; no hand tracking or physics is inferred.

Audio contains source-clock duration/rate, fades, tone tuples
`[start, duration, frequency, gain, pan]`, and noise tuples
`[start, end, seed, gain]`. The engine crops the project interval into little-endian
stereo PCM, then encodes AAC for viewing.

## Reuse and verification

Scene keys include relevant clip bytes/schedules, camera, local effects, shared
visual parameters and engine/encoder versions. A clip edit invalidates its users;
shared visual changes conservatively invalidate all shots. Audio-only edits reuse
visual scene exports and rebuild sound/assembly. Changed inputs during a build
prevent publication under the old identity.

Every FFV1 scene is decoded and checked against each RGB hash and timestamp before
its durable checkpoint is committed. `sequence verify` checks portable project
identities, scene hashes, PCM hash and complete final video/audio decoding. These
checks do not establish natural acting or artistic acceptance.

`--reuse-from` verifies an earlier completed build. `--resume` requires unchanged
inputs, engine and reuse receipt. OS advisory locking releases after process death;
ready final media have a separate publication checkpoint. Modified or unrecorded
media are preserved and cause an error. See the example for hard-kill qualification.

JSON is bounded to 1 MiB, 1–32 scenes/assets, 96 MiB combined asset bytes, 7,500
frames and a 320 Mi-pixel output budget. Unknown contract fields, nonfinite values,
out-of-range indices, gaps, invalid cameras and changed artwork fail preflight.
Sources/outputs do not use symbolic links. Builds write new destinations.
Source-clock audio synthesis is limited to 2 Mi samples per channel.
