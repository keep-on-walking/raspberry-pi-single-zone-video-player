# Raspberry Pi Single-Zone Video Player

Professional video player with draggable/resizable window control, optimized for Raspberry Pi 5. Perfect for LED walls, digital signage, and live production.

## ✨ Features

- 🎬 **Single resizable video zone** with full positioning control
- 🖱️ **Drag-and-drop interface** - Position and resize via web dashboard
- 💾 **Layout presets** - Save and load window configurations
- 📡 **RTSP streaming** - Play IP camera feeds and network streams
- 📁 **File upload** - Upload videos directly through web interface
- 🔁 **Loop playback** - Continuous video playback
- 🎛️ **HTTP API** - Full REST API for Node-RED and automation
- ⚡ **Hardware accelerated** - Optimized for Pi 5 GPU
- 🖥️ **Headless operation** - Black screen when idle (Pi OS Lite)
- 🔄 **Persistent settings** - Layouts survive reboots

## 📋 Requirements

### Hardware
- **Raspberry Pi 5** (recommended) or Raspberry Pi 4
- MicroSD card (8GB minimum) or NVMe storage
- HDMI display
- Network connection (WiFi or Ethernet)

### Software
- **Raspberry Pi OS Lite (64-bit)** - Headless recommended
- Fresh installation recommended

## 🚀 Quick Start

### One-Line Installation

SSH into your Pi and run:

```bash
curl -sSL https://raw.githubusercontent.com/keep-on-walking/raspberry-pi-single-zone-video-player/main/install.sh | sudo bash
```

Or manual installation:

```bash
git clone https://github.com/keep-on-walking/raspberry-pi-single-zone-video-player.git
cd raspberry-pi-single-zone-video-player
sudo bash install.sh
```

### After Installation

1. **Reboot** the Pi: `sudo reboot`
2. **Wait 30 seconds** for services to start
3. **Access dashboard**: `http://[your-pi-ip]:5000`
4. **Upload a video** and start playing!

The screen will be black when no video is playing (this is normal).

## 🎮 Usage

### Web Dashboard

Access the web interface at `http://[pi-ip]:5000`

**Important:** If using a 4K display, see [RESOLUTION.md](RESOLUTION.md) to configure the correct resolution.

**Video Source:**
- Select local file from dropdown OR enter RTSP URL
- Click Play to start

**Window Positioning:**
- **Drag the blue zone** to move
- **Drag corners** to resize
- Or enter X, Y, Width, Height manually

**Save Layouts:**
- Position window as desired
- Enter preset name
- Click "Save Current Layout"
- Load anytime with one click

### Supported File Formats

- MP4, AVI, MKV, MOV
- WebM, FLV, WMV, M4V
- RTSP streams (e.g., `rtsp://camera-ip:554/stream`)

### Example Layouts

**Full Screen:**
- X: 0, Y: 0, Width: 1920, Height: 1080

**Left Half:**
- X: 0, Y: 0, Width: 960, Height: 1080

**Picture-in-Picture (Bottom Right):**
- X: 1280, Y: 720, Width: 640, Height: 360

**Centered 80%:**
- X: 192, Y: 108, Width: 1536, Height: 864

## 🔌 HTTP API

Full REST API for automation and Node-RED integration.

### Play Video

```bash
curl -X POST http://pi-ip:5000/api/play \
  -H "Content-Type: application/json" \
  -d '{"source": "video.mp4", "loop": true, "volume": 50}'
```

### Stop Playback

```bash
curl -X POST http://pi-ip:5000/api/stop
```

### Set Window Position

```bash
curl -X POST http://pi-ip:5000/api/geometry \
  -H "Content-Type: application/json" \
  -d '{"x": 0, "y": 0, "width": 1920, "height": 1080}'
```

### Get Status

```bash
curl http://pi-ip:5000/api/status
```

**See [API.md](API.md) for complete API documentation.**

## 🎯 Use Cases

### LED Wall Control
Replace expensive Resolume setups with a $100 Raspberry Pi:
- Position video anywhere on LED wall
- Save layouts for different content
- Control via Node-RED

### Digital Signage
- Loop promotional videos
- Resize for different screen areas
- Remote control via API

### Live Production
- RTSP camera feeds
- Positioning for multi-camera setups
- Quick layout switching with presets

### Video Testing
- Test videos at different sizes/positions
- Quick upload and playback
- Hardware-accelerated smooth playback

## 📊 Performance

**Raspberry Pi 5:**
- 1080p: ~5% CPU, 100MB RAM
- 4K: ~15% CPU, 150MB RAM
- RTSP stream: ~8% CPU, 120MB RAM

**Raspberry Pi 4:**
- 1080p: ~12% CPU, 120MB RAM
- 720p recommended for best performance

## 🔧 Troubleshooting

### Video Won't Play

```bash
# Check if service is running
ps aux | grep video_controller

# Check logs
tail -f /opt/rpi-video-player/logs/app.log

# Manual start for debugging
cd /opt/rpi-video-player/src
DISPLAY=:0 /opt/rpi-video-player/venv/bin/python3 video_controller.py
```

### Screen Not Black

```bash
# Check if X11 is running
ps aux | grep X

# Restart the Pi
sudo reboot
```

### Can't Resize Window

- Hard refresh browser: `Ctrl+Shift+R` (or `Cmd+Shift+R` on Mac)
- Hover slowly over corners until cursor changes
- Try zooming browser in/out

### Performance Issues

```bash
# Check MPV is using hardware decoding
# Look for "hwdec" in logs
tail -f /opt/rpi-video-player/logs/app.log
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
│   ├── video_player.py       # MPV manager
│   ├── preset_manager.py     # Layout presets
│   └── video_controller.py   # Flask API
├── web/
│   ├── templates/
│   │   └── dashboard.html
│   └── static/
│       ├── css/
│       ├── js/
│       └── ...
├── data/
│   └── videos/               # Uploaded videos
├── config/
│   └── presets.json          # Saved layouts
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

Built for LED wall control and live production use cases.

Optimized for Raspberry Pi 5 with hardware acceleration.

---

**Need help?** Open an issue on GitHub or check the [API documentation](API.md).

**Happy video playing! 🎬**
