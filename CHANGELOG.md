# Changelog

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
