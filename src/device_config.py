#!/usr/bin/env python3
"""
Device output configuration: which HDMI port drives the display, and
which audio device mpv uses. Per-device (a remote picks its own HDMI
port/audio device independent of the master), persisted across reboots.

Not part of DESIGN.md's original sync/audio config blocks - HDMI port
selection came out of a real multi-HDMI-port hardware issue; audio.device
mirrors the field DESIGN.md §3 already specified but never implemented.
Follows the same load/merge-defaults/save pattern as SyncConfig.
"""

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "display": {
        "hdmi_port": "auto"  # "auto" | "hdmi-1" | "hdmi-2"
    },
    "audio": {
        "device": "auto"  # mpv audio-device name (from /api/audio/devices), or "auto"
    }
}


class DeviceConfig:
    """Loads/saves HDMI output + audio device selection as its own file."""

    def __init__(self, config_file="/opt/rpi-video-player/config/device.json"):
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
            if key in ("display", "audio") and isinstance(value, dict):
                merged[key].update(value)
            else:
                merged[key] = value
        return merged

    def load(self):
        """Load config from file, or create a default file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                self.data = self._merge(loaded)
                print(f"✅ Loaded device config (hdmi_port={self.data['display']['hdmi_port']}, "
                      f"audio_device={self.data['audio']['device']})")
            except Exception as e:
                print(f"Error loading device config: {e}; using defaults")
                self.data = self._defaults()
        else:
            print("No device config found, using defaults")
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
            print(f"Error saving device config: {e}")
            return False

    def update(self, patch):
        """Apply a partial update (e.g. {"display": {"hdmi_port": "hdmi-2"}}) and save."""
        merged = dict(self.data)
        for key, value in patch.items():
            if key in ("display", "audio") and isinstance(value, dict):
                merged[key] = {**self.data.get(key, {}), **value}
            else:
                merged[key] = value

        self.data = self._merge(merged)
        self.save()
        return self.data

    def to_dict(self):
        return dict(self.data)


if __name__ == "__main__":
    cfg = DeviceConfig("/tmp/test_device.json")
    print(json.dumps(cfg.to_dict(), indent=2))
