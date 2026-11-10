#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p deliverables
# Modest conventional spatial/temporal noise reduction, not generative synthesis.
ffmpeg -y -framerate 24 -start_number 1 -i renders/form_%04d.png -frames:v 144 -vf "hqdn3d=1.0:1.0:2.0:2.0" -c:v libx264 -crf 17 -preset slow -pix_fmt yuv420p -movflags +faststart deliverables/FORM-01.mp4
# 20 fps is exactly representable as GIF's 5-centisecond frame delay.
ffmpeg -y -i deliverables/FORM-01.mp4 -vf "fps=20,scale=640:640:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=full:max_colors=256[p];[s1][p]paletteuse=dither=sierra2_4a" -loop 0 deliverables/FORM-01.gif
