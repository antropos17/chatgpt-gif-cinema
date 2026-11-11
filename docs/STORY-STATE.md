# Authored continuity ledger

Keep explicit facts about character identity, costume, props and geography across
an entire shot list. `story-state` carries those declarations forward and points
to the shot that last changed a conflicting fact. It works without a key, network,
FFmpeg, generated footage or changes to the storyboard format.

**This checks authored facts, not the pictures.** A consistent ledger does not
prove that a GIF depicts its targets, preserves a character, or passes visual
review. It cannot infer facts from prose or discover undeclared mistakes. Existing
source files are hashed, not decoded, by this command. Keep using the film render,
full-frame and cut-review workflows for the actual footage.

## Try the two examples

From a repository checkout:

```bash
python -m gif_cinema story-state check \
  .agents/skills/gif-cinema/assets/example/storyboard.json \
  examples/story-state-astronaut.json
python -m gif_cinema story-state check \
  .agents/skills/gif-cinema/assets/example/long-story.plan.json \
  examples/story-state-lantern.json
```

The astronaut ledger records **desired storyboard states**, not newly verified
visual observations. It binds the three existing GIFs by exact SHA-256. The title
is included in shot order but creates no character action. The lantern ledger
tracks eight declared facts over all 14 planned actions, including the lantern
moving from crate to fox to ground, the moth's arrival, and the unchanged scarf.
All 14 lantern shots remain unrendered. These examples make zero provider calls.

To see a conflict, copy the lantern ledger and change shot `13-wave`'s requirement
for `lantern.holder` from `ground by tree` to `fox`. The checker reports that
`11-place:changes` last set the carried value. It does not silently move the prop
back or modify a source file.

## Start a ledger for your project

```bash
python -m gif_cinema story-state init PROJECT/storyboard.json -o PROJECT/state.json
# Edit state.json with the facts and transitions you intend to track.
python -m gif_cinema story-state check PROJECT/storyboard.json PROJECT/state.json \
  -o PROJECT/state-report.json
```

`init` creates a blank ledger with every shot ID, story fingerprint and exact
source hashes. The template is deliberately **untracked**, never a successful
continuity check. `check` writes nothing unless `-o` is given. Outputs must be new
files, including reports. There is no force/overwrite or paid execution option.

Use either a version 1 story-helper storyboard or a version 1 runtime film script.
This command checks their shot IDs/order and source paths, not all generation or
render settings. Run the corresponding compiler or `render --dry-run` separately.
Local source paths resolve relative to the story file, not the ledger or current
working directory. Sources need not be in the same directory. URLs are rejected.

## Ledger contract

Top-level fields are `schema_version` (integer 1), `story_sha256`, `source_hashes`,
`facts` and `shots`. Unknown ledger fields and duplicate JSON keys are rejected.

A fact has an `id`, a nonempty string `initial`, and optional boolean `fixed`.
IDs are `entity.attribute`, for example `lantern.holder` or `fox.scarf`. Each part
uses 1–40 ASCII letters, digits, underscores or hyphens and starts with a letter or
digit. IDs are case-sensitive in references and unique ignoring case. Values use
exact string equality: choose one spelling for each state and use it consistently.
A fixed fact cannot change. Separate related facts only when you intend to check
them separately; the checker does not know that `holder: fox` implies a location.

Every shot must appear exactly once in the original order. Its fields are:

- `shot_id`: exact story ID.
- `requires`: fact/value pairs expected at this shot's start.
- `changes`: a list of `{fact, from, to, reason}` transitions during this shot.
- `handoff_changes`: the same shape, for an explicit offscreen change or time jump
  before the shot. Explain the intentional discontinuity in `reason`.

The last three fields default to empty. Changes require declared facts and
nonempty reasons. A fact can change once per phase. Handoffs apply first, then
requirements, then within-shot changes. Both kinds of changes must match the
carried `from` value and obey fixed facts. A rejected change is reported and is
**not applied**. The checker continues to show downstream consequences, not a
repaired story. Facts omitted from a shot carry forward unchanged, even through
shots in another location. Omission is not evidence that a fact was observed.

The report includes each full before/after state, the last setter of each fact,
all conflicts, and `shots_without_requirements` so sparse coverage stays visible.
A shot with no requirements does not check its incoming state, even if it declares
an outgoing change. Human review of the intended action remains necessary.

## Results and retakes

- `declared-facts-consistent`, exit 0: there are facts and at least one requirement,
  with no declared contradiction. This is not full story coverage or visual approval.
- `conflicts`, exit 2: at least one requirement/change disagrees with a carried or
  fixed fact. The report is still available.
- `untracked`, exit 2: no facts or no requirements. Fill the template first.
- Invalid input, stale story/media or output collision: exit 1, no new report.

`story_sha256` is the SHA-256 of canonical JSON (sorted keys, compact separators,
UTF-8, no ASCII escaping). It covers all story fields but ignores whitespace, key
order and line-ending changes. `source_hashes` pins every source shot's bytes.
An existing storyboard `source_sha256` is checked too. The report additionally
fingerprints the ledger. These are local content checks, not signatures.

A retake, changed order or edited action invalidates the old ledger. Create a new
blank template at a new path, deliberately reconcile the authored facts and
requirements, and review changed footage and both adjacent cuts. Do not blindly
replace hashes to turn a stale result green. Generated shots' referenced still
images are not pinned by this sidecar; generation preflight owns their checks.

Limits: 1 MiB for each JSON input, 1–64 shots, 128 facts, 128 requirements/changes
per shot/phase, 256 characters per value, 1,000 per reason, 128 MiB per source and
512 MiB across sources. Inputs must be regular local files. No media is rewritten
or copied, and no extra drawings or character actions are created.

For actual authored hand/prop layer composition, use [prop anchor tracks](PROP-ANCHORS.md).
The ledger checks declared facts across shots; attachments position existing layers
within one scene. Neither tool interprets the pictures or generates missing actions.
