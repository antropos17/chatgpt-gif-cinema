# Creating short films from GPT-generated GIFs

New here? Follow [Getting started](GETTING-STARTED.md) for installation, a zero-call
film export, and a bounded first OpenAI GIF request.

For practical advice on framing, native motion, references and retakes, read
[Tips: make short GIFs feel like a scene](TIPS.md).

For the implemented script pipeline and zero-call demonstration, see
[Script format](SCRIPT-FORMAT.md). Begin with `render --dry-run`, then use the
existing-asset example with `--execute --max-api-calls 0`. The output includes a
manifest, first/last frames, a contact sheet and a continuity review report.

## Five production passes

1. **Script**: establish one story beat per short shot, consistent camera direction, scale, light and character props. Use explicit shot IDs and timestamps.
2. **Generate**: prefer one principal motion per GIF. Store prompt, model, frame count, frame duration, seed if supported, output dimensions and API usage. Do not assume deterministic character matching across GIF calls.
3. **Inspect**: export the first and last frame. Verify geography, eyelines, framing, character consistency, pose, color and action direction. Pixel difference scores catch discontinuities, not story logic.
4. **Edit**: hard cuts are appropriate when narrative grammar allows; for smooth motion use deliberate continuity or cutaways. Avoid automatically dissolving incompatible action.
5. **Finish**: normalize frame timing, crop/pad safely for the final aspect ratio, assemble in H.264 MP4, add original/licensed sound, review captions and loudness.

## Important GIF limitations

Animated GIFs contain no audio. Frame durations are variable, and duplicate frames can cause jerks. The generation API may reject dimensions, animation length or access. Interpolation can create artifacts. Last-to-first-frame image matching does not prove correct identity or action continuity.

## Honest validation protocol

An offline mocked test verifies request shape and decoding but **not model access or render quality**. A live end-to-end verification requires a successful OpenAI API call, inspecting actual GIF frames, and playing the final MP4.

## Output safety and offline checks

The generator decodes every GIF frame and requires at least two frames with
positive supported delays before reporting success. Use a new output path by
default. `generate --resume` reuses only matching parameters and checksum-verified
GIFs; `--force` authorizes a new paid render. Do not run concurrent jobs against
the same output path. A process lock rejects this and must only be removed after
confirming the original process has stopped.

Film export preserves existing output until FFmpeg succeeds. Short audio is padded
with silence; long audio ends with the video. Montage tests verify total decoded
frame count and the final shot's last color using synthetic GIFs with unequal frame
delays. Such tests establish timing behavior, not artistic quality.

Live API and demo publishing workflows are manual. Ordinary pushes and pull
requests run offline checks only. The committed demo can be inspected and encoded
locally without an API key. Do not infer universal API availability from a prior
successful run. GIF limits currently differ between the OpenAI guide and endpoint
reference; the client retains the conservative 2..16 frame range.
