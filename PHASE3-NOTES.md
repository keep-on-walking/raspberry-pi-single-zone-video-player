# Phase 3 — Chase loop (DESIGN.md §7, §12 phase 3)

## Files changed

- `src/video_player.py` — three additive changes, all off by default:
  - `VideoPlayer.__init__(..., mute=False)`: when `True`, bakes `--no-audio`
    into the persistent mpv launch command (DESIGN.md §3 decision 2, remotes
    are always muted). Launch-argument, not runtime-toggleable, same as
    geometry.
  - `seek(position, exact=False)`: `exact=True` uses `absolute+exact`
    (frame-accurate) instead of the default keyframe seek. The chase loop's
    hard-seek correction uses this; nothing else does, so default behavior
    is unchanged.
  - `set_speed(speed)`: new method, IPC `set_property speed`. Used only by
    the chase loop's nudge correction; not part of persisted player state.
- `src/sync_remote.py` — the chase loop itself (DESIGN.md §7):
  - `_chase_tick()` (5 Hz): detects a declared-state/file change and calls
    `_handle_transition()`; once a load is confirmed, calls `_converge()`
    every tick while `state == "playing"`.
  - `_handle_transition()`: applies a new declared state immediately via
    `VideoPlayer.play()` (playing) or `VideoPlayer._prime()` without
    releasing (paused, for frame-matching). No scheduled preroll yet
    (DESIGN.md §6.3 is phase 4) — this is the "pass T3 crudely" bar phase
    3 is held to. Resolves the file by basename against the remote's own
    `video_dir` (DESIGN.md §6.1); missing file -> `warnings:
    ["missing-file"]`, stays stopped, never guesses. Duration mismatch
    beyond `duration_tolerance_s` -> `warnings: ["duration-mismatch"]`,
    plays anyway.
  - `_converge()`: deadband -> nudge -> hard-seek exactly per §7, with
    loop-wrap-aware error wrapping (a difference near a loop boundary is
    wrapped into `[-duration/2, duration/2]` so it doesn't look like a
    huge error).
  - Heartbeats now report real `err_ms` and `warnings` (were placeholders
    in Phase 2).
  - `/api/sync/status` on a remote now includes a `chase` block:
    `applied_state`, `applied_file`, `err_ms`, `speed`, `warnings`.
- `src/video_controller.py`:
  - Reordered init so `sync_config` loads before `player` is constructed
    (mute needs to be known at launch-command build time).
  - `remote_mute = role == "remote" and not config.remote_audio` passed
    into `VideoPlayer(mute=...)`.
  - Remote API lockout (DESIGN.md §3 decision 3), now load-bearing: with
    the chase loop actually driving mpv autonomously on a remote, an
    operator's own `/api/play` etc. would otherwise fight it. All five —
    `/api/play`, `/api/pause`, `/api/stop`, `/api/seek`,
    `/api/seek-relative` — return `409` on a remote unless the request
    body carries `override: true` (the documented maintenance-only escape
    hatch). Geometry and preset endpoints are untouched, per design.

## A real bug found and fixed during local testing

Initial version set `_applied_state = "playing"` unconditionally at the
top of `_handle_transition()`, before knowing whether the load actually
succeeded. A missing file or a slow/failed `VideoPlayer.play()` left the
chase loop believing it should be converging anyway — it started nudging
and hard-seeking a player with nothing loaded. Fixed with a `_load_ok`
flag, set `True` only after a confirmed successful load; `_chase_tick()`
now gates `_converge()` on `applied_state == "playing" and _load_ok`.
Caught by deliberately testing a remote whose `video_dir` didn't have the
master's file — worth keeping that scenario in mind for the real-hardware
pass too (T3's file-missing edge case).

## Verified locally (macOS dev box, two real persistent-mpv instances over loopback UDP)

One dev-machine-only wrinkle surfaced and is **not** a Phase 3 bug: this
Mac's mpv build has no `xv` video output at all, so `--vo=xv` silently
produces no video on *either* instance — earlier phases "worked" only
because the audio stream was still decoding and driving `duration`/
`time-pos`. Muting the remote (correct, new this phase) removes that
only-working modality, so the full dual-instance dynamics test below was
run with `mute=False` on both sides to isolate the chase-loop math from
this environment quirk. `mute`'s command-line wiring was verified directly
(`_build_command()` includes `--no-audio` iff `mute=True`) instead. The
real Pi hardware has genuine `xv`/X11 support (confirmed via `xrandr` on
both boxes during Phase 2 verification), so this doesn't apply there.

With that isolated:

- **Join convergence**: remote joined an already-playing master within
  ~140ms, nudged (speed 1.02) down under the 25ms deadband by ~7s.
- **Hard-seek** (master seeks 30s forward): remote snapped to within
  ~17ms almost immediately — well inside T7's 2s convergence criterion.
- **Frame-matched pause**: master and remote landed on the identical
  position (`65.035`) — meets T5's pass criteria.
- **Resume**: remote correctly detected the transition and re-converged.
- **Stop**: remote correctly went idle/stopped.
- **Missing file**: remote stayed stopped, reported `missing-file` in its
  heartbeat, and the master's `/api/sync/status` showed it under that
  remote's `warnings` — no bogus seeks (see bug above).
- **Remote API lockout**: all five playback endpoints return `409` on a
  remote; geometry stays open; `override: true` bypasses correctly.
- **Phase 1/2 regression**: `role: off` — play/pause/resume/seek/
  seek-relative/volume/stop/status all identical to pre-sync behavior,
  `mute` defaults `False`, `/api/sync/status` returns `{"role": "off"}`.

## Verified on real hardware — CM4 master + CM4 remote, overnight soak

T4 (30-minute drift soak) formally passes, run far past its minimum:

- **~10.4 hours continuous**, zero UDP packet loss the entire time
  (`seq_gaps: 0` across 375,461 received state packets on the remote)
- **Sync error stable throughout**: `~7–20ms` / `~0.2–0.6` frames at
  `29.97fps` — under half a frame the whole run, no drift trend from
  start to finish, well inside the `|err| ≤ 50ms` target
- **~12 loop wraps** handled cleanly (master's `seq` went `3 -> 14` over
  the run; each wrap is the master re-anchoring its origin at the
  position discontinuity) — informal but real T12 coverage, on a 46-minute
  file rather than T12's specified short-file stress case
- **No crashes**: single long-lived mpv PID on each device the whole time,
  `--no-audio` genuinely active on the remote for the full run (confirmed
  real `mute=True` operation, not just the command-line unit test earlier)
- **Memory flat, zero swap** on both the 1GB master and 2GB remote across
  the full run — no leak

Also resolved two unrelated real-hardware issues found during this
session (not Phase 3 bugs, but blocking real-world use): a DRI-card
enumeration mismatch that broke X11 on reboot, and a dual-HDMI-port case
(Argon ONE V5) where the "other" physical port never had a forced mode —
both fixed with self-healing scripts re-applied on every X11 start (see
git log: "Fix: re-detect DRI card...", "Dashboard: persistent HDMI
output...").

## Not yet verified

- **T3's visual pass criteria** (photograph both screens' burned-in
  timecodes) — displays are currently disconnected from both devices for
  bench testing, so this is the one item genuinely blocked on hardware
  access rather than software. Sync-loop correctness itself is thoroughly
  confirmed via `/api/sync/status` numbers above; this would only confirm
  it *looks* right too.
- T8–T11, T13–T16 (Phase 5 hardening scenarios — freewheel, power-pull
  recovery, RTSP-on-master, etc.) — not yet exercised at all.
