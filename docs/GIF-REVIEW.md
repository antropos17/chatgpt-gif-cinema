# Review every delivered GIF frame

The local review helper closes a practical gap between endpoint inspection and
accepting an animation. It extracts the **final decoded GIF**, not an earlier atlas,
and never calls a model, edits the source or marks a frame visually approved.

This helper is included in the current source-built skill 0.2.0 package, alongside
its guide and hash manifest. The older published skill-v0.1.1 ZIP does not include it.
From a checkout with the public runtime installed:

```bash
python -m pip install -e .
python .agents/skills/gif-cinema/scripts/review_gif.py extract \
  .agents/skills/gif-cinema/assets/example/shot-01.gif \
  output/review-astronaut --focus 80 60 370 330
```

Open `output/review-astronaut/index.html` locally. No server, online assets or API key
is required. The source GIF is unchanged. Its 16 decoded frames each last 160 ms,
for 2.56 seconds total. The illustrated astronaut is existing bundled footage, not
a newly generated demonstration.

## What the helper writes

- `animation.gif`: the exact source bytes, with the original loop flag and timing.
- `frames/0000.png`, etc.: every full-resolution decoded RGBA frame. Transparency
  is preserved instead of being silently flattened onto a black background.
- `focus/0000.png`, etc.: optional full-resolution crops for a face, hand or prop.
  The box is `left top right bottom`, in source pixels. Choose it per source.
- `sheets/000.png`, etc.: numbered **thumbnail** sheets, at most 16 frames each.
  The bounded sheets help navigation; they do not replace native-size inspection.
- `index.html`: the actual GIF alongside a paused-by-default frame player. Step
  backward/forward, view native pixels, use light/dark/checkerboard backgrounds,
  and play frames with the decoded delays. Preview looping is an explicit control.
- `audit.json`: actual timing, dimensions, loop flag, source/artifact hashes,
  technical findings and transition pixel differences, including the last/first seam.
- `review.json`: a pending, editable human review record bound to this audit and GIF.

The frame player can stop after one pass, even when the source GIF loops. Manual
stepping wraps around for seam inspection. Browser GIF behavior and timer precision
vary; the helper does not claim platform-specific playback compatibility.

## Two technical profiles

The default `--purpose general` supports opaque images, full-bleed posters and
play-once story shots. It does **not** impose transparent-sticker requirements.

Use `--purpose sticker` only when a transparent looping sticker is the intended
output. That profile additionally checks an infinite loop, transparent and opaque
pixels, and clear alpha margins in every decoded frame. Profile failures still
produce the diagnostic pack, but `extract` returns a nonzero status. They never
change or resize the delivered GIF automatically.

Input limits are 32 MiB, 512 frames, a fixed canvas, the runtime's 16-megapixel
per-frame limit, and 64 megapixels of total decoded frames. Output is bounded to
512 MiB. Oversized or malformed inputs fail rather than being silently truncated.
The raw GIF descriptor scan runs before image decoding. Inputs must be ordinary
local files; FIFOs and devices are rejected. Each extraction requires a new output
directory, so repairs cannot overwrite an earlier review or retain stale approval.
Reads explicitly use binary mode on Windows; newline and control bytes remain exact.

If extraction fails after creating its directory, the partial output is retained.
It is not a completed review pack: `check` rejects missing or mismatched audit,
review or artifact files. Retry into a **new** directory after resolving the cause.
The helper never recursively deletes failed output, since another process could
have renamed the original directory and replaced its path with unrelated data.
It also checks the created output and child directories' identities before
subsequent writes and after export, and refuses unexpectedly existing child
directories instead of adopting them. These checks detect ordinary directory replacement; they are not a sandbox
against a hostile process racing every filesystem operation. Existing filenames
are opened exclusively and never overwritten.

## Complete the record after actual inspection

1. Inspect every native frame, especially identity, mouth/eyes, hand construction,
   held objects, contact, clothing and clipped edges. Note both a bad frame and the
   transitions entering/leaving it.
2. Watch the actual GIF at its normal cadence. Step through the last/first seam.
   High playback FPS, many distinct frames and small pixel differences do not
   establish coherent movement or a stable character.
3. Edit `review.json`: identify `reviewer`; set each frame's `decision` to `pass` or
   `repair`; describe issues in `notes`; explicitly record `playback` and
   `loop_seam` as `pass` only after inspecting them. Leave anything unwatched pending.
4. Keep `user_acceptance` as `pending` unless the user accepted or rejected these
   exact bytes. The checker does not authenticate that statement or obtain approval.
5. Check the recorded review against the current deliverable:

```bash
python .agents/skills/gif-cinema/scripts/review_gif.py check \
  output/review-astronaut \
  --gif .agents/skills/gif-cinema/assets/example/shot-01.gif
```

The command initially fails because the template is deliberately pending. After a
complete recorded review it prints `visual_review_record: complete`, the reviewer's
name, and the separate user-acceptance record. A rejected user-acceptance record
remains rejected even if all frames were inspected.

`check` recomputes media facts, checks the original or copied GIF hash, checks every
extracted artifact, and requires exactly one passed entry per frame. Changed GIFs,
frames, focus crops, HTML or sheets invalidate the pack. Changed audit JSON also
invalidates its review binding. Hashes detect revision mismatch; they are not a
cryptographic signature proving who watched the file or whether the judgment was
correct. Do not write approvals mechanically from the metrics.

For a repair, keep the old pack, correct the source and extract into a new directory.
No automatic image repair, optical flow, hidden face replacement, retiming or new
character poses are supplied by this helper.

## Method provenance

The workflow was informed by GIF Factory's public [stability guide](https://github.com/WoYun520/gif-factory/blob/main/references/stability.md)
and [GIF reviewer](https://github.com/WoYun520/gif-factory/blob/main/scripts/review_gif.py).
This helper is an independent implementation using GIF Cinema's bounded decoder
preflight, portable local outputs and explicit review records. No upstream sample
art, character IP, captions, music, fonts or generated poses are redistributed.
