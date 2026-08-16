# Playback tearing/rippling investigation (2026-08-16)

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

Plan going forward: test the same content on an actual Pi 5 (not
tested at all tonight — both devices used were Pi4-generation VideoCore
VI hardware, CM4 and Pi 4 2GB, which are electrically identical GPUs
despite the different form factors). Pi 5's VideoCore VII + RP1 I/O
chip is a genuinely different architecture, and the operator has prior
first-hand experience of clean playback on a Pi 5 with this same
software — real, if not perfectly controlled, evidence in its favor.
Content will likely be re-encoded to H.265 at the same time (for Pi 5's
better HEVC decode support), which means that test won't cleanly
isolate hardware-vs-codec, but does match the actual intended
production setup.

## Recommended next steps

1. **File this with mpv's own project** (github.com/mpv-player/mpv
   issues) — this is a clean, reproducible, well-isolated report: same
   file/hardware/OS, one player (`ffplay`) is clean, `mpv` tears
   regardless of `--vo`, `--hwdec`, fullscreen state, or
   `--x11-bypass-compositor`. That's exactly the kind of report
   upstream can actually act on, and is a more appropriate venue than
   continuing to guess flags — they'll know the actual difference
   between `ffplay`'s SDL2 presentation path and mpv's GPU VO path on
   this driver stack far better than trial-and-error from outside.
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
