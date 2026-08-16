#!/usr/bin/env python3
"""
Sync remote (DESIGN.md §6.1, §6.2, §6.3, §6.4, §7, §12 phases 2-4).

Listens for the master's UDP state broadcasts, reports raw packets +
clock health via /api/sync/status, and sends 1 Hz heartbeats back to the
master, unicast to the source address of the last state packet received
(DESIGN.md §6.2) — no master address needs to be configured up front.

The chase loop (§7): once a declared state names a file, this module
drives the local persistent mpv to play it and continuously corrects
position at 5 Hz (deadband -> nudge -> hard-seek).

Scheduled transitions (§6.3, phase 4): when a "playing" packet's t0 is in
the future, the remote primes now and releases exactly at t0 via a
threading.Timer — not the 5Hz chase loop's cadence, which would add up
to 200ms of its own jitter and defeat the point. A packet whose t0 has
already passed (late join, or the remote was offline) falls back to the
Phase 3 behaviour: immediate join + chase-loop convergence — exactly
DESIGN.md's "remotes that were offline converge afterwards via the chase
loop."

Local screensaver (§6.1 decision 4, phase 4): when the master declares
`unmanaged` (RTSP - sync doesn't cover it), a remote with a screensaver
configured plays it locally, looping, unsynced - there's no shared
position to chase for live content. Plain `idle` stays plain black; the
master handles idle->screensaver entirely itself (§6.4) by declaring
normal "playing" state, which remotes chase exactly like any other file
via the existing scheduled/chase machinery - no separate remote-side
"idle" screensaver path is needed.
"""

import json
import socket
import threading
import time
from pathlib import Path

from chrony_status import get_chrony_offset_ms

HEARTBEAT_HZ = 1
CHASE_HZ = 5  # DESIGN.md §7
MASTER_SEEN_TIMEOUT_S = 5  # DESIGN.md §6.2


class SyncRemote:
    """Receives master state broadcasts; reports status and heartbeats."""

    def __init__(self, config, player=None):
        self.config = config
        self.player = player
        self.hostname = socket.gethostname()

        self.last_packet = None
        self.last_packet_time = None
        self.master_addr = None
        self.packets_received = 0
        self.seq_gaps = 0
        self._last_seq = None
        self.lock = threading.Lock()

        # Chase loop state (DESIGN.md §7)
        self._applied_state = None
        self._applied_file = None
        self._load_ok = False  # only converge once the local player confirms a load
        self._last_speed = 1.0
        self.err_ms = None
        self.warnings = []

        # Scheduled-transition state (DESIGN.md §6.3, phase 4)
        self._release_timer = None      # pending threading.Timer, or None
        self._pending_release_t0 = None  # t0 we're primed-and-waiting for, or None

        self._stop = threading.Event()
        self._recv_sock = None
        self._send_sock = None
        self._threads = []

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self):
        self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._recv_sock.bind(('', self.config.data["state_port"]))
        self._recv_sock.settimeout(1.0)

        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        t1 = threading.Thread(target=self._recv_loop, daemon=True, name="sync-remote-recv")
        t2 = threading.Thread(target=self._heartbeat_loop, daemon=True, name="sync-remote-heartbeat")
        t3 = threading.Thread(target=self._chase_loop, daemon=True, name="sync-remote-chase")
        t1.start()
        t2.start()
        t3.start()
        self._threads = [t1, t2, t3]
        print(f"sync_remote: listening for state on :{self.config.data['state_port']}, "
              f"heartbeats -> master:{self.config.data['heartbeat_port']} @ {HEARTBEAT_HZ}Hz, "
              f"chase loop @ {CHASE_HZ}Hz")

    def stop(self):
        self._stop.set()
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None
        for t in self._threads:
            t.join(timeout=2)
        if self._recv_sock:
            self._recv_sock.close()
        if self._send_sock:
            self._send_sock.close()

    # -----------------------------------------------------------------
    # State receive (master -> remote)
    # -----------------------------------------------------------------

    def _recv_loop(self):
        while not self._stop.is_set():
            try:
                data, addr = self._recv_sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                packet = json.loads(data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            with self.lock:
                self.last_packet = packet
                self.last_packet_time = time.time()
                self.master_addr = addr[0]
                self.packets_received += 1
                seq = packet.get("seq")
                if self._last_seq is not None and seq is not None and seq > self._last_seq + 1:
                    self.seq_gaps += (seq - self._last_seq - 1)
                self._last_seq = seq

    # -----------------------------------------------------------------
    # Chase loop (DESIGN.md §7) — drives local mpv against the declared state
    # -----------------------------------------------------------------

    def _chase_loop(self):
        period = 1.0 / CHASE_HZ
        while not self._stop.is_set():
            time.sleep(period)
            if self.player is None:
                continue
            try:
                self._chase_tick()
            except Exception as e:
                print(f"sync_remote: chase tick error: {e}")

    def _chase_tick(self):
        with self.lock:
            packet = dict(self.last_packet) if self.last_packet else None

        if packet is None:
            return  # haven't heard from a master yet

        state = packet.get("state")
        file = packet.get("file")

        if state != self._applied_state or file != self._applied_file:
            self._handle_transition(packet)
        elif state == "playing" and self._pending_release_t0 is not None:
            # Still primed and waiting for a scheduled release - did the
            # master reschedule to a different t0 (rapid re-play before
            # the original one fired)? Re-handle if so. Steady-state t0
            # changes (loop wraps, drift re-anchors) don't reach here —
            # they only happen once _pending_release_t0 is back to None
            # after release, and are handled by _converge()'s hard-seek,
            # not by re-priming.
            if packet.get("t0") != self._pending_release_t0:
                self._handle_transition(packet)

        # Only converge once the local player has actually confirmed a
        # successful load — a missing file or a failed/slow play() must
        # not send the chase loop nudging/seeking a player with nothing
        # loaded (it never guesses, per DESIGN.md §6.1 file-resolution).
        # Also not while still primed-and-waiting for a scheduled release
        # (§6.3) — position isn't moving yet.
        if self._applied_state == "playing" and self._load_ok and self._pending_release_t0 is None:
            self._converge(packet)
        else:
            self.err_ms = None

    def _handle_transition(self, packet):
        """Apply a new declared state/file."""
        state = packet.get("state")
        file = packet.get("file")
        self._applied_state = state
        self._applied_file = file
        self._last_speed = 1.0
        self.err_ms = None
        self.warnings = []
        self._load_ok = False

        # Cancel any pending scheduled release from a previous transition
        # (e.g. operator hit play then stop before the earlier one fired).
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None
        self._pending_release_t0 = None

        if state == "idle":
            # The master handles idle->screensaver entirely itself
            # (DESIGN.md §6.4) by declaring normal "playing" state, which
            # this remote chases like any other file - genuine idle here
            # really does mean nothing is playing anywhere. Black.
            if self.player.state["status"] != "stopped":
                self.player.stop()
            return

        if state == "unmanaged":
            self._handle_unmanaged()
            return

        if not file:
            return

        local_path = self.player.video_dir / file
        if not local_path.exists():
            print(f"sync_remote: missing file {file!r}")
            self.warnings = ["missing-file"]
            if self.player.state["status"] != "stopped":
                self.player.stop()
            return

        now = time.time()
        pos0 = packet.get("pos0", 0.0)
        duration = packet.get("duration") or 0.0
        loop = packet.get("loop", True)
        t0 = packet.get("t0", now)

        if state == "playing" and t0 > now:
            # Scheduled start (DESIGN.md §6.3): prime now, release
            # exactly at t0 via a timer, not the 5Hz chase loop's own
            # cadence (which would add up to 200ms of its own jitter and
            # defeat the point of scheduling in the first place).
            #
            # Resume special case: if we're already paused at this exact
            # file/position (from the preceding "paused" broadcast),
            # skip re-priming entirely — a full reload is wasted work
            # that eats into the same lead-time budget the release timer
            # depends on, mirroring what SyncMaster.resume() already does
            # on the master side.
            already_primed = (
                self.player.state["status"] == "paused"
                and self.player.state["source"] == str(local_path)
                and abs((self.player.get_playback_position() or 0.0) - pos0) < 0.5
            )
            if not already_primed:
                try:
                    ok = self.player._prime(str(local_path), seek_to=pos0)
                except FileNotFoundError:
                    ok = False
                if not ok:
                    self.warnings = ["missing-file"]
                    return
                self.player.state["loop"] = loop
            self.player.set_speed(1.0)
            self._pending_release_t0 = t0
            # threading.Timer's delay counts from .start(), which happens
            # *after* _prime() above — priming is blocking and can take a
            # real, variable amount of time (especially on real storage,
            # unlike a fast dev-machine SSD), so the delay must be
            # measured from a fresh "now", not the one captured before
            # priming. Using the stale value here would release at
            # t0 + <priming duration> instead of at t0 — silently late by
            # exactly however long priming took.
            delay = max(0.0, t0 - time.time())
            self._release_timer = threading.Timer(
                delay, self._do_scheduled_release, args=(duration,)
            )
            self._release_timer.daemon = True
            self._release_timer.start()
            return

        try:
            if state == "playing":
                # Late join (t0 already passed) - the master was already
                # playing when we started listening, or we were offline.
                # Immediate join + chase-loop convergence, same as Phase 3.
                expected = pos0 + (now - t0) * packet.get("speed", 1.0)
                if loop and duration > 0:
                    expected = expected % duration
                ok = self.player.play(file, loop=loop, seek_to=max(0.0, expected))
            elif state == "paused":
                # Frame-match: prime (load paused + seek) without releasing
                # (DESIGN.md §4, §6.1) — mirrors the master's own pause.
                ok = self.player._prime(str(local_path), seek_to=pos0)
                if ok:
                    self.player.state["status"] = "paused"
                    self.player.state["source"] = str(local_path)
                    self.player.state["loop"] = loop
            else:
                ok = True
        except FileNotFoundError:
            ok = False

        if not ok:
            self.warnings = ["missing-file"]
            return

        self._load_ok = True
        self.player.set_speed(1.0)
        self._check_duration_mismatch(duration)

    def _do_scheduled_release(self, duration):
        """Timer callback (DESIGN.md §6.3): release a primed source
        exactly at its scheduled t0. Runs on the Timer's own thread."""
        self._release_timer = None
        self._pending_release_t0 = None
        self.player._release()
        self.player.state["status"] = "playing"
        self._load_ok = True
        self._check_duration_mismatch(duration)

    def _handle_unmanaged(self):
        """DESIGN.md §6.1 decision 4: RTSP on master. A remote with a
        screensaver configured plays it locally, looping, unsynced —
        there's no shared position to chase for live content. Otherwise
        black, same as idle."""
        screensaver = self.config.data.get("screensaver", {})
        file = screensaver.get("file")
        ok = False
        if screensaver.get("enabled") and file:
            local_path = self.player.video_dir / file
            if local_path.exists():
                try:
                    ok = self.player.play(file, loop=screensaver.get("loop", True))
                except FileNotFoundError:
                    ok = False
        if ok:
            self._load_ok = True
            return
        if self.player.state["status"] != "stopped":
            self.player.stop()

    def _check_duration_mismatch(self, duration):
        if duration and duration > 0:
            local_duration = self.player.get_duration() or 0.0
            if abs(local_duration - duration) > self.config.data["duration_tolerance_s"]:
                self.warnings.append("duration-mismatch")

    def _converge(self, packet):
        """5 Hz drift correction: deadband -> nudge -> hard-seek (§7)."""
        now = time.time()
        duration = packet.get("duration") or 0.0
        loop = packet.get("loop", True)

        expected = packet.get("pos0", 0.0) + (now - packet.get("t0", now)) * packet.get("speed", 1.0)
        if loop and duration > 0:
            expected = expected % duration

        actual = self.player.get_playback_position()
        if actual is None:
            return

        err = expected - actual  # positive: remote is behind, needs to catch up
        if loop and duration > 0:
            # Wrap the naive difference into [-duration/2, duration/2] so a
            # loop-wrap moment (expected near 0, actual near duration) doesn't
            # look like a huge error.
            err = ((err + duration / 2) % duration) - duration / 2

        err_ms = err * 1000.0
        self.err_ms = err_ms

        deadband = self.config.data["deadband_ms"]
        hard_seek = self.config.data["hard_seek_ms"]
        nudge = self.config.data["nudge_speed"]

        if abs(err_ms) >= hard_seek:
            target = expected + 0.05  # small lead to land close to on-time
            if loop and duration > 0:
                target = target % duration
            self.player.seek(target, exact=True)
            if self._last_speed != 1.0:
                self.player.set_speed(1.0)
                self._last_speed = 1.0
        elif abs(err_ms) >= deadband:
            target_speed = 1.0 + (nudge if err > 0 else -nudge)
            if target_speed != self._last_speed:
                self.player.set_speed(target_speed)
                self._last_speed = target_speed
        elif self._last_speed != 1.0:
            self.player.set_speed(1.0)
            self._last_speed = 1.0

    # -----------------------------------------------------------------
    # Heartbeat (remote -> master)
    # -----------------------------------------------------------------

    def _heartbeat_loop(self):
        period = 1.0 / HEARTBEAT_HZ
        while not self._stop.is_set():
            time.sleep(period)
            with self.lock:
                master_addr = self.master_addr
            if not master_addr:
                continue  # haven't heard from a master yet
            try:
                self._send_heartbeat(master_addr)
            except OSError as e:
                print(f"sync_remote: heartbeat send failed: {e}")

    def _send_heartbeat(self, master_addr):
        offset_ms, _leap = get_chrony_offset_ms()
        status = self.player.get_status() if self.player else {}
        fps = self.player.get_fps() if self.player else 0
        hb = {
            "v": 1,
            "id": self.hostname,
            "state": status.get("status", "stopped"),
            "file": Path(status["source"]).name if status.get("source") else None,
            "pos": status.get("position", 0),
            "err_ms": self.err_ms,
            "fps": fps or None,
            "chrony_ms": offset_ms,
            "warnings": list(self.warnings),
        }
        payload = json.dumps(hb).encode('utf-8')
        self._send_sock.sendto(payload, (master_addr, self.config.data["heartbeat_port"]))

    # -----------------------------------------------------------------
    # Status (for /api/sync/status)
    # -----------------------------------------------------------------

    def get_status(self):
        now = time.time()
        with self.lock:
            packet = dict(self.last_packet) if self.last_packet else None
            packet_age = (now - self.last_packet_time) if self.last_packet_time else None
            master_addr = self.master_addr
            packets_received = self.packets_received
            seq_gaps = self.seq_gaps

        offset_ms, leap_status = get_chrony_offset_ms()
        fps = (self.player.get_fps() if self.player else 0) or None
        err_frames = (self.err_ms * fps / 1000.0) if (self.err_ms is not None and fps) else None

        return {
            "role": "remote",
            "hostname": self.hostname,
            "master_addr": master_addr,
            "master_seen": packet_age is not None and packet_age < MASTER_SEEN_TIMEOUT_S,
            "last_packet": packet,
            "last_packet_age_s": round(packet_age, 2) if packet_age is not None else None,
            "packets_received": packets_received,
            "seq_gaps": seq_gaps,
            "chrony": {
                "offset_ms": offset_ms,
                "leap_status": leap_status,
                "available": offset_ms is not None,
            },
            "chase": {
                "applied_state": self._applied_state,
                "applied_file": self._applied_file,
                "err_ms": self.err_ms,
                "err_frames": round(err_frames, 2) if err_frames is not None else None,
                "fps": fps,
                "speed": self._last_speed,
                "warnings": list(self.warnings),
                "pending_release_t0": self._pending_release_t0,
            },
        }
