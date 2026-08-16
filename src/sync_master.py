#!/usr/bin/env python3
"""
Sync master (DESIGN.md §6.1, §6.2, §6.3, §6.4, §12 phases 2 & 4).

Broadcasts declared playback state over UDP at 10 Hz and listens for
remote heartbeats, for /api/sync/status to show raw packets + clock
health and to pass T1 (chrony offset).

Two ways the declared origin (t0/pos0) changes:

1. Reactively — the steady-state safety net (drift, loop wraps, mpv
   crashing) — `_tick()` polls video_player's status every 100ms and
   detects state/position changes beyond SEEK_JUMP_MS. This is all Phase
   2/3 had, and it's still what runs during normal playback.
2. Proactively — DESIGN.md §6.3 scheduled transitions: `play()`/
   `resume()` preroll the player, broadcast a *future* t0, wait, then
   release — so remotes preroll and start in lockstep instead of
   reactively catching up afterward. `pause()`/`stop()`/`seek()` are
   immediate (operator expects instant response) but still broadcast
   through the same explicit path rather than waiting for the next
   reactive tick to notice.

`_scheduled_pending` mediates between the two: while a play()/resume() is
between priming and releasing, `_tick()` must not reactively observe the
player sitting "paused" and stomp on the pending future-t0 packet.

video_controller.py routes /api/play, /api/pause, /api/stop, /api/seek,
/api/seek-relative through these methods when role=master; role=off is
completely unaffected (these methods are never called).
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
SCREENSAVER_RESUME_DELAY_S = 3.0  # DESIGN.md §6.4 "short delay", not config-exposed


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

        # True while play()/resume() is between priming and releasing
        # (DESIGN.md §6.3) — guards _tick() from reactively observing the
        # player "paused" mid-preroll and stomping the pending packet.
        self._scheduled_pending = False

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

        if self.declared["state"] == "idle":
            self._schedule_screensaver_check()

    def shutdown(self):
        """Lifecycle teardown — closes sockets/joins threads. Distinct
        from stop() (DESIGN.md §6.3 playback stop, broadcasts idle)."""
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

    def _build_packet(self):
        """Build the outgoing packet from self.declared. Caller must hold
        self.lock."""
        d = self.declared
        return {
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

    def _tick(self):
        # While a play()/resume() scheduled transition is between priming
        # and releasing, the player deliberately sits "paused" ahead of
        # its declared t0 — reactively polling it here would stomp the
        # pending future-t0 packet. Just keep re-sending it unchanged.
        with self.lock:
            pending = self._scheduled_pending
            pending_packet = dict(self.last_packet) if (pending and self.last_packet) else None
        if pending:
            if pending_packet:
                self._send(pending_packet)
            return

        status = self.player.get_status()
        state = _map_state(status)
        source = status.get("source")
        is_stream = bool(source) and source.startswith(('rtsp://', 'http://', 'https://'))
        file = source if (is_stream or not source) else Path(source).name
        now = time.time()

        became_idle = False
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
                became_idle = (state == "idle" and d["state"] != "idle")
                d["state"] = state
                d["file"] = file
                d["t0"] = now
                d["pos0"] = (status.get("position") or 0.0) if state in ("playing", "paused") else 0.0
                d["duration"] = status.get("duration") or 0.0
                d["loop"] = status.get("loop", True)

            packet = self._build_packet()
            self.last_packet = packet

        self._send(packet)
        if became_idle:
            # Self-healing: an *unexpected* transition to idle (mpv died,
            # RTSP dropped, etc.) still triggers the screensaver check,
            # same as an operator-initiated stop() does explicitly.
            self._schedule_screensaver_check()

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
    # Playback orchestration (DESIGN.md §6.3) — video_controller.py routes
    # /api/play, /api/pause, /api/stop, /api/seek, /api/seek-relative here
    # when role=master, instead of calling VideoPlayer directly.
    # -----------------------------------------------------------------

    def play(self, source, loop=True, volume=None, seek_to=0.0):
        """Scheduled play: prime, broadcast a future t0, wait, release —
        so remotes preroll and start in lockstep instead of catching up
        afterward (the reactive-only Phase 3 behaviour)."""
        is_stream = source.startswith(('rtsp://', 'http://', 'https://'))

        if is_stream:
            # Live content can't preroll (DESIGN.md §4) — no scheduling
            # possible. The reactive _tick() declares this "unmanaged"
            # on its next cycle, same as Phase 2/3 always did.
            return self.player.play(source, loop=loop, volume=volume, seek_to=seek_to)

        if loop is not None:
            self.player.state["loop"] = loop
        if volume is not None:
            self.player.state["volume"] = volume

        source_path = self.player.video_dir / source
        if not source_path.exists():
            raise FileNotFoundError(f"Video file not found: {source}")
        resolved_source = str(source_path.absolute())

        if not self.player._ensure_running():
            print("sync_master: failed to start MPV instance")
            return False

        with self.lock:
            self._scheduled_pending = True
        try:
            print(f"sync_master: priming {resolved_source}")
            if not self.player._prime(resolved_source, seek_to=seek_to):
                return False

            lead_s = self.config.data["start_lead_ms"] / 1000.0
            t0 = time.time() + lead_s
            duration = self.player.get_duration() or 0.0

            with self.lock:
                self.seq += 1
                self.declared.update({
                    "state": "playing",
                    "file": Path(resolved_source).name,
                    "t0": t0,
                    "pos0": max(0.0, seek_to or 0.0),
                    "duration": duration,
                    "loop": self.player.state["loop"],
                })
                packet = self._build_packet()
                self.last_packet = packet
            self._send(packet)

            sleep_for = t0 - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)

            self.player._release()
            self.player.state["status"] = "playing"
            self.player.state["source"] = resolved_source
            return True
        finally:
            with self.lock:
                self._scheduled_pending = False

    def resume(self):
        """Scheduled resume — identical mechanics to play(), but no
        re-priming needed: already paused at the right file/position
        from the earlier pause()."""
        with self.lock:
            self._scheduled_pending = True
        try:
            pos0 = self.player.get_playback_position() or 0.0
            lead_s = self.config.data["start_lead_ms"] / 1000.0
            t0 = time.time() + lead_s

            with self.lock:
                self.seq += 1
                self.declared["state"] = "playing"
                self.declared["t0"] = t0
                self.declared["pos0"] = pos0
                packet = self._build_packet()
                self.last_packet = packet
            self._send(packet)

            sleep_for = t0 - time.time()
            if sleep_for > 0:
                time.sleep(sleep_for)

            self.player._release()
            self.player.state["status"] = "playing"
            return "playing"
        finally:
            with self.lock:
                self._scheduled_pending = False

    def pause(self):
        """Immediate pause — operator expects instant response, per
        DESIGN.md §6.3. Remotes frame-match by seeking to pos0 while
        paused (unchanged Phase 3 behaviour on the receiving end)."""
        self.player.pause()
        pos = self.player.get_playback_position() or 0.0
        with self.lock:
            self.seq += 1
            self.declared["state"] = "paused"
            self.declared["t0"] = time.time()
            self.declared["pos0"] = pos
            packet = self._build_packet()
            self.last_packet = packet
        self._send(packet)
        return "paused"

    def stop(self):
        """Immediate stop: broadcast idle, then check whether the
        screensaver should take over after a short delay (DESIGN.md
        §6.4)."""
        self.player.stop()
        with self.lock:
            self.seq += 1
            self.declared.update({
                "state": "idle", "file": None, "t0": time.time(),
                "pos0": 0.0, "duration": 0.0,
            })
            packet = self._build_packet()
            self.last_packet = packet
        self._send(packet)
        self._schedule_screensaver_check()
        return "stopped"

    def seek(self, position):
        """Immediate seek: re-broadcast a fresh origin. Remotes see a
        large error and hard-seek to converge (unchanged Phase 3)."""
        self.player.seek(position)
        with self.lock:
            self.seq += 1
            self.declared["t0"] = time.time()
            self.declared["pos0"] = position
            packet = self._build_packet()
            self.last_packet = packet
        self._send(packet)

    def seek_relative(self, seconds):
        self.player.seek_relative(seconds)
        pos = self.player.get_playback_position() or 0.0
        with self.lock:
            self.seq += 1
            self.declared["t0"] = time.time()
            self.declared["pos0"] = pos
            packet = self._build_packet()
            self.last_packet = packet
        self._send(packet)

    # -----------------------------------------------------------------
    # Synced screensaver (DESIGN.md §6.4)
    # -----------------------------------------------------------------

    def _schedule_screensaver_check(self):
        """After a short idle delay, auto-play the screensaver if
        configured. Reuses play() directly, so an auto-started
        screensaver gets the same scheduled/frame-exact start as any
        operator content (T15's "in sync per T3 criteria")."""
        screensaver = self.config.data.get("screensaver", {})
        if not screensaver.get("enabled"):
            return
        file = screensaver.get("file")
        if not file:
            return
        if not (self.player.video_dir / file).exists():
            print(f"sync_master: screensaver file missing: {file}")
            return

        timer = threading.Timer(
            SCREENSAVER_RESUME_DELAY_S, self._maybe_start_screensaver,
            args=(file, screensaver.get("loop", True))
        )
        timer.daemon = True
        timer.start()

    def _maybe_start_screensaver(self, file, loop):
        # Re-check rather than track/cancel the timer: if the operator
        # started real content during the delay, this is just a no-op.
        with self.lock:
            still_idle = self.declared["state"] == "idle"
        if not still_idle:
            return
        print(f"sync_master: auto-starting screensaver: {file}")
        try:
            self.play(file, loop=loop)
        except Exception as e:
            print(f"sync_master: screensaver auto-play failed: {e}")

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
