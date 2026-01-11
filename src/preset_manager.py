#!/usr/bin/env python3
"""
Preset Manager for Video Player
Saves and loads window geometry presets
"""

import json
from pathlib import Path


class PresetManager:
    """Manages geometry presets for the video player"""
    
    def __init__(self, presets_file="/opt/rpi-video-player/config/presets.json"):
        self.presets_file = Path(presets_file)
        self.presets = {}
        self.load_presets()
    
    def load_presets(self):
        """Load presets from file"""
        if self.presets_file.exists():
            try:
                with open(self.presets_file, 'r') as f:
                    self.presets = json.load(f)
                print(f"✅ Loaded {len(self.presets)} presets")
            except Exception as e:
                print(f"Error loading presets: {e}")
                self.presets = {}
                self._create_defaults()
        else:
            print("No presets file found, starting fresh")
            self._create_defaults()
    
    def _create_defaults(self):
        """Create default presets"""
        print("Creating default presets...")
        
        defaults = [
            {
                "name": "fullscreen",
                "description": "Full screen",
                "geometry": {"x": 0, "y": 0, "width": 1920, "height": 1080}
            },
            {
                "name": "left-half",
                "description": "Left half of screen",
                "geometry": {"x": 0, "y": 0, "width": 960, "height": 1080}
            },
            {
                "name": "right-half",
                "description": "Right half of screen",
                "geometry": {"x": 960, "y": 0, "width": 960, "height": 1080}
            },
            {
                "name": "top-half",
                "description": "Top half of screen",
                "geometry": {"x": 0, "y": 0, "width": 1920, "height": 540}
            },
            {
                "name": "bottom-half",
                "description": "Bottom half of screen",
                "geometry": {"x": 0, "y": 540, "width": 1920, "height": 540}
            },
            {
                "name": "center-large",
                "description": "Centered 80% size",
                "geometry": {"x": 192, "y": 108, "width": 1536, "height": 864}
            },
            {
                "name": "corner-pip",
                "description": "Picture-in-picture (bottom right)",
                "geometry": {"x": 1280, "y": 720, "width": 640, "height": 360}
            }
        ]
        
        for preset in defaults:
            self.save_preset(preset["name"], preset["geometry"], preset["description"])
        
        print(f"✅ Created {len(defaults)} default presets")
    
    def save_preset(self, name, geometry, description=""):
        """Save a preset"""
        self.presets[name] = {
            "geometry": geometry,
            "description": description
        }
        
        # Save to file
        try:
            self.presets_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.presets_file, 'w') as f:
                json.dump(self.presets, f, indent=2)
            print(f"✅ Saved preset: {name}")
            return True
        except Exception as e:
            print(f"Error saving preset: {e}")
            return False
    
    def get_preset(self, name):
        """Get a preset by name"""
        return self.presets.get(name)
    
    def delete_preset(self, name):
        """Delete a preset"""
        if name in self.presets:
            del self.presets[name]
            
            # Save to file
            try:
                with open(self.presets_file, 'w') as f:
                    json.dump(self.presets, f, indent=2)
                print(f"✅ Deleted preset: {name}")
                return True
            except Exception as e:
                print(f"Error deleting preset: {e}")
                return False
        return False
    
    def list_presets(self):
        """List all presets"""
        return self.presets
    
    def get_preset_names(self):
        """Get list of preset names"""
        return list(self.presets.keys())


if __name__ == "__main__":
    # Test preset manager
    pm = PresetManager("/tmp/test_presets.json")
    
    print("\nAvailable presets:")
    for name, data in pm.list_presets().items():
        print(f"  {name}: {data['description']}")
        print(f"    Geometry: {data['geometry']}")
    
    print("\n✅ Preset manager test complete")
