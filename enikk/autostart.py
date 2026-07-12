"""Windows auto-start via Task Scheduler (supports UAC elevation)."""
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_TASK_NAME = "Enikk Autostart"


def get_exe_path() -> str:
    """Return the path to the running Enikk executable."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle — sys.executable is the .exe
        return sys.executable
    # Development — use the uv/python entry
    return sys.executable


def is_autostart_enabled() -> bool:
    """Check whether the Enikk Autostart scheduled task exists."""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", _TASK_NAME],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return result.returncode == 0
    except Exception:
        logger.exception("Failed to query scheduled task")
        return False


def enable_autostart() -> None:
    """Create or update the Enikk Autostart scheduled task.

    Runs at user logon with highest privileges (no UAC prompt).
    Passes --start-minimized so the app launches hidden in the tray.
    """
    exe = get_exe_path()

    # Build the command. For frozen builds, pass --start-minimized directly.
    # For dev builds, we need `python -m enikk --start-minimized`.
    if getattr(sys, "frozen", False):
        cmd = f'"{exe}" --start-minimized'
    else:
        cmd = f'"{exe}" -m enikk --start-minimized'

    # Delete existing task first (ignore errors if it doesn't exist)
    subprocess.run(
        ["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    # Create the task
    result = subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", _TASK_NAME,
            "/TR", cmd,
            "/SC", "ONLOGON",
            "/RL", "HIGHEST",
            "/F",
        ],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create scheduled task: {result.stderr.strip()}"
        )

    logger.info("Auto-start enabled: %s", cmd)


def disable_autostart() -> None:
    """Remove the Enikk Autostart scheduled task."""
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    if result.returncode != 0 and "does not exist" not in result.stderr.lower():
        raise RuntimeError(
            f"Failed to delete scheduled task: {result.stderr.strip()}"
        )

    logger.info("Auto-start disabled")
