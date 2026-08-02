"""Version and metadata information for Enikk."""

import os
import subprocess

_BASE_VERSION = "0.11.1"


def _git_version() -> str | None:
    """Derive version from git describe when running from a checkout."""
    try:
        if getattr(__import__("sys"), "frozen", False):
            return None
        here = os.path.dirname(os.path.abspath(__file__))
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=here,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        desc = out.decode("utf-8").strip()
        return desc.lstrip("v") if desc else None
    except Exception:
        return None


__version__ = _git_version() or _BASE_VERSION
__description__ = "Enikk: Open-source Computer Use Agent for Any App and Any Model."
