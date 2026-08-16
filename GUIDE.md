# Multi-Device Sync — Setup & Operation Guide

Everything needed to provision, run, and troubleshoot this player — both as
a standalone single-zone player and as a synced master + remote(s) setup.
Where this guide gives real numbers (CPU load, timing, sync accuracy),
they're from actual testing on real Raspberry Pi hardware during this
project's development, not estimates.

## Contents

- [Architecture at a glance](#architecture-at-a-glance)
- [Hardware notes](#hardware-notes)
- [Provisioning a device](#provisioning-a-device)
- [Setting the sync role](#setting-the-sync-role)
- [Dashboard walkthrough](#dashboard-walkthrough)
- [Sync status & monitoring](#sync-status--monitoring)
- [HDMI output selection](#hdmi-output-selection)
- [Audio device selection](#audio-device-selection)
- [Synced screensaver](#synced-screensaver)
- [RTSP playback](#rtsp-playback)
- [Ticker overlay](#ticker-overlay)
- [Node-RED integration patterns](#node-red-integration-patterns)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## Architecture at a glance

Every device runs the same software; a config value (`sync.role`) decides
what it does:

- **`off`** (default) — standalone single-zone player, byte-for-byte the
  original behavior. No sync code runs at all.
- **`master`** — owns the "declared state" (what should be playing, where,
  and since when) and broadcasts it over UDP at 10Hz. Also listens for
  heartbeats from remotes to show their health on the dashboard.
- **`remote`** — listens for the master's broadcasts and drives its own
  local mpv to match: same file (by basename — content can differ per
  device, only the filename needs to match), same position, in sync.

The protocol is **declarative, not command-based**: the master continuously
broadcasts *what should be true right now* (file, position, wall-clock
origin), not one-off commands. A remote that missed several packets, just
rebooted, or just joined still knows exactly where it should be from the
very next packet it receives — there's no separate "catch up" logic to get
wrong.

**Clock agreement** (chrony) is what makes "position at a given wall-clock
instant" a meaningful, shared concept across devices — this is why sync
needs wired Ethernet and a working NTP setup, covered below.

**Device identity** is just the hostname, set once via `raspi-config` during
provisioning. It shows up in the dashboard header, in heartbeats, and in
`/api/sync/status` — no separate device-naming step needed.

---

## Hardware notes

Real findings from this project's own testing — worth reading before you
buy/provision hardware, not just background color.

**Tested configuration**: CM4 master (1GB RAM, eMMC storage) + CM4 remote
(2GB RAM, SD card storage), both wired Ethernet.

**Storage matters for scheduled-start precision.** A real bug was found and
fixed where slow file-loading (priming) on the remote ate into the lead
time a scheduled play/resume needs — worse on slower storage. eMMC is
generally more *consistent* in latency than SD cards (even if not always
faster in raw throughput — cheap SD controllers are the classic weak point
in Pi reliability), and a SATA SSD (via USB3 on a Pi 4) is a solid choice
for a device that will see a lot of pause/resume activity.

**CPU cost, measured directly** (`ps -eo pid,%cpu,%mem,comm`):
- 1080p HEVC playback alone: **~48-53%** of one core on a CM4
- Same, but downscaled to a small window (e.g. a corner-pip preset): CPU
  cost was *not* dramatically higher (~53% vs ~48%) — but visible sync
  jitter increased (~±0.5 frame swings vs. the usual sub-frame accuracy).
  The likely cause isn't the scaling itself so much as general CPU headroom
  being tight enough that the sync loop's own IPC calls get noisier under
  any additional load — not something buying a bigger window fixes, only
  more headroom (a faster device) does.
- Adding a second simultaneous video (the ticker overlay) on top of a main
  synced video: mpv processes combined ~30% of one core, but **Xorg's own
  compositing cost was ~24%** — nearly as expensive as a decode process
  itself. Total system CPU under this combined load settled around
  55-58%, with the device still comfortably keeping the main content's
  sync accuracy under 3ms. Real cost, but not a problem at this scale on
  a CM4.
- A Pi 5 would likely help across the board here (faster cores, newer
  GPU/video block) — a Pi 4/CM4 upgrade with more RAM alone would **not**,
  since none of this was memory-bound (RAM stayed flat with zero swap
  throughout every test in this project, including a 10+ hour soak).

**Argon ONE V5 case** (Pi 5): breaks out **both** of the Pi 5's micro-HDMI
ports to full-size HDMI, and its "built-in DAC" option is USB-connected
through the case's own breakout board (HS100B chip) — not a device-tree
overlay, so it needs no kernel-level setup. It just shows up as a normal
ALSA/USB audio device once connected. See
[HDMI output selection](#hdmi-output-selection) for why the dual-port
detail matters.

---

## Provisioning a device

Run on **every** device (master and each remote), whether or not it'll use
sync — steps 6+ only matter if it will.

```bash
git clone -b multisync https://github.com/keep-on-walking/raspberry-pi-single-zone-video-player.git
cd raspberry-pi-single-zone-video-player
```
*(or `git pull origin multisync` if already cloned)*

```bash
sudo bash install.sh
```

Set the hostname — this becomes the device's identity everywhere in sync:
```bash
sudo raspi-config
```
→ System Options → Hostname → something meaningful (`mpv-master`,
`cm4-stage-left`, etc.)

**If `install.sh` printed a message about forcing both HDMI connectors in
`cmdline.txt`**, reboot now — that specific change needs a reboot to take
effect (see [HDMI output selection](#hdmi-output-selection)):
```bash
sudo reboot
```

**Chrony setup** — different args per role:
```bash
# Master:
sudo bash chrony-setup.sh --role master

# Remote (use the master's hostname/IP from the step above):
sudo bash chrony-setup.sh --role remote --master-host mpv-master.local
```

Verify clock agreement (this is the project's T1 test — should show well
under 1ms once both devices are up):
```bash
chronyc tracking
```

Then [set the sync role](#setting-the-sync-role) and you're done — verify
with `/api/sync/status` as shown there.

---

## Setting the sync role

There's no dashboard toggle for this yet — it's a config-file change plus
a service restart:

```bash
sudo -u <your-user> /opt/rpi-video-player/venv/bin/python3 -c "import sys; sys.path.insert(0,'/opt/rpi-video-player/src'); from sync_config import SyncConfig; SyncConfig().update({'role': 'master'})"
```
(use `'role': 'remote'` on remotes)

```bash
sudo systemctl restart video-player
```

Verify:
```bash
curl http://localhost:5000/api/sync/status | python3 -m json.tool
```

This same pattern (`SyncConfig().update({...})` + restart) is how you'd
change any other sync tuning value too (`state_port`, `deadband_ms`,
`broadcast_addr` on fussier networks, etc.) — see `src/sync_config.py` for
the full schema, or [DESIGN.md](DESIGN.md) §3 for what each value does.

---

## Dashboard walkthrough

`http://<device-ip>:5000`. Panels appear top to bottom:

- **Header** — device hostname (not "Video Player" — makes it easy to tell
  devices apart with several dashboards open) and playback status
- **Sync status panel** — only appears when `sync.role` isn't `off`. Shows
  MASTER/REMOTE badge, a green/red health indicator, and live drift stats.
  Full field reference in [Sync status & monitoring](#sync-status--monitoring).
- **Visual Layout** — display resolution, the draggable/resizable canvas,
  and the preset grid (fullscreen, halves, corner-pip, etc.)
- **Video Source** — local file dropdown or RTSP URL, Play/Pause/Stop. On
  a sync remote, these are locked (409) unless you pass `override: true` —
  see [RTSP playback](#rtsp-playback).
- **Window Geometry** — precise X/Y/Width/Height for the main video
- **Ticker Overlay** — a second, independent video (its own file picker,
  Play/Stop, and geometry) — see [Ticker overlay](#ticker-overlay)
- **Display Output & Audio** — which HDMI port, which audio device — see
  the two sections below
- **Screensaver** — enable/disable, pick the file, set the idle delay —
  see [Synced screensaver](#synced-screensaver)
- **Playback Settings** — volume, loop toggle
- **Position** — seek slider, ±10s buttons (appears during playback)
- **File Management** — upload, delete, see uploaded files (shared library
  used by every file picker on the page: main source, ticker, screensaver)
- **Save Layout Preset** — name a geometry, save/load/delete, set a default
  (applied automatically on every `/api/play`)

---

## Sync status & monitoring

`GET /api/sync/status` — shape depends on role.

**On a master:**
```json
{
  "role": "master", "hostname": "...",
  "last_packet": { "state": "playing", "file": "...", "t0": ..., "pos0": ..., "duration": ..., "seq": ... },
  "chrony": { "offset_ms": ..., "leap_status": "Normal", "available": true },
  "remotes": {
    "cm4-remote-1": {
      "state": "playing", "file": "...", "pos": ...,
      "err_ms": ..., "err_frames": ..., "fps": ...,
      "chrony_ms": ..., "warnings": [],
      "last_seen_ago_s": ..., "offline": false
    }
  }
}
```

**On a remote:**
```json
{
  "role": "remote", "hostname": "...",
  "master_addr": "...", "master_seen": true,
  "last_packet": { "...": "..." }, "last_packet_age_s": ...,
  "packets_received": ..., "seq_gaps": 0,
  "chrony": { "offset_ms": ..., "available": true },
  "chase": {
    "applied_state": "playing", "applied_file": "...",
    "err_ms": ..., "err_frames": ..., "fps": ..., "speed": 1.0,
    "warnings": [], "pending_release_t0": null
  }
}
```

**What healthy looks like** (from real multi-hour testing): `err_ms` in the
single-to-low-double digits, `chrony.offset_ms` under 1, `seq_gaps` at or
near 0, `warnings: []`, `offline`/`master_seen` reflecting reality.

**What's worth investigating**: `offline: true` on a remote the master
should be seeing, `master_seen: false` on a remote, non-empty `warnings`
(`missing-file` — the named file isn't in that device's own
`data/videos/`; `duration-mismatch` — local file's duration differs from
the master's by more than `duration_tolerance_s`), or `err_ms` that stays
large instead of settling.

**Running your own soak test**: play something with `loop: true`, then
periodically re-check `/api/sync/status` (packet counts should climb
steadily, `seq_gaps` should stay flat) and `free -h` on each device (memory
should stay flat with `Swap: 0B` used — growth over hours would indicate a
leak). This project's own 10.4-hour real-hardware soak test is documented
in `PHASE3-NOTES.md`/`PHASE4-NOTES.md` if you want a reference for what a
clean result looks like.

---

## HDMI output selection

**Why this exists**: some boards (notably the Argon ONE V5 case) expose
**two** physical HDMI ports. The boot config only forces a display mode on
one connector by default — a screen plugged into the other port gets no
signal at all, even though playback is working perfectly internally (sync
and mpv never depend on anything being physically displayed).

`install.sh` now idempotently ensures **both** connectors
(`video=HDMI-A-1:...` and `video=HDMI-A-2:...`) are forced in
`cmdline.txt` — this needs **one reboot** the first time it applies (the
installer tells you when). After that, switching which port is active is
a live operation, no further reboots.

**Dashboard**: Display Output & Audio → HDMI Output → Auto / HDMI 1 / HDMI 2.
Applies immediately.

**API**:
```bash
curl http://<device-ip>:5000/api/display/hdmi-port
curl -X POST http://<device-ip>:5000/api/display/hdmi-port -H "Content-Type: application/json" -d '{"port": "hdmi-2"}'
```

---

## Audio device selection

`GET /api/audio/devices` lists everything mpv can see — real ALSA device
names, straight from mpv's own `audio-device-list`. On a Pi with two HDMI
outputs you'll typically see `vc4-hdmi-0` (first port) and `vc4-hdmi-1`
(second port), each with several near-duplicate entries for different ALSA
access modes. **Pick the "Hardware device with all software conversions"
variant** for whichever HDMI port matches your `HDMI Output` selection
above — it auto-handles sample-rate/format differences and is the most
broadly compatible choice.

There's no automatic link between the HDMI port selector and the audio
device selector — set both once during setup, takes seconds.

**Remotes are muted by default** (`sync.remote_audio: false`, matching the
design decision that only the master outputs audio in a synced setup). The
dashboard's Audio Output selector shows "(muted — sync remote)" and is
disabled in that case — this is expected, not a bug.

```bash
curl http://<device-ip>:5000/api/audio/devices
curl http://<device-ip>:5000/api/audio/device
curl -X POST http://<device-ip>:5000/api/audio/device -H "Content-Type: application/json" -d '{"device": "alsa/hw:0,0"}'
```

---

## Synced screensaver

Two genuinely different behaviors depending on *why* nothing synced is
happening:

**Master goes idle** (nothing playing) → after a configurable delay, the
master automatically starts playing its screensaver file, looping — using
the exact same scheduled-start mechanism as any operator-triggered
content, so it starts **in sync** across every device, not just locally on
the master. Operator-started content always preempts it immediately;
stopping that content brings the screensaver back after the same delay.

**Master plays RTSP** (`unmanaged` — sync doesn't cover live streams) → a
remote with its own screensaver configured plays it **locally, looping,
unsynced** instead of just going black, since there's no shared position
to sync a live stream to. A remote without a screensaver configured shows
black during RTSP, same as before this feature existed.

**Dashboard**: Screensaver panel — enable checkbox, video picker (same
shared file list as everywhere else), delay in seconds, one Save button.

```bash
curl http://<device-ip>:5000/api/sync/screensaver
curl -X POST http://<device-ip>:5000/api/sync/screensaver -H "Content-Type: application/json" -d '{"enabled": true, "file": "screensaver.mp4", "delay_s": 30}'
```

Applies live — no restart needed, the next idle/unmanaged transition picks
it up.

---

## RTSP playback

**On the master**, RTSP just works — `/api/play` with an `rtsp://` source,
no lockout. The master declares `unmanaged` state while doing this (see
Screensaver above for what that triggers on remotes).

**On a remote**, playback endpoints are locked by default (`409`) since the
chase loop owns mpv there. To play RTSP directly on a remote (e.g. every
device showing the same live feed), add `override: true`:

```bash
curl -X POST http://mpv-remote.local:5000/api/play -H "Content-Type: application/json" -d '{"source": "rtsp://192.168.0.104:554/stream", "override": true}'
curl -X POST http://mpv-remote.local:5000/api/stop -H "Content-Type: application/json" -d '{"override": true}'
```

**Important caveat**: `override: true` bypasses the lockout for that one
call — it does **not** pause the remote's background sync listener. In
practice this is safe as long as the master's own declared state doesn't
change while the remote is in manual mode (the listener only reacts to an
actual change, so if the master just stays put, nothing interrupts the
override). If the master's state *does* change for any reason while a
remote is mid-override, that remote will get pulled back to whatever the
master just declared. This is a deliberate "maintenance escape hatch," not
a fully robust manual-control mode — treat it accordingly for anything
beyond bench testing, or ask for the more robust persistent-manual-mode
version if this becomes a regular part of your workflow.

**Stream watchdog**: `stream_watchdog.py` monitors for a frozen/stalled
RTSP feed and auto-restarts it — its restart calls now correctly include
`override: true`, so it can recover a manually-forced remote stream too
(this was a real gap, fixed).

**Testing without a real camera**: an iPhone running an RTSP-server app
(e.g. OctoStream RTSP Streamer) on the same network works well — test the
resulting `rtsp://` URL in VLC first to confirm it's actually reachable
before pointing this player at it.

---

## Ticker overlay

A **second, fully independent persistent mpv instance** — not video
compositing, just a second X11 window positioned wherever you want (a
bottom strip by default, `1920x100` at `y=980`). Always muted. Never part
of the sync protocol — it's a per-device, directly-commanded feature, the
same as the RTSP override workflow.

```bash
# Just the ticker
curl -X POST http://<device-ip>:5000/api/ticker/play -H "Content-Type: application/json" -d '{"source": "ticker.mp4", "loop": true}'
curl -X POST http://<device-ip>:5000/api/ticker/stop
curl -X POST http://<device-ip>:5000/api/ticker/geometry -H "Content-Type: application/json" -d '{"x": 0, "y": 900, "width": 1920, "height": 150}'

# Main content + ticker in one call (the Node-RED-button use case)
curl -X POST http://<device-ip>:5000/api/play-with-ticker -H "Content-Type: application/json" -d '{
  "source": "rtsp://192.168.0.104:554/stream",
  "ticker_source": "ticker.mp4",
  "override": true
}'
```
(`override` only matters for the main-content half, on a remote — same
rule as plain RTSP playback above; the ticker endpoints are never locked.)

**Dashboard**: Ticker Overlay panel — file picker, Play/Stop, X/Y/W/H +
Apply.

**Cost**: real testing showed running the ticker alongside main content
adds meaningful load (~24% CPU just in Xorg's own window compositing, on
top of both videos' decode cost) but did **not** measurably hurt the main
content's sync accuracy on a CM4 with headroom to spare. See
[Hardware notes](#hardware-notes) for the numbers, and
[Troubleshooting](#troubleshooting) for how to check this yourself under
your own load.

---

## Node-RED integration patterns

All of these are plain HTTP requests — an `http request` node with method
`POST`, the URL below, and a JSON body is all you need.

**Play synced content from the master** (drives every remote too):
```
POST http://mpv-master.local:5000/api/play
{"source": "bout3.mp4", "loop": true, "volume": 50}
```

**Pause / resume** (same endpoint, toggles based on current state):
```
POST http://mpv-master.local:5000/api/pause
```

**RTSP on a specific remote**:
```
POST http://cm4-stage-left.local:5000/api/play
{"source": "rtsp://192.168.0.104:554/stream", "override": true}
```

**RTSP + ticker on a remote, one button**:
```
POST http://cm4-stage-left.local:5000/api/play-with-ticker
{"source": "rtsp://192.168.0.104:554/stream", "ticker_source": "ticker.mp4", "override": true}
```

**Health check before/after a cue** (useful as a status node feeding a
dashboard indicator):
```
GET http://mpv-master.local:5000/api/sync/status
```

---

## Troubleshooting

**Dashboard unreachable after a reboot, but was fine before**: almost
always the DRI-card enumeration shifting between boots (which physical
`/dev/dri/cardN` drives the display isn't guaranteed stable). Fixed to be
self-healing (`detect-dri-card.sh` re-runs on every X11 start), but if you
ever see `sudo systemctl status x11-server` showing repeated restarts with
`(EE) no screens found` in the journal, that's this class of issue:
```bash
sudo journalctl -u x11-server -n 50 --no-pager
ls /sys/class/drm/ | grep HDMI
cat /etc/X11/xorg.conf.d/20-modesetting.conf
```

**Video plays (confirmed via `/api/status`) but the physical screen shows
nothing**: almost certainly the dual-HDMI-port issue — see
[HDMI output selection](#hdmi-output-selection). Check which port your
cable is actually in and try the other option in the dashboard.

**Visible sync jitter that wasn't there before**, especially after
resizing to a small window (corner-pip, etc.): likely CPU headroom, not a
bug. Compare `ps -eo pid,%cpu,%mem,comm | grep mpv` and
`ps -eo pid,%cpu,%mem,comm --sort=-%cpu | head -10` before/after the
change — a real jump (especially in `Xorg`) confirms it. See
[Hardware notes](#hardware-notes) for what "normal" looks like.

**A remote's pause/resume feels laggy or drifts noticeably right after
resuming**: this was a real bug (late scheduled release on slow storage),
fixed — make sure you're on a version that includes it (`git log` for
"remote scheduled release was late"). If it's still happening, check
whether that remote is on SD card storage and consider eMMC/SSD.

**General service diagnostics**:
```bash
sudo systemctl status x11-server video-player
tail -f /opt/rpi-video-player/logs/app.log
tail -f /opt/rpi-video-player/logs/error.log
```

---

## Known limitations

Honest gaps, not yet built:

- **No dashboard toggle for `sync.role`** — config file + service restart
  only (see [Setting the sync role](#setting-the-sync-role))
- **Freewheel resilience is partial.** If the master disappears, remotes
  *do* keep playing correctly from the last known origin (this falls out
  naturally from the declarative design — no special code needed for the
  playback continuity itself), and `master_seen: false` correctly shows up
  in `/api/sync/status` — but there's no prominent dashboard warning banner
  for this yet, so you'd need to actively check the API to notice a master
  has gone quiet.
- **Remote power-pull recovery and other Phase 5 hardening scenarios**
  (DESIGN.md's T8-T11, T13-T14, T16) haven't been explicitly tested yet.
- **The RTSP `override` flag is a one-shot bypass**, not a persistent
  "manual mode" — see the caveat in [RTSP playback](#rtsp-playback).
- **HDMI port and audio device selectors are independent** — no
  auto-linking between them (set both once, not an ongoing burden, but
  worth knowing).
