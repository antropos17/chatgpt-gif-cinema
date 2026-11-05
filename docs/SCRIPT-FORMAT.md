# Script rendering (schema version 1)

`render` assembles an author-controlled script, not an autonomous screenplay generator.
The script is UTF-8 JSON, limited to 1 MiB. Unknown fields are rejected so a typo cannot
silently change a billable request. Planning is the default and performs no network
requests, creates no output directory and needs no key or FFmpeg installation.

```bash
python -m gif_cinema render examples/film.json --dry-run
python -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/offline-story
```

The committed `film.json` uses three existing GPT-generated GIFs. It makes no new API
calls. `consistent-film.proposed.json` is a separate, unrendered proposal with the same
astronaut, camera, screen position and explicit pose targets across three shots.
Independent model outputs may still differ; prompt wording does not establish identity.

## Fields

| Level | Field | Contract |
|---|---|---|
| Script | `schema_version` | Integer 1 |
| Script | `title`, `style_bible` | Required nonempty strings |
| Script | `ratio` | Positive integer pair such as `1:1`, `9:16` |
| Script | `width`, `height`, `fps` | Optional even dimensions 2..4096; FPS 1..120; dimensions must agree with ratio |
| Script | `audio` | Optional local path relative to the script; no network URLs |
| Script | `audio_notes` | Optional author note, not a sound-generation instruction |
| Script | `shots` | Ordered list of 1..64 objects; the demonstration uses 3 |
| Shot | `id` | Required unique ASCII identifier, 1..40 characters, letters/digits/underscore/hyphen; case-insensitive uniqueness |
| Shot | `source` OR `prompt` | Exactly one; local GIF path relative to script, or generation prompt |
| Shot | `first_frame_target`, `last_frame_target` | Required author descriptions; not verified visual observations |
| Shot | `transition` | Only `cut` is supported; no generated interpolation or automatic dissolves |
| Shot | `caption`, `audio_notes` | Optional text; captions produce a separate SRT |
| Generated shot | `frames`, `duration_ms` | Default 9 and 200; 2..16 frames, 20..2000 ms in steps of 10 |
| Generated shot | `model`, `size`, `quality`, `complexity` | Same conservative generator settings as `generate` |

Imported shots retain actual frame delays; generation parameters are rejected on
imports. Script captions do not burn text into source GIFs. Width/height/FPS CLI
overrides are validated before execution. The output directory must be new/empty or
contain a valid render manifest. Keep scripts and imported originals outside it.

## Execution and accounting

`--execute` explicitly permits generation, subject to `--max-api-calls` (default 3).
Use zero for guaranteed import/reuse-only operation. The printed plan lists the minimum
new calls; the cap includes retries, which can exhaust the allowance before every shot
is finished. Only HTTP 429 and 5xx are retried, at most twice by default, with bounded
backoff. Timeouts, authentication and invalid outputs are not retried automatically.
Each invocation gets its own cap; attempts and invocation counts remain in the manifest.

The attempt is saved before the request. If the process disappears during a request,
its cost/outcome is unknown. The next run stops rather than silently paying again.
An explicit `--force-shot ID` permits another attempt after review. No exact-once
billing guarantee is possible across an interrupted network request.

Model, effective prompt, parameters, checksum, timing, numeric usage, safe error status
and outcome are recorded. No API key, bearer header or raw server error body is stored.
Token usage is not a dollar price; imported/reused shot usage is historical, not a new
charge. Keep private information out of prompts if you intend to share the manifest.

## Resume, replacement and verification

Run the same command again: matching decoded shots with matching hashes are reused,
with no API request. A changed generated shot requires `--force-shot ID`; `--force`
regenerates all prompt shots. Imported originals are never changed. Old shot versions
remain on disk. A successful replacement movie archives the previous verified movie.
An encoder/probe failure preserves the accepted movie. Do not manually edit generated
project files; changed hashes stop execution. After a crash, remove a lock only after
confirming the owning process has stopped.

Execution requires both FFmpeg and ffprobe before any paid call. Output is staged,
checked for H.264, dimensions, decoded frame count and duration, then fully decoded.
Timing may round by approximately one output frame per shot. A contact sheet, individual
first/last PNGs, continuity report, SRT, inspection JSON, manifest and receipt are written.
Derived reports in this dedicated project directory are refreshed on resume.

Every continuity join remains `human-review-required`, even when pixel difference is
small. Inspect identity, costume, pose, gaze, action direction, scene geography and
causality at full playback speed. A three-shot MP4 that passes decoding is only a
technical pass. It is not proof of a coherent story or a seamless performance.

The first acceptance film must preserve one recognizable character and aligned poses
and action across cuts. If existing GIFs fail that criterion, report the failure and
prepare a bounded replacement plan; do not disguise it with dissolves or new claims.

## Local artifact retention

Keep accepted GIFs, films, manifests and verification receipts. Temporary test directories
are scoped to a project-local `output/tmp` on a spacious drive and closed after tests.
Disposable downloaded tool archives should be removed after successful extraction and
verification; reusable binaries can remain in `output/tools` for this task. No automatic
global cleanup is installed. Before another large batch, check free space and these exact
directories; do not recursively clear system temporary directories or other projects.
