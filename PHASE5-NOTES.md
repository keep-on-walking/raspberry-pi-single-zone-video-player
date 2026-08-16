# Phase 5 — Hardening (DESIGN.md §8, §12 phase 5)

## Why

DESIGN.md §12 phase 5 gates on the failure-mode test rows T8–T11,
T13–T14, T16 (§11) and on merging to `main` with `role: "off"` default.
Unlike phases 1–4, this phase is mostly a *verification* pass — §7's
declarative design was built from the start so freewheel-on-master-loss
and reconvergence "fall out for free" (§8) rather than needing new
state machinery. The audit below traced each failure-mode row against
the actual Phase 2–4 code to find what, if anything, was still missing
before those hardware tests can be run in good faith.

## Findings

**Already correct, no code change needed** (traced, not just assumed):

- **Freewheel (T9, T16).** `sync_remote.py`'s chase loop (`_chase_tick`
  → `_converge`) computes `expected` from the *last received* packet's
  `t0`/`pos0` extrapolated against the remote's own `time.time()` on
  every 5 Hz tick — it never gates on packet freshness. So a remote that
  stops hearing from the master keeps playing, still correcting drift
  against its own clock, exactly per §8's "declarative design gives this
  for free." Confirmed by reading `_chase_tick`/`_converge` end to end;
  there is no timeout that stops playback.
- **Reconvergence on master return (T9, T16).** A restarted master boots
  with fresh `declared = {"state": "idle", ...}` (`sync_master.py`
  `__init__`) and calls `_schedule_screensaver_check()` at `start()` if
  still idle — so remotes see a normal idle/screensaver transition and
  chase it like any other declared state, matching §8's "remotes
  converge on the new declaration" without special-casing a "master
  came back" event.
- **Remote reboot / late join (T8, T10).** `_handle_transition`'s
  late-join branch (`t0` already in the past) computes `expected` and
  does an immediate `player.play(..., seek_to=expected)`, then lets the
  5 Hz chase loop true up — this is the same path already exercised in
  Phase 4's local late-join test, and it's identical whether the remote
  was gone 3 seconds or 30.
- **`seq_gaps` across a master restart.** After a restart the master's
  `seq` resets to 0. The remote's gap check is `seq > self._last_seq +
  1`, which is false when the new (small) seq arrives after a large
  pre-restart one — so no bogus gap count, and `_last_seq` just
  re-anchors to the new sequence. `seq_gaps` is a diagnostic counter
  only (not read by any convergence logic), so this is correct as-is:
  a master-down event is already visible via `master_seen`/
  `last_packet_age_s`, and packet-loss-while-connected is what
  `seq_gaps` is actually for.
- **RTSP freeze recovery on a remote (T13-adjacent).** Already fixed in
  `5a700d2` (pre-Phase-5): `restart_stream()` in `stream_watchdog.py`
  now always sends `override: true`, which is a no-op everywhere except
  a sync remote, where it was previously silently rejected with 409.
  Re-read the fix and the surrounding lock (`video_controller.py`
  `sync_locked`) to confirm it's unconditionally safe, not just
  incidentally working.
- **`unmanaged` fallback safety.** `_handle_unmanaged` falling through to
  `player.stop()` when no local screensaver is configured only fires
  once per declared-state transition (gated by the same
  `_applied_state`/`_applied_file` equality check as every other
  transition) — no risk of a restart loop if RTSP flaps.
- **T14 (1 GB CM4 headroom).** Demuxer cache is already tunable per
  device via `RPI_PLAYER_CACHE_MB` (`video_player.py`); this is a
  hardware soak test, not a code gap.

**Fixed this phase:**

- **Dashboard warning latency (T16: "< 10 s").** The sync-status poll
  ran at 10 s (`dashboard.js` `startSyncPolling`), stacked on top of
  `MASTER_SEEN_TIMEOUT_S = 5s` in `sync_remote.py` — worst case up to
  15 s before a remote's dashboard reflected a lost master, which could
  outright fail T16's stated pass criterion. Dropped to 2 s, matching
  the existing main status poll cadence; worst case is now ~7 s.
- **Warning prominence (§13 decision 5: "a *prominent* dashboard
  warning").** The existing implementation only dimmed a small header
  indicator dot and changed a line of muted-color text in the
  `sync-panel` strip — easy to miss, not what "prominent" calls for.
  Added a dedicated `#sync-banner` element: full-width, `--danger`
  background, white bold text, the same `pulse` keyframe already used
  for `.status-playing`, reading exactly "SYNC INACTIVE — master not
  seen. Playing on local clock." It's shown only when `role === "remote"
  && !master_seen` and hidden in every other state (off, master, or a
  remote that's currently synced).

## Files changed

- `web/static/js/dashboard.js`: sync poll interval 10000ms → 2000ms;
  `updateSyncStatus()` now also toggles `#sync-banner` visibility.
- `web/templates/dashboard.html`: new `#sync-banner` element, hidden by
  default, placed above the existing `#sync-panel` strip.
- `web/static/css/dashboard.css`: new `.sync-banner` rule.

No Python changes — the audit found the backend already correct for
every failure mode in scope.

## Verified

- Traced every code path above by reading `sync_master.py`,
  `sync_remote.py`, `video_controller.py`'s sync-lock/override
  handling, and `stream_watchdog.py` line by line against DESIGN.md §8's
  failure-mode table and each relevant §11 test row.
- CSS/markup reviewed by eye against the existing, already-working
  `.sync-panel`/`.status-playing` rules it reuses (`var(--danger)`,
  the `pulse` keyframe, the same flexbox pattern) — no new patterns
  introduced.

## Not verified — needs real hardware

This phase's actual gate is the hardware test plan itself, none of
which can be run from here:

- T8 — remote power-pull mid-show, power back: on-screen and in sync
  in < 15 s.
- T9 — master reboot mid-show: freewheel + dashboard warning + clean
  re-convergence.
- T10 — ethernet pull on remote 30 s mid-show, replug: no visible
  drift during the outage, converged on replug.
- T11 — different content under the same filename on each device:
  confirm nothing above assumed identical files.
- T13 — RTSP on master: remotes show local screensaver or black,
  master unaffected.
- T14 — 1 GB CM4 headroom over a 30-min soak, no swap/OOM.
- T16 — master power-pull mid-show: dashboard warning inside 10 s
  (now plausible at ~7 s worst case, was up to 15 s before this
  phase's polling fix), reconverge within 15 s of the master
  returning.

Also not independently confirmed here: the *live* browser rendering of
the new banner (this dev environment's sandboxed browser tooling
blocks both local `file://` live rendering and arbitrary localhost
ports, and the Flask app's hardcoded port 5000 collides with macOS's
own AirPlay receiver) — reviewed thoroughly by eye and by reusing only
already-proven CSS rules/patterns, but a real render on an actual
device (or a local run with the port conflict worked around) is worth
doing before or during the hardware pass above.

Per DESIGN.md §12, phase 5 merges to `main` once T8–T11, T13–T14, T16
pass on real devices. `sync.json`'s default `role: "off"` already
satisfies the merge precondition — confirmed unchanged in
`sync_config.py`'s `DEFAULT_CONFIG`, not something this phase needed to
touch.
