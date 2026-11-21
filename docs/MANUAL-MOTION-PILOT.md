# One manual direct-OpenAI motion pilot

**Prepared workflow, not a generated GIF. No live request has been made for this
preset. The bundled cost record is unknown, so paid execution currently stops.**

This is a small reproducible route from GitHub Actions to the official OpenAI
Images API using the repository's existing `OPENAI_API_KEY` secret. It adds no
credential, provider, browser requirement, automatic generation trigger or new
runtime dependency. It does not change the existing astronaut live-test workflow.

## What the pilot requests

[Chrome Trefoil script](../examples/motion/chrome-trefoil.film.json): one continuous
silver knot, small rigid sway, locked camera, near-black background. Fixed request:
`gpt-image-2.6-flare`, `output_format=gif`, 512 × 512, `quality=max`,
`complexity=high`, 16 drawings × 200 ms = **3.2 seconds at 5 drawings per second**.
This is a restrained motion test, not a promise of smoothness. No interpolation,
reverse playback, video-to-GIF conversion or animated-still fallback is used.

The current [OpenAI GIF contract](https://developers.openai.com/api/docs/guides/image-generation#generate-animated-gif-output)
permits 2–16 frames and 20–2000 ms delays. Frame dimensions must be multiples of 16.
Actual model/account access and total pixel budgets can still reject a request.
There is no automatic model substitution, parameter downgrade or retry.

## Free preparation, now

After the workflow is reviewed and merged to the default branch, open **Actions →
Manual Direct Motion Pilot → Run workflow**. Keep `execute=false` and all other
defaults. This runs offline tests and uploads an **unrendered request artifact**.
Publishing the branch or opening a PR does not start generation. A new
`workflow_dispatch` file must be present on the default branch for GitHub's manual
workflow UI; this PR does not merge itself.

For local preparation, without credentials:

```bash
python -m pip install -e '.[filmqa]'
python -m gif_cinema render examples/motion/chrome-trefoil.film.json --dry-run --max-api-calls 0 --retries 0
python -m tools.manual_motion prepare
```

Read `output/manual-motion/request.json`. It contains the exact effective prompt,
parameters and SHA-256. No GIF exists after this step. The output folder refuses
overwriting so prior results are not silently lost.

## Spending is deliberately blocked until a real upper bound exists

[Current rates](https://developers.openai.com/api/docs/models/gpt-image-2.6-flare)
checked 2026-11-09: $30 per million image-output tokens, $5 per million text-input
tokens and $8 per million image-input tokens. **These are not an all-in quote for a
16-frame maximum-quality GIF.** A documented request-level maximum was not found.
Do not multiply the old low-quality astronaut receipt into a premium-batch quote.

`--max-api-calls 1` bounds calls, not dollars. OpenAI project
[hard spend limits](https://developers.openai.com/api/docs/guides/spend-limits)
are also not exact transaction ceilings because enforcement can lag. This workflow
does not change account limits or billing settings.

The checked-in [cost-bound.json](../examples/motion/cost-bound.json) therefore has
`status=unknown`. Even selecting `execute=true` and entering a positive USD amount
will stop before reading the key or making an API call.

To make the paid path available later, a maintainer must first obtain and review a
**provider-guaranteed all-in upper bound** for this exact effective request and
update the cost record in a reviewed code change. Required fields:

- `status`: `reviewed-provider-upper-bound`.
- `request_sha256`: the exact hash from the prepared request.
- `maximum_total_usd`: a positive decimal string including all charges.
- `currency`: `USD`; `includes_all_charges`: `true`.
- `basis`: `provider-guaranteed-request-maximum`.
- `source_url`: a public official OpenAI evidence URL with no credentials/query.
- `valid_until`: the guarantee's final valid date in ISO `YYYY-MM-DD` format.

**Do not invent these values, treat an estimate as a guarantee, or paste private
billing records into the public repository.** The script validates the record's
shape, freshness, request hash and budget fit; it cannot independently authenticate
an external guarantee. If no such upper bound can be obtained, this workflow stays
preparation-only. A different spending policy requires separate explicit agreement
and a reviewed implementation change, not relabeling an estimate.

## Eventual paid dispatch, only after that gate is resolved

1. Review the exact request and cost evidence on the selected commit.
2. Review earlier runs and OpenAI usage, including failed or interrupted attempts.
3. Manually dispatch with `execute=true`, `approved_usd` at least the reviewed
   all-in request bound, `confirm_billing=true`, and `prior_attempts_reviewed=true`.
   The payer is the existing secret's OpenAI project. Confirm its ownership outside
   this public workflow; no account identifier is collected here.
4. The script rechecks the bound and allows at most **one** request, **zero** retries.
   Re-running an existing Actions run (`github.run_attempt > 1`) is refused.
   A new dispatch is a new authorization and must not hide an unknown prior charge.
5. Download the run's `direct-motion-RUN_ID-attempt-ATTEMPT` artifact within 14 days.
   Artifacts follow repository access, so assume maintainers/readers may see them.

Each attempt is recorded before dispatch in the existing durable render manifest.
Timeouts and unreadable responses remain unknown outcomes. Never assume a failed
workflow means no charge, or rerun it to obtain an unaccounted replacement.

## Review the actual media

When a native GIF has been saved, the artifact retains the original returned GIF, exact
request, authorization record, render manifest, usage counters, every decoded
frame as a numbered PNG, a contact sheet, and `review.json`. The existing film
renderer also makes an MP4 viewing derivative, which is not the native GIF master.
If that MP4 derivative fails, review still runs on any saved native GIF. The workflow
never commits media or promotes it into the public gallery.

Watch the original GIF at normal timing and inspect all numbered frames. Check tube
thickness, three-lobe topology, open center, stable framing/lighting, and the
last-to-first transition. A changed-pixel count does not prove genuine object
motion. Technical checks and human aesthetic acceptance remain separate, and the
review record starts with **user acceptance pending**.

If preparation or generation fails, the artifact step still attempts to preserve
all records that exist. Artifact upload itself can fail; use the run logs if needed.
No key, raw response body, input environment or private account data is intentionally
printed or included. Never add secrets to prompts or cost-evidence files.
