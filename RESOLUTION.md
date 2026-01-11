# Display Resolution Configuration

## Setting 4K Resolution (3840x2160)

The video player works with any resolution, but you need to configure both X11 and the web interface.

### Step 1: Check Current Resolution

```bash
# Check what X11 is using
DISPLAY=:1 xrandr
```

This will show your available displays and modes, like:
```
HDMI-A-1 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm
   3840x2160     60.00 +  30.00    25.00    24.00    29.97    23.98  
   1920x1080     60.00*   50.00    59.94    30.00    25.00    24.00    29.97    23.98  
```

### Step 2: Set X11 to 4K

```bash
# Set to 4K @ 60Hz
DISPLAY=:1 xrandr --output HDMI-A-1 --mode 3840x2160 --rate 60
```

Replace `HDMI-A-1` with your actual output name from the xrandr output.

### Step 3: Make it Permanent

Create an X11 configuration file:

```bash
sudo tee /etc/X11/xorg.conf.d/30-resolution.conf << 'EOF'
Section "Monitor"
    Identifier "HDMI-A-1"
    Option "PreferredMode" "3840x2160"
EndSection

Section "Screen"
    Identifier "Default Screen"
    Monitor "HDMI-A-1"
    DefaultDepth 24
    SubSection "Display"
        Depth 24
        Modes "3840x2160" "1920x1080"
    EndSubSection
EndSection
EOF
```

**Replace** `HDMI-A-1` with your display name.

### Step 4: Restart Services

```bash
sudo systemctl restart x11-server video-player
```

### Step 5: Update Web Interface

1. Go to `http://[pi-ip]:5000`
2. In "Display Resolution" section:
   - Width: `3840`
   - Height: `2160`
3. Click **Update**

Now the canvas and geometry calculations will match your 4K display!

---

## Common Display Modes

### 1080p (Full HD)
```bash
DISPLAY=:1 xrandr --output HDMI-A-1 --mode 1920x1080 --rate 60
```
Web interface: 1920 x 1080

### 4K (Ultra HD)
```bash
DISPLAY=:1 xrandr --output HDMI-A-1 --mode 3840x2160 --rate 60
```
Web interface: 3840 x 2160

### 720p (HD)
```bash
DISPLAY=:1 xrandr --output HDMI-A-1 --mode 1280x720 --rate 60
```
Web interface: 1280 x 720

---

## Troubleshooting

### "Can't open display"
Make sure X11 is running:
```bash
ps aux | grep X
sudo systemctl status x11-server
```

### Video plays in corner
The X11 resolution doesn't match what you set in the web interface. Check with `xrandr` and update both.

### Resolution not available
Your display might not support it. Check available modes:
```bash
DISPLAY=:1 xrandr | grep -A20 "connected"
```

### After reboot resolution resets
You need to create the permanent config file in Step 3 above.

---

## Auto-Detect Display Resolution (Optional)

Add this to the video player startup to auto-detect:

```bash
# Get resolution automatically
RESOLUTION=$(DISPLAY=:1 xrandr | grep '\*' | awk '{print $1}')
WIDTH=$(echo $RESOLUTION | cut -d'x' -f1)
HEIGHT=$(echo $RESOLUTION | cut -d'x' -f2)

# Update web interface default
# (Would require modifying video_controller.py to read these values)
```

---

## Multiple Displays

If you have multiple HDMI outputs:

```bash
# List all outputs
DISPLAY=:1 xrandr

# Set each individually
DISPLAY=:1 xrandr --output HDMI-A-1 --mode 3840x2160
DISPLAY=:1 xrandr --output HDMI-A-2 --mode 1920x1080
```

The video player will use the combined virtual screen size.

---

**Need help?** Check the main [README.md](README.md) or [API.md](API.md) documentation.
