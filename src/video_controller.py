#!/usr/bin/env python3
"""
HTTP API Controller for Single-Zone Video Player
Flask web server with REST API and web dashboard
"""

from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
from pathlib import Path
import os
import json
import socket
import subprocess

from video_player import VideoPlayer
from preset_manager import PresetManager
from sync_config import SyncConfig
from sync_master import SyncMaster
from sync_remote import SyncRemote
from device_config import DeviceConfig


# Configuration
VIDEO_DIR = Path("/opt/rpi-video-player/data/videos")
UPLOAD_DIR = VIDEO_DIR
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov', 'webm', 'flv', 'wmv', 'm4v'}
MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
HDMI_SCRIPT = "/opt/rpi-video-player/bin/select-hdmi-output.sh"

# Initialize Flask app
app = Flask(__name__,
            template_folder='../web/templates',
            static_folder='../web/static')
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Sync config is loaded before the player so remote mute (DESIGN.md §3
# decision 2) can be baked into the persistent mpv launch command.
# role="off" (the default) is a no-op: no sockets opened, mute=False,
# player behaviour unchanged from Phase 1.
sync_config = SyncConfig()
remote_mute = (sync_config.data["role"] == "remote"
               and not sync_config.data.get("remote_audio", False))

# Device config (HDMI port + audio device) - per-device, persisted,
# independent of sync role.
device_config = DeviceConfig()

# Ticker overlay: a second, independent persistent mpv instance for a
# secondary video strip (e.g. a bottom-of-screen ticker played alongside
# an RTSP stream). Always muted, never touched by sync — it's a
# per-device directly-commanded feature, not part of the declared-state
# protocol. Distinct socket_path avoids colliding with `player`'s.
#
# Constructed (and parked off-screen) *before* the main player, and that
# order matters, not just the parked position. With no window manager
# running (bare X server, install.sh), stacking is literally "whichever
# window got mapped most recently" — there's no WM to enforce --ontop or
# to guarantee a window that's moved out of the way gets properly
# re-exposed underneath. The ticker's own constructor launches its mpv
# instance at the VideoPlayer default (fullscreen, 0,0,1920,1080) before
# the parking set_geometry() below ever runs — if the main player already
# existed at that point, this briefly maps a second fullscreen black
# window on top of it, and getting the main window visible again after
# depends on mpv correctly redrawing on X Expose, which real hardware
# testing showed isn't reliable here (surfaced as a bottom cutoff
# persisting through a remote reboot even with the ticker's *steady-state*
# position already fixed off-screen). Building+parking the ticker fully
# first sidesteps that: its brief fullscreen phase has nothing to cover
# yet, and the main player, constructed and mapped last, is guaranteed to
# end up on top without ever needing anything to be re-exposed.
ticker_player = VideoPlayer(video_dir=str(VIDEO_DIR), mute=True,
                             socket_path="/tmp/mpvsocket-ticker")
# Parked just below the visible 1920x1080 frame, not overlapping it. The
# dashboard's "Apply Ticker Geometry" default (0,980,1920,100 -
# web/templates/dashboard.html) is what an operator who actually wants a
# bottom-strip ticker clicks to reclaim this space on purpose — that's a
# runtime-only change too, not persisted, so it resets to this parked
# position on every service restart/reboot the same as everything else
# here.
ticker_player.set_geometry(0, 1080, 1920, 100)

# Main player and presets — player is constructed last (see above).
player = VideoPlayer(video_dir=str(VIDEO_DIR), mute=remote_mute,
                      audio_device=device_config.data["audio"]["device"])
presets = PresetManager()

print(f"📂 Upload folder: {UPLOAD_DIR}")

sync_master = None
sync_remote = None

if sync_config.data["role"] == "master":
    sync_master = SyncMaster(sync_config, player)
    sync_master.start()
elif sync_config.data["role"] == "remote":
    sync_remote = SyncRemote(sync_config, player)
    sync_remote.start()


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def sync_locked(data):
    """DESIGN.md §3 decision 3: playback endpoints are locked on a
    sync remote (the chase loop owns mpv there) unless the request
    carries the maintenance-only override flag."""
    return bool(sync_remote) and not (data or {}).get('override')


def sync_locked_response():
    return jsonify({"error": "playback is sync-controlled on a remote device",
                     "hint": "pass override:true for maintenance testing"}), 409


# =============================================================================
# Web Interface Routes
# =============================================================================

@app.route('/')
def index():
    """Serve the main dashboard"""
    return render_template('dashboard.html')


@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


# =============================================================================
# Player Control API
# =============================================================================

def _play_main(source, loop, volume, data):
    """Core dispatch for playing the main (sync-aware) content — shared
    by /api/play and /api/play-with-ticker. Returns (success, error)
    where error is a ready-to-return (jsonify(...), status) tuple, or
    None on success."""
    if sync_locked(data):
        return None, sync_locked_response()

    if not source:
        return None, (jsonify({"error": "No source provided"}), 400)

    # Apply default preset geometry if set
    default_geometry = presets.get_default()
    if default_geometry:
        player.set_geometry(
            default_geometry['x'],
            default_geometry['y'],
            default_geometry['width'],
            default_geometry['height']
        )

    # On a sync master, this schedules a frame-exact synced start
    # (DESIGN.md §6.3) instead of playing immediately.
    if sync_master:
        success = sync_master.play(source, loop=loop, volume=volume)
    else:
        success = player.play(source, loop=loop, volume=volume)

    return success, None


@app.route('/api/play', methods=['POST'])
def api_play():
    """Play a video"""
    try:
        data = request.get_json()
        source = data.get('source')
        loop = data.get('loop', True)
        volume = data.get('volume', 50)

        success, error = _play_main(source, loop, volume, data)
        if error:
            return error

        if success:
            return jsonify({"status": "playing", "source": source})
        else:
            return jsonify({"error": "Failed to start playback"}), 500

    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop playback"""
    try:
        data = request.get_json(silent=True)
        if sync_locked(data):
            return sync_locked_response()

        if sync_master:
            sync_master.stop()
        else:
            player.stop()
        return jsonify({"status": "stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/pause', methods=['POST'])
def api_pause():
    """Pause/unpause playback"""
    try:
        data = request.get_json(silent=True)
        if sync_locked(data):
            return sync_locked_response()

        if sync_master:
            # pause() is immediate (operator expects instant response);
            # resume() is a scheduled synced start, same as play()
            # (DESIGN.md §6.3) - which one depends on the state *before*
            # this call, so decide first rather than letting a single
            # toggle method pick.
            if player.state["status"] == "playing":
                sync_master.pause()
            elif player.state["status"] == "paused":
                sync_master.resume()
        else:
            player.pause()
        return jsonify({"status": player.state["status"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/seek', methods=['POST'])
def api_seek():
    """Seek to position"""
    try:
        data = request.get_json()

        if sync_locked(data):
            return sync_locked_response()

        position = data.get('position')

        if position is None:
            return jsonify({"error": "No position provided"}), 400

        if sync_master:
            sync_master.seek(float(position))
        else:
            player.seek(float(position))
        return jsonify({"status": "ok", "position": position})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/seek-relative', methods=['POST'])
def api_seek_relative():
    """Seek relative to current position"""
    try:
        data = request.get_json()

        if sync_locked(data):
            return sync_locked_response()

        seconds = data.get('seconds', 0)

        if sync_master:
            sync_master.seek_relative(float(seconds))
        else:
            player.seek_relative(float(seconds))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/volume', methods=['POST'])
def api_volume():
    """Set volume"""
    try:
        data = request.get_json()
        volume = data.get('volume')
        
        if volume is None:
            return jsonify({"error": "No volume provided"}), 400
        
        player.set_volume(int(volume))
        return jsonify({"status": "ok", "volume": volume})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/geometry', methods=['POST'])
def api_geometry():
    """Set window geometry"""
    try:
        data = request.get_json()
        
        x = data.get('x')
        y = data.get('y')
        width = data.get('width')
        height = data.get('height')
        
        if None in [x, y, width, height]:
            return jsonify({"error": "Missing geometry parameters"}), 400
        
        player.set_geometry(x, y, width, height)
        return jsonify({"status": "ok", "geometry": player.geometry})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/status', methods=['GET'])
def api_status():
    """Get player status"""
    try:
        status = player.get_status()
        status["muted"] = player.mute
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Ticker API — a second, independent overlay instance (see
# video_controller.py's ticker_player init comment). Never lockout-gated:
# the chase loop never touches this instance, so there's no conflict for
# the remote lockout to guard against (same reasoning as geometry/presets
# staying open on a remote).
# =============================================================================

@app.route('/api/ticker/play', methods=['POST'])
def api_ticker_play():
    """Play a video in the ticker overlay"""
    try:
        data = request.get_json()
        source = data.get('source')
        if not source:
            return jsonify({"error": "No source provided"}), 400

        loop = data.get('loop', True)
        success = ticker_player.play(source, loop=loop)

        if success:
            return jsonify({"status": "playing", "source": source})
        else:
            return jsonify({"error": "Failed to start ticker playback"}), 500
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ticker/stop', methods=['POST'])
def api_ticker_stop():
    """Stop ticker playback"""
    try:
        ticker_player.stop()
        return jsonify({"status": "stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ticker/status', methods=['GET'])
def api_ticker_status():
    """Get ticker overlay status"""
    try:
        return jsonify(ticker_player.get_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ticker/geometry', methods=['GET'])
def api_get_ticker_geometry():
    """Get ticker overlay window geometry"""
    return jsonify(ticker_player.geometry)


@app.route('/api/ticker/geometry', methods=['POST'])
def api_set_ticker_geometry():
    """Set ticker overlay window geometry"""
    try:
        data = request.get_json()
        x = data.get('x')
        y = data.get('y')
        width = data.get('width')
        height = data.get('height')

        if None in [x, y, width, height]:
            return jsonify({"error": "Missing geometry parameters"}), 400

        ticker_player.set_geometry(x, y, width, height)
        return jsonify({"status": "ok", "geometry": ticker_player.geometry})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/play-with-ticker', methods=['POST'])
def api_play_with_ticker():
    """Play the main source and the ticker overlay together in one call
    (e.g. an RTSP stream plus a bottom-strip ticker video) - the
    single-command workflow this endpoint exists for. The main source
    still goes through the normal sync-aware/lockout path
    (override:true required on a remote); the ticker never does."""
    try:
        data = request.get_json()
        source = data.get('source')
        loop = data.get('loop', True)
        volume = data.get('volume', 50)

        success, error = _play_main(source, loop, volume, data)
        if error:
            return error
        if not success:
            return jsonify({"error": "Failed to start main playback"}), 500

        result = {"status": "playing", "source": source}

        ticker_source = data.get('ticker_source')
        if ticker_source:
            ticker_loop = data.get('ticker_loop', True)
            ticker_ok = ticker_player.play(ticker_source, loop=ticker_loop)
            result["ticker"] = {"status": "playing" if ticker_ok else "error",
                                 "source": ticker_source}

        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Display Resolution API
# =============================================================================

@app.route('/api/display/resolution', methods=['POST'])
def api_set_resolution():
    """Set display resolution"""
    try:
        data = request.get_json()
        width = data.get('width')
        height = data.get('height')
        
        if not width or not height:
            return jsonify({"error": "Width and height required"}), 400
        
        player.set_display_resolution(int(width), int(height))
        return jsonify({"width": width, "height": height})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/display/resolution', methods=['GET'])
def api_get_resolution():
    """Get display resolution"""
    return jsonify({
        "width": player.display_width,
        "height": player.display_height
    })


@app.route('/api/display/hdmi-port', methods=['GET'])
def api_get_hdmi_port():
    """Get the persisted HDMI output port selection"""
    return jsonify({"port": device_config.data["display"]["hdmi_port"]})


@app.route('/api/display/hdmi-port', methods=['POST'])
def api_set_hdmi_port():
    """Set which physical HDMI port drives the display, persisted across
    reboots. Applies immediately via xrandr against the running X server;
    requires both connectors to have a forced mode in cmdline.txt (see
    install.sh) - otherwise the unused port has never had a signal to
    switch to."""
    try:
        data = request.get_json()
        port = data.get('port')

        if port not in ('auto', 'hdmi-1', 'hdmi-2'):
            return jsonify({"error": "port must be one of: auto, hdmi-1, hdmi-2"}), 400

        device_config.update({"display": {"hdmi_port": port}})

        try:
            subprocess.run(['bash', HDMI_SCRIPT], timeout=5,
                            capture_output=True, text=True, env={**os.environ, 'DISPLAY': ':1'})
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            print(f"HDMI port switch: {e} (setting saved, applies on next X11 start)")

        return jsonify({"status": "ok", "port": port})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Audio API (DESIGN.md §3)
# =============================================================================

@app.route('/api/audio/devices', methods=['GET'])
def api_list_audio_devices():
    """List audio output devices mpv can see (HDMI/USB DAC/analog/etc.)"""
    try:
        return jsonify({"devices": player.get_audio_devices()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/audio/device', methods=['GET'])
def api_get_audio_device():
    """Get the persisted audio device selection"""
    return jsonify({"device": device_config.data["audio"]["device"]})


@app.route('/api/audio/device', methods=['POST'])
def api_set_audio_device():
    """Set the audio output device, persisted across reboots. Applies
    immediately (mpv supports switching audio-device live, no restart
    needed). No-op on a muted remote until it's unmuted."""
    try:
        data = request.get_json()
        device = data.get('device')

        if not device:
            return jsonify({"error": "No device provided"}), 400

        device_config.update({"audio": {"device": device}})
        player.set_audio_device(device)

        return jsonify({"status": "ok", "device": device})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Sync API (DESIGN.md §9)
# =============================================================================

@app.route('/api/sync/status', methods=['GET'])
def api_sync_status():
    """Sync role, raw sent/received packets, and chrony health"""
    try:
        if sync_master:
            return jsonify(sync_master.get_status())
        if sync_remote:
            return jsonify(sync_remote.get_status())
        return jsonify({"role": "off", "hostname": socket.gethostname()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/sync/screensaver', methods=['GET'])
def api_get_screensaver():
    """Get the synced-screensaver settings (DESIGN.md §6.4)"""
    return jsonify(sync_config.data["screensaver"])


@app.route('/api/sync/screensaver', methods=['POST'])
def api_set_screensaver():
    """Set synced-screensaver settings, persisted across reboots. Applies
    live — on a master, the next idle transition picks up the new
    enabled/file/delay immediately, no service restart needed (mirrors
    how the master and remote sync objects already share this same
    SyncConfig instance by reference)."""
    try:
        data = request.get_json()
        patch = {}
        if 'enabled' in data:
            patch['enabled'] = bool(data['enabled'])
        if 'file' in data:
            patch['file'] = data['file']
        if 'loop' in data:
            patch['loop'] = bool(data['loop'])
        if 'delay_s' in data:
            delay_s = float(data['delay_s'])
            if delay_s < 0:
                return jsonify({"error": "delay_s must be >= 0"}), 400
            patch['delay_s'] = delay_s

        sync_config.update({"screensaver": patch})
        return jsonify(sync_config.data["screensaver"])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Preset API
# =============================================================================

@app.route('/api/presets', methods=['GET'])
def api_list_presets():
    """List all presets"""
    return jsonify({
        "presets": presets.list_presets(),
        "default": presets.get_default_name()
    })


@app.route('/api/presets', methods=['POST'])
def api_save_preset():
    """Save a preset"""
    try:
        data = request.get_json()
        name = data.get('name')
        geometry = data.get('geometry')
        description = data.get('description', '')
        
        if not name or not geometry:
            return jsonify({"error": "Name and geometry required"}), 400
        
        success = presets.save_preset(name, geometry, description)
        if success:
            return jsonify({"status": "saved", "name": name})
        else:
            return jsonify({"error": "Failed to save preset"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/presets/<name>/load', methods=['POST'])
def api_load_preset(name):
    """Load a preset"""
    try:
        preset = presets.get_preset(name)
        if not preset:
            return jsonify({"error": "Preset not found"}), 404
        
        geometry = preset['geometry']
        player.set_geometry(
            geometry['x'],
            geometry['y'],
            geometry['width'],
            geometry['height']
        )
        
        return jsonify({"status": "loaded", "geometry": geometry})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/presets/<name>', methods=['DELETE'])
def api_delete_preset(name):
    """Delete a preset"""
    try:
        success = presets.delete_preset(name)
        if success:
            return jsonify({"status": "deleted", "name": name})
        else:
            return jsonify({"error": "Preset not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/presets/<name>/set-default', methods=['POST'])
def api_set_default_preset(name):
    """Set a preset as default"""
    try:
        success = presets.set_default(name)
        if success:
            return jsonify({"status": "default set", "name": name})
        else:
            return jsonify({"error": "Failed to set default"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/presets/clear-default', methods=['POST'])
def api_clear_default_preset():
    """Clear the default preset"""
    try:
        success = presets.set_default(None)
        if success:
            return jsonify({"status": "default cleared"})
        else:
            return jsonify({"error": "Failed to clear default"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# File Management API
# =============================================================================

@app.route('/api/files', methods=['GET'])
def api_list_files():
    """List available video files"""
    try:
        files = []
        if UPLOAD_DIR.exists():
            for file in UPLOAD_DIR.iterdir():
                if file.is_file() and allowed_file(file.name):
                    files.append({
                        "name": file.name,
                        "size": file.stat().st_size,
                        "modified": file.stat().st_mtime
                    })
        
        # Sort by name
        files.sort(key=lambda x: x['name'])
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/upload', methods=['POST'])
def api_upload():
    """Upload a video file"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if not allowed_file(file.filename):
            return jsonify({"error": "File type not allowed"}), 400
        
        # Secure filename and save
        filename = secure_filename(file.filename)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        filepath = UPLOAD_DIR / filename
        
        file.save(str(filepath))
        
        return jsonify({
            "status": "uploaded",
            "filename": filename,
            "size": filepath.stat().st_size
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/files/<filename>', methods=['DELETE'])
def api_delete_file(filename):
    """Delete a video file"""
    try:
        filename = secure_filename(filename)
        filepath = UPLOAD_DIR / filename
        
        if not filepath.exists():
            return jsonify({"error": "File not found"}), 404
        
        filepath.unlink()
        return jsonify({"status": "deleted", "filename": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("🎬 Raspberry Pi Single-Zone Video Player")
    print("=" * 60)
    print(f"📂 Upload folder: {UPLOAD_DIR}")
    print("🌐 Starting Flask server on port 5000...")
    print("=" * 60)
    
    # Run Flask server
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )
