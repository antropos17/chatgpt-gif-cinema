# GIF Factory capability comparison and implementation order

Snapshot: 9 November 2026. Baseline: GIF Cinema `ba629d7`; upstream:
[WoYun520/gif-factory](https://github.com/WoYun520/gif-factory), **986 stars** when
checked. Stars are a time-sensitive popularity count, not a quality score.
This comparison is based on the checked code, manifests and production guides;
it is not a claim that every upstream example was regenerated or visually accepted.

## Current implementation update — 10 November 2026

The table below preserves the **historical `ba629d7` comparison**, not the current
feature status. By Cinema `debc104`, full-frame review, sprite packing/slicing,
animated GIF/sprite layers, source trims, editable text/strokes, story pages and
story-state checks were already implemented. They are no longer missing foundations.

The new [offline factory](OFFLINE-FACTORY.md) adds a manifest-driven mixed batch of
existing GIFs and local layer scenes, exact source/output hashes, decoded-GIF previews,
a script-free local gallery and a readback-verified ZIP. It does not yet provide
video review reels, lenticular A/B transitions, raster handwriting reveal, physical
page turns or event-based SFX mixing. Those remain separate, testable next steps.

The latest independent upstream comparison used GIF Factory `ff9b8ae`: ten routing
choices and 75 unique example files, including 19 signatures. These counts are not
ten animation engines or proof that every example can be regenerated automatically.
The earlier showcase/star counts below belong only to their original snapshot.

## The systems start from different sources

GIF Cinema generates short animated GIFs through its existing direct OpenAI workflow,
then inspects and assembles reviewed takes. It has bounded request budgets, durable
attempt records, explicit handling of uncertain billable outcomes, hash-verified
reuse, endpoint inspection, film scripts and offline MP4 assembly.

GIF Factory primarily asks an image-generation tool for artwork or pose atlases,
then runs local Python/Pillow exporters. Its ten style entries are routing and
production choices, **not ten independent generation engines**:

- Pixel light motion and pixel consecutive actions.
- Illustrated character actions.
- Photographic people and pets.
- Clay mascots.
- Lenticular two-state cards.
- Type-linked posters and integrated comic-print posters.
- Compact storybooks.

Brand films are a separate extension. A style name or prompt alone cannot deliver
functional parity. Conversely, moving an entire still image does not reproduce a
requested full-character gesture. Keep direct OpenAI generation as the default;
imported/locally composed material must be labeled honestly.

## Capability matrix

| Capability | GIF Factory evidence | GIF Cinema baseline and remaining gap |
|---|---|---|
| Appearance, movement and purpose selected separately | `SKILL.md`, `styles/catalog.json`, ten `STYLE.md` routes | Cinema has story/generation/review guidance, but no comparable validated style catalog or explicit route matrix. |
| Direct model-generated animated GIF | Upstream main workflow uses generated still/pose art plus local exporters | Cinema already supports direct OpenAI GIF generation and still-conditioned scripts. Preserve it; no new provider is needed. |
| Atlas-based light-motion sticker packs | `export_pack.py`: per-entry sprite, preset motion, fixed local captions, HD/pixel modes | No public pack-manifest compiler/exporter in the baseline. Native model output and optional layered editing are different capabilities. |
| Consecutive key poses with one common crop/scale | `export_keyframes.py`, `export_pixel_actions.py`; shared union bounds prevent per-pose zoom/jump | Missing imported-atlas/keyframe composition route. If added, retain source coordinates; do not pretend a sprite warp is a new limb pose. |
| Native-resolution full-frame visual review | `review_gif.py`: frame extraction, face crops, stepping, revision-bound checklist | Baseline supplies endpoints and contact sheets, not a complete per-frame review pack. This change adds the independent [review helper](GIF-REVIEW.md), with bounded sheets and separate general/sticker profiles. |
| Transparent sticker verification | Export checks alpha, margins, loop, count and duration | No sticker delivery contract in the baseline. New review profile checks existing GIFs but does not create or remove backgrounds. |
| Batch delivery | Categorized GIFs, offline gallery, verified ZIP; decoded-GIF MP4 previews | Cinema exports individual scenes/film/chapters; a manifest-driven sticker pack and distinct-entry validation remain missing. |
| Lenticular A/B flips | `export_lenticular.py`: already-aligned states, narrow-strip transition, shared palette, exact duration | No two-state strip exporter. Needed: input ratio/alignment contract, fixed-information mask, duration audit and palette regressions. It must not imply automatic face registration or a generated second state. |
| Character/type poster loops | Upstream 720×960 examples switch two complete poster states | No corresponding packaged route. Upstream examples are **not independently animated editable glyphs**, so that should not be claimed as a parity requirement already solved there. |
| Editable typography/layer animation | Upstream describes a separate compositor route when real layers are needed | Cinema's baseline title helper makes separate title shots, not in-scene typography. Integrate the existing motion/layer work before adding a second renderer. |
| Compact story pages | Dedicated skill, fixed-camera once-only action, separate horizontal/vertical layouts, inspection helper | Storyboard/take compiler and chapters exist; physical book layout, once-only page playback and turns are not on this baseline. A pending story-pages change must be evaluated separately from shipped main. |
| Handwriting and synchronized writing sounds | Production references and the tea-party case; external compositing | Not a shipped baseline feature. Add only after precise editable local text, page timing and imported audio work. Do not substitute a text fade for handwriting. |
| Brand films | Mascot action causes a prop change; editable layered project and 15-second bakery case | Cinema's story scripts are a base, but public baseline lacks editable prop/contact/layer choreography. Reuse the current layer/audio effort and add action/prop-state contracts. |
| Sound | Imported external music plus local editing; upstream does not bundle music-generation services | Cinema can import local audio through film scripts. No reason to add Suno/Gemini/Higgsfield for parity. Mixing/ducking/SFX are distinct unfinished editing features. |
| Visual acceptance and repairs | Explicitly separates technical checks, assistant review and user acceptance; rejected examples stay rejected | Cinema already documents that distinction; this change makes per-frame review records executable. Neither project automatically guarantees identity, anatomy, physics or aesthetic quality. |
| Durable generation safety | No equivalent accounting layer established in the inspected upstream exporter scripts | Cinema's bounded requests, unknown-outcome blocking and cached-shot hashes are strengths to preserve. |
| Showcase scale | README reports 244 existing chat examples + 2 pending remakes, 9 cards and 13 posters, plus narrative cases | Cinema has far fewer style demonstrations. A larger gallery requires genuinely distinct, reviewed outputs, not renamed duplicates or copying upstream IP. |
| Install/reproduce | Upstream skill + scripts + manifests and production notes | Cinema has a package, CLI, offline source example and multi-platform test matrix. New helpers still need packaging/discoverability integration and clean-checkout verification. |

## Engineering order and acceptance gates

1. **Review the delivered bytes.** Land the full-frame review helper and add it to
   the skill package after package changes are coordinated. Gate: all native frames
   retain decoded pixels/timing/alpha; stale review cannot survive a changed source;
   no check labels technical success as visual or user acceptance.
2. **Finish the existing editing foundation.** Integrate the pending story-page,
   native-motion and consolidated layer/audio work once authorized and green on the
   actual target commit. Do not create duplicate motion engines or count draft PRs
   as main-branch functionality.
3. **Add a local asset-pack contract.** One versioned manifest with source hashes,
   per-entry identity/action/caption, purpose, expected count and status. Export
   existing GIFs into a verified ZIP/gallery first. Add imported keyframe/atlas
   composition as an explicit optional route with common coordinates, pixel/HD
   sampling, fixed local captions and clean alpha. Gate: distinct real actions,
   no source mutation, correct durations, no crop-induced identity jitter.
4. **Add two-state cards/posters.** Implement narrow-strip A/B transitions and a
   shared palette; lock fixed text regions. Gate: full endpoints visible, exact
   accumulated timing, stable dark backgrounds/skin/text, no transparent-index holes.
   Start with original geometric fixtures, then authorized art. This needs no model
   calls when the states already exist.
5. **Expose a style chooser backed by runnable recipes.** Separate appearance,
   movement and purpose. Every available recipe links its input schema, local
   command, real output and review status; every unimplemented route is labeled.
6. **Complete narrative formats.** Reuse approved page/action assets for horizontal
   and vertical layouts. Add once-only actions, result holds, page transitions,
   exact local typography, optional handwriting and imported audio. Gate: real
   6 fps means decoded cadence, not a label; no repeated footage to pad a story.
7. **Build representative original samples.** One technically verified and visually
   reviewed example per supported route before large batches. New generation still
   requires explicit budget/model authorization. Report observed output quality,
   not a promise that the model will reproduce it for every person or character.

## What “better” can mean measurably

- A review bundle supports opaque cards and play-once stories as well as stickers.
- A selected take is tied to exact source bytes and its neighboring transitions.
- Manifests preserve provenance, sources, references, timing, editable text and
  accepted/rejected status across retries.
- GIF palette/timing/alpha regressions are tested using decoded final pixels.
- Local-only operations never require an API key or accidentally dispatch a request.
- A published example can be rebuilt from authorized portable assets, with the same
  requested dimensions, count and timing; withheld/private tooling is not implied.

## Rights and limits

GIF Factory's scripts and skill documents are MIT-licensed. Its README separately
warns that character IP, third-party pictures/illustrations, music and fonts do not
inherit those software rights. Reimplementing a technique or properly attributed
MIT reuse is different from redistributing its whole gallery. GIF Cinema's existing
source-available license is unchanged. No upstream gallery media or font is included
in this change, and no private commercial engine is introduced.

Sources: [skill](https://github.com/WoYun520/gif-factory/blob/main/SKILL.md),
[style catalog](https://github.com/WoYun520/gif-factory/blob/main/styles/catalog.json),
[keyframe workflow](https://github.com/WoYun520/gif-factory/blob/main/references/keyframes.md),
[lenticular workflow](https://github.com/WoYun520/gif-factory/blob/main/references/lenticular.md),
[poster workflow](https://github.com/WoYun520/gif-factory/blob/main/references/dynamic-posters.md),
[brand-film workflow](https://github.com/WoYun520/gif-factory/blob/main/references/brand-film.md),
[storybook skill](https://github.com/WoYun520/gif-factory/blob/main/skills/compact-storybook/SKILL.md).

## Related projects worth studying

GitHub star counts below were checked on 9 November 2026. These are research
candidates, not installed dependencies or a claim that their techniques already run
inside GIF Cinema. No additional generation service or model was invoked.

| Project | Stars | Useful technique | Integration boundary |
|---|---:|---|---|
| [Remotion](https://github.com/remotion-dev/remotion) | 71,873 | Explicit time-based compositions, reusable layers, editable typography and previews | [Custom license](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md): free eligible individuals/small organizations; company license otherwise. Selling/relicensing a derivative is disallowed. Study architectural ideas, do not copy its code into a competing toolkit. |
| [ToonCrafter](https://github.com/Doubiiu/ToonCrafter) | 6,059 | Generative cartoon in-betweens between illustrated endpoints | Apache-2.0 repository; research prototype, not a quality guarantee. README reports about 24–27 GB GPU memory in its implementation and lower-memory community variants. No model/weight integration proposed for the direct-OpenAI default. |
| [gifski](https://github.com/ImageOptim/gifski) | 5,696 | Cross-frame palettes and temporal dithering for high-quality GIF encoding | AGPL-3.0-or-later, with alternative commercial licensing. Evaluate output quality and license compatibility before any embedding or redistribution. More colors do not repair the animation itself. |
| [RIFE](https://github.com/hzwer/ECCV2022-RIFE) | 5,671 | Intermediate-flow frame interpolation | MIT repository. Optional postprocessing research only; interpolation can create ghosting and cannot repair missing anatomy or a wrong action. Check actual weights and dependencies before reuse. |
| [Gifsicle](https://github.com/kohler/gifsicle) | 4,350 | GIF optimization, manipulation and compact frame storage | GPL-2.0 repository; inspect redistribution/integration requirements. Compare decoded output and timing, not file size alone. The separate `giflossy` project was merged into Gifsicle. |
| [gbro-collage-broll](https://github.com/pyang5166/gbro-collage-broll) | 1,858 | Small numbers of objects assemble into a causal visual metaphor; design first/last states before motion | MIT. Its provided generation route uses Gemini Omni Flash; borrow composition/story design without changing the authorized OpenAI workflow or executing that provider. GIF Factory itself cites this method. |

For immediate zero-API progress, prioritize output verification, common-coordinate
composition and tested palette/export behavior. Treat model-based interpolation as
an explicitly labeled optional experiment after the actual character motion is
acceptable. Star count alone is not a reason to add infrastructure or dependencies.
