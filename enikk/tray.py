"""System tray icon for Enikk — allows the app to run in the background."""
import logging
import threading
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)


class TrayManager:
    """Manages the system tray icon and its context menu.

    The tray icon lets the user:
    - Show the dashboard window again after it's been hidden
    - Fully exit the application
    """

    def __init__(self, window: Any, icon_path: Path):
        """Initialize TrayManager.

        Args:
            window: pywebview Window object (for show/hide/destroy).
            icon_path: Path to the .ico file to use as tray icon.
        """
        self._window = window
        self._icon_path = icon_path
        self._icon: Any = None
        # Set when the user exits via the tray menu, so the window's
        # closing handler knows to let the close through instead of
        # hiding/minimizing.
        self.force_exit = False

    def start(self) -> None:
        """Create and display the tray icon in a background thread."""
        import pystray

        image = Image.open(self._icon_path)
        menu = pystray.Menu(
            pystray.MenuItem("Show Dashboard", self._on_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_quit),
        )
        self._icon = pystray.Icon("enikk", image, "Enikk", menu)

        thread = threading.Thread(target=self._icon.run, daemon=True, name="tray-icon")
        thread.start()
        logger.info("System tray icon started")

    def stop(self) -> None:
        """Remove the tray icon."""
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
            logger.info("System tray icon stopped")

    def _on_show(self, icon: Any, item: Any) -> None:
        """Show the webview window."""
        try:
            self._window.show()
        except Exception:
            logger.exception("Failed to show window from tray")

    def _on_quit(self, icon: Any, item: Any) -> None:
        """Stop the tray icon and destroy the webview window to trigger shutdown."""
        self.force_exit = True
        icon.stop()
        try:
            self._window.destroy()
        except Exception:
            logger.exception("Failed to destroy window from tray")
