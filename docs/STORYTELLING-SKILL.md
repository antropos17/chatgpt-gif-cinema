# Multi-scene stories and motion-design GIFs

[Back to GIF Cinema](../README.md) · [Skill instructions](../.agents/skills/gif-cinema/SKILL.md)

GIF Cinema's current repository skill can plan a longer animated story, prepare
individual generation inputs, assemble accepted GIF takes, add local animated title
cards, and export MP4 and GIF. It is a production workflow with executable helpers,
not a new animation model or a promise of automatically smooth character motion.

## Two examples, two different claims

**Runnable source edit:** the bundled astronaut example uses three existing GIFs
and a locally animated title. It exports a 9.68-second silent MP4 at 512 × 512,
25 fps; the default 320 × 320 GIF is 9.70 seconds at 10 fps. The three character
clips still contain only 16 source drawings each. Output FPS is not new animation.
All steps below run locally with zero API calls.

**Long-story plan:** *The Lantern Delivery* has 14 distinct intended actions: discover,
open, lift, light, arrival, point, approach, test, cross, reach, place, settle, wave,
and leave. Its requested 14 × 2.56-second takes total 35.84 seconds. These scenes
have **not been generated**. The planner emits 14 individual request scripts and an
assembly template with missing media explicitly identified. It does not execute a
paid batch or present a storyboard as a finished cartoon.

## Try the current repository skill

Install the repository runtime using the main README, then run from the repository
root. `PYTHONPATH=.` lets the standalone skill helper import that checkout's runtime
without altering another Python environment (Windows: set the equivalent environment
variable, or use the installed runtime).

```bash
PYTHONPATH=. python .agents/skills/gif-cinema/scripts/story_project.py compile \
  .agents/skills/gif-cinema/assets/example/storyboard.json --out output/story-project
python -m gif_cinema render output/story-project/film.json --dry-run --max-api-calls 0
python -m gif_cinema render output/story-project/film.json --execute --max-api-calls 0 --out output/story-render
PYTHONPATH=. python .agents/skills/gif-cinema/scripts/story_project.py export-gif \
  output/story-render/film.mp4 --out output/story.gif --width 320 --fps 10
```

The project includes the editable storyboard, readable shot list, copied footage,
generated title GIF, runtime script and timing/source report. The runtime adds a
contact sheet, first/last frames, continuity review, SRT and verified MP4. Run render
again with the same arguments to check zero-call resume.

Prepare the longer plan without generating any shot:

```bash
PYTHONPATH=. python .agents/skills/gif-cinema/scripts/story_project.py compile \
  .agents/skills/gif-cinema/assets/example/long-story.plan.json --out output/lantern-plan
```

See [the exact helper schema and limits](../.agents/skills/gif-cinema/references/story-project.md).
The independent [existing-GIF story demo](GIF-STORY-DEMO.md) is a separate fixed edit,
not the generic planner or a newly generated long cartoon.

## From a brief to a finished story

1. **Plan changes, not padding.** Write the ending, causal beats, and first/action/last
   state of each short shot. A repeated clip with another caption is not a new action.
2. **Fix the visual bible.** Keep identity, materials, palette, costume, prop ownership
   and geography explicit. Preserve the requested style rather than forcing pixel art.
3. **Prepare only missing actions.** Compile existing sources or individual generation
   inputs. Check actual API/tool support and the authorized call budget before execution.
4. **Review and accept takes.** Inspect identity, contacts, incoming/outgoing poses,
   and cause/effect. A clean reference and an accepted last frame can guide another
   shot; they do not guarantee continuity.
5. **Edit and deliver.** Replace planned shots with accepted source paths, compile a
   new source-only project, assemble the MP4 with a zero-call cap, then export the GIF.
   Review the final encoded files, not just the source frames.

The title renderer supplies a once-only text entrance and animated accent rule, with
an editable hold. It does not provide layered prop animation, generated poses,
interpolation, automatic transitions, sound generation or a rigged character engine.
For those requirements, use a genuinely available compositor or generation service
and describe its role. Source-only editing can proceed when generation is unavailable.

## Package and verify the skill

The previously published `skill-v0.1.1` ZIP is an older skill. To package the current
repository version, including examples, scripts, references, license and notices:

```bash
python tools/package_skill.py --out dist/gif-cinema-story-skill.zip
python -m unittest discover -s tests -p test_story_skill.py -v
```

The ZIP is deterministic, has a single `gif-cinema/` root, and contains only an
explicit resource allowlist. Extract it into the agent's skill folder. Follow its
runtime setup, then use the same compile/render/export sequence. The pinned runtime
is immutable; no API access or model availability is implied by a successful install.

The story workflow is informed by [GIF Factory](https://github.com/WoYun520/gif-factory),
particularly its separation of style/movement/purpose and once-only causal actions.
Its MIT notice is preserved in the skill's [third-party notices](../.agents/skills/gif-cinema/THIRD_PARTY_NOTICES.md).
No GIF Factory artwork, fonts or exporter code are bundled. GIF Cinema keeps its own
[source-available evaluation license](../LICENSE).
