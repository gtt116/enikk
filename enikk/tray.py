"""System tray icon for Enikk — allows the app to run in the background."""
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .updater import UpdateInfo

logger = logging.getLogger(__name__)


class TrayManager:
    """Manages the system tray icon and its context menu.

    The tray icon lets the user:
    - Show the dashboard window again after it's been hidden
    - Open the GitHub release page when an update is available
    - Fully exit the application
    """

    def __init__(
        self,
        window: Any,
        icon_path: Path,
        update_thread: threading.Event | None = None,
        get_update_info: Callable[[], UpdateInfo | None] | None = None,
    ):
        """Initialize TrayManager.

        Args:
            window: pywebview Window object (for show/hide/destroy).
            icon_path: Path to the .ico file to use as tray icon.
            update_thread: Event that is set when update check completes.
            get_update_info: Callable returning UpdateInfo if update available.
        """
        self._window = window
        self._icon_path = icon_path
        self._icon: Any = None
        self._update_event = update_thread
        self._get_update_info = get_update_info
        self._update_info: UpdateInfo | None = None
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

        # Start background thread to wait for update check and add menu item
        if self._update_event and self._get_update_info:
            update_waiter = threading.Thread(
                target=self._wait_and_add_update_menu, daemon=True, name="update-menu"
            )
            update_waiter.start()

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

    def _wait_and_add_update_menu(self) -> None:
        """Wait for update check to complete, then add update menu item if available."""
        if not self._update_event or not self._get_update_info or not self._icon:
            return

        # Wait up to 30 seconds for the update check
        self._update_event.wait(timeout=30)
        info = self._get_update_info()
        if not info:
            return

        self._update_info = info
        logger.info("Update available: v%s", info.version)

        # Rebuild menu with update item
        import pystray

        self._icon.menu = pystray.Menu(
            pystray.MenuItem("Show Dashboard", self._on_show, default=True),
            pystray.MenuItem(f"Update to v{info.version}", self._on_update),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_quit),
        )
        self._icon.update_menu()

    def _on_update(self, icon: Any, item: Any) -> None:
        """Open GitHub release page in default browser."""
        if self._update_info and self._update_info.html_url:
            try:
                os.startfile(self._update_info.html_url)
                logger.info("Opened release page: %s", self._update_info.html_url)
            except Exception:
                logger.exception("Failed to open release URL")
