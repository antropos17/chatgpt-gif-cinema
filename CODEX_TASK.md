# CODEX TASK · GIF Cinema v0.5.0

Repository: https://github.com/antropos17/chatgpt-gif-cinema
Branch: create `feat/script-to-film`; do not modify `main` directly without tests.

## Goal
Turn a structured multi-shot script into a reproducible, resumable short film using OpenAI GPT Image GIF generation and FFmpeg. The existing v0.4 pipeline can generate individual GIFs and assemble them; it cannot yet autonomously render a full film from `film.json`.

## Implement
1. Add `gif-cinema render examples/film.json --out output/last-light --dry-run`.
2. Add `--execute` for actual API calls, `--max-api-calls 3` default, and a clear preview of planned calls before execution. No requests in dry-run.
3. Define and validate a stable script schema with title, ratio, style bible, numbered shots, per-shot prompt, frames, duration, transition, audio notes, first-frame target and last-frame target. Support the existing `examples/film.json` format.
4. Generate a `render-manifest.json` per project with API model, params, prompt checksum, output path, request duration, usage if returned, errors and result status. Do NOT store secrets or bearer headers.
5. Reuse verified existing GIF shots when resuming. Never repeat an API request for an already valid shot unless `--force` is explicit.
6. Extract first and last frames and a contact sheet. Create a `continuity-report.json` comparing adjacent shots using the current metric, but always mark subjective matching as needing human review.
7. Assemble valid GIFs to MP4 using FFmpeg with correct per-frame timing. Preserve aspect ratio, allow explicit width, height and FPS. Hard cuts initially, no fake in-between AI frames.
8. Print an accurate receipt at the end: generated/skipped shots, cost information if available from API usage, film duration, path and verification status.
9. Retry only transient 429/5xx with bounded backoff; never retry validation/authorization errors automatically. Hard cap on API calls (including retries) and visible control over billable operations.
10. Tests for dry-run, manifest, resuming, max calls, invalid files, semantic continuity disclaimer, FFmpeg availability and error redaction. Mock API requests for CI; opt-in live tests remain manual.
11. Update README, `AGENTS.md`, skills, docs and CHANGELOG.

## Acceptance tests
- `python -m unittest discover -s tests -v` passes.
- `gif-cinema render examples/film.json --dry-run` does not require OPENAI_API_KEY, has zero network calls and outputs a valid plan.
- `gif-cinema render examples/film.json --execute --max-api-calls 1` never sends more than one billable API request.
- A successful partial render can resume without repeat charges for shots already on disk.
- `gif-cinema film` remains backward compatible.
- GIF output is validated as real GIF, with per-frame durations; final MP4 verified with ffprobe.
- No secrets or sensitive data in commits, console logs, reports, Actions artifacts or issue comments.

## Source of truth
- Official GPT Image GIF docs: https://developers.openai.com/api/docs/guides/image-generation
- Explicit model: `gpt-image-2.6-flare`; output_format=gif; conservative frame_count=2..16.
- GIF edit endpoint does not accept GIF output; independent shots cannot guarantee identical characters or exact endpoints.
- Do not label the current 5.4-second film proof a fully autonomous story-to-film product.

## Design rules
Monochrome, minimalist, sharp typography, accessible contrast. No fake cinematic demo or marketing claims without corresponding artifact. Keep any proprietary models/credentials out of public source.

## Completion checklist
Produce a PR with clear CLI examples, tests, screenshots or real sample paths only when available. Explain any remaining blocker or unsupported API behavior. Do not silently make additional paid API calls.
