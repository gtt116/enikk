"""Game process lifecycle management."""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import psutil

from ..runtimes.profile import GameProfile

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

    def start(self) -> bool:
        logger.info("Starting [%s]: [%s]", self.name, self.path)
        if not os.path.exists(self.path):
            logger.error("Path does not exist: %s", self.path)
            return False

        folder = str(Path(self.path).parent)
        try:
            subprocess.Popen(
                [self.path],
                cwd=folder,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            logger.info("[%s] started", self.name)
            return True
        except Exception as e:
            logger.error("subprocess.Popen failed: %s", e)
            return False

    def stop(self) -> bool:
        logger.info("Stopping [%s]: %s", self.name, self.process_name)
        proc = self.get_process()
        if not proc:
            return False
        try:
            logger.info("Killing %s (PID=%s)", proc.name(), proc.pid)
            proc.kill()
            proc.wait(timeout=10)
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
            return False


class GameProcessManager:
    """Launch and stop a game process, with optional launcher support."""

    def __init__(self, profile: GameProfile, timeout: int = 120):
        self.profile = profile
        self.timeout = timeout
        self.game = ManagedProcess("Game", profile.game_path)
        self.launcher = (
            ManagedProcess("Launcher", profile.launcher_path)
            if profile.launcher_path
            else None
        )
        self._last_error = ""
        self._stop_event: threading.Event | None = None

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def is_game_running(self) -> bool:
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

    def launch(self, stop_event: threading.Event | None = None) -> bool:
        """Launch game directly or through its launcher."""
        self._stop_event = stop_event
        self._last_error = ""

        if self.game.is_running():
            logger.info("Game is already running")
            return True

        starter = self.launcher or self.game
        if not starter.is_running() and not starter.start():
            self._last_error = f"{starter.name} failed to start"
            return False

        if starter is self.game:
            if self._wait_until(self.game.is_running, timeout=self.timeout):
                return True
            self._last_error = "Timeout waiting for game process"
            return False

        logger.info("Waiting for game process...")
        if self._wait_until(self.game.is_running, timeout=self.timeout):
            return True

        self._last_error = "Timeout waiting for game process"
        logger.error(self._last_error)
        return False

    def app_start(self, stop_event: threading.Event | None = None) -> bool:
        """Backward-compatible alias for launch()."""
        return self.launch(stop_event=stop_event)

    def stop_game(self) -> bool:
        return self.game.stop()

    def stop_launcher(self) -> bool:
        return bool(self.launcher and self.launcher.stop())

    @property
    def game_process(self) -> str:
        return self.game.process_name

    @property
    def launcher_process(self) -> str | None:
        return self.launcher.process_name if self.launcher else None

    @property
    def game_path(self) -> str:
        return self.profile.game_path

    @property
    def launcher_path(self) -> str | None:
        return self.profile.launcher_path

    @property
    def window_class(self) -> str:
        return self.profile.game_window_class

    def _wait_until(self, condition, timeout: int, period: float = 1.0) -> bool:
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self._stop_event and self._stop_event.is_set():
                self._last_error = "Cancelled"
                return False
            if condition():
                return True
            time.sleep(period)
        return False
