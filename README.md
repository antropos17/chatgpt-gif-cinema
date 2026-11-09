<picture>
  <source media="(max-width: 600px)" srcset="docs/assets/identity/cover-mobile.svg">
  <img src="docs/assets/identity/cover.svg" alt="GIF Cinema. Small takes. Real stories. Direct, review, cut." width="1200">
</picture>

*Static identity artwork. The actual GIFs and films are below.*

# GIF Cinema

**Turn a moment into a GIF. Turn a few good takes into a story.**

An agent skill and Python CLI for **Codex and Claude Code**. Direct short shots through
an API, inspect the actual frames, choose your takes, and assemble a film. Or start
with the bundled footage, entirely offline.

[**Make your first film →**](#make-your-first-film) · [Copy a prompt](#copy-a-prompt) · [Install the skill](#install-the-skill) · [Production guide](docs/PRODUCTION.md)

[![Tests](https://github.com/antropos17/chatgpt-gif-cinema/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/antropos17/chatgpt-gif-cinema/actions/workflows/tests.yml) [![Codex and Claude Code](https://img.shields.io/badge/Codex_%2B_Claude_Code-agent_skill-263a38)](.agents/skills/gif-cinema/SKILL.md) [![Source-available](https://img.shields.io/badge/license-source--available-e65d3e)](LICENSE)

## 01 / One prompt. One small performance.

<p align="center">
  <img src="docs/assets/first-live-render.gif" width="420" alt="The actual original direct-GIF sample: a paper-cut astronaut raising a hand on the Moon.">
</p>

**A wave from the Moon** · Direct API output · 1.80 s · 9 drawings · 512 × 512

This is an existing, unaltered generated GIF, not the static silver artwork above.
Its original prompt and parameters are preserved. The movement is visibly stepped;
this is a reproducible request example, not a claim of smooth cinematic animation.

> A tiny paper-cut astronaut waves once on the Moon, locked camera, matte monochrome background, clear silhouette, smooth loop, no text

[**Exact request + how to repeat it →**](docs/RECIPES.md#one-prompt-one-gif) · [Original request record](docs/assets/first-live-render.json) · [Decoded timing](docs/assets/first-live-render-inspect.json)

A new generation needs your own supported model access and billing. The same prompt
can produce a different result. The phrase “smooth loop” is a request, not a passed
quality check.

## 02 / Three takes. A complete little exchange.

![Three story beats: a hand rises, a light replies, he is not alone. Static editorial diagram.](docs/assets/identity/story-strip.svg)

**A Reply from the Stars** · Runnable source edit · 7.68 s · 512 × 512 · Silent

An astronaut waves into the dark. A light answers. A hand moves toward the chest.
The three bundled source GIFs become one MP4, with a contact sheet and the frames
on both sides of every cut.

https://github.com/user-attachments/assets/c4dc8c9b-1e97-4f1a-9632-e285d9b969e0

[**Make this exact edit →**](#make-your-first-film) · [Open the MP4](docs/assets/showcase/astronaut-native-film.mp4) · [Read the three-shot script](examples/film.json)

**Next cut:** add the included animated title for a **9.68-second MP4**, export a
small GIF, or split the finished edit into whole-shot GIF chapters.
[Copy the complete title + story recipe](docs/RECIPES.md#add-a-title-and-export-a-gif).
These are new edits of the bundled footage, not new character actions.

## Make your first film

**No key. No API calls. Real output.** You need Python 3.10+, Git, FFmpeg and ffprobe.
[Install FFmpeg](https://ffmpeg.org/download.html) if the two video tools are missing.

```bash
git clone https://github.com/antropos17/chatgpt-gif-cinema.git
cd chatgpt-gif-cinema
python -m venv .venv
```

Activate the environment: `source .venv/bin/activate` on macOS/Linux or
`.\.venv\Scripts\Activate.ps1` in Windows PowerShell. Then:

```bash
python -m pip install .
python -m gif_cinema render examples/film.json --dry-run --max-api-calls 0
python -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/my-first-film
```

**Open `output/my-first-film/film.mp4`.** You also get a contact sheet, six endpoint
images, a continuity report, SRT captions and a resumable manifest. Run the same
render command again to reuse the verified movie.

The MP4 plays at 25 fps; each source GIF contains 16 drawings held for 160 ms.
Export FPS does not create extra poses. [Verification and limits](STATUS.md).

## Copy a prompt

Give these briefs to your agent after [installing the skill](#install-the-skill).
Each says what to make, what to preserve, and what to return.

### Assemble the included story

> Use the gif-cinema skill to render examples/film.json with zero API calls. Keep the original source timing. Return the 7.68-second MP4, contact sheet, and first/last frames. Tell me what changes across the two cuts instead of claiming automatic continuity.

**You get:** the runnable film shown above plus inspectable review artifacts.

### Add a title, then make a GIF

> Use the gif-cinema skill to compile the bundled storyboard.json, render it with zero API calls, and export a 320-pixel GIF at 10 fps. Keep the 2-second animated title and the three existing astronaut takes. Return the MP4, GIF, and editable project. Do not generate new footage.

**You get:** a 9.68-second MP4 and a 9.70-second play-once GIF. The title is locally
animated; the astronaut drawings are unchanged. [Exact commands](docs/RECIPES.md#add-a-title-and-export-a-gif).

### Plan a story with genuinely new actions

> Use the gif-cinema skill to plan a short illustrated story about a courier delivering a lantern. Keep the character, lantern, palette, and direction of travel consistent. Give each shot one visible action with a clear state before and after. Show the storyboard and request count before generation. Mark all missing footage as unrendered.

**You get:** an editable production plan and individual generation inputs, not a
finished cartoon. The included *Lantern Delivery* plan has 14 intended actions and
35.84 seconds of planned footage. [Plan, select takes, and continue](docs/STORYTELLING-SKILL.md).

## Install the skill

From the checkout, package the **current** source skill:

```bash
python tools/package_skill.py --out dist/gif-cinema-story-skill.zip
```

Extract the ZIP's single `gif-cinema` folder into:

- **Codex:** `~/.codex/skills/gif-cinema`
- **Claude Code:** `~/.claude/skills/gif-cinema`

[Read the skill](.agents/skills/gif-cinema/SKILL.md) · [Package checks](docs/STORYTELLING-SKILL.md#package-and-verify-the-skill)

<details>
<summary>Already using the published skill-v0.1.1 ZIP?</summary>

That [older release](https://github.com/antropos17/chatgpt-gif-cinema/releases/tag/skill-v0.1.1)
contains the core assembly workflow. It predates story planning, take selection and
chapter export. Package the current source for those helpers; this README is not a
new versioned release.

</details>

## From the cutting room

**Existing finishing experiments, not a promise of the public CLI.** These comparisons
use additional local interpolation and, for the cat, compositing and framing cleanup.
Those finishing tools are not included here. Each thumbnail is a 2.24-second excerpt.

<details>
<summary><strong>Cat · Walk, jump, curl up</strong> — open the animated comparison</summary>

![Existing cat before/after comparison excerpt.](docs/assets/showcase/cat-preview.gif)

[Watch the 7.68-second comparison](https://github.com/user-attachments/assets/4c200322-2bfc-46ad-8ba9-8548614608a5) · [Inspect frame pairs](docs/assets/showcase/cat-frames.png) · [Watch the 57.2-second assembled cat film](https://github.com/user-attachments/assets/32e3381d-dbd7-4ff3-8356-1d379b2b7456)

</details>

<details>
<summary><strong>Astronaut + dog</strong> — open two more finishing studies</summary>

![Existing astronaut before/after comparison excerpt.](docs/assets/showcase/astronaut-preview.gif)

[Astronaut: full 5.12-second comparison](https://github.com/user-attachments/assets/86a158cc-c346-4486-8373-1a08fd54fd34) · [Frame pairs](docs/assets/showcase/astronaut-frames.png)

![Existing dog before/after comparison excerpt.](docs/assets/showcase/dog-preview.gif)

[Dog: full 10.24-second comparison](https://github.com/user-attachments/assets/63d2cff7-2cf6-4ba9-82a2-1d61dd4e0638) · [Frame pairs](docs/assets/showcase/dog-frames.png)

</details>

[Methods, media provenance and known faults →](docs/SHOWCASE.md)

## The cut is the test

Keep the character recognizable, the prop in the right hand, and the action readable
on both sides of a cut. A reference image helps; it does not guarantee continuity.
Extra playback frames cannot repair a missing prop or an action that never happened.

- **Included:** API generation with supported access, still references, bounded script runs, inspected takes, local titles, MP4 assembly and GIF/chapter export.
- **Not included:** the private Studio UI, a general layered animation engine, music generation, private interpolation/compositing tools or automatic visual approval.
- **Generation safety:** dry-run a script, inspect the request count, then authorize a bounded run. Request counts are not dollar quotes. GIFs are silent; MP4 can use optional local audio.

[Story guide](docs/STORYTELLING-SKILL.md) · [Production](docs/PRODUCTION.md) · [Script format](docs/SCRIPT-FORMAT.md) · [Filmmaking tips](docs/TIPS.md) · [Verification](STATUS.md)

## Credits & license

Inspired by [GIF Factory](https://github.com/WoYun520/gif-factory)'s separation of
appearance, movement and purpose. [Attribution and MIT notice](.agents/skills/gif-cinema/THIRD_PARTY_NOTICES.md).
No GIF Factory artwork, fonts or exporter code are bundled. The cover and story
symbols are original static SVG artwork; [identity and media provenance](docs/README-DESIGN.md).

GIF Cinema is an independent **source-available** project. Personal non-commercial
evaluation and research are permitted; commercial use, redistribution and hosting
require permission. [Read the license](LICENSE).

[Support the workshop on Buy Me a Coffee ↗](https://buymeacoffee.com/gifcinema)
