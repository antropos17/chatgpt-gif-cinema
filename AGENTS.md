# GIF Cinema agent instructions

Use the appropriate specialized skill from `.agents/skills`. The root `gif-cinema` skill orchestrates work. Never commit OpenAI API keys or claim live API tests were run when they were mocked. Preserve the source-available license and keep private commercial logic out of this repo. Prioritize reliable first/last frame inspection before automated transitions.

The active milestone is an author-controlled GIF-to-film pipeline. Do not expand into
a website or collaborative continuations. `render` defaults to offline planning; paid
generation requires explicit user authorization and `--execute` with a bounded request
cap. Reuse existing GIFs for local verification with `--max-api-calls 0`.

Read `docs/SCRIPT-FORMAT.md` for the v1 script contract. The character must remain
recognizable and poses/actions must align across joins for visual acceptance. Neither
matching prompts, a low pixel score, nor a dissolve proves that. Preserve approved
scenes and show continuity failures. Keep diagnostic output project-local and bounded;
retain verification receipts and accepted media.
