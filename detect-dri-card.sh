#!/bin/bash
# Regenerates /etc/X11/xorg.conf.d/20-modesetting.conf with whichever DRI
# card currently exposes the HDMI connector(s).
#
# DRM device enumeration order (which /dev/dri/cardN is the vc4/display
# device vs. the v3d render-only node) is not guaranteed stable across
# reboots on the Pi. install.sh used to bake this in once at install time;
# a later reboot that re-orders the cards then leaves X pointed at a card
# with no screens ("(EE) no screens found"), and the player never comes
# up. This script is run by x11-server.service on every start instead
# (see the unit's ExecStartPre), so it self-heals across reboots.
set -e

mkdir -p /etc/X11/xorg.conf.d

KMS_CARD=""
for c in /sys/class/drm/card*; do
    [ -e "$c" ] || continue
    n=$(basename "$c")
    case "$n" in *-*) continue ;; esac
    if ls /sys/class/drm/ | grep -q "^${n}-HDMI"; then
        KMS_CARD="/dev/dri/$n"
        break
    fi
done

if [ -n "$KMS_CARD" ]; then
    echo "detect-dri-card: display DRI device detected: $KMS_CARD"
    cat > /etc/X11/xorg.conf.d/20-modesetting.conf << EOF
Section "Device"
    Identifier "Card1"
    Driver "modesetting"
    Option "kmsdev" "$KMS_CARD"
    Option "ShadowFB" "false"
EndSection
EOF
else
    echo "detect-dri-card: could not detect display DRI device - letting X11 autodetect"
    cat > /etc/X11/xorg.conf.d/20-modesetting.conf << 'EOF'
Section "Device"
    Identifier "Card1"
    Driver "modesetting"
    Option "ShadowFB" "false"
EndSection
EOF
fi
