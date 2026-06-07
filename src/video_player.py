#!/usr/bin/env python3
"""
Single-Zone MPV Video Player Manager
Optimized for CM5/Pi 5 with GPU/VAAPI output via X11
"""

import subprocess
import json
import socket
import os
import time
from pathlib import Path


class VideoPlayer:
    """Manages a single MPV instance with hardware-accelerated playback"""
    
    def __init__(self, video_dir="/opt/rpi-video-player/data/videos"):
        self.video_dir = Path(video_dir)
        self.socket_path = "/tmp/mpvsocket-player"
        self.process = None
        self.state = {
            "status": "stopped",
            "source": None,
            "position": 0,
            "duration": 0,
            "volume": 50,
            "loop": True
        }
        self.geometry = {
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080
        }
        self.display_width = 1920
        self.display_height = 1080
        self.display = ":1"
        self.audio_device = "alsa/hdmi:CARD=vc4hdmi1,DEV=0"
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    def set_display_resolution(self, width, height):
        self.display_width = width
        self.display_height = height
        print(f"Display resolution set to {width}x{height}")

    def set_geometry(self, x, y, width, height):
        self.geometry = {
            "x": int(x),
            "y": int(y),
            "width": int(width),
            "height": int(height)
        }
        print(f"Geometry updated: {width}x{height}+{x}+{y}")
        if self.state["status"] in ["playing", "paused"]:
            current_source = self.state["source"]
            current_position = self.get_playback_position()
            was_paused = self.state["status"] == "paused"
            self.stop()
            time.sleep(0.5)
            self.play(current_source, seek_to=current_position)
            if was_paused:
                time.sleep(0.5)
                self.pause()

    def play(self, source, loop=None, volume=None, seek_to=None):
        if loop is not None:
            self.state["loop"] = loop
        if volume is not None:
            self.state["volume"] = volume
        if not source.startswith(('rtsp://', 'http://', 'https://')):
            source_path = self.video_dir / source
            if not source_path.exists():
                raise FileNotFoundError(f"Video file not found: {source}")
            source = str(source_path.absolute())
        if self.process and self.process.poll() is None:
            self.stop()
            time.sleep(0.5)
        cmd = self._build_command(source)
        print(f"Starting MPV: {source}")
        env = os.environ.copy()
        env["DISPLAY"] = self.display
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env
        )
        max_wait = 5
        waited = 0
        while not os.path.exists(self.socket_path) and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
        if os.path.exists(self.socket_path):
            self.state["status"] = "playing"
            self.state["source"] = source
            if seek_to is not None and seek_to > 0:
                time.sleep(0.5)
                self.seek(seek_to)
            print(f"MPV started successfully (PID: {self.process.pid})")
            return True
        else:
            print("Failed to start MPV - socket not created")
            return False

    def _build_command(self, source):
        cmd = [
            'mpv',
            '--no-border',
            '--no-osc',
            '--no-osd-bar',
            '--really-quiet',
            '--keep-open=yes',

            # GPU output via X11 with VAAPI hardware acceleration
            '--vo=gpu',
            '--gpu-context=x11egl',
            '--hwdec=vaapi',

            # Window geometry
            f'--geometry={self.geometry["width"]}x{self.geometry["height"]}+{self.geometry["x"]}+{self.geometry["y"]}',
            '--autofit-larger=100%x100%',
            '--force-window=yes',
            '--ontop=yes',

            # Audio
            '--ao=alsa',
            f'--audio-device={self.audio_device}',

            # IPC control socket
            f'--input-ipc-server={self.socket_path}',

            # Volume
            f'--volume={self.state["volume"]}',

            # Loop
            '--loop-playlist=inf' if self.state["loop"] else '--loop-playlist=no',

            # Cursor
            '--cursor-autohide=always',

            # Fill window without maintaining aspect ratio
            '--keepaspect=no',
            '--video-aspect-override=-1',

            # Hardware decode
            '--hwdec-codecs=all',

            # Performance
            '--cache=yes',
            '--demuxer-max-bytes=50M',
            '--demuxer-max-back-bytes=25M',
            '--vd-lavc-threads=4',

            # Network/RTSP
            '--network-timeout=10',
            '--rtsp-transport=tcp',

            source
        ]
        return cmd

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            print("MPV stopped")
        self.state["status"] = "stopped"
        self.state["source"] = None
        self.state["position"] = 0
        self.state["duration"] = 0
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

    def pause(self):
        if self.state["status"] == "playing":
            self._send_command({"command": ["set_property", "pause", True]})
            self.state["status"] = "paused"
            print("Playback paused")
        elif self.state["status"] == "paused":
            self._send_command({"command": ["set_property", "pause", False]})
            self.state["status"] = "playing"
            print("Playback resumed")

    def seek(self, position):
        self._send_command({"command": ["seek", position, "absolute"]})
        print(f"Seeked to {position}s")

    def seek_relative(self, seconds):
        self._send_command({"command": ["seek", seconds, "relative"]})
        print(f"Seeked {'+' if seconds > 0 else ''}{seconds}s")

    def set_volume(self, volume):
        volume = max(0, min(100, int(volume)))
        self.state["volume"] = volume
        self._send_command({"command": ["set_property", "volume", volume]})
        print(f"Volume set to {volume}")

    def get_playback_position(self):
        try:
            response = self._send_command({"command": ["get_property", "time-pos"]})
            if response and "data" in response:
                return response["data"]
        except:
            pass
        return 0

    def get_duration(self):
        try:
            response = self._send_command({"command": ["get_property", "duration"]})
            if response and "data" in response:
                return response["data"]
        except:
            pass
        return 0

    def get_status(self):
        if self.state["status"] in ["playing", "paused"]:
            self.state["position"] = self.get_playback_position()
            self.state["duration"] = self.get_duration()
        return {
            "status": self.state["status"],
            "source": self.state["source"],
            "position": self.state["position"],
            "duration": self.state["duration"],
            "volume": self.state["volume"],
            "loop": self.state["loop"],
            "geometry": self.geometry
        }

    def _send_command(self, command, timeout=1):
        if not os.path.exists(self.socket_path):
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(self.socket_path)
            cmd_json = json.dumps(command) + '\n'
            sock.sendall(cmd_json.encode('utf-8'))
            response = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b'\n' in response:
                    break
            sock.close()
            if response:
                return json.loads(response.decode('utf-8'))
        except Exception as e:
            print(f"IPC error: {e}")
        return None

    def cleanup(self):
        self.stop()
