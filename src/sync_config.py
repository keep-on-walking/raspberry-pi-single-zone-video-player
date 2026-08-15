#!/usr/bin/env python3
"""
Sync configuration schema and persistence (DESIGN.md §3).

Additive: a missing or absent config file defaults to role "off", which
makes the player behave byte-for-byte like the pre-sync build.
"""

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "role": "off",  # "off" | "master" | "remote"
    "state_port": 5005,
    "heartbeat_port": 5006,
    "broadcast_addr": "255.255.255.255",
    "start_lead_ms": 800,
    "deadband_ms": 25,
    "nudge_speed": 0.02,
    "hard_seek_ms": 1000,
    "remote_audio": False,
    "duration_tolerance_s": 0.5,
    "screensaver": {
        "enabled": False,
        "file": "screensaver.mp4",
        "loop": True
    }
}

VALID_ROLES = {"off", "master", "remote"}


class SyncConfig:
    """Loads/saves the `sync` config block as its own file."""

    def __init__(self, config_file="/opt/rpi-video-player/config/sync.json"):
        self.config_file = Path(config_file)
        self.data = self._defaults()
        self.load()

    def _defaults(self):
        return json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    def _merge(self, loaded):
        """Merge a loaded dict onto the defaults so new fields added later
        always have a value even against an older config file on disk."""
        merged = self._defaults()
        for key, value in loaded.items():
            if key == "screensaver" and isinstance(value, dict):
                merged["screensaver"].update(value)
            else:
                merged[key] = value

        if merged["role"] not in VALID_ROLES:
            print(f"⚠️  Invalid sync role '{merged['role']}' in config, "
                  f"falling back to 'off'")
            merged["role"] = "off"

        return merged

    def load(self):
        """Load config from file, or create a default (role=off) file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                self.data = self._merge(loaded)
                print(f"✅ Loaded sync config (role={self.data['role']})")
            except Exception as e:
                print(f"Error loading sync config: {e}; using defaults (role=off)")
                self.data = self._defaults()
        else:
            print("No sync config found, defaulting to role=off")
            self.data = self._defaults()
            self.save()

    def save(self):
        """Persist current config to file."""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving sync config: {e}")
            return False

    def update(self, patch):
        """Apply a partial update (e.g. from POST /api/sync/config) and save."""
        if "role" in patch and patch["role"] not in VALID_ROLES:
            raise ValueError(f"Invalid role: {patch['role']!r}, "
                              f"must be one of {sorted(VALID_ROLES)}")

        merged = dict(self.data)
        merged.update(patch)
        if "screensaver" in patch and isinstance(patch["screensaver"], dict):
            merged["screensaver"] = {**self.data["screensaver"], **patch["screensaver"]}

        self.data = self._merge(merged)
        self.save()
        return self.data

    def to_dict(self):
        return dict(self.data)


if __name__ == "__main__":
    cfg = SyncConfig("/tmp/test_sync.json")
    print(json.dumps(cfg.to_dict(), indent=2))
