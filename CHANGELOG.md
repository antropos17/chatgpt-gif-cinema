# Changelog

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
