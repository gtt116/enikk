"""Game process management — reference: NIKKEAutoScript app_control.py + login.py."""
import ctypes
import logging
import os
import subprocess
import time
from dataclasses import dataclass

import psutil

logger = logging.getLogger("enikk")


@dataclass
class Window:
    """Unified window representation (reference: NIKKEAutoScript)."""
    name: str
    title: str
    class_name: str
    process: str
    path: str
    hwnd: int = 0


class ProcessManager:
    def __init__(
        self,
        launcher_path: str,
        game_path: str,
        launcher_process: str,
        game_process: str,
        launcher_title: str,
        game_title: str,
        window_class: str = "UnityWndClass",
        timeout: int = 120,
    ):
        self.launcher_path = os.path.normpath(launcher_path)
        self.game_path = os.path.normpath(game_path)
        self.launcher_process = launcher_process  # e.g., 'nikke_launcher.exe'
        self.game_process = game_process          # e.g., 'nikke.exe'
        self.launcher_title = launcher_title
        self.game_title = game_title
        self.window_class = window_class
        self.timeout = timeout

        self.launcher = Window(
            name="Launcher",
            title=launcher_title,
            class_name="TWINCONTROL",
            process=launcher_process,
            path=self.launcher_path,
        )
        self.game = Window(
            name="Game",
            title=game_title,
            class_name=window_class,
            process=game_process,
            path=self.game_path,
        )
        self.current_window = self.game
        self._last_error: str = ""

    @property
    def last_error(self) -> str:
        """Last error message from launch flow."""
        return self._last_error

    # ── Process checks ────────────────────────────────────────────────

    def is_process_running(self, process_name: str) -> bool:
        """Check if a process is running (current user only)."""
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
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    @property
    def is_game_running(self) -> bool:
        return self.is_process_running(self.game_process)

    @property
    def is_launcher_running(self) -> bool:
        return self.is_process_running(self.launcher_process)

    def get_process(self, process_name: str):
        """Get psutil.Process object for a running process."""
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

    # ── Launch / Stop ─────────────────────────────────────────────────

    def start_program(self, window: Window) -> bool:
        """Start a program (reference: NIKKEAutoScript start_program)."""
        logger.info(f"Starting [{window.name}]: [{window.path}]")
        if not os.path.exists(window.path):
            logger.error(f"Path does not exist: {window.path}")
            return False

        folder = window.path.rpartition('\\')[0]
        try:
            # Method 1: cmd /C start
            if os.system(f'cmd /C start "" /D "{folder}" "{window.path}"') == 0:
                logger.info(f"[{window.name}] started via cmd /C start")
                return True
        except Exception as e:
            logger.error(f"cmd start failed: {e}")

        # Method 2: subprocess.Popen
        try:
            subprocess.Popen(
                [window.path],
                cwd=folder,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            logger.info(f"[{window.name}] started via subprocess.Popen")
            return True
        except Exception as e:
            logger.error(f"subprocess.Popen failed: {e}")

        return False

    def stop_program(self, window: Window) -> bool:
        """Terminate a program (current user only)."""
        logger.info(f"Stopping [{window.name}]: {window.process}")
        killed_any = False
        try:
            system_username = os.getlogin()
        except Exception:
            import getpass
            system_username = getpass.getuser()

        for proc in psutil.process_iter(['pid', 'name', 'username']):
            try:
                proc_name = proc.info['name'] or ''
                if window.process.lower() in proc_name.lower():
                    proc_user = (proc.info['username'] or '').split('\\')[-1]
                    if system_username == proc_user:
                        logger.info(f"Killing {proc_name} (PID={proc.pid})")
                        proc.kill()
                        proc.wait(timeout=10)
                        killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass
        return killed_any

    # ── Window management ─────────────────────────────────────────────

    def switch_to_program(self) -> bool:
        """Switch the current window to foreground (reference: set_foreground_window_with_retry)."""
        import win32gui
        import win32process

        self.current_window.hwnd = 0

        def enum_windows_callback(hwnd, hwnd_list):
            try:
                title = win32gui.GetWindowText(hwnd)
                class_name = win32gui.GetClassName(hwnd)
                if not title or not win32gui.IsWindowVisible(hwnd):
                    return
                if (class_name == self.current_window.class_name and
                        title == self.current_window.title):
                    hwnd_list.append(hwnd)
            except Exception:
                pass

        hwnd_list = []
        win32gui.EnumWindows(enum_windows_callback, hwnd_list)

        if not hwnd_list:
            logger.warning(f"No matching window found for [{self.current_window.name}]")
            return False

        # Match by process path
        for hwnd in hwnd_list:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = psutil.Process(pid)
                exe_path = process.exe()
                if exe_path.lower() == self.current_window.path.lower():
                    self.current_window.hwnd = hwnd
                    self._set_foreground(hwnd)
                    return True
            except Exception:
                continue

        # Fallback: use first matching hwnd
        self.current_window.hwnd = hwnd_list[0]
        self._set_foreground(hwnd_list[0])
        return True

    def _set_foreground(self, hwnd: int):
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

    # ── Main launch flow (reference: NIKKEAutoScript app_start) ───────

    def app_start(self, skip_login: bool = False) -> bool:
        """
        Full launch flow: Launcher → Login → Game.
        Does NOT change resolution (unlike NIKKEAutoScript).
        """
        logger.info("Game starting")
        MAX_RETRY = 3

        for retry in range(MAX_RETRY):
            try:
                # Step 1: Check if game is already running
                if self.is_game_running:
                    logger.info("Game is already running")
                    self.current_window = self.game
                    if self.switch_to_program():
                        logger.info("Game window focused")
                        return True
                    else:
                        self._last_error = "Game running but window not found"
                        logger.warning("Game running but window not found, restarting...")
                        self.stop_program(self.game)

                # Step 2: Launch launcher
                self.current_window = self.launcher
                if not self.switch_to_program() and not self.start_program(self.launcher):
                    self._last_error = "Launcher failed to start"
                    logger.error("Launcher failed to start")
                    continue

                # Step 3: Wait for launcher to appear
                if not self._wait_until(lambda: self.switch_to_program(), timeout=30):
                    self._last_error = "Timeout waiting for launcher"
                    logger.error("Timeout waiting for launcher")
                    continue

                logger.info("Launcher opened successfully")

                # Step 4: Login (skip if auto-login is enabled)
                if not skip_login:
                    self._login_flow()

                # Step 5: Wait for game process to appear
                logger.info("Waiting for game process...")
                if not self._wait_until(lambda: self.is_game_running, timeout=60):
                    self._last_error = "Timeout waiting for game process"
                    logger.error("Timeout waiting for game process")
                    continue

                # Step 6: Switch to game window
                self.current_window = self.game
                if not self._wait_until(lambda: self.switch_to_program(), timeout=60):
                    self._last_error = "Timeout switching to game window"
                    logger.error("Timeout switching to game window")
                    continue

                logger.info("Game started successfully")
                return True

            except Exception as e:
                self._last_error = f"Startup error: {e}"
                logger.error(f"Startup error: {e}, retrying {retry + 1}/{MAX_RETRY}")
                self.current_window = self.game
                self.stop_program(self.game)
                if self.is_launcher_running:
                    self.current_window = self.launcher
                    self.stop_program(self.launcher)
                time.sleep(5)

        self._last_error = "Failed to start game after 3 retries"
        logger.error("Failed to start game after 3 retries")
        return False

    def _wait_until(self, condition, timeout: int, period: float = 1.0) -> bool:
        """Wait until condition is true or timeout."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            if condition():
                return True
            time.sleep(period)
        return False

    def _login_flow(self):
        """
        Login flow via launcher (simplified reference: login.py).
        Skips account/password input by default — assumes launcher auto-login or manual login.
        """
        logger.info("Login flow: waiting for launcher ready...")
        # In NIKKEAutoScript, this does OCR to find login fields and types credentials.
        # For now, we just wait for the launcher to be ready.
        # TODO: Add OCR-based auto-login if needed.
        time.sleep(5)

    def launch_game_only(self) -> bool:
        """Launch only the game process (bypass launcher, for when game is already logged in)."""
        if self.is_game_running:
            logger.info("Game already running")
            return True
        if not os.path.exists(self.game_path):
            logger.error(f"Game exe not found: {self.game_path}")
            return False

        folder = self.game_path.rpartition('\\')[0]
        try:
            if os.system(f'cmd /C start "" /D "{folder}" "{self.game_path}"') == 0:
                logger.info("Game started via cmd /C start")
                return self._wait_until(lambda: self.is_game_running, timeout=self.timeout)
        except Exception as e:
            logger.error(f"cmd start failed: {e}")

        try:
            subprocess.Popen([self.game_path], cwd=folder,
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            logger.info("Game started via subprocess.Popen")
            return self._wait_until(lambda: self.is_game_running, timeout=self.timeout)
        except Exception as e:
            logger.error(f"subprocess.Popen failed: {e}")
        return False
