"""Read-only FFmpeg capability checks used before film execution."""
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
                        core_filters={"fps", "scale", "pad", "concat", "tpad", "trim", "setpts", "format", "setsar"} <= names,
                        motion_interpolation="minterpolate" in names,
                        aac_encoder="aac" in encoder_names,
                        audio_padding="apad" in names)
    return capabilities


def require_film_capabilities(audio=False):
    """Fail before rendering or spending if this FFmpeg cannot assemble the film."""
    capabilities = inspect_ffmpeg_capabilities()
    required = {"h264_encoder": "libx264", "core_filters": "standard video filters"}
    if audio:
        required.update(aac_encoder="AAC encoder", audio_padding="apad audio filter")
    missing = [label for name, label in required.items() if not capabilities.get(name)]
    if missing:
        raise RuntimeError("FFmpeg cannot provide " + ", ".join(missing)
                           + "; install a compatible FFmpeg build")
