# Installed native backend and saved editor projects

Skill 0.4.3 pins runtime commit
`197068b60f1c4c4b9d3cd70d4a5faeca043f5c23`, the merged and CI-checked backend.
Earlier skill packages can install a runtime whose version string is also 0.5.0
but which lacks these interfaces. Use the exact install command in SKILL.md;
never infer compatibility from that version string alone or silently downgrade.

## Save working frames as a film master

Export a `.gfc` working project from Browser Studio, then run locally:

```bash
python -m gif_cinema.editor_project saved-project.gfc --out NEW_FILM_DIRECTORY
# Keep only the exact silent master, without a lossy viewing derivative:
python -m gif_cinema.editor_project saved-project.gfc --out OTHER_NEW_DIRECTORY --no-preview
```

Keep `project.gfc`, `manifest.json`, `master.mkv` and the optional `preview.mp4`
together. Outputs must be new; existing accepted films are not overwritten.
The master preserves all saved **256x256 RGBA working frames and declared holds**,
including duplicate drawings, hidden RGB and long final holds. Browser decoding,
scaling or earlier compositing cannot be undone: this is not original-GIF fidelity.
The viewing MP4 is lossy/opaque and repeats drawings on a 100 fps timeline; it does
not synthesize missing poses. The project is silent, at most 8 scenes, 240 working
frames and 30 seconds. It is not the broader engine's film-length limit.
See the [pinned format guide](https://github.com/antropos17/chatgpt-gif-cinema/blob/197068b60f1c4c4b9d3cd70d4a5faeca043f5c23/docs/EDITOR-PROJECT.md).

## Render existing atlas performances

Native `gif-cinema-shot-project` files describe authored atlas schedules, cameras,
lights and sound. They are not `gif-cinema-layer-sequence` files; these two schemas
share CLI routing but have distinct receipts and master routes.

```bash
python -m gif_cinema sequence build project.json --out NEW_BUILD --dry-run
python -m gif_cinema sequence build project.json --out NEW_BUILD
python -m gif_cinema sequence verify NEW_BUILD
# Only after interruption with unchanged input and engine:
python -m gif_cinema sequence build project.json --out NEW_BUILD --resume
```

Exact rational actor sampling fixes an accidental previous-pose hold at a loop
start. It does not add drawings, track a face, infer character identity or make a
coarse source animation smooth. Changed-engine resume fails safely; preserve old
outputs and make a new revision. See the [native contract](https://github.com/antropos17/chatgpt-gif-cinema/blob/197068b60f1c4c4b9d3cd70d4a5faeca043f5c23/docs/NATIVE-SHOTS.md).

## Check the installation, not merely the command names

From this installed skill folder, with Python, Pillow, PyAV 16.1 and FFmpeg/ffprobe:

```bash
python scripts/check_install.py --require-master
python scripts/smoke_backend.py --out ../backend-smoke
# Or include this check with every existing component:
python scripts/smoke_test.py --out ../complete-smoke
```

The backend smoke creates tiny original technical fixtures and invokes real
export commands. It reopens frames/timing instead of treating exit status as
acceptance. Outputs and completion receipts stay outside the installed package;
all targets must be new. Existing fixtures or accepted work are never overwritten.
No provider request, hosting resource, account credential or public access is
needed. These are technical checks, not artistic or browser/phone acceptance.
Installing this package **does not connect or update the private live Site**.
