# GIF Cinema

**Direct the moment. Build the story.**

A wave becomes a reply. A cat finds a windowsill. Short GIFs become scenes you can
choose, cut, and keep.

GIF Cinema is an **agent skill + local filmmaking CLI for Codex and Claude Code**.
Plan character-led stories, generate short takes with still-image references, review
the cuts, add animated titles, and export MP4 or GIF. **Start with the included
footage: no API key needed.**

[**Explore the films**](#see-it-in-motion) · [**Try the no-key demo**](#try-it-without-an-api-key) · [**Install the skill**](#give-the-skill-to-your-agent) · [Story workflow](docs/STORYTELLING-SKILL.md)

[![Tests](https://github.com/antropos17/chatgpt-gif-cinema/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/antropos17/chatgpt-gif-cinema/actions/workflows/tests.yml) [![Agents: Codex and Claude Code](https://img.shields.io/badge/agents-Codex_%2B_Claude_Code-bbe5d3)](.agents/skills/gif-cinema/SKILL.md) [![Source-available evaluation license](https://img.shields.io/badge/license-source--available-e9a67c)](LICENSE)

## See it in motion

### A window, a jump, a nap

[![Cat comparison: original GIF timing on the left, local framing, compositing and selective interpolation on the right.](docs/assets/showcase/cat-preview.gif)](https://github.com/user-attachments/assets/4c200322-2bfc-46ad-8ba9-8548614608a5)

Walk across the room. Jump to the windowsill. Curl into a ball. **Three takes,
7.68 seconds of action.** The comparison follows the same selected footage from
native GIF timing to a locally finished edit.

*2.24-second preview of the 7.68-second comparison. The finished side uses additional
local tools not included in the public CLI.*

[**Watch the full comparison**](https://github.com/user-attachments/assets/4c200322-2bfc-46ad-8ba9-8548614608a5) · [Inspect the frame pairs](docs/assets/showcase/cat-frames.png) · [How it was made](docs/SHOWCASE.md#cat--walk-jump-curl-up)

<table>
<tr>
<td width="50%" valign="top">
<a href="https://github.com/user-attachments/assets/86a158cc-c346-4486-8373-1a08fd54fd34"><img src="docs/assets/showcase/astronaut-preview.gif" alt="A paper-textured astronaut raises a hand: native GIF timing beside locally interpolated motion." width="380"></a>
<br><strong>A signal. An answer.</strong>
<br>A small gesture in a quiet universe. Two astronaut shots, 5.12 seconds, with native and locally interpolated motion side by side.
<br><a href="https://github.com/user-attachments/assets/86a158cc-c346-4486-8373-1a08fd54fd34">Watch comparison</a> · <a href="docs/assets/showcase/astronaut-frames.png">Frame pairs</a>
</td>
<td width="50%" valign="top">
<a href="https://github.com/user-attachments/assets/63d2cff7-2cf6-4ba9-82a2-1d61dd4e0638"><img src="docs/assets/showcase/dog-preview.gif" alt="An illustrated dog follows a red ball: the same source takes before and after local interpolation." width="380"></a>
<br><strong>One dog. One red ball.</strong>
<br>Four takes, 10.24 seconds. Follow the ball, paws, and contact points through the native and locally interpolated versions.
<br><a href="https://github.com/user-attachments/assets/63d2cff7-2cf6-4ba9-82a2-1d61dd4e0638">Watch comparison</a> · <a href="docs/assets/showcase/dog-frames.png">Frame pairs</a>
</td>
</tr>
</table>

**About these previews:** each animated thumbnail loops a 2.24-second excerpt;
linked videos contain the full comparisons. Their finished panels use additional
local postproduction, including interpolation and, for the cat, compositing and
framing cleanup. Those finishing tools are not included in the public toolkit.
The [no-key demo below](#try-it-without-an-api-key) shows the exact public CLI output.

### Full cat film

**57.2 seconds · Silent short · Short generated takes, assembled and finished locally.**

https://github.com/user-attachments/assets/32e3381d-dbd7-4ff3-8356-1d379b2b7456

[Open the MP4 file](docs/assets/showcase/cat-film.mp4) · [Production notes and limitations](docs/SHOWCASE.md)

## Choose your starting point

| You have… | Make this | Start here |
| --- | --- | --- |
| **A few GIFs** | A short edit with reviewed cuts, an MP4, and a contact sheet. | [No-key film demo](#try-it-without-an-api-key) |
| **A character and a story** | Story beats, a character/prop bible, per-shot generation inputs, and a growing collection of reviewed takes. | [Storytelling skill](docs/STORYTELLING-SKILL.md) |
| **Footage that needs an introduction** | An editable animated title, followed by your selected scenes. | [9.68-second title + story example](docs/STORYTELLING-SKILL.md#try-the-current-repository-skill) |
| **A completed longer edit** | A verified MP4 master plus smaller GIF chapters that keep whole shots together. | [Chapter export](docs/STORYTELLING-SKILL.md#deliver-longer-stories-as-gif-chapters) |

The current source includes these story helpers. **New character action needs new
footage** and, when generating it, supported model access and authorized requests.
The included 14-action *Lantern Delivery* example is a **35.84-second unrendered
production plan**, ready to fill with reviewed takes, not a finished cartoon.

## Try it without an API key

**Three bundled GIFs → a 7.68-second astronaut film.** An astronaut waves into
space, a star answers, and the astronaut brings a hand to his chest.

[**Watch the exact CLI export**](https://github.com/user-attachments/assets/c4dc8c9b-1e97-4f1a-9632-e285d9b969e0) · [Read the film script](examples/film.json)

You need **Python 3.10+, Git, FFmpeg, and ffprobe**. Both video tools must be on your
PATH. [Get FFmpeg](https://ffmpeg.org/download.html).

```bash
git clone https://github.com/antropos17/chatgpt-gif-cinema.git
cd chatgpt-gif-cinema
python -m venv .venv
```

Activate with `source .venv/bin/activate` on macOS/Linux or
`.\.venv\Scripts\Activate.ps1` in Windows PowerShell, then:

```bash
python -m pip install .
python -m gif_cinema render examples/film.json --dry-run --max-api-calls 0
python -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/my-first-film
```

Open **`output/my-first-film/film.mp4`**. Your edit also comes with:

- A contact sheet and the first/last frame of every shot.
- A continuity report and SRT captions.
- A resumable manifest. Run the same command again to reuse the verified result.

The film is 512 × 512 at 25 fps. Each source GIF has 16 drawings held for 160 ms;
exporting at 25 fps preserves those holds rather than creating new character poses.
[Timing and verification evidence](STATUS.md).

**Want a title and a GIF too?** Follow the [zero-call story walkthrough](docs/STORYTELLING-SKILL.md#try-the-current-repository-skill)
to turn the same footage into a 9.68-second MP4 with a local animated title, then
export a smaller GIF or whole-shot chapters.

## Give the skill to your agent

From the checkout above, package the **current storytelling skill**:

```bash
python tools/package_skill.py --out dist/gif-cinema-story-skill.zip
```

Extract its single `gif-cinema` folder into your agent's skill directory:

| Agent | Installed folder |
| --- | --- |
| Codex | `~/.codex/skills/gif-cinema` |
| Claude Code | `~/.claude/skills/gif-cinema` |

Then ask:

> Use the gif-cinema skill to assemble the included astronaut story with an
> animated title and zero API calls. Show me the MP4, a small GIF, and the frames
> on either side of each cut.

Or bring an idea:

> Use the gif-cinema skill to plan a short illustrated story about a courier
> delivering a lantern. Keep the character, lantern, and direction of travel
> consistent. Prepare one action per shot and show me the plan before generation.

The skill includes examples, helper scripts, review guidance, and setup for a pinned
runtime. [Read the skill](.agents/skills/gif-cinema/SKILL.md) · [Package and verification details](docs/STORYTELLING-SKILL.md#package-and-verify-the-skill).

<details>
<summary>Looking for the earlier downloadable release?</summary>

The [published skill-v0.1.1 ZIP](https://github.com/antropos17/chatgpt-gif-cinema/releases/tag/skill-v0.1.1)
contains the older core assembly workflow and bundled astronaut footage. It predates
the story planner, take selection, and chapter export above. Use the current source
package for those features; the README refresh is not a new versioned release.

</details>

## Make a shot, keep a take

**Brief → story beats → short takes → reviewed cuts → film**

1. **Direct.** Give each scene a clear action and a visible change: state before,
   action, state after. Keep the character, props, palette, and camera intentional.
2. **Generate deliberately.** Use still references where appropriate. Dry-run first,
   inspect the request count, then authorize a bounded run with supported model access.
3. **Review the cut.** Compare the outgoing and incoming poses, character identity,
   prop ownership, scale, and direction. Look at the actual frames.
4. **Keep what works.** Select reviewed GIFs by SHA-256 in a takes manifest. Fill
   missing scenes progressively while preserving earlier source footage.
5. **Reshoot the weak moment.** Target a runtime shot with `--force-shot SHOT_ID`.
   Unchanged accepted shots can be reused; review both neighboring cuts again.
6. **Export and inspect.** Assemble the MP4, then export a GIF or whole-shot chapters.
   Keep the storyboard, source timings, and review artifacts with the edit.

**The cut is the test.** A reference image guides the next take; it does not guarantee
continuity. Higher playback FPS does not fix an extra paw, a missing prop, or an action
that never happened. Those need a better take.

New generation uses your own OpenAI API key, billing, and supported model access.
Dry-run reports request counts, not a dollar quote. GIF exports are silent; the
runtime can import optional local audio into MP4. Music generation, automatic
continuity approval, a general layered animation engine, and the private Studio UI
are not included.

## Go further

- [**Storytelling guide**](docs/STORYTELLING-SKILL.md): plan scenes, select takes, add titles, export chapters.
- [**Production guide**](docs/PRODUCTION.md): references, retakes, and a controlled generation workflow.
- [**Script format**](docs/SCRIPT-FORMAT.md): JSON fields, request limits, render safety, and recovery.
- [**Filmmaking tips**](docs/TIPS.md): practical ways to make short takes cut together.
- [**Showcase methods**](docs/SHOWCASE.md): what was generated, what was finished locally, and what remains imperfect.
- [**Verification status**](STATUS.md): dated checks and account/model-specific generation evidence. Current source checks run in [CI](https://github.com/antropos17/chatgpt-gif-cinema/actions/workflows/tests.yml).

## Credits, license, and support

The story workflow is informed by [GIF Factory](https://github.com/WoYun520/gif-factory),
especially its separation of appearance, movement, and purpose. Its influence and
MIT notice are recorded in [third-party notices](.agents/skills/gif-cinema/THIRD_PARTY_NOTICES.md).
No GIF Factory artwork, fonts, or exporter code are bundled.

GIF Cinema is an independent, **source-available** project. Personal non-commercial
evaluation and research are permitted; commercial use, redistribution, and hosting
require permission. Read the [evaluation license](LICENSE).

If these experiments help your own, [support GIF Cinema on Buy Me a Coffee](https://buymeacoffee.com/gifcinema).
