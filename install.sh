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
# Configure Minimal X11 Environment
# =============================================================================

echo "🖥️ Configuring minimal X11 environment..."

# Create .xinitrc for automatic X11 startup
cat > "$ACTUAL_HOME/.xinitrc" << 'EOF'
#!/bin/sh
# Minimal X11 session for video playback

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Allow local connections
xhost +local:

# Hide mouse cursor
unclutter -idle 0 -root &

# Set black background
xsetroot -solid black

# Keep X11 running
exec tail -f /dev/null
EOF

chmod +x "$ACTUAL_HOME/.xinitrc"
chown $ACTUAL_USER:$ACTUAL_USER "$ACTUAL_HOME/.xinitrc"

# Configure auto-login to console
raspi-config nonint do_boot_behaviour B2

echo "✅ X11 environment configured"

# =============================================================================
# Create Startup Script
# =============================================================================

echo "🚀 Creating startup script..."

cat > "$ACTUAL_HOME/start-video-player.sh" << EOF
#!/bin/bash
# Start X11 and video player

# Wait a bit for system to stabilize
sleep 5

# Start X11 in background if not running
if [ -z "\$DISPLAY" ]; then
    startx -- -nocursor &
    sleep 10
fi

# Set DISPLAY
export DISPLAY=:0

# Wait for X11 to be ready
timeout=20
while [ \$timeout -gt 0 ]; do
    if xset q &>/dev/null; then
        break
    fi
    sleep 1
    timeout=\$((timeout - 1))
done

# Start video player
cd $INSTALL_DIR/src
$INSTALL_DIR/venv/bin/python3 video_controller.py >> $INSTALL_DIR/logs/app.log 2>> $INSTALL_DIR/logs/error.log &

echo "Video player started"
EOF

chmod +x "$ACTUAL_HOME/start-video-player.sh"
chown $ACTUAL_USER:$ACTUAL_USER "$ACTUAL_HOME/start-video-player.sh"

echo "✅ Startup script created"

# =============================================================================
# Configure Autostart
# =============================================================================

echo "⚙️ Configuring autostart..."

# Add to .bash_profile for automatic startup on login
if ! grep -q "start-video-player.sh" "$ACTUAL_HOME/.bash_profile" 2>/dev/null; then
    cat >> "$ACTUAL_HOME/.bash_profile" << 'EOF'

# Auto-start video player on login (tty1 only)
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    ~/start-video-player.sh
fi
EOF
    chown $ACTUAL_USER:$ACTUAL_USER "$ACTUAL_HOME/.bash_profile"
fi

echo "✅ Autostart configured"

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
echo "  Check if running: ps aux | grep video_controller"
echo "  View logs: tail -f $INSTALL_DIR/logs/app.log"
echo "  Manual start: $ACTUAL_HOME/start-video-player.sh"
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
