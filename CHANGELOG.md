# Changelog

## Unreleased

- Add measured integer column corrections for source atlas alignment before a
  shared crop/scale. Preserve complete RGBA cells on a common padded canvas,
  keep original-cell margin checks, reject visible clipping and retain authored
  timing. Include a reproducible known-jitter recovery check; no automatic
  centering, new poses or artistic acceptance is implied.

- Add exact source-GIF palette inspection, fixed global-table export and integer
  nearest-neighbor upscaling, with no silent color reduction. Preserve canonical
  visible RGBA timelines, delays, loop counts and original source bytes; reopen
  all outputs and reject palette overflow, altered evidence and changed originals.
  Interrupted publication retains partial output instead of deleting another
  writer's edits. No new artwork, recoloring or visual approval is implied.

- Add explicit stepped selection of existing atlas drawings with `pose_keys`,
  frame-grid validation and honest per-drawing timing receipts. Carry selected
  drawing identity through shared-stage sequences and reject boundary resets.
  This edits accepted source art; it neither generates GIFs nor adds new poses,
  palette locking or in-betweens. Legacy native sprite timing is unchanged.

- Add offline fixed-stage scene sequences with propagated poses and prop holders,
  explicit detach/rebind tracks, boundary mismatch rejection, portable sources,
  all-frame recompile verification and zero-call film assembly. Include a five-action
  original robot-cutout example and actual cut evidence. No new poses or physics.
- Accept timed one-drawing local GIF holds in film import and review, while retaining
  the two-drawing requirement for generated responses and generated-shot caches.

- Add bounded reusable prop-anchor tracks to the local layer renderer, with explicit
  holder changes, acyclic attachment chains and before/after switch-gap diagnostics.
  Include an editable no-key contact study, per-frame position/parent receipts and
  all-frame reopen verification. These are authored constraints, not hand tracking,
  full transform parenting, new character poses or automatic visual approval.

- Bound ordinary film AAC to the video timeline at 48 kHz instead of relying on
  `-shortest` with unbounded padding. Keep existing coverage checks unchanged and
  check all required audio timing filters before execution.

- Add source-only exact script montage: hash-pinned original drawing selections,
  disposal-prefix budgets, exact SRT/timeline sidecars and script soundtrack.
  Include a reproducible 120-frame Blender split-and-rejoin example. No new
  intermediate poses or semantic-continuity guarantee.
 — exact decoded-GIF film master

- Add optional FFV1/BGRA Matroska masters with one frame per stored GIF drawing,
  exact RGBA/PTS/hold verification and explicit packet durations before muxing.
- Preserve original pixels through transparent center-padding, without resizing,
  cropping, frame coalescing or interpolation. Strict ambiguous-GIF cases fail.
- Add an optional lossy H.264 viewing copy on an exact 10 ms grid; explicitly pad/trim
  optional AAC audio instead of relying on `-shortest`. Preserve a silent pixel master.
- Include bounded staging, no-clobber publication, optional PyAV tests and a reproducible
  comparison against ordinary fixed-FPS exports. Visual acceptance remains pending.

## Unreleased — offline GIF factory

- Build a strict hash-pinned manifest of local GIFs and existing layered scenes into
  a named collection, static no-JavaScript gallery and portable stored ZIP.
- Preserve imported GIF bytes and derive preview pixels/timing from the actual final
  GIFs; reject exact decoded duplicates, animated-preview substitutions and unsafe paths.
- Bound individual and aggregate work, stage all results, verify ZIP members by
  readback, and expose a separate saved-collection verifier. Visual acceptance remains pending.
- Include a mixed-input repository example and English guide. No provider calls,
  third-party code, new generated artwork or new versioned skill release is included.

## Unreleased — preserve edited subtitles

- Pin the installable skill to the published, verified offline integration, including
  input limits, script snapshots, retained subtitle edits and current story tools.
- Track generated SRT hashes and shot timing; preserve manually edited subtitles
  during resume and rebuild, with a separate generated proposal for merging.
- Warn when retained subtitles have unknown timing history or their shot order/
  millisecond boundaries changed. Keep the warning in the manifest and receipt.
- Refresh unedited generated subtitles without rewriting unchanged files, retain
  previous versions, and avoid clobbering an editor save during publication.
- Cover ordinary/edited/legacy/empty SRT, changed timing, concurrent saves,
  unreadable outputs, and a real zero-call film resume/rebuild.

## Unreleased — bounded inputs and script snapshot identity

- Reject special-file GIFs, scripts and still references before opening, with
  nonblocking descriptor checks against FIFO replacement races on POSIX.
- Bound actual script and reference reads, including the combined reference
  budget and pre-request recheck, rather than relying only on an earlier size.
- Parse and hash the same returned script bytes once; preserve that snapshot's
  identity in the manifest even if the script changes during preflight/render.
- Reject chapter export for a changed script instead of mislabelling an old
  movie. Cover equal-duration shot reordering and zero-call rerender recovery.
- Preserve regular-file symlinks, in-memory GIF streams, source timing and
  zero-call planning. Add offline regressions for FIFO hangs, growing files,
  descriptor cleanup, reference limits and unchanged valid inputs.

## Unreleased — exact shared-palette colors

- Preserve exact palette colors in motion and layered GIF exports even when a
  frame also contains colors that need approximation. Prevent a 257th color from
  collapsing a represented grayscale ramp through Pillow's lookup cache.
- Store the shared GIF color table once without changing timing, frame disposal,
  loop policy or decoded colors. Keep the full-color PNG/MP4 route unchanged.
- Use explicit per-frame delays so Pillow 10.1 retains the total hold when all
  motion/layer frames are identical, instead of failing timing verification.
- Add an offline before/after benchmark, FFmpeg palette comparisons and decoded
  fixtures. Report measured fidelity, size and CPU tradeoffs without claiming
  automatic artwork or motion acceptance.

## Unreleased — explicit film colors

- Encode `film` and script-render MP4s with a matching BT.709 color matrix and
  limited-range SDR tags instead of relying on a player's SD/HD fallback.
- Verify and record the four color tags for script renders. Rebuild older untagged
  cached films locally, preserve their archives, and retain timing and source GIFs.
- Check both real SD/HD encoded pixels and metadata offline. No new character
  action, interpolation or color-managed HDR/ICC support is implied.

## Unreleased — standalone motion GIF replay

- Add strict recipe `gif_loop` and mutually exclusive `--play-once` / `--loop`
  overrides. Existing recipes and commands still default to infinite GIF replay.
- Play-once omits the GIF loop extension; reopen and verify the encoded policy
  before publishing, and report planned/verified policy in plans and receipts.
- Preserve source playback/repeats, timing, PNG samples and MP4 content. MP4 replay
  remains player-controlled, and viewers can override GIF metadata.
- Cover real GIF/MP4 exports, single-drawing holds, CLI overrides, strict validation,
  unchanged sources and refusal to publish an incorrectly encoded loop policy.
  This runtime feature does not change the separately pinned skill package.

## Unreleased — safe motion stack integration

- Integrate standalone motion, experimental layers and audio validation with the
  current doctor, script inspector and story workflow. Keep their commands distinct.
- Reject nonregular motion sources and recipes before opening; use nonblocking
  descriptor checks to prevent FIFO hangs, including during dry-run.
- Preserve the archived Chrome study separately from standalone motion documentation.

## Unreleased — CLI conveniences and cross-platform CI

- Add `gif-cinema doctor`: a no-request readiness report for Python, Pillow,
  FFmpeg/ffprobe capabilities, the effective model and whether an API key is set.
- Add `generate --dry-run`, which prints the exact payload without a key, request or writes.
- Dry-run validates existing outputs and reports zero new calls for a verified
  `--resume`; execution repeats those checks while holding its output lock.
- Honor `GIF_CINEMA_MODEL` as the default model for `generate` and script shots.
- Run CI on Linux (Python 3.10, 3.12, 3.13), Windows and macOS; skip the dangling
  symlink check where Windows denies symlink creation.

## Unreleased — shot-aligned GIF chapters

- Export a completed film into ordered GIF chapters that keep whole shots together,
  with configurable duration, dimensions and FPS and bounded media budgets.
- Verify the exact script, completed render manifest, saved-shot timing/hashes and
  movie hash. Dry-run makes no media-process calls or output writes.
- Snapshot and decode the H.264 master, trim by source-frame boundaries, verify every
  encoded GIF, and publish a new chapter folder with timing and checksum receipts.
- Keep the MP4 and earlier outputs unchanged. Chapters are silent, play once by
  default, and round their final hold up to one GIF frame. This is local delivery
  of existing actions, not new generated motion or a new versioned release.

## Unreleased — reviewed story takes

- Fill generated storyboard slots with explicit local GIF selections, SHA-256 hashes
  and caller review notes through `compile --takes`. No provider requests are made.
- Preserve original generation scripts, measure selected GIF timing and flag duration
  changes or repeated footage. Partial selection keeps missing actions explicit.
- Emit portable storyboards with hash-pinned media and rebased references, allowing
  a longer story to continue in a new project without replacing prior sources/titles.
- Include a no-key selection example and offline regressions. This is a workflow
  improvement, not newly generated animation or a new published release.

## Unreleased — standalone film audio validation

- Apply the existing bounded audio snapshot and strict-decode preflight to
  standalone `film --audio`, rejecting empty/corrupt inputs before encoding.
- Verify expected AAC audio and duration coverage before atomic publication,
  including `--force`; failed input or output checks preserve the previous MP4.
- Audio-enabled standalone films now require working ffprobe and use the same
  input/duration limits as script render. Silent film assembly keeps its existing
  FFmpeg-only dependency and behavior. No new sidecar files or API calls.
- Add standalone regressions for corrupt/empty WAVs, source changes, missing or
  short output audio, timeout cleanup, no-clobber races and valid audio timing.

## Unreleased — audio preflight before generation

- Snapshot bounded local audio and strictly decode it before any paid render
  request; reject corrupt/truncated audio before creating a project or spending.
  Keep dry-run FFmpeg-free and explicitly mark audio decode validation as pending.
- Bound encoded audio size, duration, channels, sample rate, probing and decode
  time. Reject playlists/network protocols and preserve the exact validated bytes
  through assembly, with hash-bound audio facts in the manifest.
- Verify requested final AAC audio, strict decoding and video-duration coverage
  with packet-rounding tolerance; report audio verification in receipts. Silent
  films keep their existing verification contract.
- Add offline corruption, timeout, resource-limit, snapshot, missing-track,
  resume and 54-second/6-fps audio timeline regressions. No provider requests.

## Unreleased — experimental source-only independent layers

- Give both halves of the asset-free example card rotation explicit smootherstep
  easing; test the angular speed at the turn and loop seam and symmetric rendered poses.
- Add a separate `python -m gif_cinema.layers` proof of concept for independent
  still-image, text, rectangle and ellipse layers, local timelines, anchors,
  source-over alpha and keyframed easing. This is not Lottie-compatible.
- Add portable scene save/reopen, verified GIF/MP4/PNG export and a verifier that
  rerenders every saved frame and checks receipt hashes.
- Retain reviewed raster budgets, regular-file/FIFO defenses, shared 16 MiB
  receipt limits and bounded normalized scene serialization.
- Reuse the published bounded media runner; include only source, documentation,
  tests and an asset-free shapes/text JSON example. No showcase/demo media or
  artwork generator is included. Editable text requires Pillow 10.1 or newer.

## Unreleased — source-only motion recipes

- Add standalone offline `motion` for keyframed pan, zoom, rotation and opacity,
  source trimming/retiming, repeat/reverse/ping-pong playback, PNG frames, GIF,
  verified MP4 and optional bounded spritesheets.
- Preserve full-resolution small color accents in the shared GIF palette, honor
  EXIF still-image orientation and sample rational timing boundaries exactly.
- Reuse corrected GIF extension preflight with stricter motion input budgets;
  reject expanding GIF canvases before decoding. Search feasible atlas grids.
- Include motion source, generic recipe and offline regressions only. No new
  media, demo resources, editor or separate finishing feature is added.

## Unreleased — source-only backend hardening

- Validate GIF extension framing before decoding, including fixed headers and
  NETSCAPE loop payloads. Reject malformed/unknown extensions that can make a
  permissive decoder interpret hidden oversized disposal images differently from
  preflight; keep standard comments and application metadata supported.
- Bound shared GIF reads, decoded frame count, per-frame pixels and total pixels;
  reject oversized imports during planning before any billable request.
- Check runnable FFmpeg/ffprobe, H.264 and assembly filters before execution;
  audio scripts also check AAC and audio padding support.
- Apply 300-second deadlines and closed standard input to film assembly and both
  verification passes. Timeouts preserve accepted exports and remove staging/locks.
- Persist render manifests with an fsynced atomic writer and sync new project
  directory entries before dispatch. Sync failures stop requests; uncertain
  outcomes still require review, with no exactly-once billing claim.
- Backport only the required source helpers from the development preview. No new
  media, packaged demo, editing/motion commands or standalone generation receipts
  are included. The existing checkout examples remain available.

## Unreleased — safe resume and exact export timing

- Keep timeout, HTTP 408/5xx and unreadable-response outcomes unresolved across
  render restarts, including ambiguous failures from older manifests. Only rate
  limit rejections retry automatically; explicit review is needed before a new
  attempt with an unknown cost.
- Preserve the final GIF hold and use an explicit frame count/output rate for
  each shot. Check the exact exported frame count and keep captions on the same
  timeline. Rebuild older cached MP4s locally while retaining their archives.
- Add offline regressions for real-client timeouts, safe/unsafe resume, failed
  retakes, publication failures, legacy records, fractional timing and short shots.

## Skill 0.1.1 — verified showcase

- Add matched before/after footage for the astronaut, dog and cat, with varied
  frame pairs and a clear distinction between public tools and private finishing.
- Include three reference-conditioned astronaut GIFs in the default API-free
  example; retain the historical example separately.
- Verify a fresh public installation, real GIF assembly, endpoints and resume.
- Remove personal Git author email from active history and sanitize showcase media.
- Retire obsolete demo write-back workflows that could overwrite the current
  presentation with historical output.
- Preserve the source-available evaluation license.

## 0.5.0 — script rendering

- Integrate offline reliability fixes while preserving the independently updated GIF demo.
- Add a validated versioned script format with imported and generated shots, an offline
  dry-run default, explicit execution, and a per-run request cap including transient retries.
- Persist attempts before sending; reuse checksum-verified shots and support explicit
  single-shot regeneration without replacing other approved shots.
- Add first/last frames, contact sheet, review-required continuity diagnostics, captions,
  a render manifest and a receipt. Verify the staged H.264 film with ffprobe and full decoding.
- Include a three-shot offline example and a separate unrendered character-continuity proposal.
- Visual identity and seamless motion remain human acceptance criteria, not automated guarantees.
