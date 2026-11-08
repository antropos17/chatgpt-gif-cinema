# Story project helper

`python scripts/story_project.py compile STORY.json --out NEW_DIRECTORY [--font FONT]`

Compile is entirely offline: it validates the author-written storyboard, copies
existing inputs, creates local title GIFs, and writes strict runtime inputs. It does
not invent story beats, call a model, choose takes, or claim visual acceptance.
The agent writes the storyboard with the user's brief and source review.

## Storyboard schema 1

Top level:

- Required: `schema_version: 1`, nonempty `title`, `premise`, `ending`, `style_bible`,
  and ordered `shots` (1–64).
- Optional: even `width`/`height` (64–1280, default 512); `fps` (1–60, default 25).
  The reduced aspect ratio's terms must fit 1–99, as required by the runtime.
- Optional `characters` and `props`: up to 32 objects each with unique `id`,
  `description`, and optional `initial_state`. Identity descriptions enter the
  shared prompt bible. Track each later state in individual shots.

Each shot has a case-insensitive unique ASCII `id` (letters/digits/underscore/hyphen,
maximum 40 characters, first character alphanumeric), plus required `beat`, `action`,
`start`, `end`, `camera`. Optional `state` tracks props and contacts. Optional `caption`
becomes a separate SRT subtitle, not burned-in typography. All text is nonempty and
limited to 4,000 characters unless a narrower title limit applies. Unknown fields
fail explicitly.

Choose exactly one asset mode:

1. `source: "relative/path.gif"`: original delays and bytes are preserved. Inputs
   resolve relative to the storyboard, not the shell working directory. The same
   source can recur deliberately, but the report warns about duplicate hashes.
2. `generate: {"frames": 16, "duration_ms": 160}`: prepares an unexecuted one-shot
   runtime script. Optional `model`, `size`, `quality`, `complexity`, `references`
   follow the runtime's strict contract. Reference paths must already exist and are
   copied into the project. The action/camera/state text becomes the shot prompt.
3. `title: {"text": "A REPLY FROM THE STARS", "subtitle": "A short exchange",
   "duration_ms": 2000}`: local once-only sliding text/expanding accent rule, then hold.
   Optional `background`, `foreground`, `accent` are Pillow color strings. Text limits
   are 100/140 characters; an overlong line fails instead of being silently clipped.
   Duration is 800–6000 ms in 100 ms increments. Use `--font` for a local licensed font.
   Text is not automatically translated or wrapped; check requested-language glyphs.
   If no DejaVu Sans is available, the helper uses Pillow’s built-in font. Pillow
   10.0 has a fixed-size bitmap fallback, so provide `--font` for larger/readable
   type in that environment; no system font is required merely to run the helper.

## Output and timing

- `storyboard.original.json`: original editable planning document. Its original input
  paths remain provenance, not guaranteed portable dependencies. Recompile it where
  those inputs are available or update its paths to the copied media.
- `storyboard.md`: readable bible, shot actions and handoffs.
- `media/`: copied source GIFs and locally rendered title cards.
- `references/` and `generation/`: copied stills and validated one-shot API inputs.
- `film.json`: executable only when every shot has local media.
- `assembly-template.json`: created instead when any shot still needs generation;
  `accepted/ID.gif` deliberately marks the absent assets. Do not execute it until
  real accepted GIFs exist. Prefer updating the storyboard and recompiling.
- `story-report.json`: source timings, drawing counts, source checksums, missing-shot
  request count, planned quantized timeline, repetition warnings and review status.

A generated shot's time is a target; source/title time is measured. Per-shot MP4 time
is `max(1, round(seconds * fps)) / fps`, matching the runtime's frame rounding. Title
holds can collapse to fewer encoded GIF frames while preserving delay sums. They
remain title motion, not extra character poses. Shared inputs are capped at 512 MiB;
individual GIFs use the runtime's ingestion limits. A title uses at most 32 megapixels
across drawings. For high-resolution cards, shorten the hold or compose separately.

## Assemble and export

```bash
python -m gif_cinema render PROJECT/film.json --dry-run --max-api-calls 0
python -m gif_cinema render PROJECT/film.json --execute --max-api-calls 0 --out RENDER
python scripts/story_project.py export-gif RENDER/film.mp4 --out story.gif --width 320 --fps 10
```

The export helper uses FFmpeg palette generation/quantization and decodes the actual
GIF before publishing it without overwriting. Width is 64–640; FPS is 5, 10, 20 or 25
for exact centisecond timing. It preserves aspect ratio with even height, removes
sound, and defaults to no loop extension. `--repeat` uses an infinite loop. It checks
actual timing against the MP4 within one GIF frame and applies runtime frame/pixel
limits. It does not promise platform-specific compatibility or a particular file size.

Use a local verified MP4. Export is bounded to 300 seconds per media subprocess.
If an export fails, no previous accepted file is replaced. For long/high-resolution
stories use a smaller GIF, lower supported FPS, or chapters plus the MP4 master.
