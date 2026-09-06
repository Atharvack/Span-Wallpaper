"""span — slice one wallpaper across every connected macOS display, in millimetres.

Copyright (C) 2026  Atharva Kulkarni

This program is free software: you can redistribute it and/or modify it under the terms
of the GNU General Public License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program.
If not, see <https://www.gnu.org/licenses/>.

Layout:

* :mod:`span.algorithm` — the OS import and the wall maths. No Qt, no Pillow.
* :mod:`span.calibration` — measuring where the glass physically is, and storing it.
* :mod:`span.image_processing` — loading, cropping, resampling, saving.
* :mod:`span.cli` / :mod:`span.gui` — the app on top of them.
"""

from .algorithm import Box, Display, Estate, Panel

__version__ = "0.2.0"
__all__ = ["Box", "Display", "Estate", "Panel", "__version__"]
