"""Game process management — launcher login and game launch orchestration."""
import ctypes
import logging
import os
import subprocess
import time
from dataclasses import dataclass

import psutil

from .account import load_account
from .capture import CaptureMethod
from .input import Input
from .login import LauncherLogin

logger = logging.getLogger("enikk")


@dataclass
class Window:
    """Unified window representation."""
    name: str
    class_name: str
    process: str
    path: str
    hwnd: int = 0


class _Process:
    """Shared process and window management."""

    def __init__(self, name: str, class_name: str, process: str, path: str):
        self.name = name
        self.class_name = class_name
        self.process = process
        self.path = os.path.normpath(path)
        self.hwnd: int = 0

    def is_running(self) -> bool:
        """Check if the process is running (current user only)."""
        try:
            system_username = os.getlogin()
        except Exception:
            import getpass
            system_username = getpass.getuser()

        for proc in psutil.process_iter(['pid', 'name', 'username']):
            try:
                proc_name = proc.info['name'] or ''
                if self.process.lower() in proc_name.lower():
                    proc_user = (proc.info['username'] or '').split('\\')[-1]
                    if system_username == proc_user:
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    def get_process(self):
        """Get psutil.Process object for the running process."""
        try:
            system_username = os.getlogin()
        except Exception:
            import getpass
            system_username = getpass.getuser()

        for proc in psutil.process_iter(['pid', 'name', 'username']):
            try:
                proc_name = proc.info['name'] or ''
                if self.process.lower() in proc_name.lower():
                    proc_user = (proc.info['username'] or '').split('\\')[-1]
                    if system_username == proc_user:
                        return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def start(self) -> bool:
        """Start the program."""
        logger.info(f"Starting [{self.name}]: [{self.path}]")
        if not os.path.exists(self.path):
            logger.error(f"Path does not exist: {self.path}")
            return False

        folder = self.path.rpartition('\\')[0]
        try:
            subprocess.Popen(
                [self.path],
                cwd=folder,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            logger.info(f"[{self.name}] started")
            return True
        except Exception as e:
            logger.error(f"subprocess.Popen failed: {e}")

        return False

    def stop(self) -> bool:
        """Terminate the process (current user only)."""
        logger.info(f"Stopping [{self.name}]: {self.process}")
        killed_any = False
        try:
            system_username = os.getlogin()
        except Exception:
            import getpass
            system_username = getpass.getuser()

        for proc in psutil.process_iter(['pid', 'name', 'username']):
            try:
                proc_name = proc.info['name'] or ''
                if self.process.lower() in proc_name.lower():
                    proc_user = (proc.info['username'] or '').split('\\')[-1]
                    if system_username == proc_user:
                        logger.info(f"Killing {proc_name} (PID={proc.pid})")
                        proc.kill()
                        proc.wait(timeout=10)
                        killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass
        return killed_any

    def switch_to(self) -> bool:
        """Switch the window to foreground."""
        import win32gui
        import win32process

        self.hwnd = 0

        def enum_windows_callback(hwnd, hwnd_list):
            try:
                class_name = win32gui.GetClassName(hwnd)
                if not win32gui.IsWindowVisible(hwnd):
                    return
                if class_name == self.class_name:
                    hwnd_list.append(hwnd)
            except Exception:
                pass

        hwnd_list = []
        win32gui.EnumWindows(enum_windows_callback, hwnd_list)

        if not hwnd_list:
            logger.warning(f"No matching window found for [{self.name}]")
            return False

        # Match by process path
        for hwnd in hwnd_list:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = psutil.Process(pid)
                exe_path = process.exe()
                if exe_path.lower() == self.path.lower():
                    self.hwnd = hwnd
                    self._set_foreground(hwnd)
                    return True
            except Exception:
                continue

        # Fallback: use first matching hwnd
        self.hwnd = hwnd_list[0]
        self._set_foreground(hwnd_list[0])
        return True

    @staticmethod
    def _set_foreground(hwnd: int):
        """Set window to foreground with Alt-key bypass."""
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        SW_MINIMIZE = 6
        SW_RESTORE = 9

        # Bypass foreground lock
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)

        if ctypes.windll.user32.SetForegroundWindow(hwnd) == 0:
            logger.warning(f"Foreground set failed, trying minimize-restore")
            ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.5)
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            ctypes.windll.user32.SetForegroundWindow(hwnd)


class LauncherProcess(_Process):
    """Manages the NIKKE launcher process and login flow."""

    def __init__(self, launcher_path: str, launcher_process: str):
        super().__init__("Launcher", "TWINCONTROL", launcher_process, launcher_path)

    def login(self, config: object, stop_event=None) -> bool:
        """Run OCR-based auto-login via launcher."""
        stop_event_check = stop_event
        if stop_event_check and stop_event_check.is_set():
            logger.info("Login skipped — stop requested")
            return False

        cap = CaptureMethod("TWINCONTROL", self.path)
        inp = Input()
        config_name = getattr(config, 'account_config', 'enikk') if config else 'enikk'

        account, password = load_account(config_name)
        if not account or not password:
            logger.warning(f"No account found for config '{config_name}', skipping login")
            return False

        login_flow = LauncherLogin(cap, inp)
        if login_flow.login(stop_event_check):
            logger.info("Login flow completed successfully")
            return True
        else:
            logger.warning("Login flow failed, continuing anyway...")
            return False


class GameProcess(_Process):
    """Manages the NIKKE game process."""

    def __init__(self, game_path: str, game_process: str, window_class: str = "UnityWndClass"):
        super().__init__("Game", window_class, game_process, game_path)
        self.window_class = window_class


class ProcessManager:
    """Orchestrates the full launch flow: Launcher → Login → Game."""

    def __init__(
        self,
        launcher_path: str,
        game_path: str,
        launcher_process: str,
        game_process: str,
        window_class: str = "UnityWndClass",
        timeout: int = 120,
    ):
        self.launcher = LauncherProcess(launcher_path, launcher_process)
        self.game = GameProcess(game_path, game_process, window_class)
        self.timeout = timeout
        self._last_error: str = ""
        self._stop_event = None

    @property
    def last_error(self) -> str:
        """Last error message from launch flow."""
        return self._last_error

    @property
    def is_game_running(self) -> bool:
        return self.game.is_running()

    @property
    def is_launcher_running(self) -> bool:
        return self.launcher.is_running()

    def get_process(self, process_name: str):
        """Get psutil.Process object for a running process."""
        if process_name == self.launcher.process:
            return self.launcher.get_process()
        if process_name == self.game.process:
            return self.game.get_process()
        # Fallback: search by name
        try:
            system_username = os.getlogin()
        except Exception:
            import getpass
            system_username = getpass.getuser()

        for proc in psutil.process_iter(['pid', 'name', 'username']):
            try:
                proc_name = proc.info['name'] or ''
                if process_name.lower() in proc_name.lower():
                    proc_user = (proc.info['username'] or '').split('\\')[-1]
                    if system_username == proc_user:
                        return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    # ── Main launch flow ──────

    def app_start(self, config: object = None, skip_login: bool = False,
                  stop_event: object = None) -> bool:
        """
        Full launch flow: Launcher → Login → Game.

        Args:
            config: Config object for auto-login settings.
            skip_login: If True, skip the OCR auto-login step.
            stop_event: threading.Event to signal early termination.
        """
        logger.info("Game starting")
        self._stop_event = stop_event
        MAX_RETRY = 3

        for retry in range(MAX_RETRY):
            if stop_event and stop_event.is_set():
                logger.info("Launch cancelled by stop signal")
                self._last_error = "Cancelled"
                return False

            try:
                # Step 1: Check if game is already running
                if self.game.is_running():
                    logger.info("Game is already running")
                    if self.game.switch_to():
                        logger.info("Game window focused")
                        return True
                    else:
                        self._last_error = "Game running but window not found"
                        logger.warning("Game running but window not found, restarting...")
                        self.game.stop()

                # Step 2: Launch launcher
                if not self.launcher.switch_to() and not self.launcher.start():
                    self._last_error = "Launcher failed to start"
                    logger.error("Launcher failed to start")
                    continue

                # Step 3: Wait for launcher to appear
                if not self._wait_until(lambda: self.launcher.switch_to(), timeout=30):
                    self._last_error = "Timeout waiting for launcher"
                    logger.error("Timeout waiting for launcher")
                    continue

                logger.info("Launcher opened successfully")

                # Step 4: Login (skip if auto-login is enabled)
                if not skip_login:
                    self.launcher.login(config, stop_event)

                # Step 5: Wait for game process to appear
                logger.info("Waiting for game process...")
                if not self._wait_until(self.game.is_running, timeout=60):
                    self._last_error = "Timeout waiting for game process"
                    logger.error("Timeout waiting for game process")
                    continue

                # Step 6: Switch to game window
                if not self._wait_until(self.game.switch_to, timeout=60):
                    self._last_error = "Timeout switching to game window"
                    logger.error("Timeout switching to game window")
                    continue

                logger.info("Game started successfully")
                return True

            except Exception as e:
                self._last_error = f"Startup error: {e}"
                logger.error(f"Startup error: {e}, retrying {retry + 1}/{MAX_RETRY}")
                self.game.stop()
                if self.launcher.is_running():
                    self.launcher.stop()
                time.sleep(5)

        self._last_error = "Failed to start game after 3 retries"
        logger.error("Failed to start game after 3 retries")
        return False

    def _wait_until(self, condition, timeout: int, period: float = 1.0) -> bool:
        """Wait until condition is true, stop_event is set, or timeout."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self._stop_event and self._stop_event.is_set():
                return False
            if condition():
                return True
            time.sleep(period)
        return False
