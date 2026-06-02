"""Webview API bridge for native OS operations."""
import os
import platform
import subprocess
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


def start_webview(
    url: str,
    title: str = "Enikk Dashboard",
    width: int = 1280,
    height: int = 800,
    icon_path: Path | None = None,
    debug: bool = False,
) -> None:
    """Create and start the webview window.

    This function blocks until the webview window is closed.
    When debug=True, F12 opens DevTools (but DevTools won't auto-open on launch).
    """
    if debug:
        webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False

    webview.create_window(
        title,
        url=url,
        width=width,
        height=height,
        js_api=WebviewAPI(),
    )
    icon_str = str(icon_path) if icon_path and icon_path.exists() else None
    webview.start(icon=icon_str, debug=debug)

