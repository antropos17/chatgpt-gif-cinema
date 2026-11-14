# Catch, release, illuminate — native engine migration

The 5.60–17.20 second interval of the accepted Lantern Echo film: 290 frames,
11.60 seconds, 960 × 540 at 25 fps, with stereo sound. The catch, release,
greeting, bow and lantern shots retain their original coverage and order.
The full accepted film and original example compositor remain unchanged.

The runtime imports no example Python files. Camera crops, actor performances,
light trajectories, effect parameters and sound events live in [project.json](project.json).
Prepared artwork is referenced from the [existing sources](../lantern-echo/README.md);
it is neither duplicated nor regenerated.

## Build and verify

From the repository root, with Python 3.10+ and FFmpeg:

Use this checkout; earlier installed skill/runtime pins may predate this format.

```sh
python -m pip install ".[lossless]"
python -m gif_cinema sequence build examples/native-shots/project.json --out output/native-shots --dry-run
python -m gif_cinema sequence build examples/native-shots/project.json --out output/native-shots
python -m gif_cinema sequence verify output/native-shots
```

Open `output/native-shots/film.mp4`. Use `--ffmpeg /path/to/ffmpeg` on the build
command to select an existing encoder. Planning without reuse needs no encoder
or PyAV and writes nothing. Reuse planning verifies the earlier result and needs
PyAV plus the encoder version.

Outputs include a portable `project.json`, copied hashed artwork, verified FFV1
scenes, PCM audio, durable checkpoints and `build-receipt.json`. Copy the entire
directory to retain independent verification without the source checkout.

## Revise and recover

Copy `project.json` alongside the original so relative asset paths remain valid.
Change only `05-release.effects.gain` from `1.0` to `0.6`:

```sh
python -m gif_cinema sequence build examples/native-shots/revised.json --out output/native-shots-v2 --reuse-from output/native-shots
```

Only `05-release` is rendered; four scene exports are reused with identical bytes.
The review plan names `04-catch`, `06-greeting`, and the cuts at 1.92 and 4.80
seconds in this fragment (7.52 and 10.40 in the full film). Neighboring shots
require playback review, not automatic re-encoding.

After interruption repeat the same command with `--resume`. Completed scene
files retain their bytes and modification times. The OS releases the lock after
a killed process. Incomplete attempts remain as diagnostic evidence and are never
selected as completed scenes. Changed inputs/engine, corrupt checkpoints or changed
earlier results fail instead of being overwritten. Completed resume verifies the
result without rewriting result files.

## Native format

The reusable engine supports scheduled atlas performances, camera crops,
point/curve/orbit lights, trails, impact rings, spreading ribbons, particle swarms,
timed light arrivals, character occlusion, shadows, foreground petals and stereo
tone/noise events. These are explicit authored data, not generated acting or hand
tracking. Prepared RGB atlases use reviewed background-difference masks; other
artwork can use alpha. The original interpolation softness remains.

The new `gif-cinema-shot-project` schema is separate from existing
`gif-cinema-layer-sequence` projects. Both use `sequence build` / `sequence verify`;
existing layer semantics remain unchanged. `sequence master` still accepts layer
sequences only; native shot projects retain verified FFV1 scenes.

## Repeat qualification

```sh
python tools/verify_native_shots.py --out output/native-fragment-proof
```

The optional slow check compares all source RGB frames and the exact PCM interval
with the independent original compositor, measures decoded MP4 differences,
creates side-by-side playback and four slow cut clips, then tests one-scene reuse,
an owned native CLI hard kill, recovery, preserved files/mtimes and equality with an
uninterrupted revision. Playback review is recorded separately from these checks.
No provider or interpolation inference runs. Python socket connections are blocked
in children; this is not OS network isolation. Fast CI tests use independent
miniature artwork and exercise actual encode/reuse/resume when FFmpeg/PyAV exist.

`--baseline EXISTING_BUILD` reuses a fully verified baseline from the same project
and current engine. [Recorded qualification](verification.json) includes the exact
native result, playback scope and preserved failed attempts.

Each build is bounded to 512 MiB / 256 files; qualification stops starting new
batches after 1 GiB. Retention is manual: inspect closed diagnostic attempts after
seven days, retaining source art, accepted media and receipts. Never remove another
process's active files.

[Original film](../../docs/LANTERN-ECHO.md) · [Native contract](../../docs/NATIVE-SHOTS.md)
