# Phase 4 — Scheduled transitions + synced screensaver (DESIGN.md §6.3, §6.4, §12 phase 4)

## Why

Real-hardware testing of Phase 3 showed noticeable drift right after
pause/resume (settling to ~0.5 frame over a second or so) — the same
catch-up behavior seen at initial join. Expected: Phase 3 applies a new
declared state immediately and lets the 5Hz chase loop converge
afterward. This phase closes that gap per DESIGN.md §6.3 — prime every
device paused at the right position, then release them all at the same
pre-agreed wall-clock instant, so there's no catch-up period at all.

## Architectural shift

Phase 2/3's `SyncMaster` is purely reactive — `_tick()` polls
`player.get_status()` at 10Hz and infers transitions after the fact.
Scheduled transitions need the master to proactively orchestrate: prime
-> broadcast a future `t0` -> wait -> release. `video_controller.py`'s
five playback endpoints (`/api/play`, `/api/pause`, `/api/stop`,
`/api/seek`, `/api/seek-relative`) now route through new `SyncMaster`
methods when `role: master`, instead of calling `VideoPlayer` directly.
`role: off` is completely unaffected — the `else` branch at each endpoint
is byte-for-byte what existed before this phase.

## Files changed

- `src/sync_master.py`:
  - Renamed the lifecycle-teardown `stop()` to `shutdown()` — freed up
    `stop()` for the new DESIGN.md §6.3 playback-stop method. No
    committed code called the old `stop()`, so this was a safe rename.
  - New orchestration methods: `play()`, `resume()` (scheduled — prime,
    broadcast future `t0`, sleep, release), `pause()`, `stop()`, `seek()`,
    `seek_relative()` (all immediate, per design — operator expects
    instant response for these).
  - `_scheduled_pending` flag: while `play()`/`resume()` is between
    priming and releasing, `_tick()` skips its reactive poll (which would
    otherwise see the player "paused" mid-preroll and stomp the pending
    future-`t0` packet) and just re-sends the last packet unchanged.
    Steady-state reactive polling (drift, loop wraps) is otherwise
    untouched — still the same mechanism the overnight soak validated.
  - `_build_packet()` helper, factored out of the duplicated
    packet-construction that used to live only in `_tick()`.
  - Screensaver auto-trigger (§6.4): `_schedule_screensaver_check()` /
    `_maybe_start_screensaver()`, called from `stop()`, from `_tick()`
    when it reactively detects an unexpected idle transition (mpv dying,
    etc. — self-healing), and once at `start()` if already idle at boot.
    Reuses `play()` directly, so an auto-started screensaver gets the
    same scheduled/frame-exact start as any operator content.
- `src/sync_remote.py`:
  - `_handle_transition()` now branches on whether a "playing" packet's
    `t0` is in the future (schedule: prime now, `threading.Timer` release
    at `t0`) or the past (late join / was offline — unchanged Phase 3
    immediate-join + chase behavior). `threading.Timer` was used instead
    of the 5Hz chase loop's own cadence specifically because 200ms of
    scheduling-resolution jitter would defeat the point of scheduling.
  - Idempotency reuses the existing `_applied_state`/`_applied_file`
    equality check for the general case, plus one narrow addition: while
    genuinely primed-and-waiting (`_pending_release_t0 is not None`), a
    packet with a *different* `t0` for the same state/file (rapid
    play->stop->play before the original fired) re-triggers
    `_handle_transition()`, which cancels the old timer first. Steady-
    state `t0` changes (loop wraps, drift re-anchors) never reach this
    check — `_pending_release_t0` is back to `None` by then, and those
    are handled by `_converge()`'s existing hard-seek, not re-priming.
  - Split `idle`/`unmanaged` handling (previously identical — both just
    stopped). `unmanaged` (RTSP on master, §6.1 decision 4): if the
    remote's own `screensaver` config is enabled and the file exists
    locally, plays it immediately, looping, **unsynced** — `_converge()`
    is naturally skipped because `_applied_state` is `"unmanaged"`, not
    `"playing"` (no separate flag needed — the existing gate already
    covers it). `idle` stays plain black — the master handles
    idle->screensaver entirely itself (§6.4) by declaring normal
    "playing" state, which remotes chase like any other file.
- `src/video_controller.py`: each of the five endpoints gained an
  `if sync_master: ... else: player.X()` branch. `/api/pause` decides
  `sync_master.pause()` vs `sync_master.resume()` based on
  `player.state["status"]` *before* the call, since the single
  `VideoPlayer.pause()` toggle became two distinct methods on the sync
  side (immediate vs. scheduled).

No changes needed to `video_player.py` (`_prime`/`_release`/`play`/`seek`
were already built for exactly this reuse — see PHASE1-NOTES.md), to
`sync_config.py` (the `screensaver` config block already existed from
Phase 2), or to the dashboard (the sync status panel already shows
`chase.err_ms` etc.; added `pending_release_t0` to the chase status block
for visibility, no UI change needed).

## Verified locally (macOS dev box, real persistent-mpv instances, same setup as Phase 3)

- **Scheduled play**: direct position query *immediately* after release
  showed **0.00ms** difference between master and remote — the actual fix
  being verified. A real settling transient (~150ms, shrinking to ~7ms by
  t=12s) still appears in the following few seconds — see caveat below.
- **Pause -> resume**: frame-matched pause (small ~29ms residual, expected
  since the earlier play's settling transient hadn't fully finished when
  pause fired); resume showed the same clean **0.00ms** diff at its
  release instant as fresh play.
- **Seek during playback**: hard-seek convergence unchanged from Phase 3
  — converged to a stable ~22ms within 1s and held steady.
- **Late join**: started a remote's `SyncRemote` 3s *after* the master
  was already playing — correctly fell back to immediate join + chase
  convergence (confirmed via the `"Loading:"` log line, not a scheduled
  prime), no hang waiting for a `t0` already in the past.
- **Screensaver**: idle at boot with `screensaver.enabled` -> auto-played
  after the ~3s delay; operator `play()` preempted it immediately (no
  special-casing needed — a new `play()` call always overwrites); `stop()`
  brought it back after the same delay. All transitions used the same
  scheduled path as any operator content.
- **`unmanaged`**: master "playing" a bogus `rtsp://` source correctly
  declared `unmanaged`; remote correctly played its own local screensaver
  file (confirmed via `source` in its status) with `err_ms` staying `None`
  throughout — confirms `_converge()` is never invoked for it.
- **Flask API layer**: `/api/play` through the real `video_controller.py`
  app (not just direct object calls) correctly blocked for the lead time
  and returned with `position: 0.0000` — confirms the routing, not just
  the underlying `SyncMaster` methods, works end-to-end.
- **Phase 1/2/3 regression**: `role: off` — full play/pause/resume/seek/
  seek-relative/stop cycle identical to pre-Phase-4 behavior (the `else`
  branches were exercised, not skipped).

## A real test-harness mistake, twice

Repeated the same class of mistake from Phase 3 testing: constructing a
second `VideoPlayer` on the shared default socket path (`/tmp/mpvsocket-
player`) *after* another instance already claimed it, which silently
breaks the first instance's IPC (removes its socket file out from under
it, launches a competing mpv on the same path). Hit this specifically in
the late-join test, where the master starts playing *first* and the
remote's player is constructed later — the "relocate remote's socket
before constructing the thing that claims the default path" rule from
Phase 3 needs to be applied regardless of which script shape a given test
has, not just the ones where remote happens to be constructed first.
Purely a local dev-harness issue; separate physical Pis never hit this.

## A real bug found on real hardware, fixed post-merge

Real-hardware testing (`pause` → wait → `resume`, 3 cycles) showed a
consistent ~300ms error right after resume, decreasing at the expected
~20ms/s nudge rate but taking 10+ seconds to settle — much worse than the
near-0ms release-instant result from local Mac testing. Root cause:
`sync_remote.py`'s scheduled-release branch captured `now` *before*
calling `player._prime()` (which blocks and can take real, variable time
— worse on real storage/lower-RAM devices than a dev-machine SSD) but
didn't start the `threading.Timer` until *after* priming completed.
Since `Timer(delay, fn).start()` counts `delay` seconds from the moment
`.start()` is called, the stale `now` meant every release fired at
`t0 + <priming duration>` instead of at `t0` — silently late by exactly
how long priming took, which real hardware apparently does non-trivially
often. `sync_master.py`'s own `play()`/`resume()` never had this bug
(`t0` is computed *after* priming there), which is why local testing
against a fast SSD didn't surface it clearly.

Fixed by recomputing `now` fresh immediately before constructing the
`Timer`, and — since resume is the case this bites hardest and most
often — added the same "skip re-priming if already correctly paused"
optimization the master's `resume()` already had, so the common
pause→resume cycle doesn't re-load the file at all and has the full lead
time available for the timer to actually hit.

Re-verified locally: the same pause/resume-3x test that showed ~300ms/
10+s-to-settle on real hardware now shows ~25-35ms immediately after
release and ~16-18ms settled within 4-5s, consistently across 3 cycles —
this should be re-run on the actual Pi's to confirm it closes the gap
there too, since that's the environment that surfaced the bug in the
first place.

## Not yet verified — needs real hardware

- **True scheduled-start precision on separate physical devices.** The
  ~150ms transient observed locally (shrinking to ~7ms over several
  seconds) is very plausibly this Mac's two-mpv-instances-on-one-CPU
  contention plus a genuine decoder-unpause warmup artifact — neither of
  which applies when master and remote are separate machines. The actual
  claim being made — release happens at the *same instant* on both
  devices — is proven by the 0.00ms direct-position-query result, but
  whether real hardware shows a similarly small settling transient
  afterward, or none at all, needs a real overnight-soak-style re-test
  like the one that validated Phase 3's T4.
- T5–T7, T12, T15 formal test-plan rows — informally covered by the above
  but not run down against their exact stated pass criteria on real
  devices yet.
