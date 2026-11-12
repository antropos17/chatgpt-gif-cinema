# Script rendering (schema version 1)

`render` assembles an author-controlled script, not an autonomous screenplay generator.
The script is UTF-8 JSON, limited to 1 MiB. Unknown fields are rejected so a typo cannot
silently change a billable request. Planning is the default and performs no network
requests, creates no output directory and needs no key or FFmpeg installation.
Script, source GIF and still-reference paths must resolve to regular local files.
Named pipes, devices and directories are rejected before reading, including during
dry-run. Regular-file symlinks remain supported. The opened descriptor is checked
again, with nonblocking open where available, so a FIFO substituted during preflight
cannot make a POSIX render wait for a writer. Byte limits apply to actual reads,
including growing files and the combined 20 MiB reference budget; references are
checked again before dispatch. In-memory GIF streams remain supported by the
Python API. These checks do not create any provider request.

Each invocation reads one bounded script byte snapshot. Parsing and the manifest's
`script_sha256` use those exact bytes, including any UTF-8 BOM and line endings.
Edits or replacement of the script during preflight/render do not change the active
plan or its recorded identity. The movie and newly generated caption text still
correspond to the snapshot; separately edited SRT files are preserved as described
below. Chapter export rejects a changed script until it is rendered again.
Rerun after editing to use the new order, captions or other settings. For existing
verified footage, `--execute --max-api-calls 0` prevents new generation charges.
An older render created while its script was changing may already have an incorrect
script hash: rerender that project before exporting chapters. This fix cannot
retroactively establish which script bytes an older run actually parsed.

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
| Generated shot | `model`, `size`, `quality`, `complexity` | Same conservative generator settings as `generate`; `model` defaults to `$GIF_CINEMA_MODEL`, else `gpt-image-2.6-flare` |
| Generated shot | `references` | Optional 1..16 local still PNG/JPEG/WebP paths relative to the script, combined limit 20 MiB; uses `/v1/images/edits` |

Imported shots may include a one-drawing GIF with a valid delay for an intentional
static hold. This does not count as new motion; generated responses still require
at least two drawings. Inspection and cut review can read these local holds too.

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
filters before any paid call. Scripts with audio also require AAC and the `apad`, `aresample`, `atrim` and
`asetpts` audio filters.
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

The AAC soundtrack is resampled to 48 kHz, padded when short, and trimmed to the
nearest audio sample of the quantized video duration. Both streams are explicitly
bounded; assembly does not rely on `-shortest` to stop unbounded audio padding.
Final AAC coverage verification still permits only its existing codec-padding tolerance.

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
Film encoding explicitly converts the decoded GIF's RGB colors to limited-range
BT.709 YUV and labels the matrix, range, transfer and primaries in the H.264/MP4.
The script verifier requires those matching color tags and includes them in
`film-inspect.json`. This prevents players from having to guess an SD or HD color
matrix. It is a standard SDR delivery convention, not HDR or ICC-profile color
management, and YUV420/H.264 remains lossy. Standalone `film` uses the same encoding
settings. These settings do not change the separate motion or layer exporters.
On resume, older untagged script exports are rebuilt locally once with zero provider
calls; the previous verified MP4 is archived as usual.
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
Derived reports in this dedicated project directory are refreshed on resume;
manually edited subtitles are the exception.

### Editable subtitles on resume

The manifest now records the last generated `captions.srt` hash and its ordered,
millisecond-quantized shot timeline. A matching, unedited generated SRT can update
when script text or timing changes; an unchanged SRT is not rewritten. An automatic
update retains the displaced file as `captions-preserved-*.srt`. If an editor saves
during replacement, no-clobber publication preserves the editor's file and the
displaced copy rather than silently overwriting either.
An editor that still holds the old file open can write to the preserved copy after
replacement; those bytes are retained there, but are not automatically merged into
the new primary SRT. An interrupted update may leave a preserved copy or an empty
reserved filename for recovery instead of risking deletion after an uncertain move.

If `captions.srt` differs from the tracked generated bytes, render preserves it
exactly, including BOM, line endings and an intentionally empty file. Fresh script
captions are saved separately as `captions-generated-<hash>.srt` for manual merging.
An edited earlier proposal is not replaced. A changed shot order or actual SRT
timestamp produces a warning on stderr and `timing_review_required` in both the
manifest and receipt. The movie may still finish successfully: the warning means
the retained custom subtitles need synchronization review, not that they were retimed.
Changing FPS alone does not warn when ordered millisecond boundaries remain identical.

Legacy projects without caption provenance adopt an existing SRT only when its
bytes exactly match current generated text. Otherwise they preserve it and warn
that timing history is unknown. Symlinked, nonregular, unreadable or over-2-MiB
caption outputs are also preserved, with a separate generated proposal and warning.

The renderer does not parse or certify independently edited subtitles, and it does
not infer that further edits completed a synchronization review. A timing warning
remains conservative on later resumes. Adopting the current generated proposal as
`captions.srt`, or intentionally removing that file before render to regenerate it,
restores automatic tracking. Keep custom edits elsewhere before doing either.
The generation `--force` options do not grant permission to discard SRT edits.

Decoded transparent GIF drawings retain RGBA on every frame, including later
frames after palette/disposal composition. Opaque drawings retain RGB mode. Endpoint
PNGs preserve alpha; both the overview and join strips composite onto a dark matte.

Cut pixel diagnostics composite both frames onto black and white before thumbnail
comparison and report the larger RGB MAE. This exposes alpha-only disappearance
and ignores RGB hidden under fully transparent pixels. The JSON `pixel_metric`
field identifies this definition; historical alpha-ignorant scores are not directly
comparable for transparent inputs. Opaque-frame scores are unchanged. The review
strip uses a dark matte so invisible colors do not appear as phantom drawings.
These diagnostics never change the source frames, cadence or exported movie.

Every continuity join remains `human-review-required`, even when pixel difference is
small. Inspect identity, costume, pose, gaze, action direction, scene geography and
causality at full playback speed. A three-shot MP4 that passes decoding is only a
technical pass. It is not proof of a coherent story or a seamless performance.

The first acceptance film must preserve one recognizable character and aligned poses
and action across cuts. If existing GIFs fail that criterion, report the failure and
prepare a bounded replacement plan; do not disguise it with dissolves or new claims.

## Standalone film audio compatibility

`gif-cinema film clip.gif --audio soundtrack.wav -o film.mp4` uses the same bounded
audio snapshot, supported formats, strict input decode and final AAC coverage
checks described above. These checks run before the MP4 is published, including
with `--force`. An empty or corrupt audio file is rejected instead of being silently
padded into a successful-looking soundtrack. A failed preflight does not create
the destination directory; encoding/verification failures clean temporary files
and locks while preserving the previously accepted MP4.

Audio-enabled standalone assembly now requires working ffprobe as well as FFmpeg.
Its audio input and film duration have the same one-hour limit as script render.
These deliberate restrictions can reject files that older standalone versions
accepted permissively. Valid short tracks are still padded, long tracks trimmed,
and per-shot frame rounding and final poses are unchanged. Input GIF/audio files
are not modified. Silent `film` remains FFmpeg-only and does not acquire audio
limits or verification work.

The standalone CLI still produces just the requested MP4 with the same success
message and `--force`/no-clobber behavior; it does not create script manifests or
audio sidecars. It makes no provider calls. Script render retains its pre-generation
audio check and its own receipts, and the assembly step rechecks its private
snapshot before publishing. The additional local probe/decode work is bounded by
the existing deadlines. Technical validation does not establish artistic quality.

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
