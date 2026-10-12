"""Version and metadata information for Enikk.

The version is derived from git tags:

* frozen builds (PyInstaller): ``BUILD_VERSION`` stamped by
  ``scripts/build_version.ps1`` at package time;
* source checkouts: ``git describe --tags --long`` relative to this
  repository, e.g. ``v0.11.1-35-g8807ed1`` -> ``0.11.1+35.g8807ed1``;
* no git metadata available: ``_FALLBACK_VERSION``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__description__ = "Enikk: Open-source Computer Use Agent for Any App and Any Model."

# Used when git metadata is unavailable (e.g. an installed package without a
# repository checkout). Bump this before cutting a release tag.
_FALLBACK_VERSION = "0.12.0"

_ABBREV = 7


def format_describe(describe: str) -> str:
    """Convert a ``git describe --tags --long`` string to a version string.

    ``v0.11.1-35-g8807ed1`` becomes ``0.11.1+35.g8807ed1``; an exact tag
    match (``v0.12.0-0-g1a2b3c4``) becomes just ``0.12.0``.
    """
    tag, count, ghash = describe.rsplit("-", 2)
    tag = tag.removeprefix("v")
    if count == "0":
        return tag
    return f"{tag}+{count}.{ghash}"


def _git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _git_version() -> str | None:
    """Version from the nearest reachable tag in the source repository."""
    repo = Path(__file__).resolve().parent.parent
    describe = _git(repo, "describe", "--tags", "--long", f"--abbrev={_ABBREV}")
    if describe:
        return format_describe(describe)

    # No reachable tag yet: base version + total commit count + short hash.
    count = _git(repo, "rev-list", "--count", "HEAD")
    ghash = _git(repo, "rev-parse", f"--short={_ABBREV}", "HEAD")
    if count and ghash and count != "0":
        return f"{_FALLBACK_VERSION}+{count}.g{ghash}"
    return None


def _stamped_version() -> str | None:
    """Version baked in at package time; only present in frozen builds."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        from ._build_version import BUILD_VERSION
    except Exception:
        return None
    return BUILD_VERSION or None


def resolve_version() -> str:
    return _stamped_version() or _git_version() or _FALLBACK_VERSION


__version__ = resolve_version()
