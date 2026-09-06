"""span — slice one wallpaper across every connected macOS display, in millimetres.

Layout:

* :mod:`span.algorithm` — the OS import and the wall maths. No Qt, no Pillow.
* :mod:`span.calibration` — measuring where the glass physically is, and storing it.
* :mod:`span.image_processing` — loading, cropping, resampling, saving.
* :mod:`span.cli` / :mod:`span.gui` — the app on top of them.
"""

from .algorithm import Box, Display, Estate, Panel

__version__ = "0.2.0"
__all__ = ["Box", "Display", "Estate", "Panel", "__version__"]
