# Raspberry Pi Single-Zone Video Player
### `feature/multi-player-sync` branch

Professional video player with draggable/resizable window control, multi-player sync, and 4K/1080p switching. Supports Raspberry Pi 4, Pi 5, CM4, and CM5.

> **Note:** This branch adds multi-player UDP sync, 4K display switching, and CM5 compatibility on top of the core player. The `main` branch contains the stable single-player version.

## ✨ Features

- 🎬 **Single resizable video zone** with full positioning control
- 🖱️ **Drag-and-drop interface** - Position and resize via web dashboard
- 🔄 **Multi-player sync** - Master/remote UDP sync across multiple devices
- 📺 **4K / 1080p switching** - Switch display resolution from the dashboard
- 💾 **Layout presets** - Save and load window configurations
- 📡 **RTSP streaming** - Play IP camera feeds and network streams
- 📁 **File upload** - Upload videos directly through web interface
- 🔁 **Loop playback** - Continuous video playback
- 🎛️ **HTTP API** - Full REST API for Node-RED and automation
- ⚡ **Hardware accelerated** - GPU/VAAPI output via X11
- 🖥️ **Headless operation** - Black screen when idle (Pi OS Lite)
- 🔧 **Auto hardware detection** - Installer detects HDMI output and audio device automatically

## 📋 Requirements

### Hardware
- **Raspberry Pi 5** or **Raspberry Pi 4**
- **Compute Module 4 (CM4)** or **Compute Module 5 (CM5)** on a compatible IO board
- MicroSD card (8GB minimum), eMMC, or NVMe storage
- HDMI display
- Network connection (Ethernet recommended for sync)

### Software
- **Raspberry Pi OS Lite (64-bit)** - Headless recommended
- Fresh installation recommended

## 🚀 Quick Start

### Installation

SSH into your Pi and run:

```bash
git clone -b feature/multi-player-sync https://github.com/keep-on-walking/raspberry-pi-single-zone-video-player.git
cd raspberry-pi-single-zone-video-player
sudo bash install.sh
```

The installer will automatically detect your connected HDMI output and audio device — no manual configuration needed.

### After Installation

1. **Reboot** the Pi: `sudo reboot`
2. **Wait 30 seconds** for services to start
3. **Access dashboard**: `http://[your-pi-ip]:5000`
4. **Upload a video** and start playing!

The screen will be black when no video is playing (this is normal).

## 🎮 Usage

### Web Dashboard

Access the web interface at `http://[pi-ip]:5000`

**Video Source:**
- Select local file from dropdown OR enter RTSP URL
- Click Play to start

**Window Positioning:**
- **Drag the blue zone** to move
- **Drag corners** to resize
- Or enter X, Y, Width, Height manually

**Display Mode:**
- Toggle between **1080p** and **4K** in the Visual Layout panel
- Canvas updates automatically to reflect the active resolution

**Save Layouts:**
- Position window as desired
- Enter preset name
- Click "Save Current Layout"
- Load anytime with one click

**Multi-Player Sync:**
- Set one device as **Master** — it broadcasts position via UDP multicast
- Set other devices as **Remote** — they listen and correct drift automatically
- Leave Master IP blank for auto-discovery on the local network
- Or enter a specific Master IP to lock to that device

### Supported File Formats

**Video Codecs:**
- **HEVC/H.265** — Best performance, hardware accelerated on Pi 4/5/CM4/CM5
- **H.264** — Hardware accelerated on Pi 4/CM4; software decode on Pi 5/CM5

**Containers:**
- MP4, AVI, MKV, MOV, WebM, FLV, WMV, M4V

**Streaming:**
- RTSP streams (e.g., `rtsp://camera-ip:554/stream`)

**For best performance, use HEVC/H.265:**
```bash
ffmpeg -i input.mp4 -c:v libx265 -crf 23 -c:a copy output.mp4
```

### Example Layouts

**Full Screen (1080p):**
- X: 0, Y: 0, Width: 1920, Height: 1080

**Full Screen (4K):**
- X: 0, Y: 0, Width: 3840, Height: 2160

**Left Half:**
- X: 0, Y: 0, Width: 960, Height: 1080

**Picture-in-Picture (Bottom Right):**
- X: 1280, Y: 720, Width: 640, Height: 360

## 🔄 Multi-Player Sync

Sync uses UDP multicast on `239.70.80.80:32320` — the same address used by FPP (Falcon Player).

**How it works:**
- The **master** broadcasts its current file and playback position every 500ms
- Each **remote** compares the master position to its own and corrects drift:
  - Drift > 0.5s → hard seek to master position
  - Drift 0.1–0.5s → nudge playback speed by ±5% for smooth correction
  - Drift < 0.1s → no action needed
- Sync config persists across reboots in `/opt/rpi-video-player/config/sync.json`

**Requirements for sync:**
- All devices on the same network
- All devices playing the same filename
- One device set as Master, others as Remote

**Node-RED control:**
```bash
# Set as master
curl -X POST http://pi-ip:5000/api/sync \
  -H "Content-Type: application/json" \
  -d '{"mode": "master"}'

# Set as remote (auto-discover master)
curl -X POST http://pi-ip:5000/api/sync \
  -H "Content-Type: application/json" \
  -d '{"mode": "remote"}'

# Set as remote (specific master IP)
curl -X POST http://pi-ip:5000/api/sync \
  -H "Content-Type: application/json" \
  -d '{"mode": "remote", "master_ip": "192.168.1.50"}'

# Get sync status
curl http://pi-ip:5000/api/sync
```

## 🔌 HTTP API

Full REST API for automation and Node-RED integration.

### Playback

```bash
# Play a video
curl -X POST http://pi-ip:5000/api/play \
  -H "Content-Type: application/json" \
  -d '{"source": "video.mp4", "loop": true, "volume": 50}'

# Stop
curl -X POST http://pi-ip:5000/api/stop

# Pause/unpause
curl -X POST http://pi-ip:5000/api/pause

# Get status
curl http://pi-ip:5000/api/status
```

### Window Geometry

```bash
curl -X POST http://pi-ip:5000/api/geometry \
  -H "Content-Type: application/json" \
  -d '{"x": 0, "y": 0, "width": 1920, "height": 1080}'
```

### Display Mode

```bash
# Switch to 4K
curl -X POST http://pi-ip:5000/api/display/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "4k"}'

# Switch to 1080p
curl -X POST http://pi-ip:5000/api/display/mode \
  -H "Content-Type: application/json" \
  -d '{"mode": "1080p"}'

# Get current mode
curl http://pi-ip:5000/api/display/mode
```

**See [API.md](API.md) for complete API documentation.**

## 🎯 Use Cases

### Multi-Screen LED Wall
- Run one Pi per LED wall panel
- Set one as Master, others as Remote
- All panels play in sync automatically
- Control geometry per panel via API or dashboard

### Digital Signage
- Loop promotional videos across multiple screens
- Switch between 1080p and 4K per display
- Remote control via Node-RED

### Live Production
- RTSP camera feeds
- Positioning for multi-camera setups
- Quick layout switching with presets

## 📊 Performance

**Raspberry Pi 5 / CM5:**
- HEVC/H.265: ~30% CPU, hardware accelerated (VAAPI)
- H.264: ~100% CPU, software decoding only
- 1080p @ 60fps: Smooth with HEVC
- RAM: ~250MB

**Raspberry Pi 4 / CM4:**
- H.264: ~12% CPU, hardware accelerated
- HEVC/H.265: hardware accelerated via VAAPI
- 1080p @ 60fps: Smooth
- RAM: ~200MB

## 🔧 Troubleshooting

### Video Won't Play

```bash
# Check services
sudo systemctl status x11-server video-player

# Check logs
tail -f /opt/rpi-video-player/logs/app.log

# Check X11
DISPLAY=:1 xrandr

# Manual start for debugging
cd /opt/rpi-video-player/src
DISPLAY=:1 /opt/rpi-video-player/venv/bin/python3 video_controller.py
```

### No Audio

```bash
# List available audio devices
aplay -l

# Test audio manually
mpv --ao=alsa --audio-device=alsa/hdmi:CARD=vc4hdmi0,DEV=0 your-video.mp4
```

### Sync Not Working

```bash
# Check sync status
curl http://pi-ip:5000/api/sync

# Check multicast traffic (install tcpdump first)
sudo apt install tcpdump
sudo tcpdump -i eth0 host 239.70.80.80

# Ensure all devices are playing the same filename
```

### Can't Resize Window

- Hard refresh browser: `Ctrl+Shift+R` (or `Cmd+Shift+R` on Mac)
- Hover slowly over corners until cursor changes
- Try zooming browser in/out

### CM5 / IO Board Specific

The installer auto-detects the connected HDMI output. If the display is blank after install:

```bash
# Check which HDMI is connected
cat /sys/class/drm/card1-HDMI-A-1/status
cat /sys/class/drm/card1-HDMI-A-2/status

# Check xrandr output
DISPLAY=:1 xrandr
```

## 🔄 Updating

```bash
cd raspberry-pi-single-zone-video-player
git pull
sudo bash install.sh
sudo reboot
```

## 📁 File Structure

```
/opt/rpi-video-player/
├── src/
│   ├── video_player.py       # MPV manager (auto-configured at install)
│   ├── video_controller.py   # Flask API
│   ├── preset_manager.py     # Layout presets
│   ├── sync_service.py       # UDP multi-player sync
│   └── stream_watchdog.py    # RTSP stream watchdog
├── web/
│   ├── templates/
│   │   └── dashboard.html
│   └── static/
│       ├── css/
│       └── js/
├── data/
│   └── videos/               # Uploaded videos
├── config/
│   ├── presets.json          # Saved layouts
│   └── sync.json             # Sync mode config
└── logs/
    ├── app.log
    └── error.log
```

## 🤝 Contributing

Issues and pull requests welcome at:
https://github.com/keep-on-walking/raspberry-pi-single-zone-video-player

## 📄 License

MIT License - See LICENSE file

## 🙏 Credits

Built for LED wall control, digital signage, and live production use cases.

Supports Raspberry Pi 4, Pi 5, CM4, and CM5 with automatic hardware detection.

---

**Need help?** Open an issue on GitHub or check the [API documentation](API.md).

**Happy video playing! 🎬**
