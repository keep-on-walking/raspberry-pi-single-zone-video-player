#!/bin/bash
# =============================================================================
# Raspberry Pi Single-Zone Video Player - Installation Script
# =============================================================================
# Installs headless single-zone video player with HTTP API control
# Optimized for Raspberry Pi 5 with minimal X11
#
# Usage: sudo bash install.sh
# =============================================================================

set -e

echo "======================================================================="
echo "  Raspberry Pi Single-Zone Video Player - Installer"
echo "======================================================================="
echo ""
echo "This will install:"
echo "  * Minimal X11 environment (headless optimized)"
echo "  * MPV video player with Pi 5 hardware acceleration"
echo "  * Flask HTTP API controller"
echo "  * Web dashboard with drag-and-drop interface"
echo "  * Automatic startup on boot"
echo ""
echo "Requirements:"
echo "  * Raspberry Pi 5 (or Pi 4)"
echo "  * Raspberry Pi OS Lite (64-bit) - headless recommended"
echo "  * Internet connection"
echo ""
# Prompt via /dev/tty so this works when piped (curl | sudo bash);
# auto-continue when no terminal is available (unattended installs).
# When the self-bootstrap re-launches this script, the question was
# already answered once - don't ask twice (RPI_INSTALL_CONFIRMED).
if [ -n "$RPI_INSTALL_CONFIRMED" ]; then
    echo "(already confirmed - continuing)"
elif [ -r /dev/tty ]; then
    read -p "Continue with installation? (y/N) " -n 1 -r < /dev/tty || REPLY=y
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi
else
    echo "No terminal detected - continuing unattended."
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash install.sh"
    exit 1
fi

# =============================================================================
# Self-bootstrap: if the application files aren't alongside this script
# (e.g. it was piped from curl), install git, clone the repo at the right
# branch, and re-run from the clone. Branch defaults to the branch this
# copy of the installer ships on; override with:  ... | sudo bash -s -- <branch>
# =============================================================================

INSTALL_BRANCH="${1:-multisync}"
REPO_URL="https://github.com/keep-on-walking/raspberry-pi-single-zone-video-player.git"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || pwd)"
if [ ! -d "$SCRIPT_DIR/src" ]; then
    echo ""
    echo "Application files not found next to installer - bootstrapping from GitHub"
    echo "  Branch: $INSTALL_BRANCH"
    apt update
    apt install -y git
    BOOTSTRAP_DIR=$(mktemp -d /tmp/rpi-player-install.XXXXXX)
    git clone --branch "$INSTALL_BRANCH" --depth 1 "$REPO_URL" "$BOOTSTRAP_DIR/repo"
    echo "Re-launching installer from the cloned repo..."
    export RPI_INSTALL_CONFIRMED=1
    exec bash "$BOOTSTRAP_DIR/repo/install.sh" "$INSTALL_BRANCH"
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
ACTUAL_HOME=$(eval echo ~$ACTUAL_USER)

echo ""
echo "Installation Configuration:"
echo "  User: $ACTUAL_USER"
echo "  Home: $ACTUAL_HOME"
echo ""

# =============================================================================
# Install System Packages
# =============================================================================

echo "Installing system packages..."
apt update
apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    mpv \
    xserver-xorg \
    xinit \
    x11-xserver-utils \
    unclutter \
    git

echo "System packages installed"

# =============================================================================
# Pin mpv to a known-good version
# =============================================================================
# mpv 0.40.0 (the current Debian trixie package, just installed above) has a
# real regression on the vc4/v3d GPU driver stack used by every Pi model this
# project targets: visible screen tearing during playback, and a separate
# DRM-PRIME hardware-decode surface import failure ("Mapping hardware decoded
# surface failed" on every frame). Confirmed via extensive real-hardware
# testing across a CM4, a Pi 4, and a Pi 5 (different GPU generations),
# H.264 and H.265 content, and every mpv --vo/--hwdec/fullscreen/compositor
# combination tried - see RIPPLE-TEARING-INVESTIGATION.md for the full story.
# mpv 0.38.0 does not have either bug. Vendored here (not fetched from
# snapshot.debian.org at install time) so every install is reproducible and
# doesn't depend on that archive's availability going forward.
#
# Revisit this whenever a newer mpv release is available: re-run the tearing
# test from RIPPLE-TEARING-INVESTIGATION.md, and if a newer version is clean,
# remove this pin (delete this block and the vendor/mpv-0.38.0-1+b1/ dir).
echo "Pinning mpv to known-good 0.38.0 (see RIPPLE-TEARING-INVESTIGATION.md)..."
MPV_PIN_DIR="$SCRIPT_DIR/vendor/mpv-0.38.0-1+b1"
if [ -d "$MPV_PIN_DIR" ]; then
    apt install -y --allow-downgrades "$MPV_PIN_DIR"/libmpv2_0.38.0-1+b1_arm64.deb "$MPV_PIN_DIR"/mpv_0.38.0-1+b1_arm64.deb
    apt-mark hold mpv libmpv2
    echo "mpv pinned to $(mpv --version | head -1)"
else
    echo "⚠️  $MPV_PIN_DIR not found - staying on the repo's default mpv"
    echo "   (this will very likely have the tearing bug - see RIPPLE-TEARING-INVESTIGATION.md)"
fi

# =============================================================================
# Create Directory Structure
# =============================================================================

echo "Creating directory structure..."

INSTALL_DIR="/opt/rpi-video-player"

mkdir -p $INSTALL_DIR/{src,web/{static/{css,js},templates},config,data/videos,logs,bin}

echo "Directory structure created"

# =============================================================================
# Copy Application Files
# =============================================================================

echo "Copying application files..."

# Copy all files from current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp -r $SCRIPT_DIR/src/* $INSTALL_DIR/src/ 2>/dev/null || true
cp -r $SCRIPT_DIR/web/* $INSTALL_DIR/web/ 2>/dev/null || true
cp -r $SCRIPT_DIR/config/* $INSTALL_DIR/config/ 2>/dev/null || true

# Set ownership
chown -R $ACTUAL_USER:$ACTUAL_USER $INSTALL_DIR

echo "Application files copied"

# Operator scripts (chrony-setup.sh) aren't part of the running app, so
# they weren't copied above - but they still need to live somewhere
# stable. Cloning via the curl one-liner bootstrap leaves the source repo
# in a temp directory that may not survive a reboot, so without this,
# chrony-setup.sh would only be reachable from wherever the repo happened
# to be cloned - not reliable. Give it a permanent, predictable home.
cp $SCRIPT_DIR/chrony-setup.sh $INSTALL_DIR/bin/chrony-setup.sh
chmod +x $INSTALL_DIR/bin/chrony-setup.sh

# =============================================================================
# Install Python Dependencies
# =============================================================================

echo "Installing Python dependencies..."

# Create virtual environment
sudo -u $ACTUAL_USER python3 -m venv $INSTALL_DIR/venv

# Install packages
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install Flask==3.0.0 Werkzeug==3.0.1

echo "Python dependencies installed"

# =============================================================================
# Configure X11
# =============================================================================

echo "Configuring X11..."

# Create X11 config for Pi 5 GPU
mkdir -p /etc/X11/xorg.conf.d

# Which DRI card drives the display (the vc4/display device, not the
# v3d render-only node) isn't guaranteed stable across reboots, so this
# can't be a one-time install step - detect-dri-card.sh is installed and
# re-run by x11-server.service on every start (see ExecStartPre below).
cp $SCRIPT_DIR/detect-dri-card.sh $INSTALL_DIR/bin/detect-dri-card.sh
chmod +x $INSTALL_DIR/bin/detect-dri-card.sh
bash $INSTALL_DIR/bin/detect-dri-card.sh

# HDMI output port selection (dashboard-configurable, device_config.py) -
# re-applied by x11-server.service on every start, same self-healing
# pattern as the DRI card detection above.
cp $SCRIPT_DIR/select-hdmi-output.sh $INSTALL_DIR/bin/select-hdmi-output.sh
chmod +x $INSTALL_DIR/bin/select-hdmi-output.sh

# Boards with two HDMI outputs (e.g. cases that break out both of the
# Pi 5's micro-HDMI ports to full-size HDMI) need BOTH connectors forced
# in cmdline.txt, or whichever port isn't in the forced param never gets
# an active signal - select-hdmi-output.sh can only switch between ports
# that already have one. Idempotent: only rewrites if something's missing.
echo "Checking dual-HDMI forced output..."
CMDLINE_FILE="/boot/firmware/cmdline.txt"
if [ -f "$CMDLINE_FILE" ]; then
    CURRENT_CMDLINE=$(head -n1 "$CMDLINE_FILE")
    NEW_CMDLINE="$CURRENT_CMDLINE"
    CMDLINE_CHANGED=0
    if ! echo "$CURRENT_CMDLINE" | grep -q 'video=HDMI-A-1:'; then
        NEW_CMDLINE="$NEW_CMDLINE video=HDMI-A-1:1920x1080M@60D"
        CMDLINE_CHANGED=1
    fi
    if ! echo "$CURRENT_CMDLINE" | grep -q 'video=HDMI-A-2:'; then
        NEW_CMDLINE="$NEW_CMDLINE video=HDMI-A-2:1920x1080M@60D"
        CMDLINE_CHANGED=1
    fi
    if [ "$CMDLINE_CHANGED" -eq 1 ]; then
        echo "$NEW_CMDLINE" > "$CMDLINE_FILE"
        echo "⚠️  Forced both HDMI ports in $CMDLINE_FILE - REBOOT REQUIRED for this to take effect"
    else
        echo "Both HDMI ports already forced in $CMDLINE_FILE"
    fi
else
    echo "⚠️  $CMDLINE_FILE not found - HDMI output port selection may only work on one port"
fi

# Configure X11 wrapper to allow any user to start X server
echo "Configuring X11 permissions..."
sed -i 's/allowed_users=.*/allowed_users=anybody/' /etc/X11/Xwrapper.config 2>/dev/null || \
    echo "allowed_users=anybody" > /etc/X11/Xwrapper.config

# Configure auto-login to console
raspi-config nonint do_boot_behaviour B2

echo "X11 configured"

# =============================================================================
# Create Systemd Services
# =============================================================================

echo "Creating systemd services..."

# X11 Server Service
cat > /etc/systemd/system/x11-server.service << EOF
[Unit]
Description=X11 Server for Video Player
After=multi-user.target

[Service]
Type=simple
User=$ACTUAL_USER
Environment=DISPLAY=:1
ExecStartPre=+$INSTALL_DIR/bin/detect-dri-card.sh
ExecStart=/usr/bin/X :1 vt7 -noreset
ExecStartPost=/bin/sleep 3
ExecStartPost=/bin/sh -c 'DISPLAY=:1 bash $INSTALL_DIR/bin/select-hdmi-output.sh'
ExecStartPost=/bin/sh -c 'DISPLAY=:1 xset s off; DISPLAY=:1 xset s noblank; DISPLAY=:1 xset -dpms'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# On low-RAM devices (1GB Pi 4), trim the player's demuxer cache
TOTAL_MB=$(free -m | awk '/^Mem:/{print $2}')
CACHE_ENV=""
if [ "$TOTAL_MB" -le 1200 ]; then
    echo "Low-memory device detected (${TOTAL_MB}MB) - setting 20MB demuxer cache"
    CACHE_ENV="Environment=RPI_PLAYER_CACHE_MB=20"
fi

# Video Player Service
cat > /etc/systemd/system/video-player.service << EOF
[Unit]
Description=Video Player Service
After=x11-server.service
Requires=x11-server.service

[Service]
Type=simple
User=$ACTUAL_USER
Environment=DISPLAY=:1
$CACHE_ENV
WorkingDirectory=$INSTALL_DIR/src
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/src/video_controller.py
Restart=always
RestartSec=5
StandardOutput=append:$INSTALL_DIR/logs/app.log
StandardError=append:$INSTALL_DIR/logs/error.log
EOF

# Video Player Timer (starts service 10s after boot)
cat > /etc/systemd/system/video-player.timer << 'EOF'
[Unit]
Description=Start Video Player 10s after boot
After=x11-server.service

[Timer]
OnBootSec=10s

[Install]
WantedBy=timers.target
EOF

echo "Systemd services created"

# =============================================================================
# Enable Services
# =============================================================================

echo "Enabling services..."

systemctl daemon-reload
systemctl enable x11-server.service
systemctl enable video-player.timer

echo "Services enabled"

# =============================================================================
# Network Information
# =============================================================================

echo ""
echo "Detecting network information..."
IP_ADDRESS=$(hostname -I | awk '{print $1}')

# =============================================================================
# Installation Complete
# =============================================================================

echo ""
echo "======================================================================="
echo "  Installation Complete!"
echo "======================================================================="
echo ""
echo "Installation Directory: $INSTALL_DIR"
echo "Video Upload Directory: $INSTALL_DIR/data/videos"
echo "Logs Directory:         $INSTALL_DIR/logs"
echo ""
echo "Web Interface: http://$IP_ADDRESS:5000"
echo ""
echo "Next Steps:"
echo "  1. REBOOT to start the system: sudo reboot"
echo "  2. Wait ~30 seconds after boot for services to start"
echo "  3. Screen will be black (this is normal)"
echo "  4. Access web interface: http://$IP_ADDRESS:5000"
echo "  5. Upload videos and configure window layout"
echo ""
echo "Troubleshooting:"
echo "  Check services: sudo systemctl status x11-server video-player"
echo "  View logs:      tail -f $INSTALL_DIR/logs/app.log"
echo "  Check X11:      DISPLAY=:1 xrandr"
echo ""
echo "======================================================================="
echo ""

if [ -r /dev/tty ]; then
    read -p "Reboot now? (y/N) " -n 1 -r < /dev/tty || REPLY=n
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Rebooting..."
        reboot
    fi
fi

echo ""
echo "Installation script complete. Run 'sudo reboot' when ready!"
