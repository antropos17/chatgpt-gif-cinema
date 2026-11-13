# Rebuild Lantern Echo offline

This is the editable source of the 20.8-second README film. The original published
MP4 remains in `docs/assets/lantern-echo`; builds always write to a separate output.
No API key, generation request, model download, GPU or RIFE installation is needed.

Install Python 3.10+, FFmpeg on PATH, and the project's lossless dependencies:

```sh
python -m pip install ".[lossless]"
```

Then, from the repository root, **build with one command**:

```sh
python examples/lantern-echo/build.py --out output/lantern-echo
```

Open `output/lantern-echo/Lantern-Echo.mp4`. `--ffmpeg /path/to/ffmpeg` can select an
existing executable without changing global settings. The build checks every
lossless scene frame and the final movie's video geometry, timing and stereo
presence; it does not grant artistic acceptance.

## What is editable

- `assets/drawings/`: all six original generated drawing sheets, including the
  bow. These are preserved source artwork, not generation requests.
- `assets/motion/`: seven lossless RGB atlases of the already reviewed 4× RIFE
  samples. They preserve all 576 prepared samples, including original keys.
  Using them avoids rerunning inference or trying to reproduce generated art.
- `assets/garden.png`: the original illustrated garden.
- `assets/manifest.json`: file hashes, atlas layout, source-cell counts and
  interpolation provenance. Update the manifest deliberately when changing art;
  an unexpected source-byte change fails preflight.
- `timeline.json`: ten scenes, their camera crops and per-scene canopy intensity.
- `compositor.py`: character timing, hand anchors, deterministic VFX, petals and
  original synthesized stereo audio.
- `build.py`: scene encoding, verified reuse, checkpoints and final assembly.

The compositor consumes the prepared motion atlases. Editing an original drawing
sheet alone does not magically regenerate its inbetweens: replace/review the
corresponding prepared samples explicitly if changing character acting. This
example intentionally contains no generator or interpolation-inference launcher.

Version 1 retains the original 520-frame source clock at 25 fps. Scene intervals
must partition that clock without gaps. Camera crops and `effects.canopy_gain`
(0–2) are editable independently per scene. Changing the story duration or acting
requires authoring the compositor/source clock as well; a longer hold is not a
new action.

## Revise one scene while preserving the previous result

Copy `timeline.json`, change the canopy intensity of `05-release` to `0.6`, and
build into a **new** directory:

```sh
python examples/lantern-echo/build.py --timeline my-timeline.json --out output/lantern-echo-v2 --reuse-from output/lantern-echo
```

Only `05-release` needs rendering. The other nine lossless scene exports are
verified and copied, never hard-linked or overwritten. `build-receipt.json`
reports the decisions and names both adjoining cuts for visual re-review:
`04-catch → 05-release` and `05-release → 06-greeting`. Neighboring scenes need
boundary review, not automatic re-encoding. Global compositor/encoder changes
invalidate all relevant scene keys; changed motion assets invalidate their users.

Use `--dry-run` for the plan without writing output. Previous results are fully
verified before reuse, including every cached RGB sample. Corrupt cached scenes
cause an error; they are not silently reused or repaired over the original.

## Continue after interruption

Repeat the **same command**, adding `--resume`:

```sh
python examples/lantern-echo/build.py --timeline my-timeline.json --out output/lantern-echo-v2 --reuse-from output/lantern-echo --resume
```

Each scene becomes reusable only after lossless encode, full pixel/timestamp
verification and an atomic, synced checkpoint. An OS advisory lock is released
even if the process is killed. Completed scene files remain unchanged; an
unfinished encoder attempt remains unselected diagnostic evidence. Resuming
changed inputs or a different reuse receipt is rejected; create a new revision.
Repeating a completed build with `--resume` verifies it without rendering again.

Final publication is also checkpointed: an interrupted encode can be repeated;
an interrupted final rename can be completed only with matching verified bytes.
Existing unrecorded or modified movie files are preserved and cause an error.

## Reproduction and review limits

Prepared atlas packing is lossless. The baseline compositor preserves the original
frame calculations and PCM synthesis. Exact MP4 bytes also depend on Python,
Pillow, PyAV, FFmpeg and codec versions; cross-version bitstream equality is not
promised. Scene keys record those versions and the renderer sources.

This film uses an authored compositor and a checkpoint adapter specific to this
example. It is **not** the fixed-stage `gif-cinema sequence` format: that format
does not support this film's changing camera coverage and custom effects. Both
use the runtime's shared durable-write helper, but their schemas and receipts
are distinct. No existing sequence semantics are changed by this example.

Each output has a 512 MiB / 256-file guard. Temporary diagnostic files have a
manual seven-day retention policy; inspect an unfinished output before removal.
Accepted results, source art and receipts are retained. Never point the output at
the example source or at the published film directory.

[Original production and visual review](../../docs/LANTERN-ECHO.md) ·
[Measured rebuild/recovery qualification](verification.json)

## Repeat the real interruption qualification

This optional slow check runs the actual film builder, changes only the release
scene in a copied timeline, kills **its own** builder during that scene's encode,
and resumes it. It asserts one render, nine unchanged scene exports (four from
checkpoints and five copied from the baseline), both adjoining review cuts,
preserved baseline bytes/mtimes and idempotent completed resume. Python socket
connections are blocked in child builds. It never kills a process found by name.

```sh
python examples/lantern-echo/verify_rebuild.py --out output/lantern-proof --baseline output/lantern-echo
```

Omit `--baseline` to build one inside the new proof directory. Add `--ffmpeg` if
needed. Receipts and bounded logs stay under that directory. This full-film
qualification is opt-in; CI runs the fast planner and cache-safety regressions.
