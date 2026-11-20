#!/usr/bin/env zsh
# Upload media for Frame Control's own OpenVR player (no external player).
# Usage: scripts/push-vr-video.sh [--launch] [--layout LAYOUT] [--theatre] FILE...
# Layouts: auto, mono, sbs, ou, full-sbs, full-ou; append -rl to a stereo layout
# for right-eye-first packing. --help lists all accepted values.
#        scripts/push-vr-video.sh --list | --stop
# Files go to ~/Videos/FrameControl/<id>/; --launch accepts exactly one file.
# Directories, automatic DeoVR launching and Proton-prefix links are no longer used.
set -euo pipefail
exec python3 "${0:A:h}/../ui/frame_media_cli.py" "$@"
