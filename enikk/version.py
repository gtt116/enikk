"""Version and metadata information for Enikk."""

import os
import subprocess

_BASE_VERSION = "0.11.1"


def _to_pep440(desc: str) -> str | None:
    """Convert git describe output to a PEP 440 version string.

    Handles two forms:
      - Tagged: "0.11.1-12-g6de692b"     -> "0.11.1.post12+g6de692b"
      - Tagged+dirty: "...-dirty"         -> "...+g6de692b.dirty"
      - Bare hash (no tags / shallow):    -> None (fall back)
    """
    dirty = desc.endswith("-dirty")
    if dirty:
        desc = desc[: -len("-dirty")]

    parts = desc.rsplit("-", 2)
    if len(parts) == 3 and parts[2].startswith("g"):
        base, n, commit = parts
        local = f"{commit}.dirty" if dirty else commit
        return f"{base}.post{n}+{local}"
    # Bare hash — no usable tag info
    return None


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
        desc = out.decode("utf-8").strip().lstrip("v")
        if not desc:
            return None
        pep = _to_pep440(desc)
        if pep:
            return pep
        # Bare hash (no tags available) — use base version with dev marker
        return f"{_BASE_VERSION}.dev0+{desc}"
    except Exception:
        return None


__version__ = _git_version() or _BASE_VERSION
__description__ = "Enikk: Open-source Computer Use Agent for Any App and Any Model."
