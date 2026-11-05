# Creating short films from GPT-generated GIFs

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
