#!/usr/bin/env python3
"""
Single-Zone MPV Video Player Manager — Phase 1 (persistent mpv)

One long-lived mpv process owned by the service:
  - play()  -> IPC loadfile (preroll paused, seek, release) — fast, low-variance
  - stop()  -> IPC stop (process stays up, window stays black)
  - geometry change -> instance restart only when geometry actually changed
    (X11 --geometry is a launch argument)

Public interface and state semantics are identical to the spawn-per-play
version: video_controller.py requires no changes (T2 regression target).

The load path is deliberately split into _prime() (load paused + seek) and
_release() (unpause) — the synced-start pattern from DESIGN.md §4, so the
Phase 3/4 sync module can reuse _prime() and schedule _release() at a
wall-clock instant without touching this file's structure again.
"""

import subprocess
import json
import socket
import os
import time
from pathlib import Path


class VideoPlayer:
    """Manages a single persistent MPV instance"""

    def __init__(self, video_dir="/opt/rpi-video-player/data/videos", mute=False, audio_device="auto",
                 socket_path=None):
        self.video_dir = Path(video_dir)
        # Distinct socket paths let a second instance (e.g. the ticker
        # overlay) coexist with the main one without colliding.
        self.socket_path = socket_path or "/tmp/mpvsocket-player"
        self.process = None

        # Remotes launch muted (DESIGN.md §3 decision 2) — a launch
        # argument, so it's baked into _build_command() rather than
        # toggled at runtime.
        self.mute = mute

        # Which mpv audio-device to use when not muted (DESIGN.md §3 —
        # "auto" lets mpv pick; set_audio_device() below can also change
        # this live, without restarting the instance.
        self.audio_device = audio_device or "auto"

        # Playback state (semantics unchanged from v1.0)
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

        # Demuxer cache size (MB). Tunable for low-RAM devices
        # (e.g. export RPI_PLAYER_CACHE_MB=20 on a 1GB Pi 4).
        try:
            self.cache_mb = max(5, int(os.environ.get("RPI_PLAYER_CACHE_MB", "50")))
        except ValueError:
            self.cache_mb = 50

        # Clean up any stale socket from a previous run
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        # Start the persistent instance now (best-effort: if X isn't up yet,
        # play() will retry via _ensure_running()).
        self._ensure_running()

    # =========================================================================
    # Persistent instance management
    # =========================================================================

    def _build_command(self):
        """Build the persistent MPV command (no source — files load via IPC)"""

        cmd = [
            'mpv',

            # Core playback settings
            '--no-border',
            '--no-osc',
            '--no-osd-bar',
            '--really-quiet',
            '--keep-open=yes',

            # X11 video output (xv for Pi hardware decoding compatibility)
            '--vo=xv',

            # Window geometry (position and size)
            f'--geometry={self.geometry["width"]}x{self.geometry["height"]}+{self.geometry["x"]}+{self.geometry["y"]}',
            '--autofit-larger=100%x100%',

            # IPC control socket
            f'--input-ipc-server={self.socket_path}',

            # Volume (initial; runtime changes go via IPC)
            f'--volume={self.state["volume"]}',

            # Window settings — idle keeps the process alive with no file
            '--force-window=yes',
            '--idle=yes',
            '--ontop=yes',

            # Cursor hiding
            '--cursor-autohide=always',

            # Video scaling
            '--keepaspect=no',
            '--video-aspect-override=-1',

            # Hardware acceleration (falls back to software where absent,
            # e.g. H.264 on Pi 5)
            '--hwdec=auto',
            '--hwdec-codecs=all',

            # Performance optimizations
            '--cache=yes',
            f'--demuxer-max-bytes={self.cache_mb}M',
            f'--demuxer-max-back-bytes={max(5, self.cache_mb // 2)}M',
            '--vd-lavc-threads=4',

            # Network settings for RTSP
            '--network-timeout=10',
            '--rtsp-transport=tcp',
        ]

        if self.mute:
            cmd.append('--no-audio')
        elif self.audio_device and self.audio_device != "auto":
            cmd.append(f'--audio-device={self.audio_device}')

        return cmd

    def _ensure_running(self):
        """Start the persistent mpv instance if it isn't up. Returns bool."""
        if self.process and self.process.poll() is None and os.path.exists(self.socket_path):
            return True

        # A process without a socket (or vice versa) is a broken half-state:
        # clear both and start fresh.
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        cmd = self._build_command()
        print(f"Starting persistent MPV "
              f"({self.geometry['width']}x{self.geometry['height']}"
              f"+{self.geometry['x']}+{self.geometry['y']})")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"Failed to launch MPV: {e}")
            self.process = None
            return False

        # Wait for the IPC socket
        waited = 0.0
        while not os.path.exists(self.socket_path) and waited < 5.0:
            if self.process.poll() is not None:
                print("MPV exited during startup")
                self.process = None
                return False
            time.sleep(0.1)
            waited += 0.1

        if not os.path.exists(self.socket_path):
            print("Failed to start MPV - socket not created")
            return False

        print(f"MPV running (PID: {self.process.pid})")
        return True

    def _restart_instance(self):
        """Quit and relaunch the persistent instance (geometry changes only)."""
        if self.process and self.process.poll() is None:
            # Ask nicely over IPC first; fall back to terminate
            self._send_command({"command": ["quit"]})
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        self.process = None
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        return self._ensure_running()

    # =========================================================================
    # Load pattern: prime (load paused + seek) then release (unpause).
    # play() calls both back-to-back; the future sync module will call
    # _prime() and schedule _release() at an agreed wall-clock instant.
    # =========================================================================

    def _prime(self, source, seek_to=None, timeout=10.0):
        """Load a source paused, wait until decoded, optionally seek.
        Local files preroll paused (first frame displayed, clock stopped).
        Network streams (RTSP/HTTP) load un-paused — live content can't
        meaningfully preroll. Returns True when the source is loaded."""

        is_stream = source.startswith(('rtsp://', 'http://', 'https://'))

        # Properties are set before loadfile (version-proof: avoids the
        # loadfile options-argument reshuffle between mpv releases).
        self._send_command({"command": ["set_property", "pause", not is_stream]})
        self._send_command({"command": ["set_property", "loop-file",
                                        "inf" if self.state["loop"] else "no"]})
        self._send_command({"command": ["set_property", "volume",
                                        self.state["volume"]]})

        self._send_command({"command": ["loadfile", source, "replace"]})

        # Wait for the load to complete: files expose a duration once the
        # demuxer is ready; live streams expose their path once active.
        prop = "path" if is_stream else "duration"
        waited = 0.0
        while waited < timeout:
            resp = self._send_command({"command": ["get_property", prop]})
            if resp and resp.get("data") not in (None, ""):
                break
            if self.process is None or self.process.poll() is not None:
                print("MPV died during load")
                return False
            time.sleep(0.1)
            waited += 0.1
        else:
            print(f"Load timed out: {source}")
            self._send_command({"command": ["stop"]})
            return False

        if (seek_to is not None) and seek_to > 0 and not is_stream:
            # Seeking while paused: mpv displays the sought frame
            self._send_command({"command": ["seek", seek_to, "absolute+exact"]})

        return True

    def _release(self):
        """Start the clock on a primed source."""
        self._send_command({"command": ["set_property", "pause", False]})

    # =========================================================================
    # Public interface (unchanged signatures and semantics)
    # =========================================================================

    def set_display_resolution(self, width, height):
        """Update display resolution for geometry calculations"""
        self.display_width = width
        self.display_height = height
        print(f"Display resolution set to {width}x{height}")

    def set_geometry(self, x, y, width, height):
        """Update window geometry"""
        new_geometry = {
            "x": int(x),
            "y": int(y),
            "width": int(width),
            "height": int(height)
        }

        # No change -> no restart. Important with a persistent instance:
        # api_play applies the default preset geometry on every play, and
        # an unconditional restart would flash the window each time.
        if new_geometry == self.geometry:
            return

        self.geometry = new_geometry
        print(f"Geometry updated: {width}x{height}+{x}+{y}")

        # --geometry is a launch argument under X11, so the instance must
        # restart; reload and reposition any current playback afterwards.
        current_source = self.state["source"]
        current_position = self.get_playback_position() or 0
        was_playing = self.state["status"] == "playing"
        was_paused = self.state["status"] == "paused"

        self._restart_instance()

        if (was_playing or was_paused) and current_source:
            if self._prime(current_source, seek_to=current_position):
                if was_playing:
                    self._release()
                # was_paused: stay primed-paused on the same frame
            else:
                self.state["status"] = "stopped"
                self.state["source"] = None

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

        # Make sure the persistent instance is up (recovers from crashes,
        # watchdog pkill, or X not having been ready at service start)
        if not self._ensure_running():
            print("Failed to start MPV instance")
            return False

        print(f"Loading: {source}")

        if not self._prime(source, seek_to=seek_to):
            return False
        self._release()

        self.state["status"] = "playing"
        self.state["source"] = source
        return True

    def stop(self):
        """Stop playback (the persistent instance stays up, window black)"""
        if self.process and self.process.poll() is None:
            resp = self._send_command({"command": ["stop"]})
            if resp is None:
                # IPC dead: fall back to killing the instance; next play
                # or _ensure_running() brings it back
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                self.process = None
                if os.path.exists(self.socket_path):
                    os.remove(self.socket_path)
            print("Playback stopped")

        self.state["status"] = "stopped"
        self.state["source"] = None
        self.state["position"] = 0
        self.state["duration"] = 0

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

    def seek(self, position, exact=False):
        """Seek to a specific position (in seconds). exact=True trades
        speed for frame accuracy (used by the sync chase loop's hard-seek
        correction, DESIGN.md §7)."""
        mode = "absolute+exact" if exact else "absolute"
        self._send_command({"command": ["seek", position, mode]})
        print(f"Seeked to {position}s")

    def seek_relative(self, seconds):
        """Seek relative to current position"""
        self._send_command({"command": ["seek", seconds, "relative"]})
        print(f"Seeked {'+' if seconds > 0 else ''}{seconds}s")

    def set_speed(self, speed):
        """Set playback speed (1.0 = normal). Used by the sync chase loop
        to nudge a remote into alignment without a perceptible jump
        (DESIGN.md §7) — not part of the persisted player state."""
        self._send_command({"command": ["set_property", "speed", speed]})

    def set_volume(self, volume):
        """Set volume (0-100)"""
        volume = max(0, min(100, int(volume)))
        self.state["volume"] = volume
        self._send_command({"command": ["set_property", "volume", volume]})
        print(f"Volume set to {volume}")

    def get_audio_devices(self):
        """List available audio output devices (DESIGN.md §3), e.g. HDMI0/
        HDMI1/USB DAC/analog jack — whatever ALSA exposes. Returns [] if
        mpv isn't up or the instance is muted-and-unresponsive."""
        try:
            response = self._send_command({"command": ["get_property", "audio-device-list"]})
            if response and "data" in response and response["data"] is not None:
                return response["data"]
        except Exception:
            pass
        return []

    def set_audio_device(self, device):
        """Switch the active audio output device live (no instance restart
        needed, unlike geometry) and remember it for future restarts."""
        self.audio_device = device or "auto"
        self._send_command({"command": ["set_property", "audio-device", self.audio_device]})
        print(f"Audio device set to {self.audio_device}")

    def get_playback_position(self):
        """Get current playback position"""
        try:
            response = self._send_command({"command": ["get_property", "time-pos"]})
            if response and "data" in response and response["data"] is not None:
                return response["data"]
        except Exception:
            pass
        return 0

    def get_fps(self):
        """Get the loaded file's container-declared frame rate, or 0 if
        unavailable. Used to express sync error in frames, not just ms."""
        try:
            response = self._send_command({"command": ["get_property", "container-fps"]})
            if response and "data" in response and response["data"] is not None:
                return response["data"]
        except Exception:
            pass
        return 0

    def get_duration(self):
        """Get video duration"""
        try:
            response = self._send_command({"command": ["get_property", "duration"]})
            if response and "data" in response and response["data"] is not None:
                return response["data"]
        except Exception:
            pass
        return 0

    def get_status(self):
        """Get current player status"""
        # Detect an instance that died out from under us (crash / pkill)
        if self.state["status"] in ["playing", "paused"]:
            if self.process is None or self.process.poll() is not None:
                self.state["status"] = "stopped"
                self.state["source"] = None
                self.state["position"] = 0
                self.state["duration"] = 0
            else:
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

            # Read response lines until we find the reply (the socket also
            # carries async event lines, which have no "error" field)
            buf = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b'\n' in buf:
                    replies = [ln for ln in buf.split(b'\n') if ln.strip()]
                    for ln in replies:
                        try:
                            msg = json.loads(ln.decode('utf-8'))
                        except json.JSONDecodeError:
                            continue
                        if "error" in msg:
                            sock.close()
                            return msg
                    buf = b''

            sock.close()
        except Exception as e:
            print(f"IPC error: {e}")

        return None

    def cleanup(self):
        """Cleanup resources (full shutdown of the persistent instance)"""
        self.stop()
        if self.process and self.process.poll() is None:
            self._send_command({"command": ["quit"]})
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)


if __name__ == "__main__":
    # Test the player
    player = VideoPlayer()

    print("Video Player Test (persistent instance)")
    print("Commands: play <file>, stop, pause, seek <seconds>, volume <0-100>, status, quit")

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
