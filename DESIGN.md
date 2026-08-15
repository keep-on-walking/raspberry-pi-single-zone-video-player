# Multisync Design Document
## raspberry-pi-single-zone-video-player — `multisync` branch

**Status:** v2 — AGREED BUILD CONTRACT. All open decisions resolved (§12).
No code exists yet; Phase 1 starts on the `multisync` branch.

---

## 1. Goal

Multiple Pis play video in frame-near sync, where **each device plays its own
local file**. Files are identical in duration and may be identically named, but
the content differs per device (multi-angle / multi-screen). All existing player
features are preserved on every device: freeze-frame pause/resume, skip
forward/backward, absolute seek, start/stop, volume, resizable output, presets,
dashboard, RTSP.

### Non-goals (v1)

- Sub-frame / genlock-grade sync (target is ±1–2 frames; see §7)
- Syncing RTSP streams (explicitly excluded — streams bypass sync)
- Synced playlists (v1 syncs a single file, optionally looping; playlists remain
  a single-player feature)
- Internet/WAN sync (LAN only, trusted network)
- Mixed-version protocol compatibility (all devices run the same release; the
  packet carries a version field so this can change later)

### Design principles

1. **Additive.** Sync is a new module plus a config flag. `role: "off"` (the
   default) behaves byte-for-byte like today's player. Existing deployments are
   untouched by merging this branch.
2. **Declarative, not command-based.** The master broadcasts *desired state*
   ("file X, playing, position origin T0"), never one-shot commands. Remotes
   continuously converge on the declared state. Missed packets, late joins,
   reboots, and network blips all self-heal by the same mechanism — there is no
   separate recovery logic to get wrong.
3. **Content-agnostic.** The protocol carries a filename and a position, never
   content. Different-video-per-device costs nothing.

---

## 2. Architecture overview

```
                 ┌────────────────────────────────────────┐
                 │ MASTER (Pi 5)                          │
                 │  Flask API ──> sync_master module      │
                 │       │              │                 │
                 │  mpv (persistent) <──┘                 │
                 │       │        UDP state broadcast     │
                 └───────┼──────────────┬─────────────────┘
                         │              │ 10 Hz, port 5005
                 HDMI out│      ┌───────┴───────┬─ ─ ─ ─ ─┐
                         │      ▼               ▼         ▼
                 ┌───────┴──────────┐  ┌────────────────┐
                 │ REMOTE (CM4)     │  │ REMOTE (Pi …)  │  …
                 │  sync_remote     │  │                │
                 │   chase loop     │  │                │
                 │   │              │  │                │
                 │  mpv (persistent)│  │                │
                 │       heartbeat ─┼──┼─> master :5006 │
                 └──────────────────┘  └────────────────┘
```

Components:

- **sync_master** — owns the declared state; broadcasts it over UDP at 10 Hz;
  receives remote heartbeats for the dashboard. Runs only when `role: "master"`.
- **sync_remote** — listens for state packets; runs the chase loop against the
  local mpv. Runs only when `role: "remote"`.
- **Persistent mpv** (both roles, and role `off`) — refactor of the current
  spawn-per-play model; prerequisite for accurate synced starts. See §4.
- **chrony** — system-level wall-clock agreement. See §5.

---

## 3. Configuration

Added to the existing config (survives reboots, editable via dashboard later):

```json
"sync": {
    "role": "off",                  // "off" | "master" | "remote"
    "state_port": 5005,             // master -> remotes (UDP broadcast)
    "heartbeat_port": 5006,         // remotes -> master (UDP unicast)
    "broadcast_addr": "255.255.255.255",   // subnet-directed addr for managed networks
    "start_lead_ms": 800,           // scheduled-start lead time
    "deadband_ms": 25,              // |error| below this: no correction
    "nudge_speed": 0.02,            // chase speed = 1 ± this
    "hard_seek_ms": 1000,           // |error| above this: seek instead of nudge
    "remote_audio": false,          // remotes always muted (decision 2)
    "duration_tolerance_s": 0.5,    // warn if local file duration differs more
    "screensaver": {
        "enabled": false,
        "file": "screensaver.mp4",  // same basename deployed on every device
        "loop": true
    }
},
"audio": {
    "device": "auto"                // mpv audio device name; master only
}
```

Notes:

- Geometry, presets, and volume remain **per-device** — every screen keeps its
  own layout. Sync never touches geometry.
- **Audio (decision 2):** only the master outputs audio; remotes launch mpv
  muted (`--no-audio`). The master's output device is configurable via
  `audio.device`, populated from mpv's own device list (`GET
  /api/audio/devices`, backed by IPC `audio-device-list`) — this covers HDMI0 /
  HDMI1 / analog headphone jack / USB audio uniformly. Hardware note: the
  **Pi 5 has no analog headphone jack** (the Pi 4 and most CM4 carriers do), so
  a Pi 5 master needing analog out requires a USB audio dongle or audio HAT —
  which the device-selector approach supports without code changes.
- **Remote lockout (decision 3):** when `role: "remote"`, direct playback API
  calls (`/api/play`, `/api/pause`, `/api/seek`…) return `409 Conflict`.
  Geometry and preset endpoints stay live (per-screen layout is a local
  concern). A `"override": true` request flag is retained as a
  maintenance-only escape hatch (bench testing a remote without reconfiguring
  its role); it is deliberately undocumented in the dashboard UI.

---

## 4. Persistent-mpv refactor (prerequisite, benefits all roles)

Today: each `play()` spawns a fresh mpv process; `stop()` kills it; geometry
changes restart it. Process startup time is variable (hundreds of ms), which is
fatal for synced starts.

Change to: **one long-lived mpv process** per player, started with the service:

- Launched at service start with `--idle=yes --force-window=yes` and the
  current geometry; shows a black window (or nothing) when idle.
- `play` becomes IPC `loadfile` (fast, low-variance).
- `stop` becomes IPC `playlist-remove current` / `stop` (process stays up).
- The watchdog watches the one process; if mpv dies it is restarted and the
  current state re-applied.
- Geometry change still requires an mpv restart under X11/`--vo=xv`
  (`--geometry` is a launch argument). In sync mode a remote that restarts for
  a geometry change simply re-converges via the chase loop within ~1s. A future
  improvement (out of scope v1): live resize via `video-margin-ratio-*`
  properties without restart.

**Synced start pattern** (the reason this refactor exists):

1. `loadfile <file>` with `pause=yes`
2. seek to the required start position (exact)
3. wait for `playback-restart` / file loaded event — decoder is now prerolled,
   first frame displayed, clock not running
4. at wall-clock T0 (agreed start time): `set pause false`

Steps 1–3 absorb all the variable latency; step 4 is a single IPC write, so the
start error is dominated only by IPC scheduling jitter (single-digit ms).

---

## 5. Time base

- **chrony on every device.** The master runs chrony as an NTP server for the
  venue LAN (`allow` the subnet); remotes sync to the master. This works with
  no internet access, and internet NTP (when present) only improves the
  master's absolute time, which sync doesn't depend on — only *agreement*
  matters.
- Wired Ethernet for all sync devices. chrony on a quiet wired LAN agrees to
  well under 1 ms — negligible against a 40 ms frame.
- Health visibility: `/api/sync/status` includes each device's
  `chronyc tracking` offset; the dashboard flags any device above ~5 ms.
  Remotes include their chrony offset in heartbeats.

---

## 6. Protocol

### 6.1 State packet — master → remotes

UDP broadcast, port `state_port`, 10 Hz, JSON (tiny at this rate; debuggable
with tcpdump). One packet type; remotes converge on whatever it declares.

```json
{
    "v": 1,                      // protocol version
    "seq": 4711,                 // monotonic, detects stale/duplicate packets
    "state": "playing",          // "playing" | "paused" | "idle" | "unmanaged"
    "file": "bout3.mp4",         // basename only — remotes resolve locally
    "t0": 1786543210.123456,     // wall-clock origin (unix seconds, float)
    "pos0": 0.0,                 // media position at t0 (seconds, float)
    "speed": 1.0,                // master's nominal speed (normally 1.0)
    "loop": true,
    "duration": 312.480          // master's file duration (for wrap + checks)
}
```

Expected position on any device at wall-clock `now`:

```
expected(now) = pos0 + (now - t0) * speed          // state == "playing"
expected(now) = pos0                               // state == "paused"
if loop: expected = expected mod duration
```

Key property: `t0`/`pos0` change **only** when the master starts, seeks,
pauses, resumes, or loops — not every packet. Remotes therefore compute
position from the origin pair and their own (chrony-agreed) clock, which makes
the scheme immune to packet loss and jitter: a remote that misses 20 packets
still knows exactly where it should be.

States:

- `playing` / `paused` — as above. Frame-matched pause: on entering `paused`,
  a remote pauses mpv and then seeks (exact) to `pos0`; mpv displays that
  frame. Every screen freezes on the matched frame of its own content.
- `idle` — nothing should play; remotes stop/blank.
- `unmanaged` — master is doing something sync doesn't cover (RTSP stream, or
  a playlist in v1). Remotes with a screensaver configured play it locally
  (looping, unsynced — ambient content doesn't need sync); otherwise they show
  black (decision 4).

File resolution on remotes: by basename against the local media directory. If
the file is missing, the remote reports `error: "missing-file"` in its
heartbeat and stays idle — it never guesses. If local duration differs from the
packet's by more than `duration_tolerance_s`, it plays anyway but reports
`warning: "duration-mismatch"` (looping content with mismatched durations will
visibly diverge at the wrap; the dashboard makes this loud).

### 6.2 Heartbeat — remote → master

UDP unicast to the master (source address of state packets), port
`heartbeat_port`, 1 Hz:

```json
{
    "v": 1,
    "id": "cm4-stage-left",       // device hostname
    "state": "playing",
    "file": "bout3-anglB.mp4",
    "pos": 154.32,
    "err_ms": -6.4,               // measured sync error at last check
    "chrony_ms": 0.3,             // local clock offset estimate
    "warnings": []
}
```

Master aggregates these into `/api/sync/status` — the venue-ops view: every
remote, its drift, its clock health, missing files, last-seen time. A remote
not heard from for 5 s is flagged offline.

### 6.3 Scheduled transitions

Every transition the master makes is scheduled `start_lead_ms` in the future
and broadcast before it happens, so master and remotes act at the same instant:

- **Play:** master prerolls (per §4), sets `t0 = now + lead`, `pos0 = start
  position`, broadcasts, then unpauses itself at `t0`. Remotes that receive any
  packet before `t0` preroll and unpause at `t0` — same instant, no chase
  needed. Remotes that were offline converge afterwards via the chase loop.
- **Pause:** master pauses immediately (operator expects instant response),
  reads its exact paused position, broadcasts `state=paused, pos0=that`.
  Remotes pause on receipt and frame-match by seeking to `pos0` while paused.
  Worst-case visual raggedness on the *transition* is one packet interval
  (~100 ms); the frozen result is frame-matched regardless.
- **Resume:** identical to play, with `pos0` = the paused position.
- **Seek / skip during playback:** master seeks itself, then re-broadcasts a
  new origin (`t0 = now`, `pos0 = new position`). Remotes see a large error and
  hard-seek to converge (sub-second raggedness on the transition; steady state
  returns immediately). Skip forward/backward are just seeks.
- **Stop:** broadcast `state=idle`; everyone stops.
- **Loop wrap:** no special handling — `mod duration` in the expected-position
  formula covers it, provided durations match (hence the tolerance warning).

### 6.4 Synced screensaver (decision 4)

When `screensaver.enabled` is set **on the master** and the master would
otherwise be idle (no operator-started content), the master automatically plays
`screensaver.file` looping. This needs **no new protocol**: it is simply
declared state like any other playback, so every remote holding an
identically-named file plays its own version in sync. Operator-started content
always preempts it; when that content stops, the screensaver resumes
automatically after a short delay. Remotes missing the file report
`missing-file` and idle, per the standard rule.

This replaces external state-monitoring (e.g. a Node-RED watch-and-trigger
flow) for the idle case entirely, and is the direct port of the fpp-splash
screensaver-playlist concept into the sync system — including its guarantees:
self-healing restart and no triggering while the player service itself is down.

---

## 7. Chase loop (remote drift correction)

Runs on each remote at 5 Hz while `state == "playing"`:

```
err = expected(now) - actual        // actual = mpv time-pos via IPC
|err| <  deadband_ms      -> speed = 1.0            (do nothing)
deadband_ms <= |err| < hard_seek_ms
                          -> speed = 1.0 + sign(err) * nudge_speed
                             (2% nudge: invisible on video; remotes are
                              muted by default so audio pitch is moot)
|err| >= hard_seek_ms     -> exact seek to expected(now + small lead),
                             then re-measure
```

- Correction rate at 2%: 20 ms of drift corrected per second of playback —
  more than enough against Pi clock drift, which is orders of magnitude
  smaller once chrony is running.
- The measured `err` includes IPC round-trip skew; at single-digit ms this
  lands inside the deadband by design.
- Expected steady-state accuracy: **±1–2 frames** on `--vo=xv` (no vsync
  discipline). Acceptance target for v1: |err| ≤ 50 ms sustained. If a future
  need demands tighter, the protocol is unchanged — only the video output
  path (gpu/DRM sync mode) would change.

---

## 8. Failure modes (all handled by convergence, listed for the test plan)

| Event | Behaviour |
|---|---|
| Remote misses packets / brief network blip | Position computed from last origin + own clock; drift-free through the outage; chase loop trues up on reconnect |
| Remote reboots mid-show | Service starts, receives next state packet, prerolls, hard-seeks into position; on-screen within a few seconds |
| Late join / new device added live | Same as reboot — declarative state needs no history |
| Master reboots | Remotes **freewheel**: keep playing from the last declared origin using their own clock (decision 5); dashboard shows a prominent "SYNC INACTIVE — master not seen" warning; when the master returns (in `idle` state, or restarting the screensaver) remotes converge on the new declaration |
| Master vanishes entirely | Same freewheel + warning; looping content keeps looping; drift is limited to clock drift only (small, and chrony holdover keeps it tiny short-term). Remotes keep listening and re-converge the moment broadcasts return |
| File missing on a remote | Remote idles + reports; never guesses a substitute |
| Duration mismatch | Plays + warns; visible divergence only at loop wrap |
| mpv crash on any device | Watchdog restarts it; remote re-converges; master re-establishes state and re-broadcasts origin |
| RTSP on master | `unmanaged` broadcast; remotes play local screensaver unsynced if configured, else black |

---

## 9. API additions

Master role:

- Existing `/api/play`, `/api/pause`, `/api/seek`, `/api/seek-relative`,
  `/api/stop` become sync-aware automatically (they drive the declared state) —
  **Node-RED flows and the dashboard need no changes to control a synced
  venue.**
- `GET /api/sync/status` — remotes, drift, clock health, warnings.

Remote role:

- Playback endpoints: `409` unless `override: true` (maintenance-only, undocumented in UI).
- `GET /api/sync/status` — own chase state, last master seen, error history.

All roles:

- `GET /api/sync/config`, `POST /api/sync/config` — role and tunables.

---

## 10. Device identification & provisioning

Every device gets a meaningful hostname at provisioning time via
`sudo raspi-config` → *System Options* → *Hostname* (e.g. `master-stage`,
`cm4-stage-left`) — no custom tooling needed. The system then uses the
hostname everywhere a device is identified: heartbeat `id`, `/api/sync/status`,
dashboard header, and log lines. With avahi (stock on Pi OS), each dashboard is
reachable as `http://<hostname>.local:5000`, so identifying and reaching any
player on a venue LAN needs no IP bookkeeping. The deployment guide gains a
provisioning checklist: flash → hostname via raspi-config → wire Ethernet →
install player → set `sync.role` → verify in master's sync status by name.

---

## 11. Test plan (run down in order; CM4 remote + Pi 5 master, wired LAN)

Test content: two 1080p files, identical duration, visibly different, each with
a burned-in timecode. Generate with:

```bash
ffmpeg -f lavfi -i "color=c=darkblue:s=1920x1080:r=25:d=300,\
drawtext=text='ANGLE A %{pts\:hms\:0}':fontsize=90:fontcolor=white:x=(w-tw)/2:y=(h-th)/2" \
-c:v libx264 -pix_fmt yuv420p angleA.mp4
# repeat with c=darkred / 'ANGLE B' -> angleB.mp4, deploy one per device
```

Frame comparison method: photograph both screens in one phone photo (or
side-by-side); the burned-in timecodes read the sync error directly.

| # | Test | Pass criteria |
|---|---|---|
| T1 | chrony: `chronyc tracking` both devices | offset < 1 ms sustained |
| T2 | Persistent-mpv regression, sync **off**: every existing API endpoint + dashboard + presets + RTSP + watchdog kill-test | identical behaviour to main branch |
| T3 | Synced start | timecodes within 2 frames |
| T4 | 30-min drift soak | \|err\| ≤ 50 ms throughout (heartbeat log) |
| T5 | Pause frame-match | frozen timecodes identical (±1 frame) |
| T6 | Resume | continues from pause point, T3 criteria |
| T7 | Seek + skip fwd/back during playback | converged < 2 s after transition |
| T8 | Remote power-pull mid-show, power back | on-screen and in sync < 15 s |
| T9 | Master reboot mid-show | remotes freewheel with dashboard warning; clean re-convergence when master returns |
| T10 | Ethernet pull on remote 30 s mid-show, replug | no visible drift during outage; converged on replug |
| T11 | Different-content, same filename | everything above holds |
| T12 | Loop wrap (short 30 s files, 10 wraps) | no accumulating offset |
| T13 | RTSP on master | remotes show screensaver (local, unsynced) or black; master plays normally |
| T14 | 1 GB CM4 headroom | no swap/OOM over T4 (demuxer cache 20M on CM4) |
| T15 | Synced screensaver: master idle -> screensaver on both; start content -> preempts; stop -> screensaver returns | all transitions automatic, in sync per T3 criteria |
| T16 | Master power-pull mid-show (freewheel) | remotes keep playing; dashboard warning appears < 10 s; re-converge < 15 s after master returns |

---

## 12. Build phases (each independently testable)

1. **Persistent mpv** — refactor, sync still absent; pass T2. *This lands value
   even if sync never ships: faster starts, cleaner stop, steadier watchdog.*
2. **Clock + skeleton** — chrony setup docs/scripts; config schema; packet
   send/receive with `/api/sync/status` showing raw packets; pass T1.
3. **Chase loop** — remote follows an already-playing master (no scheduled
   transitions yet); pass T3 (crudely), T4.
4. **Scheduled transitions + screensaver** — full §6.3 and §6.4; pass T3,
   T5–T7, T12, T15.
5. **Hardening** — failure modes incl. freewheel; pass T8–T11, T13–T14, T16.
   Merge to `main` with `role: "off"` default.

---

## 13. Resolved decisions (agreed)

1. **Transport:** UDP broadcast. (Config retains `broadcast_addr` so a
   subnet-directed address can be set on fussy managed networks without a code
   change.)
2. **Audio:** master only; output device configurable (HDMI / analog / USB) via
   the mpv device selector in §3. Remotes always muted.
3. **Remote API lockout:** yes — playback endpoints locked on remotes;
   undocumented maintenance override retained.
4. **Idle behaviour:** master-controlled **synced screensaver** built in
   (§6.4) — remotes with the identically-named file play it in sync; during
   `unmanaged` (RTSP) remotes play their screensaver locally unsynced, else
   black.
5. **Master lost:** remotes **continue playing** (freewheel on last declared
   origin — the declarative design gives this for free), with a prominent
   dashboard warning that sync playback is inactive; automatic re-convergence
   when the master returns.

Additional agreed requirement: hostname-based device identity, set via
`raspi-config` at provisioning, used across heartbeats/dashboard/status (§10).

---

*This document is now the build contract: Phase 1 starts on the `multisync`
branch and each phase gate is a test-plan row, not a judgement call.*
