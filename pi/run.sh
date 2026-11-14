#!/bin/sh
# Launch inkcycle fullscreen. Used by the autostart entry.
cd "$(dirname "$0")/.." || exit 1
sleep 3   # let the desktop and audio come up
exec python3 -m inkcycle "$@"
