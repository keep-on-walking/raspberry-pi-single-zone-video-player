#!/usr/bin/env python3
"""
Multi-Player Sync Service
UDP-based master/remote synchronisation for rpi-video-player.

Master: broadcasts current file + position every 500ms.
Remote: listens, corrects mpv drift via IPC when > SEEK_THRESHOLD seconds out.
"""

import json
import socket
import threading
import time
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SYNC_PORT       = 32320          # UDP port for sync packets
MULTICAST_ADDR  = '239.70.80.80' # Same multicast group as FPP (convenient)
BROADCAST_INTERVAL = 0.5         # seconds between master broadcasts
SEEK_THRESHOLD  = 0.5            # seconds of drift before a hard seek
SPEED_THRESHOLD = 0.1            # seconds of drift where we nudge speed instead
SPEED_NUDGE     = 0.05           # fractional speed adjustment (1.05 / 0.95)


class SyncService:
    """
    Handles master broadcast and remote correction in background threads.
    Attach to an existing VideoPlayer instance after construction.
    """

    def __init__(self, player, mode='disabled', master_ip=None):
        """
        Args:
            player:    VideoPlayer instance (for IPC access)
            mode:      'disabled' | 'master' | 'remote'
            master_ip: IP of the master (only needed in remote mode).
                       If None, listens on multicast group.
        """
        self.player    = player
        self.mode      = mode
        self.master_ip = master_ip

        self._stop_event = threading.Event()
        self._thread     = None

        # Status exposed to the API
        self.status = {
            'mode':       mode,
            'master_ip':  master_ip,
            'running':    False,
            'last_rx':    None,   # remote: last packet timestamp (epoch)
            'last_tx':    None,   # master: last broadcast timestamp
            'drift':      None,   # remote: last measured drift in seconds
            'corrections': 0,     # remote: number of seeks issued
        }

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(self):
        if self.mode == 'disabled':
            return
        self._stop_event.clear()
        if self.mode == 'master':
            self._thread = threading.Thread(target=self._master_loop, daemon=True)
        else:
            self._thread = threading.Thread(target=self._remote_loop, daemon=True)
        self._thread.start()
        self.status['running'] = True
        print(f"[sync] started as {self.mode}")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.status['running'] = False
        print("[sync] stopped")

    def set_mode(self, mode, master_ip=None):
        """Change mode at runtime (stop/restart)."""
        self.stop()
        self.mode             = mode
        self.master_ip        = master_ip
        self.status['mode']   = mode
        self.status['master_ip'] = master_ip
        self.status['corrections'] = 0
        if mode != 'disabled':
            self.start()

    # ------------------------------------------------------------------
    # Master: broadcast loop
    # ------------------------------------------------------------------

    def _master_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Enable multicast TTL
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)

        print(f"[sync/master] broadcasting to {MULTICAST_ADDR}:{SYNC_PORT}")

        while not self._stop_event.is_set():
            try:
                player_status = self.player.get_status()
                if player_status['status'] in ('playing', 'paused'):
                    # Use raw IPC for position to avoid double-polling overhead
                    pos = self.player.get_playback_position() or 0
                    filename = os.path.basename(player_status['source'] or '')

                    packet = json.dumps({
                        'file': filename,
                        'pos':  round(pos, 3),
                        'ts':   time.time(),
                        'paused': player_status['status'] == 'paused',
                    }).encode()

                    sock.sendto(packet, (MULTICAST_ADDR, SYNC_PORT))
                    self.status['last_tx'] = time.time()
            except Exception as e:
                print(f"[sync/master] error: {e}")

            self._stop_event.wait(BROADCAST_INTERVAL)

        sock.close()

    # ------------------------------------------------------------------
    # Remote: listen and correct loop
    # ------------------------------------------------------------------

    def _remote_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)

        # Join multicast group
        import struct
        mreq = struct.pack('4sL', socket.inet_aton(MULTICAST_ADDR), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.bind(('', SYNC_PORT))

        print(f"[sync/remote] listening on {MULTICAST_ADDR}:{SYNC_PORT}")

        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)

                # If a specific master_ip is set, filter to that IP only
                if self.master_ip and addr[0] != self.master_ip:
                    continue

                packet = json.loads(data.decode())
                self._handle_packet(packet)

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[sync/remote] error: {e}")

        sock.close()

    def _handle_packet(self, packet):
        """Compare master position to local mpv position and correct if needed."""
        self.status['last_rx'] = time.time()

        # Account for network transit time
        transit = time.time() - packet['ts']
        master_pos = packet['pos'] + transit

        # Only sync if we're playing the same file
        local_status = self.player.get_status()
        if local_status['status'] not in ('playing', 'paused'):
            return

        local_file = os.path.basename(local_status['source'] or '')
        if local_file != packet['file']:
            print(f"[sync/remote] file mismatch (local: {local_file}, master: {packet['file']})")
            return

        # Handle pause state
        if packet['paused'] and local_status['status'] == 'playing':
            self.player.pause()
            return
        if not packet['paused'] and local_status['status'] == 'paused':
            self.player.pause()  # toggle back to playing
            return

        # Measure drift
        local_pos = self.player.get_playback_position() or 0
        drift = master_pos - local_pos
        self.status['drift'] = round(drift, 3)

        if abs(drift) > SEEK_THRESHOLD:
            # Hard seek
            self.player.seek(master_pos)
            self.status['corrections'] += 1
            print(f"[sync/remote] hard seek {drift:+.2f}s → {master_pos:.2f}s")
        elif abs(drift) > SPEED_THRESHOLD:
            # Nudge playback speed
            speed = 1.0 + (SPEED_NUDGE if drift > 0 else -SPEED_NUDGE)
            self.player._send_command({"command": ["set_property", "speed", speed]})
            print(f"[sync/remote] speed nudge {drift:+.2f}s → speed {speed}")
        else:
            # Back to normal speed if we were nudging
            self.player._send_command({"command": ["set_property", "speed", 1.0]})
