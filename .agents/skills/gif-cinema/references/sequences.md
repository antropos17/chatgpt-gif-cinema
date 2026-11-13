# Authored sequence revisions and lossless delivery

Use a reviewed `gif-cinema-layer-sequence` project, not an arbitrary GIF or a
sprite atlas. These commands do not generate new character drawings. The complete
schema and authoring example are in the [pinned runtime guide](https://github.com/antropos17/chatgpt-gif-cinema/blob/bf88126a7995c6feca20607ae71a1018eb3cc315/docs/SCENE-SEQUENCES.md).

```bash
python -m gif_cinema sequence build project/sequence.json --out output/v1 --resume
# After an intentional project edit, preserve v1 and create a new revision:
python -m gif_cinema sequence build project/sequence.json --out output/v2 --reuse-from output/v1
python -m gif_cinema sequence verify output/v2
python -m gif_cinema sequence master output/v2 --out output/v2-master
```

`--resume` requires the same project identities and output; it is not permission to
replace previously accepted footage after edits. `--reuse-from` validates the old
bundle and reuses only matching scene identities, rebuilding changed actions. Keep
both revisions. All these operations are local and make zero provider calls.

The master requires the pinned runtime with `[lossless]` (PyAV >=16.1,<17).
`master.mkv` is a lossless FFV1 archive with alpha, not a browser/README preview.
`master-receipt.json` records original scene/frame identities and decoded verification.
Use a new output directory outside the source sequence; retain the source bundle.
The existing MP4 is a lossy viewing copy. Exact pixels and holds do not prove natural
motion, aligned poses, good storytelling or visual acceptance. A 15-second master
needs 15 seconds of authored actions, not an automatically stretched short loop.
