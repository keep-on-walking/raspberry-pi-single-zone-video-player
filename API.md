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
- [Display Resolution](#display-resolution)
- [Presets](#presets)
- [File Management](#file-management)
- [Status](#status)

---

## Player Control

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
