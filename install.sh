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
echo "  • Minimal X11 environment (headless optimized)"
echo "  • MPV video player with Pi 5 hardware acceleration"
echo "  • Flask HTTP API controller"
echo "  • Web dashboard with drag-and-drop interface"
echo "  • Automatic startup on boot"
echo ""
echo "Requirements:"
echo "  • Raspberry Pi 5 (or Pi 4)"
echo "  • Raspberry Pi OS Lite (64-bit) - headless recommended"
echo "  • Internet connection"
echo ""
read -p "Continue with installation? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root: sudo bash install.sh"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
ACTUAL_HOME=$(eval echo ~$ACTUAL_USER)

echo ""
echo "📋 Installation Configuration:"
echo "  User: $ACTUAL_USER"
echo "  Home: $ACTUAL_HOME"
echo ""

# =============================================================================
# Install System Packages
# =============================================================================

echo "📦 Installing system packages..."
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

echo "✅ System packages installed"

# =============================================================================
# Create Directory Structure
# =============================================================================

echo "📁 Creating directory structure..."

INSTALL_DIR="/opt/rpi-video-player"

mkdir -p $INSTALL_DIR/{src,web/{static/{css,js},templates},config,data/videos,logs}

echo "✅ Directory structure created"

# =============================================================================
# Copy Application Files
# =============================================================================

echo "📝 Copying application files..."

# Copy all files from current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp -r $SCRIPT_DIR/src/* $INSTALL_DIR/src/ 2>/dev/null || true
cp -r $SCRIPT_DIR/web/* $INSTALL_DIR/web/ 2>/dev/null || true
cp -r $SCRIPT_DIR/config/* $INSTALL_DIR/config/ 2>/dev/null || true

# Set ownership
chown -R $ACTUAL_USER:$ACTUAL_USER $INSTALL_DIR

echo "✅ Application files copied"

# =============================================================================
# Install Python Dependencies
# =============================================================================

echo "🐍 Installing Python dependencies..."

# Create virtual environment
sudo -u $ACTUAL_USER python3 -m venv $INSTALL_DIR/venv

# Install packages
$INSTALL_DIR/venv/bin/pip install --upgrade pip
$INSTALL_DIR/venv/bin/pip install Flask==3.0.0 Werkzeug==3.0.1

echo "✅ Python dependencies installed"

# =============================================================================
# Configure X11
# =============================================================================

echo "🖥️ Configuring X11..."

# Create X11 config for Pi 5 GPU
mkdir -p /etc/X11/xorg.conf.d

cat > /etc/X11/xorg.conf.d/20-modesetting.conf << 'EOF'
Section "Device"
    Identifier "Card1"
    Driver "modesetting"
    Option "kmsdev" "/dev/dri/card1"
    Option "ShadowFB" "false"
EndSection
EOF

# Configure X11 wrapper to allow any user to start X server
echo "Configuring X11 permissions..."
sed -i 's/allowed_users=.*/allowed_users=anybody/' /etc/X11/Xwrapper.config 2>/dev/null || \
    echo "allowed_users=anybody" > /etc/X11/Xwrapper.config

# Configure auto-login to console
raspi-config nonint do_boot_behaviour B2

echo "✅ X11 configured"

# =============================================================================
# Create Systemd Services
# =============================================================================

echo "🚀 Creating systemd services..."

# X11 Server Service
cat > /etc/systemd/system/x11-server.service << EOF
[Unit]
Description=X11 Server for Video Player
After=multi-user.target

[Service]
Type=simple
User=$ACTUAL_USER
Environment=DISPLAY=:1
ExecStart=/usr/bin/X :1 vt7
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

echo "✅ Systemd services created"

# =============================================================================
# Enable Services
# =============================================================================

echo "⚙️ Enabling services..."

systemctl daemon-reload
systemctl enable x11-server.service
systemctl enable video-player.service

echo "✅ Services enabled"

# =============================================================================
# Network Information
# =============================================================================

echo ""
echo "📡 Detecting network information..."
IP_ADDRESS=$(hostname -I | awk '{print $1}')

# =============================================================================
# Installation Complete
# =============================================================================

echo ""
echo "======================================================================="
echo "✅ Installation Complete!"
echo "======================================================================="
echo ""
echo "📂 Installation Directory: $INSTALL_DIR"
echo "📁 Video Upload Directory: $INSTALL_DIR/data/videos"
echo "📝 Logs Directory: $INSTALL_DIR/logs"
echo ""
echo "🌐 Web Interface: http://$IP_ADDRESS:5000"
echo ""
echo "🎮 Control the system via:"
echo "  • Web dashboard at the URL above"
echo "  • HTTP API (see API.md for documentation)"
echo ""
echo "📋 Next Steps:"
echo "  1. REBOOT to start the system: sudo reboot"
echo "  2. Wait ~30 seconds after boot for services to start"
echo "  3. Screen will be black (this is normal)"
echo "  4. Access web interface: http://$IP_ADDRESS:5000"
echo "  5. Upload videos and configure window layout"
echo ""
echo "🔧 Troubleshooting:"
echo "  Check services: sudo systemctl status x11-server video-player"
echo "  View logs: tail -f $INSTALL_DIR/logs/app.log"
echo "  Check X11: DISPLAY=:1 xrandr"
echo ""
echo "💡 Single-zone video player with full positioning control"
echo "💡 Black screen when idle (no video playing)"
echo "💡 Optimized for Raspberry Pi 5 with hardware acceleration"
echo ""
echo "======================================================================="
echo ""

echo "Installation complete! Please reboot to start the system."
echo ""
read -p "Reboot now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🔄 Rebooting..."
    reboot
fi

echo ""
echo "Installation script complete. Run 'sudo reboot' when ready! 🎉"
