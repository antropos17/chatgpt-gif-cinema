# Attachment points on existing animation clocks

Named sprite attachment points now work **without `pose_keys`**. A prop follows
its manually authored point in the drawing actually selected by the existing
native-delay sprite sampler. This avoids transcribing an imported animation into
a new pose schedule merely to keep a prop attached. It does not infer landmarks,
change character drawings, generate in-betweens, or guarantee face identity.

This extends the existing offline layered-scene renderer, not a browser editor or
the separate native camera/light shot renderer. No network or provider is used.

## Contract

Author `anchors` in every sprite frame, then use an attachment with `"anchor":
"hand"`, as described in [POSE-ANCHORS.md](POSE-ANCHORS.md). Omit `pose_keys` to
retain the existing `duration_ms` intervals and `playback` (`once` or `loop`).
`source_range_ms` remains a half-open source trim, including partial first/last
holds. Missing points fail validation; no guessed fallback is introduced.

The shared `layer_sprites.index_at` chooses both the visible drawing and its point:
- Normal sampling selects the incoming drawing at an exact source boundary.
- Diagnostic `before=True` selects the outgoing drawing without an epsilon.
- At time zero, the first included drawing is selected, never a previous loop or
  a drawing excluded by the trim.
- A positive exact loop multiple has the final included drawing on its outgoing
  side and the first included drawing on its incoming side.
- `once` holds the final included drawing after the selected interval ends.
- The clock is relative to the parent's active `in_ms`, not the child's start.

The parent raster's translation/rotation/zoom still map the authored point.
Child rotation, scale and opacity remain independent. Ordinary point attachments,
explicit pose sampling and their report shape remain unchanged.

## Important sampling boundary

Layer exports still sample at **25 or 50fps**. Source intervals are not rewritten,
but a 10ms partial hold can appear late, merge with a neighboring output hold, or
be omitted on that output grid. The existing sprite timing report lists selected,
sampled and omitted source drawings. This feature does **not** make layered output
a variable-frame-rate, native-delay-preserving master. Use the source-only master
route when preserving each original GIF interval matters more than compositing.

The sequence compiler still requires explicit pose keys. It deliberately rejects
native animation clocks rather than silently resetting them at each new shot.
Native-clock cross-shot continuation is not implemented by this change.

## Read the report as geometry, not an animation score

Named native attachments add source-clock events to attachment review, including
loop wraps, partial-trim boundaries and inherited movement in attached descendants.
Events may occur between output samples. A reported displacement is not necessarily
a visible exported jump or an error; it can be intentional action. Transform
keyframe easing and its velocity are not newly analyzed here.

There are at most 2999 unique interior native event times in a validated 30s scene.
A long nested scene may still have many per-layer events. To bound receipts:
- Every event contributes to `switch_count` and `max_switch_gap_px`.
- `switches` retains the first 2048 rows in time/layer order.
- `omitted_switch_rows` explicitly counts rows not retained.
- `worst_switch_by_layer` retains the largest event for each affected layer, even
  if it occurs late after the row limit; ties keep the earliest event.

This report is advisory and does not certify hands, contacts, continuity or
smoothness. Truncated detail must not be presented as a complete event listing.

## Reproduce the original technical proof

```sh
python tools/build_native_anchor_proof.py --out new-native-proof --render
python -m unittest discover -s tests -p test_native_pose_anchors.py -v
```

Requires Pillow; actual exports also need FFmpeg/ffprobe and PyAV for independent
MP4 frame-clock inspection. The output path must be new and non-symlink. Without
`--render`, the helper creates editable inputs, measured samples and comparison PNG.

The proof uses three original 16×16 marker drawings, delays **40/60/180ms**,
trim **[30,270)**, one 480ms loop scene at 25fps and one 480ms once scene at 50fps.
Each is exported with a chosen fixed point and a named point:
- Marker/prop-center discrepancy: **8px maximum fixed, 0px named** at output samples.
- Actor RGBA samples, source indices and sample times remain identical.
- All **72 saved PNG frames** across four exports match expected RGBA, and all
  sampled decoded GIF colors match the matte-flattened marker fixture.
- All 72 decoded MP4 frame timestamps and holds match the existing 25/50fps grid,
  including final holds. MP4 pixels are lossy, measured separately, not claimed equal.
- Inputs remain byte-identical. Transparency is retained in PNG, not GIF/MP4.

This is a small geometric fixture, not a finished cartoon or evidence of natural
hand motion. Composite prop pixels intentionally change. There is no soundtrack;
no audio behavior changes. No performance improvement is claimed.
