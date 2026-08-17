# Raspberry Pi Video Player — Single-Zone & Multi-Device Sync

Professional video player with draggable/resizable window control, now with
optional **frame-near-synced playback across multiple Raspberry Pi devices**.
Runs standalone exactly as before, or as a **master** driving one or more
**remotes** that play their own local files in sync with it — each device
showing its own content, all moving together.

> This documents the `multisync` branch. If you just want the original
> single-device player, everything below works identically with sync left
> at its default (`role: "off"`) — nothing about single-device use changed.

## ✨ Features

**Core player** (unchanged from the original release):
- 🎬 Single resizable video zone with full positioning control
- 🖱️ Drag-and-drop dashboard, layout presets, RTSP streaming, file upload
- 🎛️ Full HTTP API for Node-RED and automation
- ⚡ Hardware-accelerated decode, persistent mpv instance (fast, low-jitter starts)

**New: multi-device sync**
- 🔗 One master, any number of remotes — each remote plays its **own local
  file** (same basename, different content per device is fine)
- 🎯 Frame-near sync (±1-2 frames target; real-world testing has shown
  single-digit-ms accuracy over multi-hour runs — see [GUIDE.md](GUIDE.md))
- ⏱️ Scheduled starts — play/resume land at the same wall-clock instant on
  every device, not "close enough after a moment"
- 📺 Per-device HDMI output port and audio device selection, persisted
  across reboots
- 🖼️ Synced screensaver — auto-plays when the master is idle, in sync,
  across every device
- 📊 Live sync status dashboard — role, drift, clock health, per-remote view
- 🎞️ Ticker overlay — a second, independently-controlled video strip
  (e.g. for a bottom-of-screen ticker alongside an RTSP feed)
- 🔓 Direct per-device override for maintenance/RTSP workflows via Node-RED

## 📋 Requirements

### Hardware
- Raspberry Pi 5, Pi 4, or CM4 (any mix — master and remotes don't need to
  match) — see [GUIDE.md](GUIDE.md) for real hardware notes and CPU/storage
  findings from testing
- HDMI display (or none — the player runs fine headless once display output
  is forced; see GUIDE.md)
- Wired Ethernet for any device using sync (chrony's sub-ms clock agreement
  assumes a quiet wired LAN)

### Software
- Raspberry Pi OS Lite (64-bit)

## 🚀 Quick Start

### Single device (no sync)

```bash
curl -sSL https://raw.githubusercontent.com/keep-on-walking/raspberry-pi-single-zone-video-player/multisync/install.sh | sudo bash
```

Reboot, then open `http://[pi-ip]:5000`. Behaves exactly like the original
single-zone player — sync defaults to off.

### Multi-device sync

Full step-by-step provisioning (hostnames, chrony, roles, verification) is
in **[GUIDE.md](GUIDE.md)** — it's a real walkthrough, not just a summary,
including the exact commands used to bring up and verify a real master +
remote pair. Short version:

```bash
curl -sSL https://raw.githubusercontent.com/keep-on-walking/raspberry-pi-single-zone-video-player/multisync/install.sh | sudo bash
sudo bash /opt/rpi-video-player/bin/chrony-setup.sh --role master   # or: --role remote --master-host <master-hostname>.local
```

Then set `sync.role` (`master` or `remote`) and restart the service — see
GUIDE.md for the exact command, since there's no dashboard toggle for this
yet.

## 🎮 Usage

Open `http://[pi-ip]:5000` for the dashboard. Every panel is covered in
detail in [GUIDE.md](GUIDE.md); quick summary:

- **Visual Layout** — drag/resize the video zone, presets
- **Video Source** — local file or RTSP
- **Window Geometry** — precise X/Y/W/H
- **Ticker Overlay** — a second video strip, independent of the main one
- **Display Output & Audio** — which HDMI port, which audio device
- **Screensaver** — auto-plays in sync when the master goes idle
- **Sync status panel** (appears automatically when sync is active) — role,
  live drift, per-remote health

### Supported File Formats

**Video Codecs:** HEVC/H.265 (hardware-accelerated on Pi 5), H.264 (works,
software decode). **Containers:** MP4, AVI, MKV, MOV, WebM, FLV, WMV, M4V.
**Streaming:** RTSP.

```bash
# Convert to HEVC for best Pi 5 performance
ffmpeg -i input.mp4 -c:v libx265 -crf 23 -c:a copy output.mp4
```

## 🔌 HTTP API

```bash
curl -X POST http://pi-ip:5000/api/play \
  -H "Content-Type: application/json" \
  -d '{"source": "video.mp4", "loop": true, "volume": 50}'

curl http://pi-ip:5000/api/status
curl http://pi-ip:5000/api/sync/status
```

**[API.md](API.md)** has the full endpoint reference. **[GUIDE.md](GUIDE.md)**
has worked examples for every feature, including Node-RED patterns for
sync-aware playback, RTSP-on-remote overrides, and the ticker overlay.

## 🎯 Use Cases

- **Multi-screen video walls / multi-angle displays** — each screen its own
  camera angle or content, frame-synced
- **LED wall control** — position video anywhere, save layouts, control via
  Node-RED
- **Digital signage** — loop content, synced screensaver when idle
- **Live production** — RTSP feeds, optional ticker overlay, multi-device
  positioning

## 📊 Performance (real hardware, this session's testing)

- **CM4, 1GB RAM, eMMC** (master role, decoding + audio output): ~62% of one
  core for 1080p HEVC
- **CM4, 2GB RAM, SD card** (remote role, muted): ~48-53% of one core
- Both comfortably handle sync's chase loop (5Hz) and 10Hz state broadcast
  on top of playback — see GUIDE.md for what happens under combined load
  (ticker + main content, scaled/resized output) and how to check for
  yourself
- Sync accuracy in a 10.4-hour real-hardware soak test: **7-20ms sustained**,
  zero UDP packet loss

## 🔧 Troubleshooting

Common issues and their real fixes are in **[GUIDE.md](GUIDE.md)**'s
troubleshooting section, including two that came up during real deployment:
a DRI-card enumeration mismatch that breaks the display after a reboot, and
a dual-HDMI-port case where video plays correctly but nothing reaches the
physically connected screen. Quick pointers:

```bash
# Service status
sudo systemctl status x11-server video-player

# Logs
tail -f /opt/rpi-video-player/logs/app.log
tail -f /opt/rpi-video-player/logs/error.log

# Sync health
curl http://localhost:5000/api/sync/status | python3 -m json.tool
```

## 🔄 Updating

```bash
cd raspberry-pi-single-zone-video-player
git pull origin multisync
sudo bash install.sh
sudo systemctl restart video-player
```

A reboot is only needed after changes to `cmdline.txt` (the installer tells
you explicitly when that's the case, e.g. the dual-HDMI forcing step).

## 📁 File Structure

```
/opt/rpi-video-player/
├── bin/
│   ├── detect-dri-card.sh       # self-healing DRI card detection
│   └── select-hdmi-output.sh    # self-healing HDMI port selection
├── src/
│   ├── video_player.py          # persistent mpv manager
│   ├── video_controller.py      # Flask API + dashboard routes
│   ├── preset_manager.py        # layout presets
│   ├── sync_config.py           # sync role/tuning schema
│   ├── sync_master.py           # declared-state broadcast + orchestration
│   ├── sync_remote.py           # chase loop + scheduled receive
│   ├── device_config.py         # HDMI port / audio device persistence
│   └── chrony_status.py         # clock health reporting
├── web/                         # dashboard (templates/static)
├── data/videos/                 # uploaded videos (shared across features)
├── config/
│   ├── presets.json
│   ├── sync.json                # role, tuning, screensaver
│   └── device.json              # HDMI port, audio device
└── logs/
```

## 📚 Further reading

- **[GUIDE.md](GUIDE.md)** — full setup and operation guide, every feature
  explained, real troubleshooting, Node-RED patterns
- **[API.md](API.md)** — complete HTTP API reference
- **[DESIGN.md](DESIGN.md)** — the sync protocol's technical design and
  build contract
- **PHASE1-NOTES.md** through **PHASE4-NOTES.md** — implementation history
  and real-hardware verification results for each build phase

## 🤝 Contributing

Issues and pull requests welcome at:
https://github.com/keep-on-walking/raspberry-pi-single-zone-video-player

## 📄 License

MIT License - See LICENSE file

---

**Need help?** Start with [GUIDE.md](GUIDE.md), then [API.md](API.md) for
endpoint details, or open an issue on GitHub.
