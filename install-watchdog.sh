#!/bin/bash
# Install Stream Watchdog Service

set -e

echo "Installing Stream Watchdog..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root: sudo bash install-watchdog.sh"
    exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
INSTALL_DIR="/opt/rpi-video-player"

# Copy watchdog script
echo "📝 Installing watchdog script..."
cp stream_watchdog.py $INSTALL_DIR/src/
chown $ACTUAL_USER:$ACTUAL_USER $INSTALL_DIR/src/stream_watchdog.py
chmod +x $INSTALL_DIR/src/stream_watchdog.py

# Create systemd service
echo "🚀 Creating systemd service..."
cat > /etc/systemd/system/stream-watchdog.service << EOF
[Unit]
Description=Stream Watchdog Service
After=video-player.service
Requires=video-player.service

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$INSTALL_DIR/src
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/src/stream_watchdog.py
Restart=always
RestartSec=5
StandardOutput=append:$INSTALL_DIR/logs/watchdog.log
StandardError=append:$INSTALL_DIR/logs/watchdog.log

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
echo "⚙️ Enabling watchdog service..."
systemctl daemon-reload
systemctl enable stream-watchdog.service
systemctl start stream-watchdog.service

echo ""
echo "✅ Stream Watchdog installed!"
echo ""
echo "Status: sudo systemctl status stream-watchdog"
echo "Logs: tail -f $INSTALL_DIR/logs/watchdog.log"
echo ""
echo "The watchdog will now automatically restart RTSP streams when they fail."
