# Real GIFs, a short story, and the path to a longer film

This is an **offline editorial demonstrator**, not a new generation or editor release.
It uses three existing GPT-generated astronaut GIFs from the bundled skill. No
provider request, paid model call, downloaded art, or fabricated generation occurs.
All public-facing story text is English.

## Run it

From a repository checkout, with Python 3.10+, Pillow 10.1 or newer, FFmpeg and
ffprobe installed. The optional demo needs Pillow 10.1 for scalable default text;
the core package still supports its existing minimum. No new font file is needed:

```sh
python -m pip install "Pillow>=10.1"
python tools/build_story_demo.py --out output/my-story-demo
python -m unittest discover -s tests -p test_story_demo.py -v
```

The output directory must be new. Open `a-reply-from-the-stars.mp4`. The folder also
contains a poster, contact sheet, original source joins, and a receipt with hashes,
the exact source-frame trace, timing, and technical verification. Source GIFs remain
unchanged. The demo uses the already committed files under
`.agents/skills/gif-cinema/assets/example/`; it is a checkout-only example, not a
wheel-packaged demo. Text uses Pillow's own scalable default font, recorded alongside
the Pillow version in the receipt. Reproducible pixels require the same Pillow/font
and media-tool versions; encoded bytes may differ between environments. The builder is a fixed example; it does not silently add capabilities to
`gif-cinema render`. It imports only the existing public GIF validator and
Pillow, not the unpublished motion, font or layer modules. Generated MP4/PNG
artifacts stay under the ignored local output directory and are not added to Git.

## What the example actually shows

**12.24 seconds, 1024 × 576, 25 fps, silent.**

1. An astronaut raises a hand: a signal.
2. A star appears above the greeting: a reply.
3. A hand comes to the heart: acknowledgement.

Each source has 16 native drawings, held for 160 ms each. All 48 drawings play once,
forward, in order. The subject still changes at **6.25 native drawings per second**;
25 fps is the presentation and design grid, not newly generated or interpolated
character motion.

The 12.24 seconds comprise:

- 7.68 s of original action.
- 1.20 s of establishing holds, 0.40 s per shot.
- 2.40 s of result holds, 0.80 s per shot.
- 0.96 s for two editorial chapter slides, 0.48 s each.

The local design adds narrative typography, page numbering, a subtle 2.5% whole-image
push, and chapter changes. Each transition freezes the old last pose and the new
first pose. It does not morph between characters, invent action, reverse footage,
or run the same gesture repeatedly to inflate the length.

## Visual assessment

The astronaut is recognizable across the three selected scenes and the sequence has
a beginning, response and payoff. The framing deliberately changes from a wide shot
to a close-up and back. Helmet/hand/suit details and character proportions are not
identical between independently generated sources. This is a readable short story,
not a claim of seamless character animation. Native held poses remain visibly stepped.

The chapter slides make the edit legible but do not repair continuity. Inspect
`original-joins.png` without the design around it, then watch the actual movie.
Successful decoding and low pixel differences are not visual acceptance.

## Why three GIFs cannot become a genuinely long story

A 60-second file could be made by replaying, reversing or slowing these three clips.
That would not provide a minute of new narrative action. This demo does not do that.

For a real longer film, create and review more distinct beats first. At these source
durations, 24 shots supply 61.44 s of native action before transitions. With modest
story-reading/result holds and chapter changes, roughly 15–20 meaningful scenes can
support about a minute. That is a planning range, not a promise that every generated
take will work. Count failed takes and retakes separately.

A practical production sequence is:

1. Write a beginning, goal, complication, decision and payoff. Give every scene one
   real state change, not another arbitrary gesture.
2. Make a character/prop sheet and a state ledger. Record who holds each object,
   its count/location, gaze, camera, scale, first pose, action and final pose.
3. Test one representative action and its follow-up. Use a clean identity reference
   plus the reviewed preceding endpoint. Prompts alone do not establish continuity.
4. Generate the remaining scenes only within an explicitly authorized call budget.
   Keep approved shots immutable. If a middle shot changes, inspect both joins.
5. Assemble single-play actions with brief purposeful holds. Add design, transitions
   and licensed/user-provided sound separately. Recheck every scene and transition
   in the actual full export, including prop contact and source artifacts.

## What already exists, and what is missing

Available on the public main baseline `fa82b13366a9ae94a4ece730ec6b2d065cd9a060`,
plus this source-only patch:

- Source-only JSON scripts, real GIF ingestion, reference-conditioned shot generation,
  bounded request accounting, per-shot reuse/retakes, endpoint inspection and MP4 export.
- This optional fixed three-shot design example, using standard Pillow transforms
  and the public `validate_gif` decoder. It does not add a generic motion editor.
- The **existing 57.2-second cat showcase**, already in
  `docs/assets/showcase/cat-film.mp4`. It is a previously assembled and locally finished
  generated-shot film, not a new output of this demo builder. Its raw per-shot cat
  source GIFs and all private finishing logic are not supplied in this checkout, so
  it is evidence of the earlier film rather than a fully reproducible public workflow.

Still needed for a general author-friendly GIF story workflow:

- An editable story timeline connecting generated/imported GIF scenes and independent
  design layers. Main does not currently include a layered GIF compositor.
- A scene/state ledger and explicit review/accept/reject gates that keep approved
  footage and show continuity failures.
- Safe, inspectable cross-scene design transitions and timing in the shared script
  contract. Core `render` currently supports cuts only; the fixed builder's chapter
  slides are not general renderer support.
- Reproducible long-story source sets, editable scene recipes, and the licensed sound
  assets needed to reproduce a complete showcase.
- If smoother subject motion is desired, a separately evaluated interpolation route
  or more source poses. Camera moves and higher export FPS do not solve this.

## GIF Factory comparison, checked at an immutable revision

The reference is [WoYun520/gif-factory](https://github.com/WoYun520/gif-factory) at
`373c6a74ff28ef3a38aea225cbd5e02ef52fff6a`.

Its [Tea Party example](https://github.com/WoYun520/gif-factory/tree/373c6a74ff28ef3a38aea225cbd5e02ef52fff6a/examples/storybooks/tea-party)
is documented as **54 seconds, 12 pages, 1920 × 1080, actual 6 fps, 324 frames**, with
music and writing cues. Its method uses transparent character key poses, fixed
backgrounds, object paths/hand anchors and separately composed book turns. It is not
one long native video generation, and it does not claim interpolated character motion.

Its [compact-storybook instructions](https://github.com/WoYun520/gif-factory/blob/373c6a74ff28ef3a38aea225cbd5e02ef52fff6a/skills/compact-storybook/SKILL.md)
explicitly call for one meaningful action per page, a brief result hold, no automatic
reverse/repetition, and more meaningful pages for longer stories. They separate
page animation from outer design and require first/middle/last/contact checks.

Those are the useful production principles to carry forward. The reference's book
art, music and private inputs are not copied into this demonstration. No claim is
made that the two repositories have equivalent editors or rendering features.
