# Offline GIF factory

Build a named collection from **existing GIFs and editable GIF Cinema layer scenes**
with one manifest. The result is a static offline gallery, verified final GIFs,
still/sample previews made from those GIFs, and a portable ZIP.

No JavaScript animation, model/API call, remote asset, prompt execution or Blender
installation is involved. A Blender-produced GIF is accepted like any other existing
GIF; rendering `.blend` files remains a separate production step.

This is the first bounded batch-delivery route, not complete GIF Factory parity.
It does not generate artwork, new poses, background removal, motion interpolation,
lenticular transitions, sound, video reels or automatically approved animation.

## Run the complete repository example

Install the **current checkout**, then run from its root:

```bash
python -m pip install -e .
python -m gif_cinema factory build factory.example.json --out output/my-collection --dry-run
python -m gif_cinema factory build factory.example.json --out output/my-collection
python -m gif_cinema factory verify output/my-collection
```

The example copies the existing archived Chrome Trefoil GIF and renders the existing
stroke scene. It is a functional mixed-input check, not two newly commissioned
artworks. `factory.example.json` pins their exact source bytes.

Open `output/my-collection/index.html` in a browser, or unzip
`output/my-collection/collection.zip` and open `collection/index.html`.
The gallery has no scripts, server dependency or remote fonts/assets. Its GIFs play
natively; a reduced-motion preference selects a single-frame PNG instead. Individual
GIFs and previews have local links. The ZIP intentionally does not contain itself
or a broken link to another archive.

Only Python 3.10+ and Pillow 10.1+ are needed for existing-GIF collections. Scene
entries also use the existing layer renderer, so FFmpeg and ffprobe must be installed.
`python -m gif_cinema.factory build ...` is an equivalent module entry point.
The maintained source skill package 0.4.0 pins a runtime with this command and bundles
a smaller two-entry example plus `smoke_factory.py`. Generate its ZIP with
`python tools/package_skill.py --out dist/gif-cinema.skill.zip`. The older GitHub
Release `skill-v0.1.1` and previous source package 0.3.1 do not contain this installed
workflow. Generating a source package does not publish a new GitHub Release.

## Manifest contract

Use UTF-8 JSON with no duplicate keys. Relative paths start at the manifest's
folder, so put the manifest above all its inputs. JSON is data, never code.

```json
{
  "format": "gif-cinema-factory",
  "schema_version": 1,
  "title": "Form studies",
  "items": [
    {
      "id": "copper-form",
      "title": "Copper form",
      "group": "Blender studies",
      "caption": "A reviewed local Blender render.",
      "gif": "renders/copper-form.gif",
      "sha256": "REPLACE_WITH_THE_ACTUAL_LOWERCASE_SHA256"
    },
    {
      "id": "draw-on",
      "title": "Draw-on lettering",
      "group": "Editable graphics",
      "caption": "An authored local stroke scene.",
      "scene": "scenes/draw-on.json",
      "sha256": "REPLACE_WITH_THE_ACTUAL_LOWERCASE_SHA256"
    }
  ]
}
```

The placeholder hashes are intentionally invalid. Compute the digest of each exact
input file after choosing/reviewing it, for example:

```bash
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('renders/copper-form.gif').read_bytes()).hexdigest())"
```

- Supply 1–12 items. IDs are unique lowercase ASCII slugs beginning with a letter,
  at most 40 characters. Windows device names such as `con` and `com1` are rejected.
- Each item needs `id`, `title`, `sha256` and exactly one of `gif` or `scene`.
  `group` and `caption` are optional plain text, displayed in the gallery. They
  do **not** burn captions into an imported GIF or imply completed visual review.
- Titles are at most 120 characters, groups 80 and captions 500, without controls
  or newlines. Unknown fields fail. HTML-looking text is escaped, not interpreted.
- Paths cannot be absolute, URLs, symlinks, parent traversals, dot segments or use
  backslashes. Scene dependencies must remain inside the scene folder and follow
  the existing [layer schema](MULTILAYER-POC.md). Factory scene inputs reject symlinks.
- A scene hash pins its JSON. Its dependency hashes are recorded during preflight,
  checked again, and snapshotted before rendering. The factory does not edit inputs.
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
