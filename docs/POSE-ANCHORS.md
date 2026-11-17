# Authored landmarks that follow sprite poses

This backend feature adds reusable, per-drawing attachment points to the existing
layer/sequence renderer. A prop can follow an explicitly selected hand drawing
without repeating a fixed-point schedule in every shot. It is not hand tracking,
face lock, a skeleton solver, drawing generation or automatic contact acceptance.
The separate native camera/light shot-project renderer is not extended by this MVP.

## Author one point for each existing drawing

Sprite frames may optionally contain `anchors`, a map of 1–32 named normalized
points. Coordinates refer to the original drawing rectangle, not the atlas or
whole stage. The renderer maps them through the **actual fitted raster** and parent
translation, rotation and zoom. Names are case-sensitive ASCII identifiers of
1–40 letters, digits, underscores or hyphens. Coordinates must be finite numbers
between 0 and 1; booleans are not accepted.

```json
{
  "frames": [
    {"rect": [0, 0, 16, 16], "duration_ms": 40,
     "anchors": {"hand": [0.25, 0.5]}},
    {"rect": [16, 0, 16, 16], "duration_ms": 120,
     "anchors": {"hand": [0.75, 0.5]}}
  ],
  "pose_keys": [
    {"at": 0, "frame": 0},
    {"at": 0.5, "frame": 1},
    {"at": 1, "frame": 1}
  ]
}
```

A child's attachment segment selects either a named `anchor` **or** the existing
fixed `point`, never both:

```json
{"start_ms": 0, "end_ms": 800, "parent": "carrier", "anchor": "hand"}
```

The parent must be a sprite layer. **Explicit `pose_keys`** use the authored pose
clock described here. Native source-delay, trim and loop playback are now supported
in standalone layered scenes; see [NATIVE-ANCHORS.md](NATIVE-ANCHORS.md). Native GIF
layers have no per-drawing landmark metadata and remain unsupported as named parents. Each parent drawing, including unselected and conceptual endpoint drawings,
must declare the requested name. Missing or malformed landmarks fail validation
before asset loading; there is no fallback to a guessed center or old point.
Ordinary fixed-point bindings remain valid and unchanged.

Sprite pack/slice/import does not infer or import these landmarks. Add them to the
editable scene's frame records after inspecting the original drawings. Metadata
alone does not prove the points coincide with depicted hands. Coordinates use the
existing continuous raster-boundary convention: e.g. the center of pixel x is
`(x + 0.5) / width`, while the center of a two-pixel marker straddling x is `x / width`.
The child's own anchor is positioned at the resolved target; its rotation, scale
and opacity are **not** inherited, as with existing point attachments.

## One pose clock, explicit sides of a boundary

Named points and visible sprite drawings share `layer_sprites.index_at`, which
delegates to `pose_tracks.index_at` for explicit poses. At an exact pose key, normal rendering selects the incoming drawing.
Handoff review uses `before=True` to select the outgoing drawing with `bisect_left`,
not a floating-point epsilon. The clock is relative to the parent's `in_ms`.

At `at=1`, the conceptual closing pose is used to carry state into the next scene.
It is not an extra exported sample. The last stored frame can differ from that
endpoint; inspect the existing LAST STORED / CARRIED ENDPOINT / NEXT FIRST join.
This feature does not invent missing in-between drawings or smooth a pose jump.

Sequence compilation already carries transforms, selected source drawing and
attachment state. Named bindings use that mechanism without a second compositor.
A holder change at a scene boundary is accepted only when carried world coordinates
match; implicit positional/drawing resets are still rejected. Resolved metadata is
inside `state.attachment` (`anchor`, selected parent `source_index`, resolved `point`).

## Review remains advisory

Named-anchor review includes interior parent pose changes, not only holder changes,
and propagates displacement to attached descendants. It distinguishes a semantic
holder/anchor switch from a point moving because its drawing changed. A displacement
can be the intended action, not an error. Ordinary point-only reports stay unchanged.
Conceptual closing pose changes are left to the sequence join, not counted as an
extra exported transition. Status remains `human-review-required`.

## Reproducible geometric proof

```bash
python tools/build_pose_anchor_proof.py --out new-anchor-proof --render
```

Requires the current runtime, Pillow, FFmpeg/ffprobe and the `lossless` extra.
Without `--render`, it still creates original tiny marker artwork, editable inputs,
the comparison PNG and per-sample geometry measurements. It uses no API/provider.
Use a new output directory. `--shot-ms` accepts 80–2000 in 80ms units.

The default proof is **two 800ms scenes, 40 output samples at 25fps**. It compares
one chosen pair of legacy fixed-point bindings against authored per-pose points:
- Maximum marker/prop-center discrepancy: **8px fixed → 0px named**.
- Original actor RGBA samples, source drawing choices and sample times are identical.
- Both FFV1 masters reopen with zero RGBA/PTS/hold mismatches and zero decoded prop
  center mismatches, including the final 40ms hold.
- Every input's bytes/hash remain unchanged through export and verification.

This is a technical marker fixture, not a finished cartoon. Geometry is measured
from actual original marker pixels and rendered prop pixels at native size. It
does not prove contact under arbitrary filtering/rotation, recognizable characters,
natural motion or narrative quality. A manually authored fixed-point schedule could
also follow each pose; the feature removes that repeated schedule bookkeeping.
`pose_keys` already overrides native source-delay playback. This feature preserves
the authored comparison's timing, not an unrequested reinterpretation of those delays.
There is no soundtrack in this proof and no audio behavior change.

The 19 new tests cover validation limits, missing/unused landmarks, point/name XOR,
non-sprite parent rejection, cycles/visibility, source clocks, 25/50fps boundaries,
rotation/zoom/fit, nested attachments, paint order, outgoing pose and closing endpoint,
sequence handoff/carry, portable save/reopen, source preservation and real master
export. Run them with `python -m unittest discover -s tests -p test_pose_anchors.py -v`.
