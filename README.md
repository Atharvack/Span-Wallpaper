# span

A macOS command-line tool that slices **one** wallpaper across **every** connected
display. It auto-detects your monitors (name, native resolution, physical arrangement),
opens a small GUI where you drag/resize one rectangle per display over the image, and on
**Apply** writes one PNG per display at that display's native resolution — sized so the
picture spans your monitors with the seams lined up.

You never type a pixel count. The tool only produces files; you assign each one to its
display manually (it never changes OS wallpaper state).

## Install

```bash
cd /path/to/Span-Wallpaper
uv venv --python "$(which python3)" .venv
source .venv/bin/activate
uv pip install pyside6 pillow         # runtime deps
uv pip install -e .                    # installs the `span` command
```

(Plain `python3 -m venv .venv` + `pip install` works too.)

## Use

```bash
span path/to/wallpaper.jpg     # opens the placement GUI
span                           # prompts for the image path once
span --list                    # print detected displays as JSON, no GUI
span IMAGE --out DIR           # choose the output directory
```

In the GUI:

- **Drag** a rectangle to choose which part of the image that monitor shows.
- **Drag the corner handle** to resize — locked to the display's aspect ratio.
- Rectangles are clamped so they never leave the image.
- **Reset layout** re-seeds from the detected arrangement; **Apply** crops + saves.

Output files are named `{image-stem}_{display}_{WxH}.png`.

## How it maps the image

Displays are detected in macOS global *points*-space (bottom-left origin) via a read-only
`NSScreen` query. A display's **native pixels** are `round(w·scale) × round(h·scale)` —
both the export resolution and the rectangle's locked aspect ratio. Rectangles are seeded
from the displays' real physical arrangement (honoring gaps, vertical offsets, and
differing sizes), uniformly fit into the image and centered, so adjacent crops line up
across the seam out of the box. The GUI scene holds the image at full resolution, so every
rectangle's geometry is an exact crop box; crops are resampled to native with LANCZOS.

## Output confinement

If the `SPAN_ROOT` environment variable is set, `--out` must resolve to a path inside it
(default output is `SPAN_ROOT` itself). Otherwise output defaults to the current
directory.

## Develop / test

```bash
uv pip install pytest
QT_QPA_PLATFORM=offscreen pytest        # geometry units + offscreen GUI/export tests
```

The geometry math (`span/geometry.py`) is pure and fully unit-tested; the GUI and export
paths run headless under Qt's offscreen platform, so tests never touch your real displays.
