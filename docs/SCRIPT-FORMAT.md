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
calls. `consistent-film.proposed.json` was tested in run 41982718167; both joins failed
visual continuity despite matching textual identity and pose targets.
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
| Generated shot | `references` | Optional 1..16 local still PNG/JPEG/WebP paths relative to the script, combined limit 20 MiB; uses `/v1/images/edits` |

Imported shots retain actual frame delays; generation parameters are rejected on
imports. Script captions do not burn text into source GIFs. Width/height/FPS CLI
overrides are validated before execution. The output directory must be new/empty or
contain a valid render manifest. Keep scripts and imported originals outside it.

All shared GIF ingestion, including imports, cached footage and decoded provider
results, is bounded to 128 MiB of encoded bytes, 1,500 frames, 16,777,216 pixels per
frame and 167,772,160 decoded pixels across all frames. Pixel limits count the full
composited drawing, not just changed rectangles. Reads are bounded even if a file
grows; GIF descriptors are scanned before decoding, so disposal frames and later
canvas expansion cannot bypass the pixel limit. Oversized footage fails explicitly
rather than being silently resized or truncated.
Extension framing is checked before decoding as well: standard graphic control,
comment, plain-text and application extensions are supported, with fixed headers
and a complete NETSCAPE loop payload. Malformed or unknown extensions are rejected
instead of relying on permissive decoder recovery that could hide image descriptors.

## Execution and accounting

`--execute` explicitly permits generation, subject to `--max-api-calls` (default 3).
Use zero for guaranteed import/reuse-only operation. The printed plan lists the minimum
new calls; the cap includes retries, which can exhaust the allowance before every shot
is finished. Only HTTP 429 rate-limit rejections are retried, at most twice by default,
with bounded backoff. Timeouts, HTTP 408/5xx, invalid responses and other unknown
outcomes are not retried, either automatically or by simply restarting the command.
Authentication and other definitive 4xx rejections are not retried in the same run.
Each invocation gets its own cap; attempts and invocation counts remain in the manifest.

The attempt is saved as `started` before the request, using a flushed and fsynced
temporary file, atomic replacement and directory sync where supported. Newly created
project directory entries are synced before requests. Real sync failures stop dispatch.
Directory sync is best-effort when unsupported on POSIX and is unavailable through
Python's OS API on Windows; file fsync remains mandatory. These measures improve
local crash recovery, not provider-side exactly-once billing.
A network failure, server error
or unreadable result is saved as `unknown`, because the provider may already have
generated and charged for the shot. A crash leaves `started` durable. Both states
block another generation on the next run rather than silently paying again. Older
`failed` records are treated the same way unless they show a definitive 4xx rejection
(excluding HTTP 408). Accepted, hash-verified footage can still be reused for free.

Review the provider's request/billing history before retrying an unknown outcome.
An explicit `--force-shot ID` (or `--force` for all generated shots) permits another
attempt after review and may create another charge; the original attempt remains in
the manifest. No exact-once billing guarantee is possible across an interrupted
network request. Do not use a new output directory to bypass this review.

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

Execution checks runnable FFmpeg/ffprobe, the `libx264` encoder and all assembly
filters before any paid call. Scripts with audio also require AAC and `apad`.
Offline planning still needs no FFmpeg and performs none of these process checks.
For audio, the plan explicitly reports that decode validation is still pending.

Before execution looks up a key, creates the render project or dispatches a paid
request, it snapshots the audio and probes and strictly decodes the complete first
audio stream. A valid container header alone is not enough: corrupt or truncated
audio fails before generation rather than being silently replaced by padding.
Assembly uses those exact validated snapshot bytes even if the original changes
while shots are generated. The manifest records the audio hash, encoded size,
codec, sample rate, channels and decoded duration; the snapshot is removed after
the run. Existing audio/films are never changed by a failed preflight.

Audio input is limited to a regular local file of 128 MiB, one hour, eight channels
and 192 kHz. Films with audio are limited to one hour. Supported containers are WAV,
MP3, FLAC, Ogg, AAC, AIFF, M4A/MP4 and Matroska/WebM. Playlists, device inputs and
network protocols are rejected. Probe and strict audio decode each have a
30-second deadline, closed stdin, one decoder thread, an 8 MiB probe budget,
ten seconds of stream analysis and a 64 MiB maximum individual allocation.
Diagnostic reads are capped at 64 KiB; raw decoder error payloads are not printed.

Film assembly, video probe and full video decode have a 300-second deadline each
and cannot wait on standard input. A timeout fails the run, cleans staging/locks
and preserves an existing accepted movie; completed shots remain reusable.
Output is staged,
checked for H.264, dimensions, decoded frame count and duration, then fully decoded.
When audio was requested, verification also requires an AAC track and a strict
audio decode, with start/duration coverage checked against the video. A tolerance
of two 1,024-sample AAC packets plus one millisecond allows codec padding and muxer
rounding; it does not accept a missing or substantially shorter track. Audio
verification details are included in the inspection report and receipt. Silent
scripts retain their existing video-only contract. These are technical checks,
not a judgment of the soundtrack's content or artistic synchronization.
Each shot's output frame count is its duration multiplied by FPS, rounded to the
nearest integer (ties to even), with a minimum of one frame. Final-frame holds are
preserved; captions follow the same quantized timeline. Previously cached exports
are rebuilt locally once with this timing correction, retaining the old MP4 archive.
A contact sheet, individual
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

## Reference-conditioned GIF scenes

Live run 41984076055 confirmed that `gpt-image-2.6-flare` accepts a still image
and returns a native animated GIF through `/v1/images/edits`. The endpoint reference
includes GIF output even though the image-generation guide says edits are unsupported.
This evidence is scoped to the tested model/account and November 5, 2026.

For each new scene, supply the original character reference plus the reviewed last
frame of the previous scene, and describe which image controls identity versus pose.
Example generated-shot field: `"references": ["previous-last.png", "character.png"]`.
All references are decoded before any paid call. Their hashes affect cache identity;
changes require explicit regeneration. Images are checked again before transmission.
The manifest stores relative filenames, MIME types and hashes, never base64 images.

This version uses explicit local references, not an automatic last-frame dependency
graph. Review a scene before exporting its last frame for the next request. The same
call budget and resume protections apply. References improve control but do not
guarantee identity or correct action: inspect every output and join.
