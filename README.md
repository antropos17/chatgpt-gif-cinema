# GIF Cinema

**Turn existing GIFs into a film. Inspect every cut.**

A local workshop for **Codex and Claude Code**. No API key needed for the bundled demo.

[Try it](#make-your-first-film) · [Exact-frame master](docs/GIF-MASTER.md) · [Agent skill](#install-the-skill) · [100-character grid](#anime-pixel-art) · [Workflows](#choose-a-workflow)

<a href="docs/EXAMPLES.md#2-titled-story-a-small-gif-to-share"><picture><img src="docs/assets/example-gallery/titled-story.gif" width="300" alt="A Reply from the Stars: a local title and three existing astronaut takes, played once."></picture></a>

**Three takes + a title.** A 9.70-second example, not proof of perfect continuity.
[Sources & recipe](docs/EXAMPLES.md)

<a id="try-it-without-an-api-key"></a>

## Make your first film

**Three bundled GIFs → a 7.68-second MP4. No key, no paid requests.**

You need Python 3.10+, Git, FFmpeg and ffprobe. Pillow installs with the package.

```bash
git clone https://github.com/antropos17/chatgpt-gif-cinema.git
cd chatgpt-gif-cinema
python -m venv .venv
```

Activate with `source .venv/bin/activate` on macOS/Linux, or
`.\.venv\Scripts\Activate.ps1` in Windows PowerShell. Then:

```bash
python -m pip install .
python -m gif_cinema doctor
python -m gif_cinema render examples/film.json --dry-run --max-api-calls 0
python -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/my-first-film
```

Open **`output/my-first-film/film.mp4`**. The folder also includes a contact sheet,
cut endpoints and a resumable manifest. Repeat the last command to verify reuse
with zero new provider calls. [What this example preserves](docs/EXAMPLES.md#1-plain-film-preserve-the-source-timing).

Need exact decoded drawings and native GIF holds? Use the optional
[lossless film master](docs/GIF-MASTER.md). Ordinary MP4 export is a fixed-FPS,
lossy viewing format.

<a id="give-the-skill-to-your-agent"></a>
<a id="copy-a-prompt"></a>

## Install the skill

Build the maintained **0.4.1 skill package** from this checkout:

```bash
python tools/package_skill.py --out dist/gif-cinema.skill.zip
```

Extract its single `gif-cinema` folder into:

- **Codex:** `~/.codex/skills/gif-cinema`
- **Claude Code:** `~/.claude/skills/gif-cinema`

Follow [the included installation check](.agents/skills/gif-cinema/SKILL.md#runtime-and-a-no-key-check)
to install and verify its pinned Python runtime separately. The older `skill-v0.1.1`
GitHub Release is not this package.

Try this with your agent:

> Use the gif-cinema skill to assemble the included astronaut story with zero API calls. Return the MP4, a small GIF, the editable project and a review of both cuts.

## Anime pixel art

Already tried the film? Explore the full cast below, or [browse methods and recipes](docs/GALLERY.md).
The full grid stays on this page by design; animated media across the README totals about **93 MB**.
On a slow connection, jump straight to [setup](#make-your-first-film) or open a character’s **Still** link.


**100 characters · 3 outfit studies · real GIF previews**

Short 1.44–1.92 s character studies, not finished 15-second scenes. Click to watch; “Method & limits” explains the remaining drift.

<table>
<tr>
<td align="center" valign="top" width="33.33%">
<a href="examples/anime-pixel/character-previews/fox-knight.gif"><picture><source media="(prefers-reduced-motion: reduce)" srcset="examples/anime-pixel/character-previews/frames/fox-knight/00.png"><img src="examples/anime-pixel/character-previews/fox-knight.gif" width="100%" alt="Fox knight · shield salute: drawn poses."></picture></a><br>
<strong>001 · Fox knight</strong><br>
<sub>shield salute · 1.92 s</sub><br>
<sub><a href="examples/anime-pixel/character-previews/README.md" title="Generated-pose preview; face/outline drift.">Method &amp; limits</a> · <a href="examples/anime-pixel/character-previews/frames/fox-knight/00.png">Still</a></sub>
</td>
<td align="center" valign="top" width="33.33%">
<a href="examples/anime-pixel/character-previews/dragon-chef.gif"><picture><source media="(prefers-reduced-motion: reduce)" srcset="examples/anime-pixel/character-previews/frames/dragon-chef/00.png"><img src="examples/anime-pixel/character-previews/dragon-chef.gif" width="100%" alt="Dragon chef · offering basket: drawn poses."></picture></a><br>
<strong>002 · Dragon chef</strong><br>
<sub>offering basket · 1.92 s</sub><br>
<sub><a href="examples/anime-pixel/character-previews/README.md" title="Generated-pose preview; face/outline drift.">Method &amp; limits</a> · <a href="examples/anime-pixel/character-previews/frames/dragon-chef/00.png">Still</a></sub>
</td>
<td align="center" valign="top" width="33.33%">
<a href="examples/anime-pixel/character-previews-batch2…32658 tokens truncated…shotted before rendering. The factory does not edit inputs.
- Identical decoded drawings/timing/loop records cannot be counted as two entries,
  even under different names. This catches exact duplicates, not semantic similarity.

## What gets verified

Dry-run reads and fully decodes GIF inputs, validates scenes/assets and output
budgets, and reports the plan. It creates no output and starts no media subprocess.
A planned scene is not a rendered GIF; actual output verification happens on build.

Build copies accepted GIF bytes unchanged. Layer scenes are snapshotted and rendered
by the existing compositor. The factory then independently decodes **each final GIF**
with a fixed canvas and bounded frames/pixels, measures native delays and loop metadata,
and records per-frame RGBA hashes. It does not replace drawing count with a claimed FPS.

Every card has:

- Its delivered GIF, with original bytes retained for imported entries.
- A transparent PNG poster from the actual drawing at half of the GIF duration.
- A five-column PNG sheet sampled by elapsed time, including the first and last
  drawing. Labels are `frame index / time in ms`; repeated samples are possible
  when a long hold spans several sample points.
- Dimensions, drawing count, measured duration, loop metadata, provenance and hashes.
  A one-state GIF is labeled as such, not presented as newly animated work.

The ZIP has a single `collection/` root, a fixed timestamp, stored members and an
explicit allowlist. Every member is read back and hashed. No path from an archive is
extracted during verification. The gallery contains only generated local paths and
escaped text, with a restrictive content-security policy.

`factory verify` rechecks file hashes, every GIF drawing/timing value, regenerated
preview pixels, static PNG frame count, safe gallery HTML and exact archive members.
It rejects animated PNG substitutions and HTML/script replacements even if someone
updates their checksum records. Numeric sheet labels do not rely on a system/default
font. Preview resampling and layer rendering can still depend on Pillow versions;
keep the tested environment for reproducible rebuilds. ZIP bytes are deterministic
for the same generated files, not a promise of identical rendering on every machine.

Receipts are **not cryptographic signatures** or proof of artistic acceptance.
A person who controls the files can create a different self-consistent collection.
Visual review and user acceptance always remain `pending`; native playback must be
inspected for timing, typography, artifacts, contacts and loop quality.

## Files and limits

The output directory must be new. All rendering, preview generation and ZIP checks
finish in staging first. Publication claims the directory exclusively and uses
no-clobber file publication; `catalog.json` is the completion marker and is written
last. Failed checks do not publish a candidate. A publication I/O failure rolls back
files created by that run without touching a previously existing collection.

```text
my-collection/
  index.html
  catalog.json
  collection.zip
  gifs/<id>.gif
  previews/<id>-poster.png
  previews/<id>-sheet.png
```

- Manifest: 128 KiB; generated catalog: 2 MiB; 12 entries maximum.
- Per GIF: 32 MiB, 512 drawings, 64 Mi decoded pixels, fixed canvas, at most 120 s.
  Each frame delay is 20–60,000 ms. One-state GIFs are permitted and labeled honestly.
- Batch: 128 MiB of source bytes, including scene dependencies; 256 Mi decoded
  pixel-frames of planned work. Repeated dependencies count toward each entry.
- Delivered files: 256 MiB plus the bounded catalog. The stored ZIP takes approximately
  the same disk space again. Scene intermediates need additional temporary space and
  are removed after each item; they are not part of the delivery ZIP.
- Scene frames/pixels must fit the factory review limits, even when the standalone
  compositor accepts a larger scene. All existing renderer limits and subprocess
  timeouts still apply.

A lower output resolution or smaller batch is the next step when a budget is exceeded.
The factory does not silently resize, shorten or skip a requested entry.

## Scope and rights

This implementation is original and reuses GIF Cinema's existing readers/compositor.
No GIF Factory code, fonts or artwork are imported. Existing project licensing is
unchanged. Verify your rights to every input before sharing a generated collection;
the software does not grant rights to characters, third-party art or fonts. Captions
and source-derived metadata can be private too. Building a package does not upload it.
