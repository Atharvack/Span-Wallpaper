# span

A macOS tool that slices **one** wallpaper across **every** connected display, laid out in
**millimetres** so the picture is physically continuous across the bezel.

## Why millimetres

A pixel is a count, not a length. On a 108 ppi panel one pixel is 0.235 mm; on a 92 ppi
panel it is 0.276 mm. So no pixel-space arrangement can be physically correct across two
different monitors — a ridge crossing the seam changes size, and a vertical offset
measured in pixels is wrong by however much the densities differ.

macOS makes this worse by reporting monitor positions in *points*, a count-based space
that assumes every display has the same density. That assumption is false for a mixed
setup, and the resulting error is tens of millimetres — the step you see in a spanned
wallpaper.

span works entirely in physical units instead:

```
wall (mm)  →  crop = panel rectangle × S  →  image pixels
```

Every panel becomes a rectangle of glass on an imaginary wall. The image is pinned to that
wall at a chosen density `S` (image pixels per mm). A display's crop is whatever falls
behind its glass. Pixel counts appear once, in a final `round()`.

Bezel compensation is not a feature — it falls out. The gap between two panels is
millimetres you do not cover, so the picture continues behind the plastic.

## The one thing software cannot know

Where your monitors physically sit. No API reports it, and even a tape measure gives you
geometric truth when what you want is perceptual truth from your chair — angled panels are
never coplanar.

So span asks your eyes, which are extremely good at judging whether two line segments are
collinear. Draw a pattern on every screen, nudge until it joins across the bezel, save.
Measured once per desk, stored in `~/.span/wall.json`, reused for every image after that.

That is also what every serious tool does — NVIDIA Surround and AMD Eyefinity both ship a
visual bezel-correction wizard for exactly this reason.

## Install

```bash
uv venv --python "$(which python3)" .venv
source .venv/bin/activate
uv pip install pyside6 pillow
uv pip install -e .
```

## Use

```bash
span --calibrate            # measure the wall (do this first, once)
span path/to/photo.jpg      # place the image, then export
span --wall                 # print the calibrated physical layout
span --list                 # detected displays as JSON
span --raw                  # every field macOS reports
span IMAGE --out DIR        # choose the output directory
```

### The flow

`span` opens a small **welcome window** on one screen — displays detected, calibration
status, and a **Browse image…** button. Nothing goes fullscreen until there is a reason.

After you choose an image:

* **Wall already calibrated** → straight to placement, fullscreen across every display.
* **Not calibrated yet** → the welcome window explains why placing now would step at the
  seam, and offers **Start calibration**.

`esc` from the wall returns to the welcome window rather than quitting, so you can pick
another image without relaunching.

Once the wall is up it covers **every** display at once, so what you see is the export —
the rectangle on screen is literally the crop box handed to Pillow.

**calibrate mode** — where the glass is. A fact about your room.

```
↑ ↓        move this panel 1 mm (shift: 0.2 mm)
← →        open or close the bezel gap
g          cycle pattern: line / rules + circles / full
⏎          save to ~/.span/wall.json
```

Nudge until the circles close and the diagonals carry on across the bezel. Circles are the
harshest test; diagonals are the only element sensitive to a wrong horizontal gap.

**place mode** — where you want the picture. A preference.

```
drag       move the image behind the fixed panels
↑ ↓ ← →    nudge 5 mm (shift: 1 mm)
f / n      scale policy: fit the estate / densest panel 1:1
0          recentre
o          open a different image
⏎          export one PNG per display
w          export and set as wallpaper
```

`tab` switches modes, `o` opens the file chooser from either, `esc` quits. The panels never
move, because they cannot — monitors are fixed and the poster is what slides.

Output is `{image-stem}_{display}_{W}x{H}.png`, at each display's native resolution.
Existing files are never overwritten; a `" (1)"` suffix is appended instead.

## Setting the wallpaper

`w` in place mode exports and then assigns each crop to its own display, via
`NSWorkspace.setDesktopImageURL:forScreen:options:error:` — reached through the same
`osascript` bridge used to read `NSScreen`, so no extra dependency and no Automation
permission prompt.

The flow:

1. **Calibration is required.** On an unmeasured wall the crops are laid out as though the
   panels were flush and touching, which is exactly the stepped result this tool exists to
   avoid. `w` refuses, switches to calibrate mode, and says so.
2. **What's on screen now is recorded** to `~/.span/tmp/wallpaper-before.json` — a mapping
   of display name to file path.
3. **The new crops are set.**
4. **A dialog asks whether to keep it, counting down from 60 seconds.** Keep, and the app
   exits. Revert — or let it time out — and your previous wallpapers come back.

The timeout reverts rather than keeps, same as a display-resolution confirmation and for
the same reason: if the result is unusable, or you walked away, doing nothing has to undo
it.

Three other details it handles:

* **Scaling is pinned.** The crops are already exactly native resolution; letting macOS
  pick a scaling mode could silently undo the millimetre work.
* **The files go to `tmp/desktop_wallpaper_do_not_remove/`**, not your output directory.
  macOS stores a *reference* to a wallpaper file, so it has to keep existing — writing to
  the system temp directory would make the desktop revert when the OS cleaned up. That
  folder holds only the current set; the previous one is cleared once you press Keep.
* **One failed display doesn't hide the others.** Each result is reported separately, and
  the undo snapshot only stores paths — so if you delete an original in the meantime, the
  revert says which one it could not restore rather than skipping it silently.

It applies to the current Space only; macOS exposes no public API for the others.

## Files and logs

```bash
span --paths        # print every location
```

Working from a checkout, they sit beside the code:

```
tmp/wall.json              measured wall geometry, per setup
tmp/wallpaper-before.json  what was on screen before the last set
tmp/*.png                  every generated image — exports, patterns
tmp/desktop_wallpaper_do_not_remove/
                           the images currently ON your desktop
logs/span.log              one append-only log across every session
```

`tmp` is span's whole working directory, state and images together. Every image span
generates lands there — including `⏎` exports, which default to `tmp/` rather than the
directory you happened to run the command in.

`desktop_wallpaper_do_not_remove/` is named as a warning to a future human with a cleanup
impulse: macOS stores a *reference* to a wallpaper file, not a copy, so deleting what is
in there blanks the desktop. Nothing else is written to it, it holds only the current set,
and pruning cannot reach it — `prune_tmp` does not recurse, so the folder is out of scope
by construction rather than by an exclusion someone could forget.

The log is a single file, never truncated, flushed per record — so you can point a
terminal at it once and watch the tool work:

```bash
tail -f logs/span.log
```

Installed as a package there is no checkout to write into, so the base becomes `~/.span`.
`$SPAN_HOME` overrides either; `$SPAN_DIAG_LOG` overrides just the log.

## Layout

```
span/
  algorithm/          the OS import and the millimetre maths — no Qt, no Pillow
    displays.py       NSScreen via JXA + CGDisplayScreenSize via ctypes
    wall.py           Panel, Estate, scale policies, plan_layout
  calibration/        measuring where the glass is, and remembering it
    solve.py          line rows → wall offsets
    store.py          ~/.span/wall.json, keyed by which monitors are plugged in
    pattern.py        the test pattern, defined in mm, renderer-agnostic
  image_processing/   loading, cropping, resampling, saving
  cli.py  gui.py      the app
playground/           standalone experiments the model was derived from
```

`algorithm` and `calibration` import nothing from Qt or Pillow, so the whole layout model
is testable with hand-built objects and no hardware.

## Playground

Standalone scripts, each one isolating a single question. They were how the model was
derived, and they are still the fastest way to check an assumption without launching the
app. Run them from the repo root.

```bash
python3 playground/scale.py            # is a millimetre really a millimetre?
python3 playground/calibrate_y.py      # where does the glass sit vertically?
python3 playground/wall_live.py        # does the wall join across the bezel?
python3 playground/wall_export.py      # does the exported file match what was on screen?
```

**`scale.py`** draws a bar of identical *mm* height on each display — 250 mm is 1063 px on
a 108 ppi panel and 906 px on a 92 ppi one. Put them side by side at the bezel. If they
read as the same height, EDID is truthful and the whole mm model rests on solid ground. If
one is visibly taller, that panel's reported physical size is wrong and every layout built
on it inherits the error. **Run this first on a new setup.**

**`calibrate_y.py`** is the measurement in its rawest form: one draggable horizontal line
per display, moved until they read as a single continuous line, then solved with
`y_offset_i = d_0 - d_i`. The app's calibrate mode does the same thing more conveniently by
letting you nudge the offset directly; this version shows the arithmetic.

**`wall_live.py`** renders the pattern across every display with the offsets adjustable
live — a standalone twin of the app's calibrate mode, useful for testing pattern changes
without touching `span/`.

**`wall_export.py`** runs the full pipeline to disk: wall → plan → PNGs. With no `--image`
it generates the test pattern at estate size, so the exported files can be set as
wallpapers and compared against what the live view showed.

## Where the numbers come from

`width_mm` / `height_mm` come from EDID via `CGDisplayScreenSize`. Nothing in `NSScreen`
reports a physical size — its `NSDeviceResolution` field says 72 dpi for every display ever
made, a legacy PostScript constant rather than a measurement.

Panel *positions* come from calibration only. `Display.x/y` are used for exactly one thing:
sorting displays left to right.

If a panel reports no EDID, span cannot place it on the wall and says so rather than
guessing.

## Develop / test

```bash
QT_QPA_PLATFORM=offscreen pytest        # 95 tests, no real displays touched
```

Display detection is tested by faking `subprocess.run`, so every failure branch runs
anywhere. The GUI is constructed under Qt's offscreen platform.

## Output confinement

If `SPAN_ROOT` is set, `--out` must resolve inside it (default output is `SPAN_ROOT`
itself). Otherwise output defaults to `tmp/`. The directory is created only when files are
actually written, so quitting without exporting leaves nothing behind.

## Licence

Copyright © 2026 Atharva Kulkarni. Released under the
[GNU General Public License v3.0](LICENSE).

In short: use it, study it, change it, share it. If you distribute span — modified or not
— you must pass on the source under the same licence, so whoever receives it has the same
freedoms you did.

Contributions are welcome and go through pull requests; only merged changes become part of
the project.
