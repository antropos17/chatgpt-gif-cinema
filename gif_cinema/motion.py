"""Offline native-GIF art direction and inspection; never dispatches paid requests."""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path

from .cli import make_payload, read_gif_bytes, validate_gif, write_result

COMMON = (
    "Premium abstract motion-design loop, a single coherent sculptural subject centered "
    "on a clean studio background specified below. Square composition, entire silhouette "
    "inside frame with generous negative space. Locked camera and focal length, "
    "broad softbox reflections, crisp readable geometry, restrained cinematic contrast. "
    "Animate the actual object in 3D, not a camera move over a still. "
    "One continuous periodic cycle; the final state flows into the first without a "
    "pause, duplicated endpoint, cut, dissolve or reverse-playback trick. "
    "No people, characters, text, logos, watermark, borders or montage. "
)
PRESETS = {
    "chrome-trefoil": {
        "title": "Chrome Trefoil",
        "direction": "A polished liquid-chrome trefoil knot with three rounded lobes and a hollow center. The rigid knot turns one full revolution around its vertical axis with a small smooth periodic tilt, retaining its original shape throughout. Keep the tube continuous and its topology intact. Near-black background. Silver highlights with a subtle ice-blue rim; sculptural, weighty, precise."
    },
    "copper-ribbon": {
        "title": "Copper Folded Ribbon",
        "direction": "One broad satin-copper ribbon folded into a freestanding angular accordion sculpture, with visible thin edges. Sequential hinges open from left to right like a wave and fold back in a continuous cyclic phase, never flattening into a sheet. Warm terracotta and rose-gold reflections against warm off-white; deliberate elastic folding, no spinning knot."
    },
    "pearl-orbits": {
        "title": "Pearl Gyroscopic Orbits",
        "direction": "Three thin pearlescent ceramic elliptical rings nested around one small stationary ivory sphere. Each ring rotates a full turn about a different fixed orthogonal axis, with coordinated phases and generous clearance so the rings never collide. Deep indigo background, cool pearlescent silver and opal white with restrained pale lavender interference highlights; airy gyroscopic choreography, no morphing or melting."
    },
    "cobalt-bloom": {
        "title": "Cobalt Kinetic Bloom",
        "direction": "Twelve glossy cobalt-blue beveled rectangular tiles arranged radially as a geometric mechanical flower. Tiles hinge outward in a continuous clockwise traveling wave and curl inward again, revealing electric cyan undersides. Tile count and solid dimensions remain constant, with clean spacing and no intersections. Pale-blue background. Architectural, rhythmic, sharply faceted, not organic petals."
    },
    "amber-torus": {
        "title": "Amber Liquid Torus",
        "direction": "A thick translucent honey-amber glass torus suspended in air. A smooth bulge travels once around its circumference while the central opening breathes gently in and out, remaining open. Warm ivory background. Internal golden caustics follow the flowing mass; rounded liquid volume, dark burnt-orange shadows, no droplets detaching and no rigid mechanical rotation."
    },
    "coral-helices": {
        "title": "Coral Braided Helices",
        "direction": "Two luminous coral-pink flexible tubes braided as a compact upright double helix. A continuous corkscrew deformation travels upward through both strands, with their end positions fixed and softly rounded, returning exactly to the starting configuration after one period. Dark navy background, hot coral and restrained violet edge light, clear dark gaps between strands, no intersections, no growth or camera motion."
    },
}
FIRST = "Initial phase of a continuous periodic cycle."
LAST = "Next phase flows naturally back into the first; visual review required."
ROUTES = ("openai-direct-16",)


def canonical(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def compile_request(preset, route):
    if not isinstance(route, str) or route not in ROUTES:
        raise ValueError("Unknown route")
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError("Unknown preset")
    prompt = COMMON + PRESETS[preset]["direction"]
    effective = (f"Style and character bible: {COMMON}\nShot {preset}: {prompt}\n"
                 f"Start: {FIRST}\nEnd: {LAST}\nOne continuous shot. No captions or text.")
    parameters = make_payload(effective, frames=16, duration=200, size="512x512", quality="max", complexity="high")
    dispatch = {"kind": "existing-gif-cinema-render", "endpoint": "https://api.openai.com/v1/images/generations"}
    return {"schema_version": 1, "preset": preset, "title": PRESETS[preset]["title"], "route": route, "status": "unrendered", "source_prompt": prompt, "dispatch": dispatch, "parameters": parameters, "parameters_sha256": sha(canonical(parameters)), "artifact_requirements": {"background": "opaque"}}



@contextmanager
def fresh_output(path):
    """Refuse symlink ancestors and existing output; clean partial local writes."""
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Output path and its parents must not be symlinks")
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    except BaseException:
        # Only files from this flat, exclusively created output directory.
        if not path.is_symlink():
            for child in path.iterdir():
                if child.is_file() or child.is_symlink():
                    child.unlink()
            path.rmdir()
        raise


def compile_project(args):
    ids = list(PRESETS) if args.preset == "all" else [args.preset]
    requests = [compile_request(p, args.route) for p in ids]
    with fresh_output(args.out) as out:
        _write_project(out, requests, args.route)
    print(f"Prepared {len(requests)} unrendered requests in {out}; no provider calls.")


def _write_project(out, requests, route):
    entries = []
    for request in requests:
        name = request["preset"]
        raw = canonical(request)
        write_result(out / f"{name}.request.json", raw)
        entries.append({"preset": name, "request": f"{name}.request.json", "sha256": sha(raw)})
        if route == "openai-direct-16":
            p = request["parameters"]
            shot = {"id": name, "prompt": request["source_prompt"], "frames": p["frame_count"], "duration_ms": p["frame_duration_ms"], **{k: p[k] for k in ("model", "size", "quality", "complexity")}, "first_frame_target": FIRST, "last_frame_target": LAST, "transition": "cut"}
            script = {"schema_version": 1, "title": request["title"], "style_bible": COMMON, "ratio": "1:1", "shots": [shot]}
            write_result(out / f"{name}.film.json", canonical(script))
    write_result(out / "manifest.json", canonical({"schema_version": 1, "route": route, "status": "unrendered", "paid_calls_made": 0, "requests": entries}))


def read_request(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Request exceeds 1 MiB")
    request = json.loads(raw)
    if not isinstance(request, dict):
        raise ValueError("Request must be an object")
    if request != compile_request(request.get("preset"), request.get("route")):
        raise ValueError("Request differs from this preset version; preserve the original runtime or compile a new request")
    return request, sha(raw)


def inspect_result(args):
    from PIL import Image, ImageChops, ImageStat, ImageSequence
    request, request_hash = read_request(args.request)
    raw = read_gif_bytes(args.gif)
    frames, durations, loop = validate_gif(io.BytesIO(raw))
    # The shared preflight and full decode above validate these immutable bytes
    # against all ingestion budgets before any additional RGBA allocation. Stream
    # one composited RGBA frame at a time, never retain a second frame collection.
    transparent_indices = []
    with Image.open(io.BytesIO(raw)) as image:
        for index, frame in enumerate(ImageSequence.Iterator(image)):
            if frame.convert("RGBA").getchannel("A").getextrema()[0] < 255:
                transparent_indices.append(index)
    dimensions = [list(frame.size) for frame in frames]
    p = request["parameters"]
    hashes = [sha(frame.tobytes()) for frame in frames]
    def difference(a, b):
        return round(sum(ImageStat.Stat(ImageChops.difference(a.resize((128, 128)), b.resize((128, 128)))).mean) / 3, 4)
    warnings = []
    if len(frames) != p["frame_count"]:
        warnings.append("Decoded frame count differs from requested frame count.")
    if any(d != p["frame_duration_ms"] for d in durations):
        warnings.append("Decoded frame delays differ from requested delays.")
    if any(frame.size != (512, 512) for frame in frames):
        warnings.append("Decoded dimensions differ from requested 512x512.")
    if request["artifact_requirements"]["background"] == "opaque" and transparent_indices:
        warnings.append("Composited GIF frames contain transparent pixels despite the opaque artifact requirement.")
    if loop != 0:
        warnings.append("GIF does not declare infinite looping.")
    if len(set(hashes)) < 2:
        warnings.append("All decoded frames are identical; no visible motion detected.")
    report = {"schema_version": 1, "request_sha256": request_hash, "request": request, "gif_sha256": sha(raw), "bytes": len(raw), "actual": {"frames": len(frames), "unique_decoded_frames": len(set(hashes)), "width": frames[0].width, "height": frames[0].height, "frame_dimensions": dimensions, "all_frames_opaque": not transparent_indices, "transparent_frame_indices": transparent_indices, "duration_ms": sum(durations), "frame_durations_ms": durations, "loop": loop}, "first_last_pixel_mae_0_255": difference(frames[-1], frames[0]), "adjacent_pixel_mae_0_255": [difference(a, b) for a, b in zip(frames, frames[1:])], "warnings": warnings, "technical_status": "decoded-with-warnings" if warnings else "requested-format-matched", "visual_status": "human-review-required", "provenance_note": "Caller-supplied request association, not authenticated proof of provider origin. Pixel metrics cannot establish seamlessness, geometry quality or genuine object motion."}
    with fresh_output(args.out) as out:
        frames[0].save(out / "first.png")
        frames[-1].save(out / "last.png")
        indices = sorted(set(round(f * (len(frames) - 1)) for f in (0, .125, .25, .375, .5, .625, .75, 1)))
        sheet = Image.new("RGB", (4 * 192, 2 * 192), "#171717")
        for i, index in enumerate(indices):
            thumb = frames[index].copy()
            thumb.thumbnail((192, 192))
            sheet.paste(thumb, ((i % 4) * 192, (i // 4) * 192))
        sheet.save(out / "contact-sheet.png")
        report["contact_sheet_frame_indices"] = indices
        write_result(out / "inspection.json", canonical(report))
    print(json.dumps(report, indent=2))


def configure_parser(parser):
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.set_defaults(func=lambda args: print(json.dumps(PRESETS, indent=2)))
    compile_cmd = sub.add_parser("compile", help="Prepare requests offline; never generates media")
    compile_cmd.add_argument("--preset", choices=["all", *PRESETS], default="all")
    compile_cmd.add_argument("--route", choices=ROUTES, default=ROUTES[0])
    compile_cmd.add_argument("--out", required=True)
    compile_cmd.set_defaults(func=compile_project)
    inspect_cmd = sub.add_parser("inspect", help="Inspect an actual returned GIF without modifying it")
    inspect_cmd.add_argument("gif")
    inspect_cmd.add_argument("--request", required=True)
    inspect_cmd.add_argument("--out", required=True)
    inspect_cmd.set_defaults(func=inspect_result)
    return parser


def main():
    parser = configure_parser(argparse.ArgumentParser(description=__doc__))
    args = parser.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
