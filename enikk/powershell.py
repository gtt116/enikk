"""PowerShell command execution service."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import unicodedata

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 25_000


def _sanitize_output(text: str) -> str:
    """Remove control characters from output, keeping \\t, \\n, \\r."""
    if not text:
        return text

    chars: list[str] = []
    for ch in text:
        cp = ord(ch)
        if cp == 0x09 or cp == 0x0A or cp == 0x0D:
            chars.append(ch)
            continue
        if cp < 0x20:
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("C"):
            continue
        chars.append(ch)
    return "".join(chars)


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text to max_chars, keeping the tail. Returns (text, was_truncated)."""
    if len(text) <= max_chars:
        return text, False
    return "..." + text[-(max_chars - 3):], True


def resolve_powershell_path() -> str:
    """Find the best available PowerShell executable.

    Search order:
        1. PowerShell 7 in Program Files (preferred — supports &&)
        2. PowerShell 7 in ProgramW6432
        3. pwsh in PATH
        4. Windows PowerShell 5.1 (system built-in)
        5. Fallback: powershell.exe (hopes it's on PATH)
    """
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    pwsh7 = os.path.join(program_files, "PowerShell", "7", "pwsh.exe")
    if os.path.isfile(pwsh7):
        return pwsh7

    program_w6432 = os.environ.get("ProgramW6432")
    if program_w6432 and program_w6432 != program_files:
        pwsh7_alt = os.path.join(program_w6432, "PowerShell", "7", "pwsh.exe")
        if os.path.isfile(pwsh7_alt):
            return pwsh7_alt

    pwsh_in_path = shutil.which("pwsh")
    if pwsh_in_path:
        return pwsh_in_path

    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if system_root:
        win_ps = os.path.join(
            system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
        )
        if os.path.isfile(win_ps):
            return win_ps

    return "powershell.exe"


class PowerShellService:
    """Execute PowerShell commands and return structured output."""

    def __init__(self) -> None:
        self._shell_path = resolve_powershell_path()

    @property
    def shell_path(self) -> str:
        return self._shell_path

    def execute(self, command: str, *, timeout: float = 30) -> dict:
        """Run a PowerShell command and return the result.

        Returns a dict with keys: exit_code, stdout, stderr, truncated.
        On timeout, exit_code is -1 and stderr contains a timeout message.
        """
        argv = [self._shell_path, "-NoProfile", "-NonInteractive", "-Command",
                f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"]
        logger.info("powershell: executing %r (timeout=%.1fs)", command, timeout)

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            logger.warning("powershell: command timed out after %.1fs", timeout)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "truncated": False,
            }
        except Exception as e:
            logger.error("powershell: failed to start: %s", e)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Failed to execute: {e}",
                "truncated": False,
            }

        stdout = _sanitize_output(proc.stdout)
        stderr = _sanitize_output(proc.stderr)

        stdout, stdout_trunc = _truncate(stdout, MAX_OUTPUT_CHARS)
        stderr, stderr_trunc = _truncate(stderr, MAX_OUTPUT_CHARS)

        logger.info(
            "powershell: exit_code=%d, stdout=%d chars, stderr=%d chars",
            proc.returncode,
            len(stdout),
            len(stderr),
        )

        return {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": stdout_trunc or stderr_trunc,
        }
