# Script-to-film verification — November 5, 2026

## Delivered

The script renderer was implemented on `feat/script-to-film`, based on main's
post-processed demo update `42ad8d9` and the reliability fixes from PR #1
(`871016a`). The website file is identical to the main baseline; no website feature
was developed. Existing API GIFs and the newly cleaned looping demo were preserved.

Local checks: 37 tests passed, including real FFmpeg/ffprobe integration, plus
`compileall` and `git diff --check`. API behavior was tested using offline fixtures,
with the actual network forbidden. No new paid API requests were made.

`examples/film.json` executed successfully using three existing generated GIFs.
The result is H.264, 512×512, 25 fps, 135 decoded frames, 5.4 seconds. Its duration
differs from the older 24 fps proof (5.375 seconds) because 200 ms frame delays fit
exactly at 25 fps. A second execution reused all three shots and the movie with zero
API calls. See `verification.json` for both runs, hashes and actual timing.

Files: [film](film.mp4), [captions](captions.srt), [contact sheet](contact-sheet.png),
[probe](film-inspect.json), [join report](continuity-report.json).

## Visual acceptance: not passed

The first/last-frame sheet was visually inspected. The narrative order is greeting,
answering light, constellation. However, the first cut changes from a round cartoon
astronaut to a differently rendered glove and lunar surface. It does not establish
the same recognizable character with aligned pose/motion across shots. The final
shot is a sky cutaway without the character. A full real-time human playback review
was not performed in this implementation run; complete video decoding did pass.

No dissolve, loop stretching or synthetic interpolation was used to hide the mismatch.
The software receipt deliberately retains `human-review-required`. The visual criterion
is not marked complete because the movie can be decoded or its storyline can be described.

## Prepared next step; approval required for generation

`examples/consistent-film.proposed.json` proposes three short shots using one astronaut,
one static camera and explicit pose handoffs: raise hand → hold while star answers →
lower hand to chest. It was validated with dry-run only. Matching prompts are still
not a guarantee of identity or continuity, and no image-conditioned GIF endpoint is
assumed to exist.

The bounded initial test would use exactly three calls at most, `gpt-image-2.6-flare`,
nine frames per shot, 200 ms per frame, low quality/complexity, no automatic retries.
It would need review of all frames and both joins before any claim of visual acceptance.
No exact dollar estimate is asserted. Do not run until the user authorizes paid requests:

```bash
python -m gif_cinema render examples/consistent-film.proposed.json --execute --max-api-calls 3 --retries 0 --out output/consistent-story
```

If a scene fails, preserve accepted scenes and request any additional budget before
regenerating it with `--force-shot`. A website and public continuation mechanics remain
out of scope.

## Disk and diagnostic hygiene

Worktree, tests and media are on X:. Existing FFmpeg and ffprobe binaries were reused
without installing or changing global configuration. A partially downloaded optional
tool archive was stopped and its exact closed file removed after discovering ffprobe
already installed. Temporary test directories were closed and cleaned by the test runner.
Keep accepted output and receipts. CI artifact retention is seven days. No global cache
or other project's diagnostics were removed.
