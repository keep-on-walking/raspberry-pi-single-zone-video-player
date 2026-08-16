# HTTP API Documentation

Complete REST API reference for Raspberry Pi Single-Zone Video Player.

Perfect for Node-RED automation, custom scripts, and remote control.

## Base URL

```
http://[pi-ip]:5000
```

## Table of Contents

- [Player Control](#player-control)
- [Window Geometry](#window-geometry)
- [Ticker Overlay](#ticker-overlay)
- [Display Resolution](#display-resolution)
- [Display Output](#display-output)
- [Audio](#audio)
- [Presets](#presets)
- [File Management](#file-management)
- [Status](#status)
- [Sync](#sync)

---

## Player Control

> **Sync-aware.** On a device with `sync.role: "master"`, these five
> endpoints drive the whole synced deployment: `/api/play` and
> `/api/pause` (when resuming) schedule a frame-exact start across every
> remote instead of just playing locally (see `DESIGN.md` §6.3);
> `/api/stop`, `/api/seek`, and `/api/seek-relative` apply immediately
> and re-broadcast the new state. On a `"remote"`, all five are **locked**
> — they return `409 Conflict` since the remote's own sync loop owns
> local playback. Add `"override": true` to the request body to bypass
> this for direct control (e.g. playing RTSP directly on a remote — see
> `GUIDE.md`'s RTSP section). `role: "off"` (the default) behaves exactly
> as documented below, no sync involved.

### Play Video

Start playing a video file or RTSP stream.

**Endpoint:** `POST /api/play`

**Request Body:**
```json
{
  "source": "video.mp4",
  "loop": true,
  "volume": 50
}
```

**Parameters:**
- `source` (required): Video filename or RTSP URL
- `loop` (optional, default: true): Loop playback
- `volume` (optional, default: 50): Volume 0-100

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/play \
  -H "Content-Type: application/json" \
  -d '{"source": "promo.mp4", "loop": true, "volume": 75}'
```

**Response:**
```json
{
  "status": "playing",
  "source": "promo.mp4"
}
```

### Stop Playback

Stop video and return to black screen.

**Endpoint:** `POST /api/stop`

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/stop
```

**Response:**
```json
{
  "status": "stopped"
}
```

### Pause/Resume

Toggle pause state.

**Endpoint:** `POST /api/pause`

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/pause
```

**Response:**
```json
{
  "status": "paused"
}
```

### Seek to Position

Seek to specific time position.

**Endpoint:** `POST /api/seek`

**Request Body:**
```json
{
  "position": 30.5
}
```

**Parameters:**
- `position` (required): Position in seconds (float)

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/seek \
  -H "Content-Type: application/json" \
  -d '{"position": 45}'
```

### Seek Relative

Seek forward or backward from current position.

**Endpoint:** `POST /api/seek-relative`

**Request Body:**
```json
{
  "seconds": 10
}
```

**Parameters:**
- `seconds` (required): Seconds to seek (negative for backward)

**Example:**
```bash
# Skip forward 10 seconds
curl -X POST http://192.168.1.100:5000/api/seek-relative \
  -H "Content-Type: application/json" \
  -d '{"seconds": 10}'

# Go back 5 seconds
curl -X POST http://192.168.1.100:5000/api/seek-relative \
  -H "Content-Type: application/json" \
  -d '{"seconds": -5}'
```

### Set Volume

Adjust playback volume.

**Endpoint:** `POST /api/volume`

**Request Body:**
```json
{
  "volume": 75
}
```

**Parameters:**
- `volume` (required): Volume level 0-100

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/volume \
  -H "Content-Type: application/json" \
  -d '{"volume": 80}'
```

---

## Window Geometry

### Set Window Position/Size

Position and resize the video window.

**Endpoint:** `POST /api/geometry`

**Request Body:**
```json
{
  "x": 0,
  "y": 0,
  "width": 1920,
  "height": 1080
}
```

**Parameters:**
- `x` (required): X position in pixels
- `y` (required): Y position in pixels
- `width` (required): Width in pixels
- `height` (required): Height in pixels

**Example:**
```bash
# Full screen
curl -X POST http://192.168.1.100:5000/api/geometry \
  -H "Content-Type: application/json" \
  -d '{"x": 0, "y": 0, "width": 1920, "height": 1080}'

# Picture-in-picture (bottom right)
curl -X POST http://192.168.1.100:5000/api/geometry \
  -H "Content-Type: application/json" \
  -d '{"x": 1280, "y": 720, "width": 640, "height": 360}'
```

**Response:**
```json
{
  "status": "ok",
  "geometry": {
    "x": 0,
    "y": 0,
    "width": 1920,
    "height": 1080
  }
}
```

---

## Ticker Overlay

A second, independent persistent mpv instance — its own video, its own
geometry, always muted. Never touched by sync — purely per-device, same
as the RTSP `override` workflow above.

### Play Ticker

**Endpoint:** `POST /api/ticker/play`

**Request Body:**
```json
{
  "source": "ticker.mp4",
  "loop": true
}
```

**Parameters:**
- `source` (required): video filename (not sync-aware — plays directly on
  this device only)
- `loop` (optional, default: true)

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/ticker/play \
  -H "Content-Type: application/json" \
  -d '{"source": "ticker.mp4", "loop": true}'
```

**Response:**
```json
{
  "status": "playing",
  "source": "ticker.mp4"
}
```

### Stop Ticker

**Endpoint:** `POST /api/ticker/stop`

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/ticker/stop
```

### Get Ticker Status

Same response shape as [Get Player Status](#get-player-status).

**Endpoint:** `GET /api/ticker/status`

**Example:**
```bash
curl http://192.168.1.100:5000/api/ticker/status
```

### Get/Set Ticker Geometry

Same request/response shape as
[Set Window Position/Size](#set-window-positionsize), applied to the
ticker instance instead of the main one. Default is a bottom strip:
`{"x": 0, "y": 980, "width": 1920, "height": 100}` (assuming 1080p).

**Endpoints:** `GET /api/ticker/geometry`, `POST /api/ticker/geometry`

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/ticker/geometry \
  -H "Content-Type: application/json" \
  -d '{"x": 0, "y": 900, "width": 1920, "height": 150}'
```

### Play Main + Ticker Together

The single-command version for a Node-RED button — plays the main source
(sync-aware, identical dispatch to `/api/play`) and the ticker in one
call.

**Endpoint:** `POST /api/play-with-ticker`

**Request Body:**
```json
{
  "source": "rtsp://192.168.0.104:554/stream",
  "loop": true,
  "volume": 50,
  "ticker_source": "ticker.mp4",
  "ticker_loop": true,
  "override": true
}
```

**Parameters:**
- `source` (required): main video/RTSP source
- `ticker_source` (optional): if given, also plays this in the ticker
  overlay
- `ticker_loop` (optional, default: true)
- `override`: required on a sync remote for the *main* content only (see
  the note under [Player Control](#player-control)) — the ticker itself
  is never locked

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/play-with-ticker \
  -H "Content-Type: application/json" \
  -d '{"source": "rtsp://192.168.0.104:554/stream", "ticker_source": "ticker.mp4", "override": true}'
```

**Response:**
```json
{
  "status": "playing",
  "source": "rtsp://192.168.0.104:554/stream",
  "ticker": { "status": "playing", "source": "ticker.mp4" }
}
```

---

## Display Resolution

### Set Display Resolution

Configure the target display resolution for geometry calculations.

**Endpoint:** `POST /api/display/resolution`

**Request Body:**
```json
{
  "width": 1920,
  "height": 1080
}
```

**Example:**
```bash
# Set 4K resolution
curl -X POST http://192.168.1.100:5000/api/display/resolution \
  -H "Content-Type: application/json" \
  -d '{"width": 3840, "height": 2160}'
```

### Get Display Resolution

**Endpoint:** `GET /api/display/resolution`

**Example:**
```bash
curl http://192.168.1.100:5000/api/display/resolution
```

**Response:**
```json
{
  "width": 1920,
  "height": 1080
}
```

---

## Display Output

### Get HDMI Output Port

**Endpoint:** `GET /api/display/hdmi-port`

**Example:**
```bash
curl http://192.168.1.100:5000/api/display/hdmi-port
```

**Response:**
```json
{ "port": "auto" }
```

### Set HDMI Output Port

Selects which physical HDMI connector drives the display — for boards
with two HDMI ports (e.g. the Argon ONE V5 case). Persists across
reboots; applies immediately via `xrandr`. Requires both connectors to
have a forced mode in `cmdline.txt` first (`install.sh` handles this,
one-time reboot required — see `GUIDE.md`). A single-HDMI-port board can
safely leave this at `"auto"`.

**Endpoint:** `POST /api/display/hdmi-port`

**Request Body:**
```json
{ "port": "hdmi-2" }
```

**Parameters:**
- `port` (required): one of `"auto"`, `"hdmi-1"`, `"hdmi-2"`

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/display/hdmi-port \
  -H "Content-Type: application/json" \
  -d '{"port": "hdmi-2"}'
```

**Response:**
```json
{ "status": "ok", "port": "hdmi-2" }
```

---

## Audio

### List Audio Devices

Every audio output device mpv can see on this device — real ALSA device
names, straight from mpv's own `audio-device-list` (HDMI outputs, USB
DACs, analog jacks, whatever the hardware exposes).

**Endpoint:** `GET /api/audio/devices`

**Example:**
```bash
curl http://192.168.1.100:5000/api/audio/devices
```

**Response:**
```json
{
  "devices": [
    { "name": "auto", "description": "Autoselect device" },
    { "name": "alsa/hw:0,0", "description": "vc4-hdmi-0, MAI PCM i2s-hifi-0/Hardware device with all software conversions" }
  ]
}
```

### Get Current Audio Device

**Endpoint:** `GET /api/audio/device`

**Example:**
```bash
curl http://192.168.1.100:5000/api/audio/device
```

**Response:**
```json
{ "device": "auto" }
```

### Set Audio Device

Persists across reboots; applies immediately (mpv supports switching
live, no instance restart needed). No-op on a muted sync remote until
it's unmuted (`sync.remote_audio`).

**Endpoint:** `POST /api/audio/device`

**Request Body:**
```json
{ "device": "alsa/hw:0,0" }
```

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/audio/device \
  -H "Content-Type: application/json" \
  -d '{"device": "alsa/hw:0,0"}'
```

**Response:**
```json
{ "status": "ok", "device": "alsa/hw:0,0" }
```

---

## Presets

### List All Presets

Get all saved layout presets.

**Endpoint:** `GET /api/presets`

**Example:**
```bash
curl http://192.168.1.100:5000/api/presets
```

**Response:**
```json
{
  "fullscreen": {
    "geometry": {"x": 0, "y": 0, "width": 1920, "height": 1080},
    "description": "Full screen"
  },
  "left-half": {
    "geometry": {"x": 0, "y": 0, "width": 960, "height": 1080},
    "description": "Left half of screen"
  }
}
```

### Save Preset

Save current window geometry as a preset.

**Endpoint:** `POST /api/presets`

**Request Body:**
```json
{
  "name": "my-layout",
  "geometry": {
    "x": 100,
    "y": 100,
    "width": 1600,
    "height": 900
  },
  "description": "Custom centered layout"
}
```

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/presets \
  -H "Content-Type: application/json" \
  -d '{
    "name": "corner-pip",
    "geometry": {"x": 1280, "y": 720, "width": 640, "height": 360},
    "description": "Bottom right corner"
  }'
```

### Load Preset

Apply a saved preset layout.

**Endpoint:** `POST /api/presets/{name}/load`

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/presets/fullscreen/load
```

**Response:**
```json
{
  "status": "loaded",
  "geometry": {"x": 0, "y": 0, "width": 1920, "height": 1080}
}
```

### Delete Preset

Remove a saved preset.

**Endpoint:** `DELETE /api/presets/{name}`

**Example:**
```bash
curl -X DELETE http://192.168.1.100:5000/api/presets/my-layout
```

---

## File Management

### List Video Files

Get all uploaded video files.

**Endpoint:** `GET /api/files`

**Example:**
```bash
curl http://192.168.1.100:5000/api/files
```

**Response:**
```json
[
  {
    "name": "promo.mp4",
    "size": 15728640,
    "modified": 1704470400.0
  },
  {
    "name": "demo.mp4",
    "size": 31457280,
    "modified": 1704384000.0
  }
]
```

### Upload Video File

Upload a video file to the Pi.

**Endpoint:** `POST /api/upload`

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/upload \
  -F "file=@/path/to/video.mp4"
```

**Response:**
```json
{
  "status": "uploaded",
  "filename": "video.mp4",
  "size": 20971520
}
```

### Delete Video File

Remove an uploaded video.

**Endpoint:** `DELETE /api/files/{filename}`

**Example:**
```bash
curl -X DELETE http://192.168.1.100:5000/api/files/old-video.mp4
```

---

## Status

### Get Player Status

Get current playback status and window geometry.

**Endpoint:** `GET /api/status`

**Example:**
```bash
curl http://192.168.1.100:5000/api/status
```

**Response:**
```json
{
  "status": "playing",
  "source": "promo.mp4",
  "position": 23.5,
  "duration": 120.0,
  "volume": 50,
  "loop": true,
  "muted": false,
  "geometry": {
    "x": 0,
    "y": 0,
    "width": 1920,
    "height": 1080
  }
}
```

**Status Values:**
- `stopped` - No video playing
- `playing` - Video is playing
- `paused` - Video is paused

`muted` reflects whether this device's audio is disabled — always `true`
on a sync remote unless `sync.remote_audio` is set (DESIGN.md §3 decision 2).

---

## Sync

Multi-device sync (`sync.role` in the sync config, see `DESIGN.md` §3).
`role: "off"` (the default) means this device isn't part of a sync group.

### Get Sync Status

**Endpoint:** `GET /api/sync/status`

**Example:**
```bash
curl http://192.168.1.100:5000/api/sync/status
```

**Response (`role: "off"`):**
```json
{ "role": "off" }
```

**Response (`role: "master"`):** the last broadcast state packet, this
device's own chrony offset, and every remote heard from recently.
```json
{
  "role": "master",
  "hostname": "master-stage",
  "last_packet": {
    "v": 1, "seq": 4711, "state": "playing", "file": "bout3.mp4",
    "t0": 1786543210.123456, "pos0": 0.0, "speed": 1.0,
    "loop": true, "duration": 312.48
  },
  "chrony": { "offset_ms": 0.12, "leap_status": "Normal", "available": true },
  "remotes": {
    "cm4-stage-left": {
      "state": "playing", "file": "bout3-angleB.mp4", "pos": 154.32,
      "err_ms": -6.4, "err_frames": -0.19, "fps": 29.97,
      "chrony_ms": 0.3, "warnings": [],
      "last_seen_ago_s": 0.4, "offline": false
    }
  }
}
```

**Response (`role: "remote"`):** the last state packet received from the
master, this device's own reception/clock stats, and a `chase` block with
its own live drift-correction state (DESIGN.md §7).
```json
{
  "role": "remote",
  "hostname": "cm4-stage-left",
  "master_addr": "192.168.1.100",
  "master_seen": true,
  "last_packet": { "v": 1, "seq": 4711, "state": "playing", "...": "..." },
  "last_packet_age_s": 0.05,
  "packets_received": 812,
  "seq_gaps": 0,
  "chrony": { "offset_ms": -0.31, "leap_status": "Normal", "available": true },
  "chase": {
    "applied_state": "playing", "applied_file": "bout3-angleB.mp4",
    "err_ms": -6.4, "err_frames": -0.19, "fps": 29.97, "speed": 1.0,
    "warnings": [], "pending_release_t0": null
  }
}
```

`pending_release_t0` is non-null only briefly, while the remote is primed
and waiting for a scheduled start/resume to land at its exact wall-clock
instant (DESIGN.md §6.3) — normally `null`.

A remote not heard from for 5 seconds is flagged `"offline": true` in the
master's view; `master_seen: false` on a remote means the same thing from
its own side (DESIGN.md §6.2).

### Get Screensaver Settings

**Endpoint:** `GET /api/sync/screensaver`

**Example:**
```bash
curl http://192.168.1.100:5000/api/sync/screensaver
```

**Response:**
```json
{ "enabled": false, "file": "screensaver.mp4", "loop": true, "delay_s": 30 }
```

### Set Screensaver Settings

When `enabled` and the master goes idle, it auto-plays `file` on a loop,
in sync across every device, after `delay_s` seconds (DESIGN.md §6.4).
Applies live — the next idle transition picks up the change, no restart
needed. See `GUIDE.md` for the full idle-vs-RTSP(`unmanaged`) behavior,
which differs.

**Endpoint:** `POST /api/sync/screensaver`

**Request Body:**
```json
{ "enabled": true, "file": "screensaver.mp4", "delay_s": 30 }
```

**Parameters:**
- `enabled` (optional): turn the auto-screensaver on/off
- `file` (optional): filename, resolved the same way as any other video
- `loop` (optional)
- `delay_s` (optional): seconds of idle before it auto-starts

**Example:**
```bash
curl -X POST http://192.168.1.100:5000/api/sync/screensaver \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "file": "screensaver.mp4", "delay_s": 30}'
```

**Response:**
```json
{ "enabled": true, "file": "screensaver.mp4", "loop": true, "delay_s": 30 }
```

---

## Node-RED Examples

### Example Flow 1: Play Video on Button Press

```json
[
  {
    "id": "button",
    "type": "inject",
    "name": "Play Promo",
    "topic": "",
    "payload": "",
    "repeat": "",
    "once": false
  },
  {
    "id": "http_request",
    "type": "http request",
    "method": "POST",
    "url": "http://192.168.1.100:5000/api/play",
    "headers": {
      "content-type": "application/json"
    },
    "payload": "{\"source\":\"promo.mp4\",\"loop\":true}"
  }
]
```

### Example Flow 2: Monitor Status

```json
[
  {
    "id": "timer",
    "type": "inject",
    "name": "Poll Status",
    "repeat": "2",
    "crontab": ""
  },
  {
    "id": "get_status",
    "type": "http request",
    "method": "GET",
    "url": "http://192.168.1.100:5000/api/status"
  },
  {
    "id": "debug",
    "type": "debug",
    "name": "Status"
  }
]
```

### Example Flow 3: Layout Switcher

Switch between different video layouts:

```javascript
// In a function node
if (msg.payload === "fullscreen") {
    msg.url = "http://192.168.1.100:5000/api/presets/fullscreen/load";
} else if (msg.payload === "pip") {
    msg.url = "http://192.168.1.100:5000/api/presets/corner-pip/load";
}
return msg;
```

---

## Error Handling

All endpoints return appropriate HTTP status codes:

- `200 OK` - Success
- `400 Bad Request` - Invalid parameters
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

**Error Response:**
```json
{
  "error": "Video file not found: missing.mp4"
}
```

---

## Rate Limiting

No rate limiting currently implemented. Use responsibly.

## Authentication

No authentication currently implemented. Secure your network accordingly.

---

**Questions?** Open an issue at: https://github.com/keep-on-walking/raspberry-pi-single-zone-video-player
