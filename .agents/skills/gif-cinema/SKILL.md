---
name: gif-cinema
description: Make multi-scene animated stories, mini cartoons, and motion-design GIFs or MP4s with story beats, character references, short generated takes, local animated titles, and continuity review. Use for longer narrative edits, not just extending a short loop.
---

# GIF Cinema

Turn a brief into **different visible actions with cause and effect**, then assemble
reviewed shots into a longer story. Separate appearance, character action, graphic
motion, and delivery format. Keep the user's chosen art style and approved footage.
This is an author-guided workflow, not an autonomous animation model.

## Choose a real production route

- **Existing GIFs:** inspect what each take actually shows; build the story around
  those actions. The bundled example tests this route without an API key.
- **New character action:** plan one main action per short generated GIF. Use only
  an available, authorized generation tool/API. Inspect and accept each result before
  extending its state into another scene. See [generation.md](references/generation.md).
- **Motion design:** use the included local animated-title renderer for typography
  and accent-rule entrances. For layered characters, movable props, masks, or rigged
  action, use a compositor actually available in the environment and preserve its
  editable sources. This package does not contain a general layered animation engine.

Do not count camera drift, an overlay, reversed footage, another caption on the same
clip, or longer holds as a new character action. A long cartoon needs additional
story events. If those drawings are missing and generation is unavailable, deliver
an honest animatic or production plan, not a claimed finished cartoon.

## Runtime and a no-key check

Requires Python 3.10+, Pillow, Git, FFmpeg and ffprobe. Use an isolated environment.
The skill's helpers work with this reviewed, immutable public runtime:

```bash
python -m venv .venv
# Activate .venv with the command for your shell, then:
python -m pip install "gif-cinema @ git+https://github.com/antropos17/chatgpt-gif-cinema.git@fa82b13366a9ae94a4ece730ec6b2d065cd9a060"
python -m gif_cinema --help
ffmpeg -version
ffprobe -version
```

An existing checkout of that revision or a tested compatible newer runtime is also
usable. Do not downgrade a working project automatically. The runtime uses the
included source-available [evaluation license](LICENSE). GIF Factory's attributed
workflow influence has its own MIT notice in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Resolve helper and asset paths relative to **this skill folder**. The examples below
assume the shell is in that folder. From elsewhere, use absolute paths to the helpers
and input JSON; keep outputs in the user's project, never in the installed skill.

```bash
python scripts/story_project.py compile assets/example/storyboard.json --out output/story-project
python -m gif_cinema render output/story-project/film.json --dry-run --max-api-calls 0
python -m gif_cinema render output/story-project/film.json --execute --max-api-calls 0 --out output/story-render
python scripts/story_project.py export-gif output/story-render/film.mp4 --out output/story.gif
```

This is a **9.68-second source edit**, not a new long cartoon: a 2-second locally
animated title followed by three existing 2.56-second astronaut actions. The MP4 uses
25 fps; the source characters have 16 drawings per take, not 25 new drawings per
second. GIF export defaults to 320 px wide, 10 fps, silent, play-once. `--repeat`
loops the entire result. Some viewers override GIF loop behavior.

For the core CLI regression check, run `scripts/smoke_test.py --out NEW_DIRECTORY`.
Neither helper needs a key. The story helper never makes provider calls and refuses
an existing output project. [story-project.md](references/story-project.md) documents
its exact schema, commands, timing, and limits.

## Direct before generating

For a new story or a substantial extension, read [storytelling.md](references/storytelling.md).
Produce an editable storyboard with:

1. The premise and ending; audience, target duration, aspect ratio, language and
   sound requirements when relevant. Infer low-risk defaults instead of asking again.
2. A compact visual bible: recognizable character anchors, palette/material,
   costume, prop counts, ownership, scale, geography, and camera conventions.
3. A beat/shot list: **state before → visible action → state after**, camera,
   expected duration, and purpose in the story. Track hands/props/contact at each cut.
4. A source/generation map: which actions already exist, which need new drawings,
   which are local graphics. Mark unrendered shots as unrendered.

Scale the story by adding meaningful actions and consequences, not repeating footage
until a timer reaches the brief. The long-story example in
`assets/example/long-story.plan.json` is an **unrendered 14-action production plan**.
Compiling it prepares 14 one-shot generation inputs; it does not render those actions.

## Generate and join deliberately

Compile the storyboard with `scripts/story_project.py compile ...`. A source-only
project has an executable `film.json`. A project with missing/generated shots has
separate `generation/ID.json` inputs and a deliberately incomplete
`assembly-template.json`. No paid batch is executed by the compiler.

Use one representative action to establish feasibility when the character/method is
new. New generation needs the user's own API access and the agreed bounded call cap.
For endpoint continuity, extract the accepted previous last frame, inspect it, then
attach that **existing** still plus a clean identity reference to the next shot input.
The compiler does not create future references or an automatic dependency graph.

Keep separate take folders and a record of accepted/rejected candidates. A retake
must be reviewed at both neighboring joins. After selection, change the storyboard
shot from `generate` to `source` using its actual accepted GIF path and compile a new
portable project. Accepted source footage is copied unchanged; it is never regenerated
by offline assembly. Use zero-call render even when a key happens to be configured.

## Motion, timing, and export

Title cards are once-only text/line entrances followed by a hold. Lettering is local
and editable in the storyboard, rather than entrusted to a generation prompt. Titles
are **separate shots**, not overlays; runtime captions are a separate SRT, not burned
into GIFs. Specify a licensed local font with `--font` if needed, and inspect its glyphs.

Character timing comes from the decoded source GIF. Source retiming, transitions,
interpolation, audio generation and automatic action synthesis are not supplied by
this helper. The pinned runtime uses hard cuts and can import optional local audio
through its film script. GIF has no audio. Follow current runtime help if using newer
editing tools; do not imply the pinned package includes them.

Export a verified MP4 first, then a smaller GIF or chapters. GIF palette conversion
can damage gradients and fine outlines; review the actual final GIF too. High playback
FPS does not create new motion. [review.md](references/review.md) gives the visual and
technical acceptance checks.

## Deliver the actual result

Provide requested GIF/MP4 files with actual duration, dimensions, loop behavior,
source drawing cadence versus export FPS, silent/audio status, and known visual
faults. Include an editable project when requested. Review source names, prompts,
references and licensing before sharing a project; do not publish private inputs.
Distinguish technical verification, your visual review, and user acceptance.
