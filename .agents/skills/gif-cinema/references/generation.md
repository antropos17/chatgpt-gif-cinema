# Generation inputs and actual API boundaries

The pinned GIF Cinema runtime has OpenAI Images generation/edit adapters for the
model labels `gpt-image-2.6-flare` and `gpt-image-2.6-sunburst`. A repository label is
not an assurance that a user's account currently supports that model or native GIFs.
The repository records an account-specific reference-conditioned GIF test on
November 5, 2026. No new provider test is implied by installing or using this skill.

Before spending, check the available tool/model interface, user authorization, and
project request budget. Do not invent another provider's GIF endpoint or substitute
paid generation just because it is installed. If native GIF generation is unavailable,
use existing clips or an explicitly available image-sequence/compositor workflow and
label that method accurately. The skill does not embed a video service or free credits.

## Current public runtime contract

Read the pinned [script schema](https://github.com/antropos17/chatgpt-gif-cinema/blob/fa82b13366a9ae94a4ece730ec6b2d065cd9a060/docs/SCRIPT-FORMAT.md)
when changing generation settings. It validates strict JSON fields before dispatch.

- Request 2–16 frames, 20–2000 ms per frame in 10 ms steps. These are requested
  settings; inspect actual output. A 16 × 160 ms request targets 2.56 seconds.
- `references` accepts 1–16 existing local still PNG/JPEG/WebP files, combined 20 MiB.
  No video/GIF references, masks, temporal seeds, character locks or automatic chaining
  are exposed by this script contract. References resolve relative to the script.
- Shared style and identity text is prepended. The simple `generate` CLI does not
  expose references; use `render` with the compiled single-shot script.
- Preflight is offline. A missing reference fails before dispatch. Acquire and inspect
  the previous endpoint before adding it, instead of naming a future file and hoping.

```bash
python -m gif_cinema render PROJECT/generation/03-catch.json --dry-run --max-api-calls 0
# Only after authorized generation, substituting the agreed cap:
python -m gif_cinema render PROJECT/generation/03-catch.json --execute --max-api-calls 1 --retries 0 --out PROJECT/takes/03-catch-v1
```

`--max-api-calls` limits requests, not dollars or total lifetime attempts. Use the
exact approved budget, not a larger sample value. Never print or save the API key.
For a timeout or unknown result, inspect request/billing status before retrying;
creating a new folder is not a way around the runtime's unknown-outcome protection.
Authentication/model rejection is a blocker, not permission to switch models/services.

## Accepted shots and references

Inspect the GIF's first/middle/last frames and action contact frames. Extract endpoints
with `python -m gif_cinema endpoints TAKE.gif -o UNIQUE_PREFIX`. Pass a clean approved
identity still plus the accepted preceding endpoint into the next shot. Inspect the
endpoint itself for drift before passing it forward. This is manual dependency review.

Keep each generated GIF linked to its script, take folder, request/usage record and
acceptance status. Preserve rejected takes when needed for rollback. Use the runtime's
actual `--force-shot ID` workflow only with the required retry authorization. Review
both sides of a replaced shot. Finally, replace that storyboard's `generate` object
with `source: "path/to/accepted.gif"` and compile a new source-only project. No titles
or added montage shots are needed in a single-shot paid generation request.
