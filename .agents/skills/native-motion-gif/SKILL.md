---
name: native-motion-gif
description: Prepare six art-directed abstract native GIF loop presets and inspect actual returned GIFs, without a 3D renderer or video conversion.
---
# Native motion GIFs

Use an installed checkout of GIF Cinema containing `gif_cinema.motion` (Python 3.10+
and Pillow). Run `python -m gif_cinema motion --help` to verify the runtime. No API
key or FFmpeg is needed for preparation or inspection. Keep the source license.

1. Choose a preset with `python -m gif_cinema motion list`, or prepare all six.
2. Choose a real route, do not invent endpoints or copy provider limits across APIs:
   - `openai-direct-16`: existing GIF Cinema direct adapter, 16 frames at 200 ms.
     Actual model/account access must be checked separately.
   - `higgsfield-tool-64`: installed Higgsfield tool, 64 frames at 50 ms. Recheck
     `higgsfield.generate_image` schema, preferences and live price before execution.
     This tool configuration is not evidence of direct OpenAI 64-frame support.
3. Compile into a NEW project folder:
   `python -m gif_cinema motion compile --route higgsfield-tool-64 --out output/motion-plan`
   Preserve the exact request files and manifest. They are unrendered plans, not GIFs.
4. Paid execution is separate and needs authorization and a bounded budget. Start
   with one pilot. For Higgsfield, use a request's exact `tool_arguments` with the
   named installed tool. Save the returned job ID before waiting; do not resubmit
   an uncertain job. This package intentionally has no Higgsfield HTTP client.
   For the direct route use the generated single-shot film script with existing
   `render --execute --max-api-calls 1 --retries 0`; never bypass its pending status.
5. Download the actual GIF through the provider's supported artifact mechanism.
   Preserve original bytes and the provider job/receipt alongside the request.
   Inspect it with:
   `python -m gif_cinema motion inspect actual.gif --request output/motion-plan/chrome-trefoil.request.json --out output/chrome-review`
6. Review the GIF in motion, plus first/last images and the phase contact sheet.
   Check geometry, overlap, clipped highlights, material stability, genuine rigid-object motion or
   deformation and the wraparound cadence. Low pixel difference and distinct frames
   cannot prove quality, seamlessness, provenance or absence of camera-only motion.
   Record acceptance separately. Deliver actual GIFs, not just these plans.

Do not substitute Blender, video-to-GIF conversion, a still-image pan or reverse
playback for requested native generation. Do not claim a smooth 64-frame output
until the returned file actually decodes to that count and timing. Both profiles
request 3.2 seconds but have different temporal sampling. See
`docs/NATIVE-MOTION.md` for complete commands and provenance limits.
