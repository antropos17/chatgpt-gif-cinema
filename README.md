# GIF CINEMA

**A film pipeline built on ChatGPT GIFs.**

Generate animated GIF shots with OpenAI GPT Image 2.6, inspect first/last frames, and assemble silent scenes into MP4.

> Status: Offline checks passed. Live OpenAI GIF generation has not been verified on this account.

## Quickstart

```bash
python -m pip install -e ".[filmqa]"
export OPENAI_API_KEY="your-key"
python -m gif_cinema generate "Astronaut waving, static camera, seamless loop" --frames 9 --duration 200 -o output/shot.gif
python -m gif_cinema inspect output/shot.gif
python -m gif_cinema film output/shot.gif -o output/film.mp4
```

## Included

- GPT Image GIF generator CLI
- First/last frame inspection and continuity checks
- FFmpeg GIF-to-MP4 assembler
- Six Codex agent skills: gif-cinema, chat-director, api-gif-generator, continuity-editor, film-assembler, qa-release
- Minimal black-and-white website

## License

Source-available evaluation license, not an open-source license. See LICENSE. Commercial use requires permission.

## Verification

11 offline local tests passed in the packaged v0.4.0 release. A live API call is still pending.

[OpenAI Image Generation guide](https://developers.openai.com/api/docs/guides/image-generation)
