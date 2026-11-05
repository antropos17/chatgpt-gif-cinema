# GIF Cinema verification status · November 5, 2026

## Verified
- Public repository: https://github.com/antropos17/chatgpt-gif-cinema
- Offline unit tests: GitHub Actions CI passed.
- Authenticated GPT Image 2.6 Flare GIF generation: **PASS**, run [#41978897155](https://github.com/antropos17/chatgpt-gif-cinema/actions/runs/41978897155).
- First GIF: 512×512, nine frames, 1,800 ms, 754,055 bytes; source: `docs/assets/first-live-render.gif`.
- GIF-to-H.264 MP4 export: **PASS**, run [#41979370241](https://github.com/antropos17/chatgpt-gif-cinema/actions/runs/41979370241).
- Three separately generated GIF scenes into one H.264 MP4: **PASS**, run [#41979631572](https://github.com/antropos17/chatgpt-gif-cinema/actions/runs/41979631572).
- Three-shot output: 512×512, 129 video frames, 5.375 seconds; `docs/assets/three-shot/three-shot-film.mp4`.

## Not yet established
- Character identity consistency across independent renders (requires human QA).
- Smoothness of match cuts, narrative continuity, audio mixing or subtitles.
- Reliable production of a long film from a single idea. Script assembly now executes explicit author-defined shots; it does not autonomously validate story meaning.
- Browser-based generation service; site is a static showcase.

## Continuity diagnostics
- Shot 1→2 pixel MAE: 60.643 / 255; manual review flagged.
- Shot 2→3 pixel MAE: 33.075 / 255; still requires subjective review.
- These heuristics are not identity detection.

## Security and licensing
- OpenAI API key is stored as an Actions secret and is not in the repository.
- Custom source-available license, not OSI open-source.

## Offline reliability checks
- Regression tests cover corrupt GIF responses, credential-safe errors, protected outputs, checksum-based reuse, concurrent output locks, and real FFmpeg montage with short and long audio.
- Local verification makes no paid API requests. CI installs FFmpeg and uses fixtures only.
- Film timing and final-frame retention are checked; this does not establish artistic quality or sound mixing quality.
- Live generation and demo publishing workflows require manual dispatch.
- Script orchestration is implemented through `render`; the offline and generated-shot acceptance scopes are documented in `docs/SCRIPT-FORMAT.md`.
