---
name: gif-cinema
description: Orchestrate AI GIF filmmaking from prompt to storyboard, OpenAI API GIFs, continuity checks, and MP4 release.
---
# GIF Cinema Orchestrator

Choose `chat-director` → `api-gif-generator` → `continuity-editor` → `film-assembler` → `qa-release`.
Refer to the actual CLI and `docs/PRODUCTION.md`. Only assert a live API render when an authenticated request has succeeded.

Quickstart: `gif-cinema generate "A lantern flickers" -o output/scene.gif`.

For a film, start with `gif-cinema render examples/film.json --dry-run`. Execute the
existing-asset example with `--execute --max-api-calls 0 --out output/offline-story`.
Follow `docs/SCRIPT-FORMAT.md`; `--execute` with prompt shots may spend money and needs
user authorization. Keep website work out of the current milestone.
