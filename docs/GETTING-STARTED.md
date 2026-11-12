# Getting started with GIF Cinema

[Project overview](../README.md) · [Script reference](SCRIPT-FORMAT.md) · [Story workflow](STORYTELLING-SKILL.md)

Make your first film with the included footage, then decide whether you need new
animation. You can use the CLI directly; an agent is optional.

[Install](#1-install-from-this-repository) · [No-key film](#2-make-a-film-without-a-key) · [New GIF](#3-generate-one-new-gif-directly-with-openai) · [Agent skill](#4-let-your-agent-use-the-workflow) · [Troubleshooting](#troubleshooting)

| Start with | What happens | OpenAI API calls |
| --- | --- | --- |
| Included GIFs | Assemble a real 7.68-second MP4 and review its cuts. | **0** |
| Your own GIFs | Inspect and assemble existing animation locally. | **0** |
| A new action | Request a native GIF directly from OpenAI, then assemble it. | Paid, account/model access required |

“No API calls” means no new generation charges, not free hosted compute or bundled
API credits. The public toolkit has no hosted editor. Finished showcase comparisons
use additional local postproduction that is not included in the CLI.

## 1. Install from this repository

You need **Python 3.10 or newer**, Git, and Pillow. Exporting movies also needs
**FFmpeg and ffprobe**, including FFmpeg's `libx264` encoder. Get video tools through
[FFmpeg's official download page](https://ffmpeg.org/download.html) and put both
executables on your PATH. They are separate from the Python package.

```bash
git clone https://github.com/antropos17/chatgpt-gif-cinema.git
cd chatgpt-gif-cinema
python -m venv .venv
```

On macOS/Linux, use `python3` in the last command if `python` is unavailable, then
activate the environment:

```bash
source .venv/bin/activate
```

In Windows PowerShell, activate with:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you do not need to change its execution policy.
Use `.\.venv\Scripts\python.exe` instead of `python` in the commands below.

Install and check the tools, from the repository root:

```bash
python -m pip install .
python -m gif_cinema doctor
python -m gif_cinema --help
ffmpeg -version
ffprobe -version
```

The doctor checks local Python, Pillow, FFmpeg and configuration without sending
requests or printing the API key. It does not verify provider access or billing.

These instructions install this checkout, not an assumed PyPI release. Keep the
checkout: examples and standalone skill scripts are repository files, not commands
installed into the Python package. The CLI is also available as `gif-cinema` when
the environment's executable directory is on PATH.

## 2. Make a film without a key

Plan first, then assemble the three included astronaut GIFs:

```bash
python -m gif_cinema render examples/film.json --dry-run --max-api-calls 0 --out output/my-first-film
python -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/my-first-film
```

The plan should report `minimum_new_api_calls: 0` and three `import` actions.
Planning does not write output, use the network or require FFmpeg. Execution checks
the video tools, copies and verifies the sources, and encodes the movie. The explicit
zero-call cap prevents generation even if a key is already configured.

Open `output/my-first-film/film.mp4`. It is a **7.68-second, 512 × 512, 25 fps,
silent MP4**. The folder also contains:

- `contact-sheet.png` and each shot's first/last PNGs for cut review.
- `continuity-report.json`, with every join still requiring human review.
- `captions.srt`, a separate subtitle file, not text burned into the video.
- `film-inspect.json`, `receipt.json`, and `render-manifest.json` with technical
  verification, call accounting and reusable shot records.

Run the execution command again unchanged. It should reuse all three verified
shots, with `api_calls: 0` and `skipped: 3` in the new receipt. Keep the entire render
folder, including its saved GIFs and manifest, for resume and chapter export.

Each original take has 16 drawings held for 160 ms. A 25 fps movie preserves those
holds; it does not invent 25 new poses per second. Watch the whole movie and compare
both sides of each cut. A successful decode is not continuity approval.

### Export a shareable GIF

The repository's story helper can convert the completed MP4 locally:

```bash
python .agents/skills/gif-cinema/scripts/story_project.py export-gif output/my-first-film/film.mp4 --out output/my-first-film.gif --width 320 --fps 10
```

This produces a silent 320-pixel-wide GIF, play-once by default. Its timing is rounded
to the GIF frame grid and may differ slightly from the MP4. Add `--repeat` only to
loop the whole edit; some viewers override GIF loop behavior. Choose a new output
filename when exporting again.

For an editable animated title, take selection, or whole-shot GIF chapters, continue
with the [zero-call story walkthrough](STORYTELLING-SKILL.md#try-the-current-repository-skill).

### Bring your own footage

First inspect a GIF and extract its endpoints:

```bash
python -m gif_cinema inspect path/to/your-shot.gif
python -m gif_cinema endpoints path/to/your-shot.gif -o output/your-shot
```

The second command writes `output/your-shot-first.png` and
`output/your-shot-last.png`; use a new prefix for another take. For a quick montage:

```bash
python -m gif_cinema film path/to/shot-a.gif path/to/shot-b.gif -o output/my-montage.mp4 --width 512 --height 512 --fps 25
```

`film` is a local encoder, not a generator, and does not make the script renderer's
manifest or review reports. For those, copy [examples/film.json](../examples/film.json)
to a project folder, replace its `source` paths, shot IDs and target descriptions,
then use `render` with a zero-call cap. **Source and audio paths resolve relative to
the JSON script**, not the shell. Keep inputs outside the render output directory.
Imported GIFs use their actual frame delays; remove generation fields such as
`frames`, `duration_ms` and `model` from imported shots.

## 3. Generate one new GIF directly with OpenAI

This is optional and can incur charges. You need your own OpenAI API key, billing,
and current access to a model that accepts native GIF output. A ChatGPT subscription
or successful package install does not establish that API access. This adapter sends
requests directly to `https://api.openai.com`, with no intermediate generation service.

The public code accepts the model labels `gpt-image-2.6-flare` and
`gpt-image-2.6-sunburst`. These names are not a guarantee of availability for your
account. The repository's successful live tests are account-specific and dated;
see [verification status](../STATUS.md). No new live request was needed to verify
this onboarding guide. If access is unavailable, the no-key workflow above still works.

### Review the request without spending

The included [first-shot.json](../examples/first-shot.json) asks for **one fox raising
one paw**, targeting 16 frames × 160 ms = 2.56 seconds. Its opening and closing
states are instructions, not verified observations.

```bash
python -m gif_cinema render examples/first-shot.json --dry-run --max-api-calls 0 --retries 0 --out output/first-shot
```

Expect one `generate` action and `minimum_new_api_calls: 1`. A dry-run can describe
that request even with a zero cap because it sends nothing. It checks the script,
not model access or dollar cost. Review the prompt, model and settings in the JSON
before proceeding. The complete [script contract](SCRIPT-FORMAT.md) lists limits.

### Configure the key in this terminal

On macOS/Linux, read it without echoing it or putting the key itself in shell history:

```bash
export OPENAI_API_KEY="$(python -c 'import getpass; print(getpass.getpass("OpenAI API key: "))')"
```

In Windows PowerShell:

```powershell
$secret = Read-Host "OpenAI API key" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secret).Password
Remove-Variable secret
```

The CLI reads `OPENAI_API_KEY` from the current process environment. **It does not
load `.env` automatically.** Copying `.env.example` is not enough. `GIF_CINEMA_MODEL`
sets the default for `generate` and generated script shots without an explicit
`model`. An explicit script model or `generate --model` takes precedence. The
included first-shot example already selects its model explicitly.
Do not paste a real key into a script, commit, issue, screenshot or shared terminal log.

### Execute only when you accept the charge

**The following command can send one paid request.** It is not another preview:

```bash
python -m gif_cinema render examples/first-shot.json --execute --max-api-calls 1 --retries 0 --out output/first-shot
```

The cap permits at most one request in this invocation, not one dollar or one
lifetime attempt. Usage is not a currency quote. No automatic retries are enabled
in this example. Inspect the output GIF, actual duration, endpoints and MP4 before
accepting the action. Its hashed GIF filename is recorded under
`shots` → `01-hello` → `output` in `render-manifest.json`.

A successful result can be checked and reused without permitting another request:

```bash
python -m gif_cinema render examples/first-shot.json --execute --max-api-calls 0 --retries 0 --out output/first-shot
```

If the first request has an unknown outcome, stop and review provider request/billing
history instead. Do not use `--force`, `--force-shot`, a fresh directory or a renamed
shot to work around that protection. An explicitly reviewed retake can cost again;
the [recovery contract](SCRIPT-FORMAT.md#execution-and-accounting) explains it.

When done, clear the session key with `unset OPENAI_API_KEY` on macOS/Linux or
`Remove-Item Env:OPENAI_API_KEY` in PowerShell. This does not revoke the provider key.

### Guide a following shot with still references

Use `render`, not the simpler `generate` command, for references. Add a
`references` array to a generated shot with existing local PNG, JPEG or WebP stills:
for example, `"references": ["character.png", "accepted-last.png"]`. Paths are
relative to that script. The runtime accepts 1–16 stills, at most 20 MiB combined,
and uses `/v1/images/edits`; animated GIFs are not valid references.

Inspect an accepted take's last frame before using it, keep the identity reference
clean, and say which image controls appearance versus pose. Referenced images are
sent to OpenAI with the prompt. References guide, but do not guarantee, identity or
action. There is no automatic last-frame dependency graph. See the
[reference workflow](SCRIPT-FORMAT.md#reference-conditioned-gif-scenes) before a batch.

## 4. Let your agent use the workflow

The CLI installation and agent skill are separate. From the checkout, package the
current skill, including its scripts, references and sample footage:

```bash
python tools/package_skill.py --out dist/gif-cinema-story-skill.zip
```

Extract the ZIP's single `gif-cinema` folder into:

- Codex: `~/.codex/skills/gif-cinema`
- Claude Code: `~/.claude/skills/gif-cinema`

Back up any existing installation before replacing it. Follow the packaged skill's
runtime setup; installing the skill alone does not install the CLI, Python or FFmpeg.
Run its `scripts/check_install.py` and no-key `scripts/smoke_media.py` to check the
actual extracted review/sprite installation. Its
helpers use paths relative to the skill folder, and project outputs belong outside
that installed folder. Source package 0.4.0 also includes offline collection and
lossless-master guides and smokes. Its full smoke requires the pinned `[lossless]`
runtime plus FFmpeg/ffprobe; `check_install.py --require-master` checks the optional
codec before output. Building this package does not publish a release. The older `skill-v0.1.1` release predates the current story
planner and chapter helpers. [Packaging details](STORYTELLING-SKILL.md#package-and-verify-the-skill).

Try asking your agent:

> Use the gif-cinema skill to assemble the included astronaut story with zero API
> calls. Deliver an MP4 and a small GIF, and show the frames on either side of each cut.

For new animation, ask for a plan first and explicitly agree to any paid request
budget. The 14-action *Lantern Delivery* example is an unrendered plan, not a finished
cartoon or a free generation batch.

## Troubleshooting

| Symptom | Check and next step |
| --- | --- |
| `No module named gif_cinema` | Use the same environment for `python -m pip install .` and execution; run from the checkout. With a non-editable install, source changes elsewhere are not automatically installed. |
| `python` or activation is unavailable | Use `python3` on macOS/Linux or `py -3` to create the Windows venv, then the venv's Python. Activation is optional if you use its full executable path. |
| FFmpeg/ffprobe is missing or `libx264`/filters are unavailable | Install a compatible FFmpeg build and check both commands in this terminal. `render --execute` checks media capabilities before a paid request. Planning needs neither tool. |
| Key configured in `.env`, but CLI still asks for it | Set `OPENAI_API_KEY` in the environment of the terminal or agent running the command. The runtime does not auto-load `.env`. |
| HTTP 401/403 or unsupported model/GIF settings | Check the account, key permissions and current model access with OpenAI. A dry-run cannot verify them; do not keep resubmitting or silently switch to another paid service. |
| HTTP 429 or call budget exhausted | Completed shots stay saved. The cap includes retry requests and resets for each invocation. Review the provider/account limit and approved budget before retrying. |
| Timeout, server error, interrupted request, or unknown cost | The provider may have generated and charged already. Preserve the manifest and check provider history before authorizing a retake. Restarting in a new folder is not a safe workaround. |
| Output exists, is busy, or has no valid manifest | Reuse a valid render with the same command; choose a new path for genuinely new work. Never remove a lock until its owning process has stopped. Do not overwrite accepted media to make a command pass. |
| Missing reference or source file | Resolve the path relative to the script, verify the file exists, and keep imports outside the render folder. References must be still PNG/JPEG/WebP. |
| GIF rejected during inspection | Inputs need at least two frames, each delayed at least 20 ms, and must fit the decoder's byte/frame/pixel limits. Convert questionable footage separately; do not just rename another file to `.gif`. |
| More FPS, but motion still looks stepped | Output FPS repeats/resamples existing drawings. The public helper does not add poses or interpolation. Wrong action or character continuity needs another take, not a higher FPS. |
| Subtitle missing from GIF, or no sound | GIF is silent and runtime captions are a separate SRT. Local title cards are separate shots. An MP4 can import optional local audio through its script. |

Technical checks verify decoding, timing and hashes. They do not approve likeness,
prop contact or story logic. Keep known faults visible and review the final delivery
file, not only its contact sheet. [Production advice](PRODUCTION.md) · [Practical tips](TIPS.md).

## License before sharing or commercial use

GIF Cinema uses a custom **source-available evaluation license**, not an
OSI-approved open-source license. Personal non-commercial evaluation and research
are permitted; commercial use, redistribution and hosting require written permission.
Read the [license](../LICENSE), and review prompts, references, media rights and
private project records before sharing an editable project.

### Direct generation: interrupted requests and paid retries

`generate` writes a durable `scene.gif.attempts.json` receipt **before** contacting
OpenAI. A timeout, malformed response, process interruption, or local save failure
can leave a billable request with no usable output. Repeating the same output path
(including `--resume`) then fails closed instead of silently paying again.

Check your provider history first. Use `--resume` when the GIF and matching metadata
are already present; it verifies and reuses them without a request. Only use
`--force` after review to explicitly authorize **one new paid request**, which may
replace an existing result. The journal preserves prior attempts. It contains
parameter hashes and status, not API keys, prompts, response bodies or exception
messages. Corrupt journals fail closed, even with `--force`; preserve them for
inspection rather than deleting them to retry.

This is an output-path guard, not provider-side idempotency or a global spending
cap. A different output path is a new request. Old runs made before this guard have
no receipt, and provider history remains the source for actual billing. A stale
`.lock` after a hard crash must only be removed once the process is confirmed dead;
the retained attempt receipt still prevents an accidental new request.
