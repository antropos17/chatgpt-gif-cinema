# Verification status

Checked on November 6, 2026.

## Working public path

The public agent skill supplies instructions and a smoke helper; the included Python
CLI performs the work. It can generate authorized short GIF shots, accept still-image
references in scripts, extract endpoints, execute bounded retakes and assemble MP4.
The skill itself is not a hosted video model or the separate Studio interface.

A fresh isolated installation fetched the public runtime from GitHub. The public
skill helper passed inspection, endpoint extraction, reference preflight, complete
MP4 decode, script execution and repeat/resume. The 40-test offline suite passed
without failures, errors or skips. These checks made zero provider calls.

The original real-media check used the historical three-GIF example:
27 native drawings, 5.4 seconds, 135 exported frames at 25 fps, H.264 512×512.
All six diagnostic endpoints matched decoded source pixels exactly. Encoded video
edges differed slightly because H.264 encoding is lossy. Repeat execution reused
identical movie bytes and preserved the source GIFs.

The default example now uses three existing reference-conditioned astronaut GIFs:
16 native drawings per shot at 160 ms each, 7.68 seconds total. Its source GIFs are
included for an API-free reproduction; the original example remains separately
available as `examples/film-historical.json`.

The seven-file skill ZIP was also extracted into an unrelated directory and tested
with its own bundled example. It produced the expected 7.68-second, 192-frame film;
dry-run, zero-call execution, resume, all six endpoints and full decode passed.
The bundled files remained unchanged. Relative documentation links and all public
asset-manifest hashes were checked as well.

## Generation evidence

Authenticated GPT Image 2.6 Flare generation was verified in historical runs
[41978897155](https://github.com/antropos17/chatgpt-gif-cinema/actions/runs/41978897155)
and [41984076055](https://github.com/antropos17/chatgpt-gif-cinema/actions/runs/41984076055).
The latter tested still-reference image edits returning an animated GIF. These are
account/model/date-specific observations. No fresh paid generation was submitted
for this presentation and verification pass.

The prompt-only three-shot experiment in run 41982718167 failed visual continuity
at both joins. It is not a character-lock recipe. The later reference-conditioned
astronaut takes preserve a more recognizable character but still need human review.

## Showcase scope

The astronaut, dog and cat comparisons use existing footage and local postprocessing.
The public toolkit does not include the private motion/compositing engine or Studio.
The complete cat movie is 57.2 seconds, assembled from short generated takes with
additional local editing. It is not a single native minute-long API generation.
See [comparison methods](docs/SHOWCASE.md).

Successful decoding, low pixel difference and export FPS do not establish identity,
correct prop physics, seamless cuts or artistic acceptance. Some finished intervals
retain the native stepped pose cadence. Sound generation, automatic take ranking
and an automatic last-frame dependency graph are outside the public release.

## Privacy and licensing

Public files and showcase media are checked for personal paths, credentials and
embedded personal metadata. Public Git authors use a GitHub no-reply identity.
Historical copies, forks and provider caches cannot be erased by changing this tree.
The existing source-available evaluation license is preserved.
