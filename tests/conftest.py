"""Shared pytest setup.

Force Qt's offscreen platform so the GUI smoke-tests construct without a real display
(and never touch the user's monitors).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
