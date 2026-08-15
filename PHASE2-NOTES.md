# Phase 2 — Clock + skeleton (DESIGN.md §5, §6.1, §6.2, §12 phase 2)

## Files added

- `chrony-setup.sh` — provisioning script: master serves LAN time, remotes
  sync to it. Not part of the systemd install (`install.sh` is untouched);
  run once per device during provisioning, per DESIGN.md §10.
- `src/sync_config.py` — `SyncConfig`: loads/saves the `sync` block
  (DESIGN.md §3) as `/opt/rpi-video-player/config/sync.json`. Missing file
  or invalid `role` falls back to `role: "off"` — the safe, additive default.
- `src/chrony_status.py` — `get_chrony_offset_ms()`: parses `chronyc
  tracking`, returns `(None, None)` when chrony isn't installed/running
  instead of raising (dev machines, or before `chrony-setup.sh` has run).
- `src/sync_master.py` — `SyncMaster`: broadcasts the declared state packet
  (DESIGN.md §6.1) over UDP at 10 Hz and listens for remote heartbeats
  (§6.2). Runs only when `role: "master"`.
- `src/sync_remote.py` — `SyncRemote`: receives the master's broadcasts,
  tracks packet/seq stats, and sends 1 Hz heartbeats back to the source
  address of the last packet received — no master address needs
  configuring up front. Runs only when `role: "remote"`.

## Files changed

- `src/video_controller.py` — imports and starts `SyncMaster`/`SyncRemote`
  based on `sync_config.data["role"]` right after the player/presets are
  initialized; adds `GET /api/sync/status`. `role: "off"` opens no sockets
  and changes no other behavior — Phase 1 endpoints are untouched.
- `API.md` — documents `GET /api/sync/status` for all three roles.

## What's deliberately NOT in this phase

Per DESIGN.md §12, phase 2 is chrony + config schema + raw packet
send/receive + status visibility only:

- No chase loop yet (`sync_remote` receives and reports; it does not drive
  local mpv playback against the declared state — that's phase 3).
- No scheduled transitions (§6.3) or synced screensaver (§6.4) — phase 4.
  `sync_master`'s declared origin (`t0`/`pos0`) is derived by polling
  `player.get_status()` at 10 Hz and detecting play/pause/stop/seek
  transitions, not by explicit scheduling hooks. The wire format and
  broadcast loop won't need to change when phase 4 adds real scheduling.
- No remote API lockout (§3 decision 3) or freewheel handling (§8) — those
  land with the phases that need them (4 and 5 respectively).
- No `/api/sync/config` write endpoint — role changes are made by editing
  `config/sync.json` and restarting the service, same as today's `role`
  read at startup. Read/write via the dashboard can follow in a later phase.

## Verified locally (macOS dev box, real `mpv`, no chrony/no LAN)

- `SyncConfig`: defaults to `role: "off"`, round-trips through
  `update()`/`save()`/`load()`, rejects invalid roles.
- `SyncMaster` + `SyncRemote` over loopback UDP: master broadcasts real
  packets driven by an actual persistent-mpv playback session; remote
  receives them, resolves the master's address from the packet source,
  and heartbeats back; master's `/api/sync/status` shows the remote,
  `last_seen_ago_s`, and `offline` correctly.
- `chrony_status.get_chrony_offset_ms()` returns `(None, None)` cleanly
  with no chrony installed (`chrony.available: false` in status output) —
  confirms the master/remote status calls never crash the dashboard
  when clock health is unknown.
- Phase 1 regression with `role: "off"`: `/api/play`, `/api/pause`
  (pause+resume), `/api/stop`, `/api/status` all behave identically to
  pre-sync — same persistent mpv PID throughout.

## Not yet verified (needs real Pi hardware — T1)

- `chrony-setup.sh` on an actual Pi 5 master + CM4 remote over wired
  Ethernet: `allow <subnet>` reachability, `confdir` drop-in behavior on
  Raspberry Pi OS's shipped chrony package, and the T1 pass criteria
  (`chronyc tracking` offset < 1 ms sustained on both devices).
- UDP broadcast (`255.255.255.255` default) on real Pi NICs/switches —
  loopback testing here used unicast/loopback-broadcast workarounds since
  macOS doesn't route `255.255.255.255` the way a Linux LAN NIC does.
