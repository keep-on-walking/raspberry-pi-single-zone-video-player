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

from video_player import VideoPlayer
from preset_manager import PresetManager
from sync_service import SyncService


# Configuration
VIDEO_DIR = Path("/opt/rpi-video-player/data/videos")
UPLOAD_DIR = VIDEO_DIR
CONFIG_FILE = Path("/opt/rpi-video-player/config/sync.json")
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

_sync_cfg = _load_sync_config()
sync = SyncService(player, mode=_sync_cfg.get('mode', 'disabled'),
                   master_ip=_sync_cfg.get('master_ip'))
sync.start()

print(f"📂 Upload folder: {UPLOAD_DIR}")
print(f"🔄 Sync mode: {_sync_cfg.get('mode', 'disabled')}")


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
        success = player.play(source, loop=loop, volume=volume)
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
    try:
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
        return jsonify({"status": "ok", "position": position})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/seek-relative', methods=['POST'])
def api_seek_relative():
    try:
        data = request.get_json()
        seconds = data.get('seconds', 0)
        player.seek_relative(float(seconds))
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
    """Switch display between 1080p and 4K via xrandr"""
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

        # Detect connected HDMI output
        xrandr_output = subprocess.check_output(
            ['bash', '-c', 'DISPLAY=:1 xrandr | grep " connected" | awk \'{print $1}\''],
            text=True
        ).strip().split('\n')[0]

        if not xrandr_output:
            return jsonify({"error": "No connected display found"}), 500

        # Stop playback before switching
        was_playing = player.state['status'] == 'playing'
        current_source = player.state.get('source')
        if was_playing:
            player.stop()

        # Switch resolution
        subprocess.run(
            ['bash', '-c', f'DISPLAY=:1 xrandr --output {xrandr_output} --mode {xrandr_mode}'],
            check=True
        )

        # Update player display resolution
        player.set_display_resolution(width, height)
        player.geometry = {"x": 0, "y": 0, "width": width, "height": height}

        # Resume playback if it was playing
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
    """Get current display mode"""
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
