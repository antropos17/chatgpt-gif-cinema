---
name: api-gif-generator
description: Generate real animated GIF files with OpenAI GPT Image API and report raw settings and errors.
---
# API GIF Generator
Use `gif-cinema generate "A candle flickers, locked camera" --frames 9 --duration 200 -o output/01.gif`. Require OPENAI_API_KEY in environment. Do not store credentials. Capture metadata and report if API rejects access, frames, size or model. Do not claim a successful live test without file verification.