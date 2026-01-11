#!/usr/bin/env python3
"""
Single-Zone MPV Video Player Manager
Optimized for Raspberry Pi 5 with hardware acceleration
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
        
        # Playback state
        self.state = {
            "status": "stopped",  # stopped, playing, paused
            "source": None,
            "position": 0,
            "duration": 0,
            "volume": 50,
            "loop": True
        }
        
        # Window geometry (position and size)
        self.geometry = {
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080
        }
        
        # Display resolution
        self.display_width = 1920
        self.display_height = 1080
        
        # Clean up any existing socket
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
    
    def set_display_resolution(self, width, height):
        """Update display resolution for geometry calculations"""
        self.display_width = width
        self.display_height = height
        print(f"Display resolution set to {width}x{height}")
    
    def set_geometry(self, x, y, width, height):
        """Update window geometry"""
        self.geometry = {
            "x": int(x),
            "y": int(y),
            "width": int(width),
            "height": int(height)
        }
        print(f"Geometry updated: {width}x{height}+{x}+{y}")
        
        # If playing, restart MPV with new geometry
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
        """Start playing a video file or RTSP stream"""
        
        # Update state
        if loop is not None:
            self.state["loop"] = loop
        if volume is not None:
            self.state["volume"] = volume
        
        # Determine full path for local files
        if not source.startswith(('rtsp://', 'http://', 'https://')):
            source_path = self.video_dir / source
            if not source_path.exists():
                raise FileNotFoundError(f"Video file not found: {source}")
            source = str(source_path.absolute())
        
        # Stop any existing playback
        if self.process and self.process.poll() is None:
            self.stop()
            time.sleep(0.5)
        
        # Build MPV command with Pi 5 optimizations
        cmd = self._build_command(source)
        
        print(f"Starting MPV: {source}")
        print(f"Geometry: {self.geometry['width']}x{self.geometry['height']}+{self.geometry['x']}+{self.geometry['y']}")
        
        # Start MPV process
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait for socket to be created
        max_wait = 5
        waited = 0
        while not os.path.exists(self.socket_path) and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
        
        if os.path.exists(self.socket_path):
            self.state["status"] = "playing"
            self.state["source"] = source
            
            # Seek if requested
            if seek_to is not None and seek_to > 0:
                time.sleep(0.5)
                self.seek(seek_to)
            
            print(f"MPV started successfully (PID: {self.process.pid})")
            return True
        else:
            print("Failed to start MPV - socket not created")
            return False
    
    def _build_command(self, source):
        """Build MPV command with all necessary flags for Pi 5"""
        
        cmd = [
            'mpv',
            
            # Core playback settings
            '--no-border',
            '--no-osc',
            '--no-osd-bar',
            '--really-quiet',
            '--keep-open=yes',
            
            # X11 video output with GPU acceleration
            '--vo=gpu',
            '--gpu-context=x11egl',
            
            # Window geometry (position and size)
            f'--geometry={self.geometry["width"]}x{self.geometry["height"]}+{self.geometry["x"]}+{self.geometry["y"]}',
            '--autofit-larger=100%x100%',
            
            # IPC control socket
            f'--input-ipc-server={self.socket_path}',
            
            # Volume
            f'--volume={self.state["volume"]}',
            
            # Loop settings
            '--loop-playlist=inf' if self.state["loop"] else '--loop-playlist=no',
            
            # Window settings
            '--force-window=yes',
            '--idle=yes',
            '--ontop=yes',
            
            # Cursor hiding
            '--cursor-autohide=always',
            
            # Video scaling
            '--keepaspect=no',
            '--video-aspect-override=-1',
            
            # Hardware acceleration for Pi 5
            '--hwdec=auto',
            '--hwdec-codecs=all',
            
            # Performance optimizations
            '--cache=yes',
            '--demuxer-max-bytes=50M',
            '--demuxer-max-back-bytes=25M',
            '--vd-lavc-threads=4',
            
            # Network settings for RTSP
            '--network-timeout=10',
            '--rtsp-transport=tcp',
            
            # The video source
            source
        ]
        
        return cmd
    
    def stop(self):
        """Stop playback"""
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
        
        # Clean up socket
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
    
    def pause(self):
        """Pause/unpause playback"""
        if self.state["status"] == "playing":
            self._send_command({"command": ["set_property", "pause", True]})
            self.state["status"] = "paused"
            print("Playback paused")
        elif self.state["status"] == "paused":
            self._send_command({"command": ["set_property", "pause", False]})
            self.state["status"] = "playing"
            print("Playback resumed")
    
    def seek(self, position):
        """Seek to a specific position (in seconds)"""
        self._send_command({"command": ["seek", position, "absolute"]})
        print(f"Seeked to {position}s")
    
    def seek_relative(self, seconds):
        """Seek relative to current position"""
        self._send_command({"command": ["seek", seconds, "relative"]})
        print(f"Seeked {'+' if seconds > 0 else ''}{seconds}s")
    
    def set_volume(self, volume):
        """Set volume (0-100)"""
        volume = max(0, min(100, int(volume)))
        self.state["volume"] = volume
        self._send_command({"command": ["set_property", "volume", volume]})
        print(f"Volume set to {volume}")
    
    def get_playback_position(self):
        """Get current playback position"""
        try:
            response = self._send_command({"command": ["get_property", "time-pos"]})
            if response and "data" in response:
                return response["data"]
        except:
            pass
        return 0
    
    def get_duration(self):
        """Get video duration"""
        try:
            response = self._send_command({"command": ["get_property", "duration"]})
            if response and "data" in response:
                return response["data"]
        except:
            pass
        return 0
    
    def get_status(self):
        """Get current player status"""
        # Update position and duration if playing
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
        """Send command to MPV via IPC socket"""
        if not os.path.exists(self.socket_path):
            return None
        
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(self.socket_path)
            
            # Send command
            cmd_json = json.dumps(command) + '\n'
            sock.sendall(cmd_json.encode('utf-8'))
            
            # Read response
            response = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b'\n' in response:
                    break
            
            sock.close()
            
            # Parse response
            if response:
                return json.loads(response.decode('utf-8'))
        except Exception as e:
            print(f"IPC error: {e}")
        
        return None
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop()


if __name__ == "__main__":
    # Test the player
    player = VideoPlayer()
    
    print("Video Player Test")
    print("Commands: play <file>, stop, pause, seek <seconds>, volume <0-100>, quit")
    
    while True:
        try:
            cmd = input("> ").strip().split()
            if not cmd:
                continue
            
            if cmd[0] == "play" and len(cmd) > 1:
                player.play(cmd[1])
            elif cmd[0] == "stop":
                player.stop()
            elif cmd[0] == "pause":
                player.pause()
            elif cmd[0] == "seek" and len(cmd) > 1:
                player.seek(float(cmd[1]))
            elif cmd[0] == "volume" and len(cmd) > 1:
                player.set_volume(int(cmd[1]))
            elif cmd[0] == "status":
                print(json.dumps(player.get_status(), indent=2))
            elif cmd[0] == "quit":
                break
            else:
                print("Unknown command")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
    
    player.cleanup()
