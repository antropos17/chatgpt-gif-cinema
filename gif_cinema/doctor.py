"""Read-only FFmpeg capability checks used before film execution."""
import json
import os
import platform
import shutil
import subprocess


def inspect_tool(name):
    path = shutil.which(name)
    if not path:
        return {"available": False, "reason": f"{name} is not on PATH"}
    try:
        result = subprocess.run([path, "-version"], capture_output=True, text=True, check=True, timeout=10)
        version = result.stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return {"available": False, "reason": f"{name} could not report its version"}
    return {"available": True, "version": version}


def inspect_ffmpeg_capabilities():
    capabilities = {"h264_encoder": False, "core_filters": False, "motion_interpolation": False,
                    "aac_encoder": False, "audio_padding": False}
    try:
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True, timeout=10).stdout
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return capabilities
    names = {line.split()[1] for line in filters.splitlines() if len(line.split()) >= 2}
    encoder_names = {line.split()[1] for line in encoders.splitlines() if len(line.split()) >= 2}
    capabilities.update(h264_encoder="libx264" in encoder_names,
                        core_filters={"fps", "scale", "pad", "concat", "tpad", "trim", "setpts", "format", "setsar", "setparams", "split", "lutrgb", "overlay"} <= names,
                        motion_interpolation="minterpolate" in names,
                        aac_encoder="aac" in encoder_names,
                        audio_padding={"apad", "aresample", "atrim", "asetpts"} <= names)
    return capabilities


def require_film_capabilities(audio=False):
    """Fail before rendering or spending if this FFmpeg cannot assemble the film."""
    capabilities = inspect_ffmpeg_capabilities()
    required = {"h264_encoder": "libx264", "core_filters": "standard video filters"}
    if audio:
        required.update(aac_encoder="AAC encoder", audio_padding="apad, aresample, atrim and asetpts audio filters")
    missing = [label for name, label in required.items() if not capabilities.get(name)]
    if missing:
        raise RuntimeError("FFmpeg cannot provide " + ", ".join(missing)
                           + "; install a compatible FFmpeg build")


def environment_report():
    """Summarize local readiness without printing secrets or sending requests."""
    from .cli import default_model
    try:
        from PIL import __version__ as pillow
    except ImportError:
        pillow = None
    try:
        model = {"value": default_model(), "ok": True}
    except ValueError as exc:
        model = {"value": os.environ.get("GIF_CINEMA_MODEL"), "ok": False, "error": str(exc)}
    tools = {name: inspect_tool(name) for name in ("ffmpeg", "ffprobe")}
    capabilities = inspect_ffmpeg_capabilities() if tools["ffmpeg"]["available"] else {}
    film_ready = (tools["ffmpeg"]["available"] and tools["ffprobe"]["available"]
                  and capabilities.get("h264_encoder", False) and capabilities.get("core_filters", False))
    return {
        "python": platform.python_version(),
        "pillow": pillow,
        "tools": tools,
        "ffmpeg_capabilities": capabilities,
        "default_model": model,
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "provider_access": "not checked; no provider request was sent",
        "ready": {
            "offline_film": bool(film_ready and pillow),
            "generation": bool(film_ready and pillow and model["ok"] and os.environ.get("OPENAI_API_KEY")),
        },
    }


def doctor(args):
    report = environment_report()
    print(json.dumps(report, indent=2))
    if not report["ready"]["offline_film"]:
        raise RuntimeError("Local film assembly is not ready; see the report above")


def add_parser(sub):
    parser = sub.add_parser("doctor", help="Check Python, Pillow, FFmpeg and API settings; sends no requests")
    parser.set_defaults(func=doctor)
