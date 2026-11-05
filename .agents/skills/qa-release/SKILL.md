---
name: qa-release
description: Run offline checks, prevent secrets from shipping, and distinguish mocked API tests from actual renders.
---
# QA Release
Run `python -m unittest discover -s tests -v` and `python -m compileall -q gif_cinema`. Review for leaked API keys, .env, private/ and outputs. Check README claims and live access. Only label API rendering passed after real authenticated output has been verified.