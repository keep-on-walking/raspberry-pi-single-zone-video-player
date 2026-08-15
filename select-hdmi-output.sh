#!/bin/bash
# Applies the persisted display.hdmi_port setting (dashboard-configurable,
# device_config.py / /opt/rpi-video-player/config/device.json) against the
# already-running X server.
#
# Run on every X11 start (x11-server.service ExecStartPost - same
# self-healing-on-every-start pattern as detect-dri-card.sh) and again
# live from the Flask app when the setting is changed via the dashboard.
#
# Requires both HDMI connectors to have a forced mode in cmdline.txt
# (video=HDMI-A-1:... and video=HDMI-A-2:...) - install.sh ensures this.
# No root needed: xrandr talks to the already-running X server as the
# user it's running as.

CONFIG_FILE="/opt/rpi-video-player/config/device.json"
export DISPLAY="${DISPLAY:-:1}"

PORT="auto"
if [ -f "$CONFIG_FILE" ]; then
    PORT=$(python3 -c "
import json
try:
    with open('$CONFIG_FILE') as f:
        print(json.load(f).get('display', {}).get('hdmi_port', 'auto'))
except Exception:
    print('auto')
" 2>/dev/null)
    [ -n "$PORT" ] || PORT="auto"
fi

case "$PORT" in
    hdmi-2)
        xrandr --output HDMI-2 --primary --mode 1920x1080 --pos 0x0 --output HDMI-1 --off 2>/dev/null \
            && echo "select-hdmi-output: active output HDMI-2" \
            || echo "select-hdmi-output: failed to switch to HDMI-2"
        ;;
    hdmi-1|auto|*)
        xrandr --output HDMI-1 --primary --mode 1920x1080 --pos 0x0 --output HDMI-2 --off 2>/dev/null \
            && echo "select-hdmi-output: active output HDMI-1" \
            || echo "select-hdmi-output: failed to switch to HDMI-1"
        ;;
esac

exit 0
