# Tips: make short GIFs feel like a scene

[← README](../README.md) · [Try the example](../examples/film.json) · [Script format](SCRIPT-FORMAT.md) · [Before / after](SHOWCASE.md)

Start with a tiny story you can judge in motion: an action, a response, a payoff.
Get three short shots working together before expanding the film.

## 1. Give each shot one readable action

Split a busy request into clear beats. For a cat at a window:

| Shot | Start | Main action | End |
| --- | --- | --- | --- |
| Walk | Cat on the floor, facing the window | A few coordinated steps | Gathered crouch below the sill |
| Jump | The same crouch | One complete jump | All paws land on the sill |
| Sleep | Cat settled on the sill | Curl up and close its eyes | Resting pose |

Describe the first and last poses explicitly. Leave time for anticipation and
landing; these contacts make an action easier to read. Keep head, paws and the
whole jump arc inside the frame.

For a resting character, give the shot a small visible action such as restrained
torso breathing or one ear reaction. Keep the face, paws and camera stable so the
motion reads as life rather than a change of body size.

## 2. Decide what stays fixed

For a continuous action, keep the camera, horizon, subject size, light and action
direction stable. Pick a visible anchor such as the window edge or floor line.
Compare the subject's position relative to it at every cut.

A deliberate wide-to-close cut can work. Review it as a change of camera position;
matching the subject's screen coordinates alone does not establish continuity.

## 3. Keep a clean identity reference

Use a clean approved still for appearance and the reviewed previous last frame for
the next shot's starting composition. Explain each reference's role. Inspect the
endpoint for new spots, altered costume details, extra limbs or changed props before
passing it onward. Return to a clean approved image when drift accumulates.

The public script accepts local PNG/JPEG/WebP references. Paths resolve relative to
the JSON script. Reference files must already exist when the next script is validated;
the public release uses an explicit, manually reviewed chain.

Inspect a bundled GIF and extract its endpoints from the repository root:

```bash
python -m gif_cinema inspect .agents/skills/gif-cinema/assets/example/shot-01.gif
python -m gif_cinema endpoints .agents/skills/gif-cinema/assets/example/shot-01.gif -o output/tips-review/shot-01
```

This creates `shot-01-first.png` and `shot-01-last.png`. Use a fresh output prefix
for another review so the earlier images remain available.

## 4. Separate drawing cadence from export FPS

The bundled shots each contain **16 drawings at 160 ms**: 2.56 seconds per shot,
or 6.25 native drawing updates per second. Exporting at 25 fps produces repeated
frames between those updates. It does not add newly generated poses.

Longer frame delays hold drawings for longer. A small speed change can alter the
rhythm, but it also changes action timing. Interpolation can add intermediate frames
and can introduce trails, double contours or malformed contacts. Watch paws, hands,
tails and moving props at full speed as well as in individual frames.

The public CLI supports 2–16 requested GIF frames. Account/model acceptance still
depends on the actual API request. The private finishing used in the showcase is
separate from this release; see [the comparison methods](SHOWCASE.md).

## 5. Judge both cuts around a retake

Watch the previous shot → replacement → next shot together. Check:

- Identity, markings, costume and prop shape.
- Subject scale, horizon, camera geography and movement direction.
- Pose handoff, contact and cause-and-effect: a bird should visibly leave the frame
  if its exit matters to the story.

For a **prompt-based** shot, retain the original script, shot ID and render directory.
After reviewing the dry-run, an explicitly authorized retake can use:

```bash
python -m gif_cinema render my-film.json --execute --out output/my-film --force-shot 02-jump --max-api-calls 1 --retries 0
```

That command can make a paid request. The ID must exist in your own script.
`--force-shot` applies to generated shots; the bundled import-only example instead
lets you choose another GIF as a shot's `source`. Keep separate scripts/output
directories for alternate candidates and retain the old selection for rollback.

Changing a middle shot does not silently regenerate its neighbors. If its new ending
changes a downstream reference, review that dependency and the second cut explicitly.

## 6. Compare settings with a clear question

Keep the action and references stable while changing one setting. Compare the result
in motion: did contact improve, did the prop stay present, did the framing hold?
More computation or more takes does not establish that a replacement is better.

Use a dry-run and an explicit call cap. The cap counts attempts, including retries;
token usage is not a fixed dollar price. Include discarded takes and reference
creation when estimating a complete experiment's cost. Keep keys in your local
environment and review prompts before sharing manifests.

## 7. Build length from reviewed beats

For a longer story, add meaningful actions, reactions and cutaways. Review short
sections before joining them. The public v1 script accepts up to 64 shots; it does
not include the private chapter system or autonomous hour-long film creation.
Extending a GIF's delay mainly extends held poses.

## 8. Finish with the exact export

Try the included film without a key:

```bash
python -m gif_cinema render examples/film.json --dry-run
python -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/tips-first-film
```

Play `film.mp4` all the way through. Inspect its contact sheet and first/last PNGs,
then repeat the same command to check reuse. A valid MP4 and a low pixel-difference
score establish technical facts; character identity and story continuity still
need visual review. [Current verification and limits](../STATUS.md).
