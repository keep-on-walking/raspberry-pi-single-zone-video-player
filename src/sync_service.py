#!/usr/bin/env python3
"""
Multi-Player Sync Service - Aggressive initial sync version
"""

import json
import socket
import struct
import threading
import time
import os

SYNC_PORT = 32320
MULTICAST_ADDR = '239.70.80.80'
BROADCAST_INTERVAL = 0.5
SEEK_THRESHOLD = 0.5
SPEED_THRESHOLD = 0.1
SPEED_NUDGE = 0.05
INITIAL_SYNC_DURATION = 15  # seconds of aggressive sync after play starts


class SyncService:

    def __init__(self, player, mode='disabled', master_ip=None):
        self.player = player
        self.mode = mode
        self.master_ip = master_ip
        self._stop_event = threading.Event()
        self._thread = None
        self._play_start_time = None
        self.status = {
            'mode': mode,
            'master_ip': master_ip,
            'running': False,
            'last_rx': None,
            'last_tx': None,
            'drift': None,
            'corrections': 0,
        }

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
        self.stop()
        self.mode = mode
        self.master_ip = master_ip
        self.status['mode'] = mode
        self.status['master_ip'] = master_ip
        self.status['corrections'] = 0
        if mode != 'disabled':
            self.start()

    def notify_play_started(self):
        """Call this when playback starts to reset the aggressive sync timer"""
        self._play_start_time = time.time()
        print(f"[sync] play started, aggressive sync active for {INITIAL_SYNC_DURATION}s")

    def _master_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        print(f"[sync/master] broadcasting to {MULTICAST_ADDR}:{SYNC_PORT}")
        while not self._stop_event.is_set():
            try:
                player_status = self.player.get_status()
                if player_status['status'] in ('playing', 'paused'):
                    pos = self.player.get_playback_position() or 0
                    filename = os.path.basename(player_status['source'] or '')
                    packet = json.dumps({
                        'file': filename,
                        'pos': round(pos, 3),
                        'ts': time.time(),
                        'paused': player_status['status'] == 'paused',
                    }).encode()
                    sock.sendto(packet, (MULTICAST_ADDR, SYNC_PORT))
                    self.status['last_tx'] = time.time()
            except Exception as e:
                print(f"[sync/master] error: {e}")
            self._stop_event.wait(BROADCAST_INTERVAL)
        sock.close()

    def _remote_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        mreq = struct.pack('4sL', socket.inet_aton(MULTICAST_ADDR), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.bind(('', SYNC_PORT))
        print(f"[sync/remote] listening on {MULTICAST_ADDR}:{SYNC_PORT}")
        while not self._stop_event.is_set():
            try:
                data, addr = sock.recvfrom(1024)
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
        self.status['last_rx'] = time.time()

        # Account for network transit time
        transit = time.time() - packet['ts']
        master_pos = packet['pos'] + transit

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
            self.player.pause()
            return

        # Get local position directly from mpv IPC
        local_pos = self.player.get_playback_position() or 0
        drift = master_pos - local_pos

        # Get video duration to detect loop boundary crossings
        duration = self.player.get_duration() or 0

        # If drift is close to +/- duration, one device has looped - ignore
        if duration > 0 and abs(abs(drift) - duration) < 5:
            print(f"[sync/remote] loop boundary detected, ignoring drift {drift:+.2f}s")
            return

        # Also ignore large negative drifts that are impossible
        if drift < -10:
            print(f"[sync/remote] impossible drift {drift:+.2f}s, ignoring")
            return

        self.status['drift'] = round(drift, 3)

        # Check if we're in the aggressive sync window
        in_aggressive_sync = (
            self._play_start_time is not None and
            (time.time() - self._play_start_time) < INITIAL_SYNC_DURATION
        )

        if in_aggressive_sync:
            # During initial sync period, always hard seek if drift > 0.1s
            if abs(drift) > 0.1:
                self.player.seek(master_pos)
                self.status['corrections'] += 1
                print(f"[sync/remote] aggressive seek {drift:+.2f}s → {master_pos:.2f}s")
        else:
            # Normal sync
            if abs(drift) > SEEK_THRESHOLD:
                self.player.seek(master_pos)
                self.status['corrections'] += 1
                print(f"[sync/remote] hard seek {drift:+.2f}s → {master_pos:.2f}s")
            elif abs(drift) > SPEED_THRESHOLD:
                speed = 1.0 + (SPEED_NUDGE if drift > 0 else -SPEED_NUDGE)
                self.player._send_command({"command": ["set_property", "speed", speed]})
            else:
                self.player._send_command({"command": ["set_property", "speed", 1.0]})

