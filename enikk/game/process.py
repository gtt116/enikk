"""App process lifecycle management."""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
from pathlib import Path

import psutil
import win32con
import win32gui
import win32process

from ..config import AppConfig

logger = logging.getLogger(__name__)


def _current_username() -> str:
    try:
        return os.getlogin()
    except Exception:
        return getpass.getuser()


class ManagedProcess:
    """Stateless process operations for one executable."""

    def __init__(self, name: str, exe_path: str):
        self.name = name
        self.path = os.path.normpath(exe_path)
        self.process_name = Path(self.path).name
        self.process = self.process_name

    def is_running(self) -> bool:
        return self.get_process() is not None

    def get_process(self):
        system_username = _current_username()
        for proc in psutil.process_iter(["pid", "name", "username"]):
            try:
                proc_name = proc.info["name"] or ""
                if self.process_name.lower() != proc_name.lower():
                    continue
                proc_user = (proc.info["username"] or "").split("\\")[-1]
                if system_username == proc_user:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def start(self) -> str | None:
        """Start the process.

        Returns:
            None on success, or an error message string on failure.
        """
        logger.info("Starting [%s]: [%s]", self.name, self.path)
        if not os.path.exists(self.path):
            err = f"Path does not exist: {self.path}"
            logger.error(err)
            return err

        folder = str(Path(self.path).parent)
        try:
            subprocess.Popen(
                [self.path],
                cwd=folder,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            logger.info("[%s] started", self.name)
            return None
        except Exception as e:
            logger.error("subprocess.Popen failed: %s", e)
            return str(e)

    def _find_windows_by_pid(self, pid: int) -> list[int]:
        """Find all window handles owned by a process."""
        hwnds: list[int] = []

        def enum_callback(hwnd: int, _):
            try:
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid and win32gui.IsWindowVisible(hwnd):
                    hwnds.append(hwnd)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(enum_callback, None)
        return hwnds

    def _send_close_message(self, proc: psutil.Process) -> bool:
        """Try to gracefully close process via WM_CLOSE to its windows.

        Returns True if any WM_CLOSE was sent.
        """
        hwnds = self._find_windows_by_pid(proc.pid)
        if not hwnds:
            return False
        sent = False
        for hwnd in hwnds:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                sent = True
                logger.info("Sent WM_CLOSE to window 0x%x of %s", hwnd, proc.name())
            except Exception as e:
                logger.debug("PostMessage WM_CLOSE failed for hwnd 0x%x: %s", hwnd, e)
        return sent

    def stop(self, graceful_timeout: float = 10.0, force_timeout: float = 5.0) -> bool:
        """Stop the process with graceful degradation.

        Strategy:
          1. WM_CLOSE — ask windows to close (most graceful)
          2. terminate() — SIGTERM signal
          3. kill() — force kill as last resort

        Args:
            graceful_timeout: Seconds to wait after WM_CLOSE before escalating.
            force_timeout: Seconds to wait after terminate() before kill().
        """
        logger.info("Stopping [%s]: %s", self.name, self.process_name)
        proc = self.get_process()
        if not proc:
            logger.info("[%s] not running, nothing to stop", self.name)
            return False

        pid = proc.pid

        # Stage 1: WM_CLOSE — most graceful
        try:
            if self._send_close_message(proc):
                logger.info("[%s] WM_CLOSE sent, waiting %.1fs for graceful exit", self.name, graceful_timeout)
                try:
                    proc.wait(timeout=graceful_timeout)
                    logger.info("[%s] exited gracefully after WM_CLOSE", self.name)
                    return True
                except psutil.TimeoutExpired:
                    logger.info("[%s] did not exit after WM_CLOSE, escalating", self.name)
        except psutil.NoSuchProcess:
            return True

        # Stage 2: terminate() — SIGTERM
        try:
            proc = psutil.Process(pid)  # refresh
            logger.info("[%s] sending terminate()", self.name)
            proc.terminate()
            try:
                proc.wait(timeout=force_timeout)
                logger.info("[%s] exited after terminate()", self.name)
                return True
            except psutil.TimeoutExpired:
                logger.info("[%s] did not exit after terminate(), escalating to kill()", self.name)
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied:
            logger.warning("[%s] terminate() access denied, escalating to kill()", self.name)

        # Stage 3: kill() — force kill
        try:
            proc = psutil.Process(pid)  # refresh
            logger.warning("[%s] force killing (PID=%s)", self.name, pid)
            proc.kill()
            proc.wait(timeout=5)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as e:
            logger.error("[%s] kill() failed: %s", self.name, e)
            return False


class AppProcessManager:
    """Launch and stop an app process, with optional launcher support."""

    def __init__(self, profile: AppConfig, timeout: int = 120):
        self.profile = profile
        self.timeout = timeout
        self.game = ManagedProcess("Game", profile.app_path)
        self.launcher = (
            ManagedProcess("Launcher", profile.launcher_path)
            if profile.launcher_path
            else None
        )

    @property
    def is_app_running(self) -> bool:
        return self.game.is_running()

    @property
    def is_launcher_running(self) -> bool:
        return bool(self.launcher and self.launcher.is_running())

    def get_process(self, process_name: str):
        if process_name.lower() == self.game.process_name.lower():
            return self.game.get_process()
        if self.launcher and process_name.lower() == self.launcher.process_name.lower():
            return self.launcher.get_process()

        system_username = _current_username()
        for proc in psutil.process_iter(["pid", "name", "username"]):
            try:
                proc_name = proc.info["name"] or ""
                if process_name.lower() != proc_name.lower():
                    continue
                proc_user = (proc.info["username"] or "").split("\\")[-1]
                if system_username == proc_user:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def stop_app(self) -> bool:
        return self.game.stop()

    def stop_launcher(self) -> bool:
        return bool(self.launcher and self.launcher.stop())

    @property
    def app_process(self) -> str:
        return self.game.process_name

    @property
    def launcher_process(self) -> str | None:
        return self.launcher.process_name if self.launcher else None

    @property
    def app_path(self) -> str:
        return self.profile.app_path

    @property
    def launcher_path(self) -> str | None:
        return self.profile.launcher_path
