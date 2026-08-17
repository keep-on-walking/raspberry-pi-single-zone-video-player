# Playback tearing/rippling investigation (2026-08-16)

## RESOLVED

Turned out to be **two independent, compounding bugs**, both of which
had to be fixed - fixing only one still tears:

1. **A real mpv regression between `0.38.0` and `0.40.0`** affecting
   `--vo=gpu`/`gpu-next` specifically (see "BREAKTHROUGH" section
   below). Fixed in `install.sh`: mpv pinned to the known-good
   `0.38.0-1+b1` build, vendored in `vendor/mpv-0.38.0-1+b1/` (not
   fetched from snapshot.debian.org at install time) and held via
   `apt-mark hold` so a routine `apt upgrade` can't silently
   reintroduce it.
2. **`video_player.py` was using `--vo=xv`** (the legacy X11 video
   extension) the entire time, in every test throughout this
   investigation *except* the manual one-off comparisons that
   diagnosed bug #1 — those all explicitly used `--vo=gpu`, which is
   *not* what production actually runs. `--vo=xv` has no real
   vsync/tear-free presentation without a compositor (this project
   runs a bare X server, no window manager) and tears on **every**
   mpv version tested, `0.38.0` included. This means the mpv version
   regression (bug #1), while real and worth having found/fixed, was
   never actually what caused production's tearing - production never
   used `--vo=gpu` at all until this fix. Fixed in `video_player.py`:
   changed the hardcoded `--vo=xv` to `--vo=gpu`.

Confirmed clean combination: mpv `0.38.0` + `--vo=gpu`, on a Pi 5,
using production's exact launch flags. The other three combinations
(`0.40.0`+`xv`, `0.40.0`+`gpu`, `0.38.0`+`xv`) all tear - both fixes
are genuinely required together, neither one alone is sufficient.

**Confirmed end-to-end through the actual app** (not just a manual mpv
invocation): deployed both fixes to `mpv-master-pi5` via `install.sh`,
verified the running processes show `--vo=gpu`, played
`Lola-Young-fake.mp4` from the dashboard, clean through panning shots.
This is the real result, not a synthetic test.

Not yet re-verified on the CM4/Pi 4 devices used for earlier tests in
this investigation, though the shared `vc4`/`v3d` driver stack across
all Pi generations tested makes it very likely both fixes hold there
too.

Revisit the mpv pin whenever a newer release is available — re-run the
test below, and if `--vo=gpu` is clean on it, remove the pin (delete
the `install.sh` block and the `vendor/mpv-0.38.0-1+b1/` directory).

## Symptom

Visible tearing/warping artifact during playback, most obvious on slow
panning shots over flat/light backgrounds (easiest to spot on
`Lola-Young-fake.mp4`, but confirmed present on at least two other
unrelated 1080p files too — `boxingv14.mp4` and a third
`1920_1080_24fps.mp4`). Persists throughout playback, not just at
start. Reported on a CM4 (`mpv-remote`) and confirmed to reproduce
identically on a second, physically different CM4 (`mpv-master`) once
that device's display was reachable.

## Conclusively ruled out

Each of these was tested directly, not assumed:

- **The source files themselves** — same exact file plays perfectly
  clean via `mpv` on a MacBook (both on its own screen and connected to
  the *same* Sony TV used for the Pi tests). Multiple different files
  all show the artifact on the Pi, so it isn't one bad encode either.
- **Resolution/interlacing/frame-rate mismatch** — `ffprobe` confirmed
  `Lola-Young-fake.mp4` is exactly 1920x1080, progressive, clean 25fps.
  No scaling or deinterlacing should even be happening.
- **Hardware vs. software decode** — `--hwdec=no` and `--hwdec=auto`
  produce identical results on the Pi. (Side finding: `--hwdec=auto`
  was never actually achieving hardware decode in the first place —
  see below.)
- **`--vo=xv` vs `--vo=gpu`** — identical results.
- **GPU memory split** — bumped `gpu_mem` 76M → 160M, no change.
- **Forced HDMI timing (CVT vs. standard)** — removed the `M` (CVT)
  flag from `cmdline.txt`'s `video=` parameter, no change. (Forcing
  full native 4K instead of 1080p failed to establish a signal at all
  — separate, since-abandoned finding, not the cause of the tearing.)
- **HDMI cable/port/EDID** — the original cable had a genuine fault
  (X reported `0mm x 0mm` physical size / no real EDID data at all).
  Swapping cable+port fixed EDID (`xrandr` now shows the TV's real
  mode list, physical dimensions). The tearing persisted regardless —
  a real, worthwhile fix in its own right, just not the cause of this.
- **TV motion smoothing / "MotionFlow"** — confirmed already off.
- **Physical Pi unit** — reproduces identically on two different CM4
  boards (`mpv-remote` and `mpv-master`), ruling out one specific
  board's hardware being defective.
- **Compositor absence** — tried both `picom` (GLX backend failed to
  init on this Mesa/V3D driver; `xrender` backend was too CPU-heavy on
  the CM4 to test cleanly) and `xcompmgr` (installed and ran cleanly,
  tearing persisted regardless).
- **`TearFree` X11 option** — turns out this option doesn't exist on
  the `modesetting` driver this system uses at all (it's a legacy
  `fbturbo`-driver-only option); confirmed via `Xorg.1.log` showing
  `Option "TearFree" is not used`. Reverted.
- **Real X11 fullscreen (`--fs`) vs. the app's normal borderless
  `--geometry` window** — no difference. Ruled out the "unredirected
  fullscreen gets direct scanout" theory.
- **`--x11-bypass-compositor=yes`** — no difference.
- **`--hwdec=drm-copy`** (V4L2/DRM-based hardware decode, distinct from the
  broken VDPAU path above) — flag accepted, no difference, still tears.
- **`--vo=gpu --gpu-context=drm`** (bypass X11 entirely, direct KMS
  rendering) — failed to start: `Failed to acquire DRM master: Permission
  denied`. The running X server holds exclusive DRM master, so this
  couldn't actually be tested live via SSH; a real test needs X stopped
  entirely (e.g. from a separate VT), which wasn't attempted tonight.
- **GPU generation and codec** — Pi 5 (VideoCore VII) with H.265/HEVC
  content still tears, identically to CM4/Pi 4 (VideoCore VI) with
  H.264. See below.

**Not tested, still open:** `--vo=gpu-next` (the newer libplacebo-based
renderer — notably what mpv used by default on the clean Mac test, but
never explicitly forced on any Pi tonight).

## The one variable that matters: mpv itself

`ffplay -fs -loop 0 <file>` on the exact same file, same Pi, same TV,
same cable, same everything — **completely clean**. This is the only
variable across the entire investigation that changed the outcome.
Every mpv configuration tried (both video output backends, both decode
modes, real fullscreen, bypass-compositor hint) still tears.

This isolates the cause specifically to mpv's rendering/presentation
path on this system (Mesa V3D / vc4-kms-v3d driver stack, no desktop
compositor), not to anything about the Pi hardware, the display chain,
or the source content.

## Separate, real finding worth fixing regardless

`libvdpau_vc4.so` is missing on this system:
```
Failed to open VDPAU backend libvdpau_vc4.so: cannot open shared object file
```
This means `--hwdec=auto` (what `video_player.py` actually uses in
production) has never been achieving real hardware-accelerated decode
— it silently falls through CUDA (no NVIDIA GPU present) → Vulkan
(unsupported) → VDPAU (missing library) → software decode, every
single time. Worth installing the correct VDPAU driver package for
this GPU (commonly `mesa-vdpau-drivers`, exact package name varies by
OS version) as a legitimate performance fix on CM4 hardware, entirely
independent of the tearing issue.

Also worth applying regardless of the above: `video_player.py` uses
the deprecated `--video-aspect-override=-1`; this mpv version doesn't
yet support the suggested modern replacement
(`--video-aspect-mode=container` errored as an unknown option), so
this needs checking against the actual installed mpv version before
changing — not a like-for-like drop-in on this system yet.

## Status as of end of this session

Software-side testing via SSH is essentially exhausted at this point —
every `--vo`, `--hwdec` mode (including the V4L2/DRM-based
`drm-copy`, not just the broken VDPAU path), fullscreen state, and
compositor option tried still tears, with `ffplay` remaining the only
clean comparison point. The one genuinely untested lever left on this
hardware is direct DRM/KMS rendering with X stopped entirely (`--vo=gpu
--gpu-context=drm` failed only because the running X server holds DRM
master — a real test needs a separate VT with X down, not attempted
tonight).

**Update: tested on an actual Pi 5.** VideoCore VII + RP1 I/O chip,
genuinely different silicon from the VideoCore VI on the CM4/Pi 4 used
for every earlier test — and tested with H.265/HEVC content instead of
H.264 too. **Tearing reproduced identically.** `ffplay -fs` on the same
Pi 5, same HEVC file, stayed completely clean — matching the exact
pattern seen all night on the older hardware with H.264.

This is the decisive result: `ffplay` is clean across every
combination tested (CM4 + H.264, Pi 4 + H.264, Pi 5 + H.265). `mpv`
tears on all of them, across every `--vo`/`--hwdec`/fullscreen/
compositor combination tried. Two GPU generations, two codecs, one
consistently clean player, one consistently not — this rules out GPU
generation, decode method, and codec as explanations entirely, and
narrows it to mpv's own rendering/presentation path specifically, on
the Raspberry Pi Linux/X11 stack in general (not one specific chip).

## BREAKTHROUGH: it's an mpv regression between 0.38.0 and 0.40.0

Tested `mpv 0.38.0-1+b1` (downgraded from `0.40.0-3+deb13u1` via a
pinned Debian snapshot install — `deb
http://snapshot.debian.org/archive/debian/20241210T023135Z/ trixie
main`, `apt-get install mpv:arm64=0.38.0-1+b1`) on the Pi 5, same file,
same everything else:

- **`--hwdec=no`**: clean. No tearing, confirmed over extended playback
  (through multiple panning sections, well past a minute of continuous
  playback).
- **`--hwdec=auto`**: hardware decode engages (`Using hardware decoding
  (drm)`) with **no `Mapping hardware decoded surface failed` errors at
  all** — the DRM-PRIME import bug found on 0.40.0 is also absent here.

This is the answer: a real regression was introduced somewhere between
mpv `0.38.0` and `0.40.0` that both (a) breaks DRM-PRIME hardware
surface import on this driver stack, and (b) causes visible tearing
even in the plain software-decode path. Two releases, `0.38.0` clean
on both counts, `0.40.0` broken on both counts.

**Practical next steps:**
1. Narrow down further if there's appetite — test `0.39.0` (once a
   working arm64 build/snapshot is found — the exact `0.39.0-1` arm64
   build referenced on mpv's snapshot.debian.org package page wasn't
   actually indexed in the snapshot tested; `0.38.0-1+b1` was what was
   actually available and used instead) to bisect which specific
   release introduced it — valuable for the upstream bug report, not
   required for the practical fix.
2. **Test the same downgrade on the CM4/Pi4 devices** (`mpv-master`,
   `mpv-remote`) — if `0.38.0` fixes it there too (very likely, given
   the bug appears to be in shared vc4/DRM rendering code rather than
   anything Pi-5-specific), the practical, ship-tonight answer for the
   whole project is: **pin mpv to `0.38.0` on every device**, rather
   than waiting on an upstream fix, changing player, or any of the
   architectural options considered earlier.
3. File the upstream mpv bug report regardless — this is now a genuinely
   strong, bisectable regression report (works in 0.38.0, broken in
   0.40.0, both the DRM-PRIME import and the tearing symptom together),
   which is exactly the kind of report that gets fixed fast.

**A separate, genuinely concrete bug found along the way on the Pi 5:**
with `--hwdec=auto`, hardware decode does engage (`Using hardware
decoding (drm)`), but mpv fails to import the resulting DRM-PRIME
buffer for display on *every single frame*, on both `--vo=gpu`
(`Mapping hardware decoded surface failed`) and `--vo=gpu-next`
(`mapping DRM dmabuf failed` / `Failed rendering frame!`). This is a
real, separate, reproducible bug — hardware decode is not actually
usable at all on this Pi 5 + mpv combination right now, regardless of
the tearing issue. However, forcing `--hwdec=no` (plain software
decode, no DRM-PRIME surface involved at all, confirmed via a clean
`yuv420p` frame format with zero mapping errors) **still tears**. This
rules the DRM-PRIME failure out as the cause of the visible artifact —
it's a real bug worth reporting on its own, but the tearing survives
even with that entire code path completely bypassed, pointing squarely
at mpv's basic GPU buffer-swap/presentation logic itself, independent
of decode method.

## Recommended next steps

1. **File this with mpv's own project** (github.com/mpv-player/mpv
   issues) — this is now a strong, reproducible, well-isolated report:
   two different Pi GPU generations (VideoCore VI and VII), two
   different codecs (H.264 and H.265/HEVC), `ffplay` clean on every
   combination, `mpv` tearing on all of them regardless of `--vo`,
   `--hwdec` (including `drm-copy`), fullscreen state, or
   `--x11-bypass-compositor`. That's exactly the kind of report
   upstream can actually act on, and is a more appropriate venue than
   continuing to guess flags — they'll know the actual difference
   between `ffplay`'s SDL2 presentation path and mpv's GPU VO path on
   this driver stack far better than trial-and-error from outside.
   (One quick, cheap thing worth trying first if there's appetite:
   `--vo=gpu-next`, the newer libplacebo renderer — untested on any Pi
   tonight, and notably what mpv used by default on the one clean
   non-Pi comparison, a MacBook.)
2. **Install the missing VDPAU driver** and re-confirm hardware decode
   is genuinely active (`hwdec-current` in `mpv --hwdec=auto`'s
   property list, or checking the startup log no longer shows the
   "Failed to open VDPAU backend" line) — a real, separate win on CM4
   performance headroom regardless of the tearing outcome.
3. If tearing turns out to be a known/unfixable mpv-on-vc4 limitation,
   the fallback options are (a) live with it as a cosmetic issue if
   it's acceptable for the venue use case, or (b) a genuinely bigger
   change — evaluating whether this app's video playback could move to
   a different rendering path (e.g. mpv's `--gpu-context=drm` direct
   KMS rendering instead of through X11, which is a substantial
   architectural change given the app's current reliance on X11
   windows for multi-region positioning and the ticker overlay).
