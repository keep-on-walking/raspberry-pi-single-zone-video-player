#!/usr/bin/env python3
"""
Sync master — Phase 2 skeleton (DESIGN.md §6.1, §6.2, §12 phase 2).

Broadcasts declared playback state over UDP at 10 Hz and listens for
remote heartbeats, for /api/sync/status to show raw packets + clock
health and to pass T1 (chrony offset).

The declared origin (t0/pos0) changes only when the player's actual state
changes (start/stop/pause/resume or a seek beyond SEEK_JUMP_MS) — detected
by polling video_player's status each tick, since Phase 2 has no
scheduled-transition hooks yet. Phase 4 (DESIGN.md §12) adds explicit
scheduled transitions (§6.3) and a synced screensaver (§6.4) without
changing this wire format or the broadcast loop itself.
"""

import json
import socket
import threading
import time
from pathlib import Path

from chrony_status import get_chrony_offset_ms

BROADCAST_HZ = 10
SEEK_JUMP_MS = 300  # position delta beyond this while otherwise steady = a seek
OFFLINE_AFTER_S = 5  # DESIGN.md §6.2: remote not heard from in 5s is offline


def _map_state(status):
    """Map VideoPlayer status -> sync protocol state (DESIGN.md §6.1)."""
    source = status.get("source")
    is_stream = bool(source) and source.startswith(('rtsp://', 'http://', 'https://'))
    player_status = status.get("status")

    if is_stream and player_status in ("playing", "paused"):
        return "unmanaged"
    if player_status in ("playing", "paused"):
        return player_status
    return "idle"


class SyncMaster:
    """Owns the declared state; broadcasts it; aggregates remote heartbeats."""

    def __init__(self, config, player):
        self.config = config
        self.player = player
        self.hostname = socket.gethostname()

        self.seq = 0
        self.declared = {
            "state": "idle",
            "file": None,
            "t0": time.time(),
            "pos0": 0.0,
            "duration": 0.0,
            "loop": True,
        }
        self.last_packet = None
        self.lock = threading.Lock()

        self.remotes = {}  # device id -> last heartbeat + bookkeeping
        self.remotes_lock = threading.Lock()

        self._stop = threading.Event()
        self._send_sock = None
        self._recv_sock = None
        self._threads = []

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self):
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._recv_sock.bind(('', self.config.data["heartbeat_port"]))
        self._recv_sock.settimeout(1.0)

        t1 = threading.Thread(target=self._broadcast_loop, daemon=True, name="sync-master-broadcast")
        t2 = threading.Thread(target=self._heartbeat_loop, daemon=True, name="sync-master-heartbeat")
        t1.start()
        t2.start()
        self._threads = [t1, t2]
        print(f"sync_master: broadcasting on {self.config.data['broadcast_addr']}:"
              f"{self.config.data['state_port']} @ {BROADCAST_HZ}Hz, "
              f"heartbeats on :{self.config.data['heartbeat_port']}")

    def stop(self):
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        if self._send_sock:
            self._send_sock.close()
        if self._recv_sock:
            self._recv_sock.close()

    # -----------------------------------------------------------------
    # Broadcast (master -> remotes)
    # -----------------------------------------------------------------

    def _broadcast_loop(self):
        period = 1.0 / BROADCAST_HZ
        while not self._stop.is_set():
            started = time.time()
            try:
                self._tick()
            except Exception as e:
                print(f"sync_master: broadcast tick error: {e}")
            elapsed = time.time() - started
            time.sleep(max(0.0, period - elapsed))

    def _tick(self):
        status = self.player.get_status()
        state = _map_state(status)
        source = status.get("source")
        is_stream = bool(source) and source.startswith(('rtsp://', 'http://', 'https://'))
        file = source if (is_stream or not source) else Path(source).name
        now = time.time()

        with self.lock:
            d = self.declared
            transitioned = (state != d["state"]) or (file != d["file"])

            if not transitioned and state in ("playing", "paused"):
                expected = d["pos0"] + (now - d["t0"]) if state == "playing" else d["pos0"]
                actual = status.get("position") or 0.0
                if abs(actual - expected) * 1000 > SEEK_JUMP_MS:
                    transitioned = True

            if transitioned:
                self.seq += 1
                d["state"] = state
                d["file"] = file
                d["t0"] = now
                d["pos0"] = (status.get("position") or 0.0) if state in ("playing", "paused") else 0.0
                d["duration"] = status.get("duration") or 0.0
                d["loop"] = status.get("loop", True)

            packet = {
                "v": 1,
                "seq": self.seq,
                "state": d["state"],
                "file": d["file"],
                "t0": d["t0"],
                "pos0": d["pos0"],
                "speed": 1.0,
                "loop": d["loop"],
                "duration": d["duration"],
            }
            self.last_packet = packet

        self._send(packet)

    def _send(self, packet):
        try:
            payload = json.dumps(packet).encode('utf-8')
            self._send_sock.sendto(
                payload,
                (self.config.data["broadcast_addr"], self.config.data["state_port"])
            )
        except OSError as e:
            print(f"sync_master: broadcast send failed: {e}")

    # -----------------------------------------------------------------
    # Heartbeats (remotes -> master)
    # -----------------------------------------------------------------

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            try:
                data, _addr = self._recv_sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                hb = json.loads(data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            device_id = hb.get("id")
            if not device_id:
                continue

            with self.remotes_lock:
                self.remotes[device_id] = {**hb, "last_seen": time.time()}

    # -----------------------------------------------------------------
    # Status (for /api/sync/status)
    # -----------------------------------------------------------------

    def get_status(self):
        now = time.time()
        with self.lock:
            packet = dict(self.last_packet) if self.last_packet else None

        with self.remotes_lock:
            remotes = {}
            for device_id, hb in self.remotes.items():
                age = now - hb["last_seen"]
                err_ms = hb.get("err_ms")
                fps = hb.get("fps")
                err_frames = (err_ms * fps / 1000.0) if (err_ms is not None and fps) else None
                remotes[device_id] = {
                    "state": hb.get("state"),
                    "file": hb.get("file"),
                    "pos": hb.get("pos"),
                    "err_ms": err_ms,
                    "err_frames": round(err_frames, 2) if err_frames is not None else None,
                    "fps": fps,
                    "chrony_ms": hb.get("chrony_ms"),
                    "warnings": hb.get("warnings", []),
                    "last_seen_ago_s": round(age, 1),
                    "offline": age > OFFLINE_AFTER_S,
                }

        offset_ms, leap_status = get_chrony_offset_ms()
        return {
            "role": "master",
            "hostname": self.hostname,
            "last_packet": packet,
            "chrony": {
                "offset_ms": offset_ms,
                "leap_status": leap_status,
                "available": offset_ms is not None,
            },
            "remotes": remotes,
        }
