# Phase 1 — Persistent mpv (DESIGN.md §4, §12 phase 1)

## Files changed

- `src/video_player.py` — full replacement
- `src/stream_watchdog.py` — one function (`is_mpv_running`)
- `src/video_controller.py` — **unchanged** (public interface preserved)

## What changed

One long-lived mpv process per player, started with the service:

- `play` = IPC `loadfile` (fast, low-variance) instead of process spawn
- `stop` = IPC `stop`; the instance stays up, window stays black
- Load path is split into `_prime()` (load paused, wait decoded, seek —
  first frame displayed, clock stopped) and `_release()` (unpause). Phase 3/4
  sync reuses `_prime()` and schedules `_release()` at a wall-clock instant.
- RTSP/HTTP streams load un-paused (live content can't preroll); watchdog
  freeze detection unchanged.
- Geometry change still restarts the instance (X11 `--geometry` is a launch
  arg) and restores playback at position — but **only when geometry actually
  changed**: api_play applies the default preset on every play, and with a
  persistent instance an unconditional restart would flash the window.
- Crash resilience: `get_status()` detects a dead instance (crash or watchdog
  `pkill`) and reports `stopped`; the next `play()` relaunches automatically.
- Loop and volume are applied per-load via IPC properties (version-proof:
  avoids the mpv `loadfile` options-argument reshuffle between releases).
- Demuxer cache is tunable: `RPI_PLAYER_CACHE_MB` env var (default 50).
  Set `Environment=RPI_PLAYER_CACHE_MB=20` in the player service on the
  1 GB Pi 4.
- Watchdog: `is_mpv_running` now matches the IPC socket argument instead of
  `mpv.*rtsp://` (the source no longer appears in mpv's command line).

## Verified in container (fake-mpv IPC harness)

play/pause/resume/seek/seek-relative/volume; stop keeps process; replay on
same instance; unchanged geometry = no restart; changed geometry = restart
with playback restored; crash detection + auto-recovery on next play;
missing file still raises 404-path error.

## T2 regression on the Pi 5 (must pass before Phase 2)

Every row exercised through the real dashboard + curl, sync absent:

1. Boot: black screen, one mpv process running (`pgrep -af mpv`)
2. `/api/play` file: starts within ~1s, plays fullscreen
3. Pause -> freeze frame; pause again -> resumes in place
4. `/api/seek`, `/api/seek-relative` both directions
5. `/api/volume` audible change
6. `/api/stop` -> black screen; `pgrep` shows the SAME mpv PID still up
7. Play again -> same PID (no respawn)
8. Geometry drag/resize in dashboard while playing -> window moves,
   playback resumes at position (brief restart is expected)
9. Play with a default preset set -> no window flash (unchanged-geometry
   no-op)
10. Presets save/load; upload; `/api/status` fields identical in shape
11. RTSP stream plays; pull the stream source; watchdog restarts it
    (watch `/opt/rpi-video-player/logs/watchdog.log`)
12. `pkill -9 mpv` mid-playback -> status shows stopped; next play recovers
13. Reboot -> service comes up clean, black screen, instance running

Pass = behaviour indistinguishable from `main` on rows 2–5, 10–11, and the
new persistent-instance behaviours on 1, 6–9, 12–13.
