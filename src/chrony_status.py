#!/usr/bin/env python3
"""
Reads local clock health from `chronyc tracking` (DESIGN.md §5).

Used by both sync_master and sync_remote to report chrony offset in
/api/sync/status and in remote heartbeats. Returns (None, None) when
chrony isn't installed/running (e.g. dev machines) rather than raising —
sync status reporting must never crash the dashboard.
"""

import re
import subprocess

_SYSTEM_TIME_RE = re.compile(r"([\d.]+)\s+seconds\s+(slow|fast)")


def get_chrony_offset_ms():
    """Return (offset_ms, leap_status) from `chronyc tracking`.

    offset_ms is signed: negative means the local clock is behind
    (slow of) chrony's reference, positive means ahead (fast of).
    Returns (None, None) if chronyc isn't available or times out.
    """
    try:
        result = subprocess.run(
            ["chronyc", "tracking"],
            capture_output=True, text=True, timeout=2
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None, None

    if result.returncode != 0:
        return None, None

    offset_ms = None
    leap_status = None
    for line in result.stdout.splitlines():
        if line.startswith("System time"):
            m = _SYSTEM_TIME_RE.search(line)
            if m:
                value_ms = float(m.group(1)) * 1000.0
                offset_ms = -value_ms if m.group(2) == "slow" else value_ms
        elif line.startswith("Leap status"):
            leap_status = line.split(":", 1)[1].strip()

    return offset_ms, leap_status


if __name__ == "__main__":
    offset, leap = get_chrony_offset_ms()
    if offset is None:
        print("chrony unavailable")
    else:
        print(f"offset: {offset:+.3f} ms, leap status: {leap}")
