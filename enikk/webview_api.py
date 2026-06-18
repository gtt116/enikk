"""Webview API bridge for native OS operations."""
import os
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

import webview

from .config import enikk_home


class WebviewAPI:
    """JS-API bridge exposed to the webview frontend."""

    def open_dir(self, path: str) -> None:
        """Open a directory in the system file explorer."""
        p = Path(path).resolve()
        if p.is_dir():
            if platform.system() == "Windows":
                os.startfile(str(p))
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(p)])
            else:
                subprocess.run(["xdg-open", str(p)])

    def pick_dir(self, initial_dir: str | None = None) -> str | None:
        """Open a folder picker dialog and return the selected path."""
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.FOLDER,
            directory=initial_dir or str(enikk_home()),
        )
        if result and result[0]:
            return result[0]
        return None

    def pick_file(self, file_types: str = "") -> str | None:
        """Open a file picker dialog and return the selected path.

        file_types: extension like "exe" or pattern like "*.exe"
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info("pick_file called with file_types=%r", file_types)

        # Build file filter in pywebview format: "description (*.ext)"
        if not file_types:
            file_filter = "All Files (*.*)"
        else:
            # Extract extension if it's a pattern like *.exe
            ext = file_types.replace("*.", "").replace("*", "")
            if ext:
                file_filter = f"Executable (*.{ext})"
            else:
                file_filter = "All Files (*.*)"

        logger.info("passing file_types=%r to create_file_dialog", file_filter)

        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(enikk_home()),
            allow_multiple=False,
            file_types=(file_filter,),  # must be a tuple
        )
        if result and result[0]:
            return result[0]
        return None


def start_webview(
    url: str,
    title: str = "Enikk Dashboard",
    width: int = 1280,
    height: int = 800,
    icon_path: Path | None = None,
    debug: bool = False,
    on_closing: Callable[[], bool] | None = None,
    on_ready: Callable | None = None,
) -> None:
    """Create and start the webview window.

    This function blocks until the webview window is closed.
    When debug=True, F12 opens DevTools (but DevTools won't auto-open on launch).

    Args:
        on_closing: Callback invoked when the user tries to close the window.
            Return True to allow closing, False to prevent it (e.g. minimize to tray).
        on_ready: Callback invoked after window creation but before the event loop
            starts. Receives the window object as its only argument.
    """
    if debug:
        webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False

    window = webview.create_window(
        title,
        url=url,
        width=width,
        height=height,
        js_api=WebviewAPI(),
    )
    assert window is not None

    if on_closing is not None:
        window.events.closing += on_closing

    if on_ready is not None:
        on_ready(window)

    icon_str = str(icon_path) if icon_path and icon_path.exists() else None
    webview.start(icon=icon_str, debug=debug)

