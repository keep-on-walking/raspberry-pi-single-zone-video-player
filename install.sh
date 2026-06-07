#!/bin/bash
# =============================================================================
# Raspberry Pi Single-Zone Video Player - Installation Script
# =============================================================================
# Supports: Raspberry Pi 4, Pi 5, CM4, CM5
# Features: Resizable video output, HTTP API, multi-player sync, 4K/1080p switching
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
echo "  * MPV video player with GPU/VAAPI hardware acceleration"
echo "  * Flask HTTP API controller"
echo "  * Web dashboard with drag-and-drop interface"
echo "  * Multi-player UDP sync (master/remote)"
echo "  * 4K / 1080p display mode switching"
echo "  * Automatic startup on boot"
echo ""
echo "Requirements:"
echo "  * Raspberry Pi 4, Pi 5, CM4, or CM5"
echo "  * Raspberry Pi OS Lite (64-bit) - headless recommended"
echo "  * Internet connection"
echo ""
read -p "Continue with installation? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo bash install.sh"
    exit 1
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
    x11-utils \
    unclutter \
    git

echo "System packages installed"

# =============================================================================
# Auto-detect Hardware
# =============================================================================

echo "Detecting hardware configuration..."

# Wait briefly for DRM to settle
sleep 2

# Find the DRM card (card1 is the GPU on Pi 4/5/CM4/CM5)
DRM_CARD="card1"
DRM_DEVICE="/dev/dri/$DRM_CARD"

# Detect connected HDMI connector
HDMI_CONNECTOR=""
for connector in /sys/class/drm/${DRM_CARD}-HDMI-A-*; do
    name=$(basename $connector)
    status=$(cat $connector/status 2>/dev/null || echo "disconnected")
    if [ "$status" = "connected" ]; then
        # Extract just the connector name e.g. HDMI-A-2
        HDMI_CONNECTOR="${name#${DRM_CARD}-}"
        echo "  Found connected display: $HDMI_CONNECTOR"
        break
    fi
done

# Fallback if nothing detected
if [ -z "$HDMI_CONNECTOR" ]; then
    HDMI_CONNECTOR="HDMI-A-1"
    echo "  No connected display detected, defaulting to $HDMI_CONNECTOR"
fi

# Map DRM connector to xrandr output name
# DRM: HDMI-A-1 -> xrandr: HDMI-1
# DRM: HDMI-A-2 -> xrandr: HDMI-2
HDMI_NUM="${HDMI_CONNECTOR##*-}"
XRANDR_OUTPUT="HDMI-$HDMI_NUM"
echo "  xrandr output: $XRANDR_OUTPUT"

# Detect ALSA HDMI audio device
# vc4hdmi0 = HDMI-1, vc4hdmi1 = HDMI-2
ALSA_CARD_NUM=$((HDMI_NUM - 1))
ALSA_DEVICE="alsa/hdmi:CARD=vc4hdmi${ALSA_CARD_NUM},DEV=0"
echo "  ALSA audio device: $ALSA_DEVICE"

echo "Hardware detection complete"
echo "  DRM device:    $DRM_DEVICE"
echo "  HDMI connector: $HDMI_CONNECTOR"
echo "  xrandr output: $XRANDR_OUTPUT"
echo "  Audio device:  $ALSA_DEVICE"
echo ""

# =============================================================================
# Create Directory Structure
# =============================================================================

echo "Creating directory structure..."

INSTALL_DIR="/opt/rpi-video-player"

mkdir -p $INSTALL_DIR/{src,web/{static/{css,js},templates},config,data/videos,logs}

echo "Directory structure created"

# =============================================================================
# Copy Application Files
# =============================================================================

echo "Copying application files..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp -r $SCRIPT_DIR/src/* $INSTALL_DIR/src/ 2>/dev/null || true
cp -r $SCRIPT_DIR/web/* $INSTALL_DIR/web/ 2>/dev/null || true
cp -r $SCRIPT_DIR/config/* $INSTALL_DIR/config/ 2>/dev/null || true

echo "Application files copied"

# =============================================================================
# Write video_player.py with detected hardware values
# =============================================================================

echo "Configuring video player for detected hardware..."

cat > $INSTALL_DIR/src/video_player.py << PYEOF
#!/usr/bin/env python3
"""
Single-Zone MPV Video Player Manager
Auto-configured for detected hardware at install time
  DRM device:    $DRM_DEVICE
  HDMI connector: $HDMI_CONNECTOR
  xrandr output: $XRANDR_OUTPUT
  Audio device:  $ALSA_DEVICE
"""

import subprocess
import json
import socket
import os
import time
from pathlib import Path


class VideoPlayer:
    """Manages a single MPV instance with hardware-accelerated playback"""

    def __init__(self, video_dir="/opt/rpi-video-player/data/videos"):
        self.video_dir = Path(video_dir)
        self.socket_path = "/tmp/mpvsocket-player"
        self.process = None
        self.state = {
            "status": "stopped",
            "source": None,
            "position": 0,
            "duration": 0,
            "volume": 50,
            "loop": True
        }
        self.geometry = {
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080
        }
        self.display_width = 1920
        self.display_height = 1080
        self.display = ":1"
        self.audio_device = "$ALSA_DEVICE"
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    def set_display_resolution(self, width, height):
        self.display_width = width
        self.display_height = height
        print(f"Display resolution set to {width}x{height}")

    def set_geometry(self, x, y, width, height):
        self.geometry = {
            "x": int(x),
            "y": int(y),
            "width": int(width),
            "height": int(height)
        }
        print(f"Geometry updated: {width}x{height}+{x}+{y}")
        if self.state["status"] in ["playing", "paused"]:
            current_source = self.state["source"]
            current_position = self.get_playback_position()
            was_paused = self.state["status"] == "paused"
            self.stop()
            time.sleep(0.5)
            self.play(current_source, seek_to=current_position)
            if was_paused:
                time.sleep(0.5)
                self.pause()

    def play(self, source, loop=None, volume=None, seek_to=None):
        if loop is not None:
            self.state["loop"] = loop
        if volume is not None:
            self.state["volume"] = volume
        if not source.startswith(('rtsp://', 'http://', 'https://')):
            source_path = self.video_dir / source
            if not source_path.exists():
                raise FileNotFoundError(f"Video file not found: {source}")
            source = str(source_path.absolute())
        if self.process and self.process.poll() is None:
            self.stop()
            time.sleep(0.5)
        cmd = self._build_command(source)
        print(f"Starting MPV: {source}")
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )
        max_wait = 5
        waited = 0
        while not os.path.exists(self.socket_path) and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
        if os.path.exists(self.socket_path):
            self.state["status"] = "playing"
            self.state["source"] = source
            if seek_to is not None and seek_to > 0:
                time.sleep(0.5)
                self.seek(seek_to)
            print(f"MPV started successfully (PID: {self.process.pid})")
            return True
        else:
            print("Failed to start MPV - socket not created")
            return False

    def _build_command(self, source):
        cmd = [
            'mpv',
            '--no-border',
            '--no-osc',
            '--no-osd-bar',
            '--really-quiet',
            '--keep-open=yes',
            '--vo=gpu',
            '--gpu-context=x11egl',
            '--hwdec=vaapi',
            f'--geometry={self.geometry["width"]}x{self.geometry["height"]}+{self.geometry["x"]}+{self.geometry["y"]}',
            '--autofit-larger=100%x100%',
            '--force-window=yes',
            '--ontop=yes',
            '--ao=alsa',
            f'--audio-device={self.audio_device}',
            f'--input-ipc-server={self.socket_path}',
            f'--volume={self.state["volume"]}',
            '--loop-playlist=inf' if self.state["loop"] else '--loop-playlist=no',
            '--cursor-autohide=always',
            '--keepaspect=no',
            '--video-aspect-override=-1',
            '--hwdec-codecs=all',
            '--cache=yes',
            '--demuxer-max-bytes=50M',
            '--demuxer-max-back-bytes=25M',
            '--vd-lavc-threads=4',
            '--network-timeout=10',
            '--rtsp-transport=tcp',
            source
        ]
        return cmd

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            print("MPV stopped")
        self.state["status"] = "stopped"
        self.state["source"] = None
        self.state["position"] = 0
        self.state["duration"] = 0
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    def pause(self):
        if self.state["status"] == "playing":
            self._send_command({"command": ["set_property", "pause", True]})
            self.state["status"] = "paused"
            print("Playback paused")
        elif self.state["status"] == "paused":
            self._send_command({"command": ["set_property", "pause", False]})
            self.state["status"] = "playing"
            print("Playback resumed")

    def seek(self, position):
        self._send_command({"command": ["seek", position, "absolute"]})
        print(f"Seeked to {position}s")

    def seek_relative(self, seconds):
        self._send_command({"command": ["seek", seconds, "relative"]})
        print(f"Seeked {'+' if seconds > 0 else ''}{seconds}s")

    def set_volume(self, volume):
        volume = max(0, min(100, int(volume)))
        self.state["volume"] = volume
        self._send_command({"command": ["set_property", "volume", volume]})
        print(f"Volume set to {volume}")

    def get_playback_position(self):
        try:
            response = self._send_command({"command": ["get_property", "time-pos"]})
            if response and "data" in response:
                return response["data"]
        except:
            pass
        return 0

    def get_duration(self):
        try:
            response = self._send_command({"command": ["get_property", "duration"]})
            if response and "data" in response:
                return response["data"]
        except:
            pass
        return 0

    def get_status(self):
        if self.state["status"] in ["playing", "paused"]:
            self.state["position"] = self.get_playback_position()
            self.state["duration"] = self.get_duration()
        return {
            "status": self.state["status"],
            "source": self.state["source"],
            "position": self.state["position"],
            "duration": self.state["duration"],
            "volume": self.state["volume"],
            "loop": self.state["loop"],
            "geometry": self.geometry
        }

    def _send_command(self, command, timeout=1):
        if not os.path.exists(self.socket_path):
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(self.socket_path)
            cmd_json = json.dumps(command) + '\n'
            sock.sendall(cmd_json.encode('utf-8'))
            response = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b'\n' in response:
                    break
            sock.close()
            if response:
                return json.loads(response.decode('utf-8'))
        except Exception as e:
            print(f"IPC error: {e}")
        return None

    def cleanup(self):
        self.stop()
PYEOF

echo "video_player.py configured"

# =============================================================================
# Set Ownership
# =============================================================================

chown -R $ACTUAL_USER:$ACTUAL_USER $INSTALL_DIR

# =============================================================================
# Install Python Dependencies
# =============================================================================

echo "Installing Python dependencies..."

sudo -u $ACTUAL_USER python3 -m venv $INSTALL_DIR/venv
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install Flask==3.0.0 Werkzeug==3.0.1

echo "Python dependencies installed"

# =============================================================================
# Configure X11
# =============================================================================

echo "Configuring X11..."

mkdir -p /etc/X11/xorg.conf.d

cat > /etc/X11/xorg.conf.d/20-modesetting.conf << 'EOF'
Section "Device"
    Identifier "Card1"
    Driver "modesetting"
    Option "kmsdev" "/dev/dri/card1"
    Option "ShadowFB" "false"
EndSection
EOF

sed -i 's/allowed_users=.*/allowed_users=anybody/' /etc/X11/Xwrapper.config 2>/dev/null || \
    echo "allowed_users=anybody" > /etc/X11/Xwrapper.config

raspi-config nonint do_boot_behaviour B2

echo "X11 configured"

# =============================================================================
# Create Systemd Services
# =============================================================================

echo "Creating systemd services..."

# X11 Server Service - uses detected HDMI output at 1080p
cat > /etc/systemd/system/x11-server.service << EOF
[Unit]
Description=X11 Server for Video Player
After=multi-user.target

[Service]
Type=simple
User=$ACTUAL_USER
Environment=DISPLAY=:1
ExecStart=/usr/bin/X :1 vt7
ExecStartPost=/bin/sleep 3
ExecStartPost=/bin/sh -c 'DISPLAY=:1 xrandr --output $XRANDR_OUTPUT --mode 1920x1080 2>/dev/null || true'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

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
WorkingDirectory=$INSTALL_DIR/src
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/src/video_controller.py
Restart=always
RestartSec=5
StandardOutput=append:$INSTALL_DIR/logs/app.log
StandardError=append:$INSTALL_DIR/logs/error.log

[Install]
WantedBy=multi-user.target
EOF

echo "Systemd services created"

# =============================================================================
# Enable Services
# =============================================================================

echo "Enabling services..."

systemctl daemon-reload
systemctl enable x11-server.service
systemctl enable video-player.service

echo "Services enabled"

# =============================================================================
# Add user to video group
# =============================================================================

echo "Configuring user permissions..."
usermod -a -G video $ACTUAL_USER
echo "User $ACTUAL_USER added to video group"

# =============================================================================
# Network Information
# =============================================================================

IP_ADDRESS=$(hostname -I | awk '{print $1}')

# =============================================================================
# Installation Complete
# =============================================================================

echo ""
echo "======================================================================="
echo "  Installation Complete!"
echo "======================================================================="
echo ""
echo "Hardware Configuration:"
echo "  HDMI output:   $XRANDR_OUTPUT"
echo "  Audio device:  $ALSA_DEVICE"
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
echo "Multi-Player Sync:"
echo "  Set one device as Master and others as Remote in the dashboard"
echo "  Sync uses UDP multicast on 239.70.80.80:32320"
echo ""
echo "Troubleshooting:"
echo "  Check services: sudo systemctl status x11-server video-player"
echo "  View logs:      tail -f $INSTALL_DIR/logs/app.log"
echo "  Check X11:      DISPLAY=:1 xrandr"
echo ""
echo "======================================================================="
echo ""

read -p "Reboot now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Rebooting..."
    reboot
fi

echo ""
echo "Installation script complete. Run 'sudo reboot' when ready!"
