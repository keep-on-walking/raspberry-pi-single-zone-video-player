#!/usr/bin/env python3
"""
Sync remote — Phase 2 skeleton (DESIGN.md §6.1, §6.2, §12 phase 2).

Listens for the master's UDP state broadcasts and reports raw packets +
clock health via /api/sync/status, to pass T1. Also sends 1 Hz heartbeats
back to the master, unicast to the source address of the last state
packet received (DESIGN.md §6.2) — no master address needs to be
configured up front.

The chase loop that actually drives local mpv playback against the
declared state lands in Phase 3 (DESIGN.md §12); this module only
receives, records, and reports for now.
"""

import json
import socket
import threading
import time

from chrony_status import get_chrony_offset_ms

HEARTBEAT_HZ = 1
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
        t1.start()
        t2.start()
        self._threads = [t1, t2]
        print(f"sync_remote: listening for state on :{self.config.data['state_port']}, "
              f"heartbeats -> master:{self.config.data['heartbeat_port']} @ {HEARTBEAT_HZ}Hz")

    def stop(self):
        self._stop.set()
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
        hb = {
            "v": 1,
            "id": self.hostname,
            "state": status.get("status", "stopped"),
            "file": status.get("source"),
            "pos": status.get("position", 0),
            "err_ms": None,  # populated once the Phase 3 chase loop exists
            "chrony_ms": offset_ms,
            "warnings": [],
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
        }
