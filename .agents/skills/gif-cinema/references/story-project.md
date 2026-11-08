# Story project helper

`python scripts/story_project.py compile STORY.json --out NEW_DIRECTORY [--font FONT] [--takes TAKES.json]`

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
   Optional `source_sha256` pins the exact bytes; mismatches fail before publication.
   Compiled portable storyboards include this pin for every copied/rendered source.
   A source hash is invalid on a `generate` or `title` shot.
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

## Select reviewed takes

After inspecting character identity, the visible action and both neighboring joins,
write a UTF-8 JSON manifest (maximum 1 MiB). It records the caller's selection, not
an automatic visual verdict. For example:

```json
{
  "schema_version": 1,
  "takes": [
    {
      "shot_id": "01-signal",
      "source": "takes/signal-take-02.gif",
      "sha256": "REPLACE_WITH_THE_ACTUAL_64_CHARACTER_LOWERCASE_SHA256",
      "review_notes": "Describe identity, action, incoming and outgoing cut review, and any remaining faults."
    }
  ]
}
```

The placeholder hash above is deliberately invalid. Calculate the actual file hash
only after reviewing that file. `shot_id` must exactly match a generated slot;
unknown or duplicate IDs fail, including case-only duplicates. `source` resolves
relative to the manifest, independently of the storyboard's location. `sha256`
contains 64 lowercase hexadecimal characters. `review_notes` is required nonempty
text, at most 4,000 characters. Unknown fields fail. Supply 1–64 selections.

```bash
python scripts/story_project.py compile story.json --takes takes.json --out output/selected-v1
```

The helper reads the GIF once into a bounded buffer and hashes, validates and copies
those same bytes. It never chooses candidates, generates shots or spends API calls.
A duration mismatch produces a warning and uses measured timing, not the request's
target. Repeated footage is still flagged; selection does not create a new action.
Existing `source` and `title` shots cannot be replaced through the manifest.

Partial selection is supported. Continue with the **portable** storyboard and a
manifest containing only the next missing shots:

```bash
python scripts/story_project.py compile output/selected-v1/storyboard.json \
  --takes next-takes.json --out output/selected-v2
```

The previous project and original media remain unchanged. The whole project folder
can move before this step: media and remaining references use project-relative
paths. Previously compiled titles are now pinned source GIFs, so continuing a project
does not redraw typography or need its original font. Their editable title settings
remain in the earlier `storyboard.original.json`. Keep previous project versions for
their original prompts and selection receipts; those records are not merged into a
cumulative audit history. Editing a pinned source requires a deliberate new storyboard
and another review, not silently changing the copied file.

Try the full selection workflow without generating anything:

```bash
python scripts/story_project.py compile assets/example/storyboard.pending.json \
  --takes assets/example/takes.example.json --out output/selected-example
python -m gif_cinema render output/selected-example/film.json --execute \
  --max-api-calls 0 --out output/selected-render
```

This maps the **same three bundled astronaut GIFs** into pending slots and adds the
existing local title. It is the same 9.68-second source edit, not new character
animation or a rendered version of the separate 14-action long-story plan. The
example review notes explicitly record a technical workflow check, not visual approval.

## Output and timing

- `storyboard.json`: portable continuation document. Source paths and remaining
  reference paths point into this project. Rendered titles and selected takes become
  hash-pinned sources; unfilled generated slots remain generated.
- `storyboard.original.json`: original editable planning document. Its original input
  paths remain provenance, not guaranteed portable dependencies. Recompile it where
  those inputs are available or update its paths to the copied media.
- `storyboard.md`: readable bible, shot actions and handoffs.
- `media/`: copied source GIFs and locally rendered title cards.
- `references/` and `generation/`: copied stills and validated one-shot API inputs.
  The generation input for a selected take remains as provenance; it is no longer
  listed as a missing request in the report.
- `take-selections.json` (when `--takes` is used): selected media hashes, caller review
  notes, original request links, requested and measured durations. This is an output
  receipt, not an input takes manifest. It describes this compile only.
- `film.json`: executable only when every shot has local media.
- `assembly-template.json`: created instead when any shot still needs generation;
  `accepted/ID.gif` deliberately marks the absent assets. Do not execute it until
  real accepted GIFs exist. Prefer selecting reviewed takes and recompiling.
- `story-report.json`: source timings, drawing counts, source checksums, missing-shot
  request count, selection count, quantized timeline, repetition warnings and review status.
  `visual_acceptance` remains `not-established`, including when review notes are recorded.

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
