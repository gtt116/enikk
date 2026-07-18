"""Lightweight process-level memory tracking (RSS).

Usage:
    from .mem_track import mem_tag
    mem_tag("after model load")

Output:
    [mem] after model load:           850 MB (+230 MB)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_last_rss_mb: float = 0.0


def mem_tag(label: str, *, extra: str = "") -> None:
    """Log process RSS at a checkpoint, with delta from previous call.

    Args:
        label: Short description of the checkpoint.
        extra: Optional additional info appended to the log line.
    """
    global _last_rss_mb
    try:
        import psutil

        rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        delta = rss_mb - _last_rss_mb if _last_rss_mb else 0.0
        delta_str = f" (+{delta:.0f} MB)" if _last_rss_mb else ""
        extra_str = f"  {extra}" if extra else ""
        logger.info("[mem] %-28s %6.0f MB%s%s", label + ":", rss_mb, delta_str, extra_str)
        _last_rss_mb = rss_mb
    except Exception:
        pass
