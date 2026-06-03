"""Diagnostic logging for tracing the full span flow.

Built on the stdlib :mod:`logging`. Inactive until :func:`enable` is called (the CLI
calls it; or set ``SPAN_DIAG=1``). Streams to ``<project>/span-diag.log`` (override with
``SPAN_DIAG_LOG``) and mirrors every line to stderr, flushing each record so the file can
be tailed / monitored live.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

_logger = logging.getLogger("span.diag")
_on = False
_configured = False


def default_log_path() -> Path:
    override = os.environ.get("SPAN_DIAG_LOG")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / "span-diag.log"


class _FlushingFileHandler(logging.FileHandler):
    """A FileHandler that flushes after every record so tails see lines immediately."""

    def emit(self, record):
        super().emit(record)
        self.flush()


def enable(path: Optional[Path] = None) -> Path:
    """Activate diagnostic logging and return the resolved log file path."""
    global _on, _configured
    log_path = Path(path) if path is not None else default_log_path()
    if not _configured:
        _logger.setLevel(logging.DEBUG)
        _logger.propagate = False
        fmt = logging.Formatter("%(asctime)s.%(msecs)03d | %(message)s", datefmt="%H:%M:%S")
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        file_handler = _FlushingFileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setFormatter(fmt)
        _logger.addHandler(file_handler)
        stream_handler = logging.StreamHandler()  # stderr
        stream_handler.setFormatter(fmt)
        _logger.addHandler(stream_handler)
        _configured = True
    _on = True
    return log_path


def _env_on() -> bool:
    return os.environ.get("SPAN_DIAG", "").strip().lower() not in ("", "0", "false", "no", "off")


def _active() -> bool:
    global _on
    if not _on and _env_on():
        enable()
    return _on


def banner(msg: str) -> None:
    if not _active():
        return
    _logger.debug("=" * 72)
    _logger.debug("=== %s", msg)
    _logger.debug("=" * 72)


def log(tag: str, msg: str = "", **fields) -> None:
    """Emit one structured diagnostic line: ``TAG  msg  k=v  k=v``."""
    if not _active():
        return
    parts = [tag]
    if msg:
        parts.append(msg)
    parts.extend(f"{k}={v}" for k, v in fields.items())
    _logger.debug("  ".join(parts))
