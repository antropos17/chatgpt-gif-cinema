# Build an offline GIF collection

Package 0.4.2 includes the `factory` command through its separately installed,
immutable runtime pin. It gathers existing GIFs and local editable layer scenes
into a static gallery and verified ZIP. It makes no provider calls or new poses.

Run from this skill folder, keeping every output outside it:

```bash
python -m gif_cinema factory build assets/example/factory.json --out ../project/collection --dry-run
python -m gif_cinema factory build assets/example/factory.json --out ../project/collection
python -m gif_cinema factory verify ../project/collection
python scripts/smoke_factory.py --out ../project/factory-smoke
```

The bundled manifest pins `shot-01.gif` and `stroke-reveal.json` by SHA-256. Build
preserves imported GIF bytes and renders the original editable stroke geometry.
Scene rendering needs FFmpeg and ffprobe. Inputs never change. The example is
existing artwork plus authored graphic motion, not an autonomous story generator.

For your own manifest, use `format: gif-cinema-factory`, `schema_version: 1`, a
`title`, and 1–12 `items`. Each item has a unique lowercase slug `id`, a `title`,
`sha256`, and exactly one relative `gif` or `scene` path. Optional `group` and
`caption` are plain text. Paths must stay within the manifest folder, without
symlinks, URLs or parent traversal. Recompute a source hash after intentional edits.

Each delivered GIF is fully decoded and checked. The collection includes a local
HTML gallery, `catalog.json`, per-item GIFs, actual midpoint posters and labeled
sample sheets, and `collection.zip`. Verification checks the file inventory,
hashes, all GIF drawing/timing values, preview pixels and exact ZIP members/bytes.
The ZIP has one `collection/` root. It is deterministic for identical generated
files, not a cross-platform rendering promise or publisher signature.

Inputs are bounded to 32 MiB, 512 drawings and 64 Mi decoded pixels per GIF, with
20–60,000 ms frame delays and a 120-second maximum. The batch accepts up to 128 MiB
of source bytes and 256 Mi planned pixel-frames. Output must be a new directory.
A limit failure does not silently trim, resize or skip content.

The smoke exercises public CLI planning, build and verify with network blocked;
it rechecks the actual ZIP and unchanged bundled hashes. Technical success leaves
visual review and user acceptance pending. Inspect playback, typography, contacts,
loop seams and rights before sharing. Building a collection does not upload it.
