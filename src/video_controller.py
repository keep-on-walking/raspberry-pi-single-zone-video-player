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

from video_player import VideoPlayer
from preset_manager import PresetManager


# Configuration
VIDEO_DIR = Path("/opt/rpi-video-player/data/videos")
UPLOAD_DIR = VIDEO_DIR
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

print(f"📂 Upload folder: {UPLOAD_DIR}")


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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

@app.route('/api/play', methods=['POST'])
def api_play():
    """Play a video"""
    try:
        data = request.get_json()
        
        source = data.get('source')
        if not source:
            return jsonify({"error": "No source provided"}), 400
        
        loop = data.get('loop', True)
        volume = data.get('volume', 50)
        
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
    """Stop playback"""
    try:
        player.stop()
        return jsonify({"status": "stopped"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/pause', methods=['POST'])
def api_pause():
    """Pause/unpause playback"""
    try:
        player.pause()
        return jsonify({"status": player.state["status"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/seek', methods=['POST'])
def api_seek():
    """Seek to position"""
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
    """Seek relative to current position"""
    try:
        data = request.get_json()
        seconds = data.get('seconds', 0)
        
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
        return jsonify(status)
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


# =============================================================================
# Preset API
# =============================================================================

@app.route('/api/presets', methods=['GET'])
def api_list_presets():
    """List all presets"""
    return jsonify(presets.list_presets())


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
