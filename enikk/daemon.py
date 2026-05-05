"""Enikk daemon — game monitoring + analysis loop."""
import logging
import threading
import time

from .capture import CaptureMethod
from .config import Config
from .process import ProcessManager
from .analyzer import GameAnalyzer, GameState
from .input import Input

logger = logging.getLogger("enikk")


class Daemon:
    def __init__(self, config: Config):
        self.config = config
        self.proc_mgr = ProcessManager(
            launcher_path=config.launcher_path,
            game_path=config.game_path,
            launcher_process=config.launcher_process_name,
            game_process=config.game_process_name,
            window_class=config.window_class,
            timeout=config.launch_timeout,
        )
        self.capture = CaptureMethod(config.window_class, config.game_path)
        self.analyzer = GameAnalyzer(config.assets_dir) if hasattr(config, 'assets_dir') else GameAnalyzer()
        self.input = Input()
        self._latest_state: GameState | None = None
        self._lock = threading.Lock()
        self.stop_event = threading.Event()

    def stop(self):
        """Signal the daemon to stop all blocking operations."""
        logger.info("Stop requested, shutting down...")
        self.stop_event.set()
        if self.proc_mgr.is_game_running:
            logger.info("Terminating game process...")
            self.proc_mgr.game.stop()

    def init(self, auto_launch: bool = False):
        """Initialize the daemon."""
        if auto_launch:
            self.launch_and_wait()

    def launch_and_wait(self) -> bool:
        """Full launch flow: Launcher → Login → Game."""
        return self.proc_mgr.app_start(config=self.config, stop_event=self.stop_event)

    def analyze(self) -> GameState:
        """Capture + analyze current game state."""
        frame = self.capture.capture()
        if frame is None:
            state = GameState(
                game_state="not_running",
                state_reason="capture_failed",
                actions=["launch_game"],
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            self._latest_state = state
            return state

        state = self.analyzer.analyze(frame)
        with self._lock:
            self._latest_state = state
        return state

    # ── Actions ──

    def action_confirm(self) -> dict:
        """Click center-bottom (common confirm position)."""
        frame = self.capture.capture()
        if frame is None:
            return {"success": False, "message": "Capture failed"}
        h, w = frame.shape[:2]
        x, y = w // 2, int(h * 0.85)
        self.input.mouse_click(x, y)
        return {"success": True, "x": x, "y": y}

    def action_connect(self) -> dict:
        """Click center (common login position)."""
        frame = self.capture.capture()
        if frame is None:
            return {"success": False, "message": "Capture failed"}
        h, w = frame.shape[:2]
        x, y = w // 2, int(h * 0.75)
        self.input.mouse_click(x, y)
        return {"success": True, "x": x, "y": y}

    def action_click(self, x: int, y: int) -> dict:
        """Click at screen coordinates."""
        self.input.mouse_click(x, y)
        return {"success": True, "x": x, "y": y}

    def action_esc(self) -> dict:
        """Send ESC key."""
        self.input.press_key("esc")
        return {"success": True}

    def action_exit(self) -> dict:
        """Force-terminate the game process."""
        result = self.proc_mgr.game.stop()
        self._latest_state = None
        return {"success": result, "message": "Game terminated" if result else "Failed"}
