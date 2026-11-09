---
name: native-motion-gif
description: Prepare six art-directed abstract native GIF loop presets for direct OpenAI API use and inspect actual returned GIFs, without a 3D renderer or video conversion.
---
# Native motion GIFs

Use an installed checkout of GIF Cinema containing `gif_cinema.motion` (Python 3.10+
and Pillow). Run `python -m gif_cinema motion --help` to verify the runtime. No API
key or FFmpeg is needed for preparation or inspection. Keep the source license.

1. Choose a preset with `python -m gif_cinema motion list`, or prepare all six.
2. The sole route is `openai-direct-16`: the existing direct OpenAI API adapter,
   requesting 16 frames at 200 ms. Check actual model/account access separately.
   Do not invent endpoints, increase limits without evidence, or add third-party services.
3. Compile into a NEW project folder:
   `python -m gif_cinema motion compile --out output/motion-plan`
   `--route openai-direct-16` is optional. Preserve exact request files and manifest.
   These are unrendered plans, not GIFs. Opaque background is a local artifact
   acceptance requirement, not an unsupported API parameter.
4. Paid execution is separate and needs authorization, API access via an environment
   `OPENAI_API_KEY`, and a bounded budget. Never print or save the key. Start with
   one pilot using the generated single-shot film script with existing
   `render --execute --max-api-calls 1 --retries 0`; never bypass pending/unknown
   status or resubmit an uncertain request. Keep the runtime's receipt.
   In ChatGPT, native GIF generation is an alternative only if the current chat
   actually exposes that capability; do not promise it from prompt text alone.
5. Preserve the actual returned native GIF bytes. Inspect with:
   `python -m gif_cinema motion inspect actual.gif --request output/motion-plan/chrome-trefoil.request.json --out output/chrome-review`
6. Review the GIF in motion, plus first/last images and the phase contact sheet.
   Check geometry, overlap, clipped highlights, material stability, genuine rigid-object
   motion or deformation and wraparound cadence. Pixel differences and distinct frames
   cannot prove quality, seamlessness, provenance or absence of camera-only motion.
   Record acceptance separately. Deliver actual GIFs, not just these plans.

Do not substitute Blender, video-to-GIF conversion, a still-image pan or reverse
playback for requested native generation. Verify actual returned frame count and
delays before claiming them. Inspection checks every composited frame's dimensions
and actual RGBA transparency while preserving shared decoder safety limits.
See `docs/NATIVE-MOTION.md` for complete commands and provenance limits.
