# GIF Cinema

**Turn short takes into films you can edit.**

A Python toolkit and skill for **Codex and Claude Code**. Assemble GIFs, animate
graphics, review frames and export films.

[Pixel-art gallery](#anime-pixel-art) · [See the work](#selected-work) · [Try it without a key](#make-your-first-film) · [Install the skill](#install-the-skill) · [Choose a workflow](#choose-a-workflow)

## Anime pixel art

**Separate outfits, separate takes.** Early motion studies; smoother pose sequences
are still in progress.

<p align="center">
<a href="examples/anime-pixel/README.md#wave-and-bow"><picture><source media="(prefers-reduced-motion: reduce)" srcset="examples/anime-pixel/anime-pixel-wave-and-bow-v2-poster.png"><img src="examples/anime-pixel/anime-pixel-wave-and-bow-v2.gif" width="240" alt="Cream jacket: a blue-haired heroine waves, then bows in a separate short phase."></picture></a><br>
<strong>Cream jacket · wave and bow</strong><br>
32 frames · 3.84 s · 320 × 320 · repeating
</p>

<p align="center">
<a href="examples/anime-pixel/traveler.gif"><picture><source media="(prefers-reduced-motion: reduce)" srcset="examples/anime-pixel/traveler-poster.png"><img src="examples/anime-pixel/traveler.gif" width="240" alt="Jade traveler outfit: a standalone transparent character greeting and lifting one knee."></picture></a><br>
<strong>Jade traveler · greeting</strong><br>
16 frames · 1.92 s · 320 × 320 · repeating
</p>

<p align="center">
<a href="examples/anime-pixel/festival.gif"><picture><source media="(prefers-reduced-motion: reduce)" srcset="examples/anime-pixel/festival-poster.png"><img src="examples/anime-pixel/festival.gif" width="240" alt="Coral festival yukata: a separate transparent character greeting and lifting one knee."></picture></a><br>
<strong>Coral festival · greeting</strong><br>
16 frames · 1.92 s · 320 × 320 · repeating
</p>

Each outfit has its own source drawings and GIF. These silent drafts still show
pose jumps and drift in face, hair and costume details; loop endpoints do not match.
No interpolated poses or JavaScript animation.

[Separate source atlases & recipe](examples/anime-pixel/README.md#sources-and-method) ·
[Measured GIF facts](examples/anime-pixel/verification.json) ·
[Draft festival film, 15.36 s](examples/anime-pixel/README.md#draft-festival-film)

<details>
<summary>Earlier shared-stage experiments</summary>

[Three outfits in one garden](examples/anime-pixel/README.md#three-outfits) and
[two heroes](examples/anime-pixel/README.md#two-heroes) are earlier composition tests,
each 16 frames / 1.92 seconds. They are not the target format for the separate,
smoother outfit studies.

</details>

<a id="blender-motion-study"></a>

<p align="center">
<a href="examples/blender-form-01/README.md"><picture><img src="examples/blender-form-01/deliverables/FORM-01.gif" width="480" alt="FORM / 01: porcelain arcs unfold around a copper sphere in an actual Blender-rendered six-second loop."></picture></a>
</p>

<p align="center">
<strong>FORM / 01</strong><br>
Porcelain, copper, six seconds. Rendered in Blender EEVEE.<br>
<a href="examples/blender-form-01/deliverables/FORM-01.mp4">Watch MP4</a> · <a href="examples/blender-form-01/form_01.blend">Open the .blend</a> · <a href="examples/blender-form-01/README.md#import-into-gif-cinema-with-zero-api-calls">Import into GIF Cinema</a>
</p>

The scene and Python source are included. Blender renders this artwork separately;
GIF Cinema can import the finished GIF. No model call or JavaScript animation.

<a id="see-it-in-motion"></a>
<a id="on-the-screen"></a>
<a id="a-wave-from-the-moon"></a>
<a id="01--one-prompt-one-small-performance"></a>

## Selected work

Real files, with their source and method. Click a preview to see how it was made.

<a id="character-stories"></a>
<a id="a-reply-from-the-stars"></a>
<a id="02--three-takes-a-complete-little-exchange"></a>
<a id="motion-graphics"></a>

<table>
<tr>
<td width="50%" align="center" valign="top">
<a href="docs/EXAMPLES.md#2-titled-story-a-small-gif-to-share"><picture><img src="docs/assets/example-gallery/titled-story.gif" width="300" alt="A Reply from the Stars: a local title and three existing astronaut takes, played once."></picture></a><br>
<strong>A Reply from the Stars</strong><br>
Three generated takes + local title · 9.70 s GIF<br>
<a href="docs/EXAMPLES.md">Story recipe</a> · <a href=".agents/skills/gif-cinema/assets/example/storyboard.json">Storyboard</a>
</td>
<td width="50%" align="center" valign="top">
<a href="docs/MOTION-DESIGN.md"><picture><source media="(prefers-reduced-motion: reduce)" srcset="docs/assets/motion-elements/poster.png"><img src="docs/assets/motion-elements/chrome.gif" width="300" alt="Chrome Trefoil: the original archived Blender EEVEE rotation, one 3.20-second loop."></picture></a><br>
<strong>Chrome Trefoil</strong><br>
Archived Blender EEVEE study · 3.20 s loop<br>
<a href="docs/assets/motion-elements/chrome.mp4">Watch MP4</a> · <a href="docs/MOTION-DESIGN.md">Source & provenance</a>
</td>
</tr>
<tr>
<td width="50%" align="center" valign="top">
<a href="docs/STROKE-REVEAL.md"><picture><img src="docs/assets/stroke-reveal/preview.gif" width="300" alt="Three authored strokes reveal a heart, an underline and a sparkle. Local rendering, no generated artwork."></picture></a><br>
<strong>Draw, pause, finish</strong><br>
Editable stroke paths · 4.00 s play-once GIF<br>
<a href="docs/STROKE-REVEAL.md">Draw-on workflow</a> · <a href="examples/stroke-reveal.json">Scene JSON</a>
</td>
<td width="50%" align="center" valign="top">
<a href="docs/GIF-LAYERS.md"><picture><img src="docs/assets/gif-layer/preview.gif" width="300" alt="An existing astronaut action beside independently animated text and an accent line."></picture></a><br>
<strong>Action beside typography</strong><br>
Existing GIF + local graphic layers · 3.20 s<br>
<a href="docs/GIF-LAYERS.md">Composition workflow</a> · <a href="examples/gif-layer/scene.json">Scene JSON</a>
</td>
</tr>
</table>

[More examples & recipes](docs/GALLERY.md) · [Original API take](docs/RECIPES.md#one-prompt-one-gif) · [Vertical motion](docs/VERTICAL-MOTION-EXAMPLE.md) · [Review the source drawings](docs/EXAMPLES.md#the-actual-three-shot-story)

The astronaut examples reuse the same existing footage. Titles and layouts add no
new character actions; hand, suit and framing differences remain between takes.
The local graphics use the experimental layer renderer. Blender examples are
standalone scenes, not a CLI rendering backend.

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

Build the maintained **0.4.0 skill package** from this checkout:

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

<a id="sprites-and-frame-review"></a>

<a id="exact-script-montage"></a>

## Choose a workflow

| Make or inspect | Start here |
| --- | --- |
| Connected actions on one shared stage, with persistent props | [Scene sequences](docs/SCENE-SEQUENCES.md) |
| A short film with titles or illustrated story pages | [Storytelling skill](docs/STORYTELLING-SKILL.md) |
| Independent text, shapes, strokes and existing GIF layers | [Layer renderer](docs/MULTILAYER-POC.md) · [GIF composition](docs/GIF-LAYERS.md) |
| Whole-image motion with editable timing | [Motion recipes](docs/STANDALONE-MOTION.md) |
| Exact GIF palette control and integer pixel-art scaling | [Pixel palettes](docs/PIXEL-PALETTES.md) |
| Explicit pose holds and continuity from accepted atlas drawings | [Authored pose tracks](docs/AUTHORED-POSES.md) |
| A sprite atlas from accepted drawings | [Pack or slice sprites](docs/SPRITES.md) |
| Every frame, cut and loop seam | [Review player & checklist](docs/GIF-REVIEW.md) |
| Frame-accurate cuts, subtitle sidecars and a soundtrack | [Exact script montage](docs/EXACT-SCRIPT-EDIT.md) |
| A portable collection with an offline gallery and ZIP | [Offline GIF factory](docs/OFFLINE-FACTORY.md) |

<a id="build-an-offline-gif-collection"></a>

The factory combines existing GIFs and local layer scenes. From the installed
checkout, build and verify the bundled collection:

```bash
python -m gif_cinema factory build factory.example.json --out output/my-collection
python -m gif_cinema factory verify output/my-collection
```

Open `output/my-collection/index.html`, or share `collection.zip` when you have the
rights to its contents. The gallery is static HTML with native GIF playback, no scripts.

## Before making new footage

- **Generation is optional.** New model-generated takes need supported provider
  access, billing and an explicitly authorized request cap. The demo and local tools
  work without them. [Generation guide](.agents/skills/gif-cinema/references/generation.md).
- **Review the actual motion.** Matching prompts, high playback FPS and successful
  checks do not establish character continuity or a clean loop. Missing actions
  stay unrendered until suitable footage exists.
- **Keep the edit reproducible.** Preserve accepted source files, inspect neighboring
  cuts after a retake, and deliver the project with its receipts. Technical
  verification and artistic acceptance are separate.

[Production guide](docs/PRODUCTION.md) · [Script format](docs/SCRIPT-FORMAT.md) · [Verification status](STATUS.md)

<a id="finishing-studies"></a>
<a id="03--from-the-cutting-room"></a>
<a id="from-the-cutting-room"></a>
<a id="cat--walk-jump-curl-up"></a>
<a id="dog--follow-the-ball"></a>
<a id="astronaut--a-signal-an-answer"></a>
<a id="archived-3d-study"></a>

<details>
<summary>Earlier films and finishing studies</summary>

The [cat, dog and astronaut comparisons](docs/SHOWCASE.md) show native takes beside
private local finishing, **not included in the public CLI**. The gallery previews
loop a 2.24-second excerpt; linked films show the full action.

- [A window, a jump, a nap](docs/SHOWCASE.md#cat--walk-jump-curl-up): three takes, 7.68-second comparison.
- [Follow the red ball](docs/SHOWCASE.md#dog--the-same-four-takes): four takes, 10.24-second comparison.
- [A signal, an answer](docs/SHOWCASE.md#astronaut--two-shots-one-exchange): two takes, 5.12-second comparison.
- [The complete cat short](docs/assets/showcase/cat-film.mp4): 57.2 seconds, assembled and locally finished.

[Chrome Trefoil](docs/MOTION-DESIGN.md) above is one archived Blender EEVEE loop,
not native API output. [FORM / 01 review scope](examples/blender-form-01/README.md#review-status)
records the newer scene's technical checks and sampled visual review.

</details>

## Rights and credits

Inspired by [GIF Factory](https://github.com/WoYun520/gif-factory)'s visual catalog
and separation of production methods. No upstream artwork, character assets or code
are copied into this catalog. [Attribution](.agents/skills/gif-cinema/THIRD_PARTY_NOTICES.md).

GIF Cinema is **source-available**, not an OSI open-source release. Personal
non-commercial evaluation and research are permitted; commercial use, redistribution
and hosting require permission. [License](LICENSE) · [Support the workshop](https://buymeacoffee.com/gifcinema).
