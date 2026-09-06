"""Shared pytest setup.

Two things are forced before any span module is imported:

* Qt's offscreen platform, so GUI tests construct without a real display and never touch
  the user's monitors.
* A throwaway diagnostic log. Otherwise the suite appends to the same ``logs/span.log``
  the real app writes, and a test run is indistinguishable from someone actually using
  the tool — which made a live monitor on that file useless.
"""

import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SPAN_DIAG_LOG"] = os.path.join(
    tempfile.mkdtemp(prefix="span-tests-"), "span-test.log"
)
