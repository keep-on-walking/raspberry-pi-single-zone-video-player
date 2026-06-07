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
import subprocess
import threading
import urllib.request

from video_player import VideoPlayer
from preset_manager import PresetManager
from sync_service import SyncService


# Configuration
VIDEO_DIR = Path("/opt/rpi-video-player/data/videos")
UPLOAD_DIR = VIDEO_DIR
CONFIG_FILE = Path("/opt/rpi-video-player/config/sync.json")
REMOTES_FILE = Path("/opt/rpi-video-player/config/remotes.json")
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov', 'webm', 'flv', 'wmv', 'm4v'}
MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB

# Initialize Flask app
app = Flask(__name__,
            template_folder='../web/templates',
            static_folder='../web/static')
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Initialize player and preset manager
player = VideoPlayer(video_dir=str(VIDEO_DIR))
presets = PresetManager()

# Load sync config and start sync service
def _load_sync_config():
    if CONFIG_FILE.exists():
        try:
            return json.load(open(CONFIG_FILE))
        except Exception:
            pass
    return {'mode': 'disabled', 'master_ip': None}

def _save_sync_config(cfg):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

# Load/save remote IPs
def _load_remotes():
    if REMOTES_FILE.exists():
        try:
            return json.load(open(REMOTES_FILE))
        except Exception:
            pass
    return []

def _save_remotes(remotes):
    REMOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REMOTES_FILE, 'w') as f:
        json.dump(remotes, f, indent=2)

def _notify_remotes(source, loop=True, volume=50):
    """Fire play command to all configured remote IPs in background threads"""
    remotes = _load_remotes()
    if not remotes:
        return

    def send_play(remote):
        try:
            payload = json.dumps({
                "source": os.path.basename(source),
                "loop": loop,
                "volume": volume
            }).encode()
            req = urllib.request.Request(
                f"http://{remote['ip']}:{remote.get('port', 5000)}/api/play",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=3)
            print(f"[remotes] play sent to {remote['ip']}")
        except Exception as e:
            print(f"[remotes] failed to notify {remote['ip']}: {e}")

    for remote in remotes:
        t = threading.Thread(target=send_play, args=(remote,), daemon=True)
        t.start()

def _notify_remotes_stop():
    """Fire stop command to all configured remote IPs"""
    remotes = _load_remotes()
    if not remotes:
        return

    def send_stop(remote):
        try:
            req = urllib.request.Request(
                f"http://{remote['ip']}:{remote.get('port', 5000)}/api/stop",
                data=b'',
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=3)
            print(f"[remotes] stop sent to {remote['ip']}")
        except Exception as e:
            print(f"[remotes] failed to stop {remote['ip']}: {e}")

    for remote in remotes:
        t = threading.Thread(target=send_stop, args=(remote,), daemon=True)
        t.start()

def _notify_remotes_seek(position):
    """Send seek command to all remote players"""
    remotes = _load_remotes()
    if not remotes:
        return

    def send_seek(remote):
        try:
            payload = json.dumps({"position": position}).encode()
            req = urllib.request.Request(
                f"http://{remote['ip']}:{remote.get('port', 5000)}/api/seek",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=3)
            print(f"[remotes] seek to {position:.2f}s sent to {remote['ip']}")
        except Exception as e:
            print(f"[remotes] failed to seek {remote['ip']}: {e}")

    for remote in remotes:
        t = threading.Thread(target=send_seek, args=(remote,), daemon=True)
        t.start()

_sync_cfg = _load_sync_config()
sync = SyncService(player, mode=_sync_cfg.get('mode', 'disabled'),
                   master_ip=_sync_cfg.get('master_ip'))
sync.start()

print(f"📂 Upload folder: {UPLOAD_DIR}")
print(f"🔄 Sync mode: {_sync_cfg.get('mode', 'disabled')}")
print(f"📡 Remotes: {len(_load_remotes())} configured")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# =============================================================================
# Web Interface Routes
# =============================================================================

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/health')
def health():
    return jsonify({"status": "ok"})


# =============================================================================
# Player Control API
# =============================================================================

@app.route('/api/play', methods=['POST'])
def api_play():
    try:
        data = request.get_json()
        source = data.get('source')
        if not source:
            return jsonify({"error": "No source provided"}), 400
        loop = data.get('loop', True)
        volume = data.get('volume', 50)
        default_geometry = presets.get_default()
        if default_geometry:
            player.set_geometry(
                default_geometry['x'],
                default_geometry['y'],
                default_geometry['width'],
                default_geometry['height']
            )

        # If master, notify remotes first then delay before starting local playback
        if sync.mode == 'master':
            _notify_remotes(source, loop=loop, volume=volume)
            import time
            time.sleep(2)  # Give remotes time to start mpv before master starts

        success = player.play(source, loop=loop, volume=volume)
        if success:
            # After master is playing, snap all remotes to master position
            if sync.mode == 'master':
                import threading
                def snap_remotes():
                    import time
                    time.sleep(4)  # Wait for master and remotes to be playing
                    pos = player.get_playback_position()
                    print(f"[snap] firing seek to remotes at pos={pos}")
                    if pos and pos > 0:
                        _notify_remotes_seek(pos)
                    else:
                        print("[snap] pos is 0 or None, skipping seek")
                t = threading.Thread(target=snap_remotes, daemon=True)
                t.start()
            return jsonify({"status": "playing", "source": source})
        else:
            return jsonify({"error": "Failed to start playback"}), 500
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/stop', methods=['POST'])
def api_stop():
    try:
        # If master, stop all remotes too
        if sync.mode == 'master':
            _notify_remotes_stop()
        player.stop()
        return jsonify({"status": "stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/pause', methods=['POST'])
def api_pause():
    try:
        player.pause()
        return jsonify({"status": player.state["status"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/seek', methods=['POST'])
def api_seek():
    try:
        data = request.get_json()
        position = data.get('position')
        if position is None:
            return jsonify({"error": "No position provided"}), 400
        player.seek(float(position))
        # If master, propagate seek to all remotes
        if sync.mode == 'master':
            _notify_remotes_seek(float(position))
        return jsonify({"status": "ok", "position": position})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/seek-relative', methods=['POST'])
def api_seek_relative():
    try:
        data = request.get_json()
        seconds = data.get('seconds', 0)
        player.seek_relative(float(seconds))
        # If master, propagate absolute position to remotes after seek
        if sync.mode == 'master':
            import time
            time.sleep(0.1)
            pos = player.get_playback_position()
            if pos:
                _notify_remotes_seek(pos)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/volume', methods=['POST'])
def api_volume():
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
    try:
        status = player.get_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Display Resolution API
# =============================================================================

@app.route('/api/display/resolution', methods=['POST'])
def api_set_resolution():
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
    return jsonify({
        "width": player.display_width,
        "height": player.display_height
    })


@app.route('/api/display/mode', methods=['POST'])
def api_set_display_mode():
    try:
        data = request.get_json()
        mode = data.get('mode')
        if mode == '4k':
            xrandr_mode = '3840x2160'
            width, height = 3840, 2160
        elif mode == '1080p':
            xrandr_mode = '1920x1080'
            width, height = 1920, 1080
        else:
            return jsonify({"error": "mode must be 1080p or 4k"}), 400

        xrandr_output = subprocess.check_output(
            ['bash', '-c', 'DISPLAY=:1 xrandr | grep " connected" | awk \'{print $1}\''],
            text=True
        ).strip().split('\n')[0]

        if not xrandr_output:
            return jsonify({"error": "No connected display found"}), 500

        was_playing = player.state['status'] == 'playing'
        current_source = player.state.get('source')
        if was_playing:
            player.stop()

        subprocess.run(
            ['bash', '-c', f'DISPLAY=:1 xrandr --output {xrandr_output} --mode {xrandr_mode}'],
            check=True
        )

        player.set_display_resolution(width, height)
        player.geometry = {"x": 0, "y": 0, "width": width, "height": height}

        if was_playing and current_source:
            import time
            time.sleep(1)
            player.play(current_source)

        return jsonify({
            "status": "ok",
            "mode": mode,
            "resolution": f"{width}x{height}",
            "output": xrandr_output
        })

    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"xrandr failed: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/display/mode', methods=['GET'])
def api_get_display_mode():
    try:
        output = subprocess.check_output(
            ['bash', '-c', 'DISPLAY=:1 xrandr | grep "\\*"'],
            text=True
        ).strip()
        if '3840x2160' in output or '4096x2160' in output:
            mode = '4k'
        else:
            mode = '1080p'
        return jsonify({"mode": mode, "resolution": f"{player.display_width}x{player.display_height}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Preset API
# =============================================================================

@app.route('/api/presets', methods=['GET'])
def api_list_presets():
    return jsonify({
        "presets": presets.list_presets(),
        "default": presets.get_default_name()
    })


@app.route('/api/presets', methods=['POST'])
def api_save_preset():
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
        files.sort(key=lambda x: x['name'])
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/upload', methods=['POST'])
def api_upload():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        if not allowed_file(file.filename):
            return jsonify({"error": "File type not allowed"}), 400
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
# Sync API
# =============================================================================

@app.route('/api/sync', methods=['GET'])
def api_sync_status():
    return jsonify(sync.status)


@app.route('/api/sync', methods=['POST'])
def api_sync_configure():
    try:
        data = request.get_json()
        mode = data.get('mode', 'disabled')
        master_ip = data.get('master_ip', None)
        if mode not in ('master', 'remote', 'disabled'):
            return jsonify({"error": "mode must be master, remote, or disabled"}), 400
        sync.set_mode(mode, master_ip)
        _save_sync_config({'mode': mode, 'master_ip': master_ip})
        return jsonify({"status": "ok", "mode": mode, "master_ip": master_ip})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Remotes API
# =============================================================================

@app.route('/api/remotes', methods=['GET'])
def api_list_remotes():
    """List all configured remote players"""
    return jsonify(_load_remotes())


@app.route('/api/remotes', methods=['POST'])
def api_add_remote():
    """Add a remote player"""
    try:
        data = request.get_json()
        ip = data.get('ip')
        port = data.get('port', 5000)
        name = data.get('name', ip)
        if not ip:
            return jsonify({"error": "IP address required"}), 400
        remotes = _load_remotes()
        # Check for duplicate
        if any(r['ip'] == ip for r in remotes):
            return jsonify({"error": "Remote already exists"}), 400
        remotes.append({"ip": ip, "port": port, "name": name})
        _save_remotes(remotes)
        return jsonify({"status": "added", "ip": ip, "port": port, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/remotes/<ip>', methods=['DELETE'])
def api_remove_remote(ip):
    """Remove a remote player"""
    try:
        remotes = _load_remotes()
        remotes = [r for r in remotes if r['ip'] != ip]
        _save_remotes(remotes)
        return jsonify({"status": "removed", "ip": ip})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/remotes/<ip>/ping', methods=['GET'])
def api_ping_remote(ip):
    """Check if a remote player is reachable"""
    try:
        remotes = _load_remotes()
        remote = next((r for r in remotes if r['ip'] == ip), None)
        port = remote.get('port', 5000) if remote else 5000
        req = urllib.request.Request(f"http://{ip}:{port}/health")
        urllib.request.urlopen(req, timeout=2)
        return jsonify({"status": "online", "ip": ip})
    except Exception:
        return jsonify({"status": "offline", "ip": ip})


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
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    )
