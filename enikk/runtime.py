"""Enikk game runtime orchestration."""
from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time
import uuid
from collections.abc import Callable

import cv2
import numpy as np
from websockets import ServerConnection

from . import analyzer
from .agent.manager import AgentManager
from .config import Config, GameConfig
from .game import capture, input as input_mod, process, window
from .runtimes.nikke import nikke_profile_from_config
from .runtimes.profile import GameProfile
from .ui_parser import MAX_DIM, UIParser
from .ws_server import WsServer

logger = logging.getLogger(__name__)
DEFAULT_MAX_DIM = 1366

_rpc_registry: dict[str, Callable[..., object]] = {}


def rpc(method: str):
    """Decorator: register a GameRuntime method as JSON-RPC handler."""

    def decorator(fn):
        _rpc_registry[method] = fn
        return fn

    return decorator


def profile_from_config(config: Config) -> GameProfile:
    return nikke_profile_from_config(config)


class GameRuntime:
    """Stateful orchestrator for one game runtime."""

    def __init__(self, config: Config):
        self.config = config
        self.profile = profile_from_config(config)

        gc = config.games.get("nikke", GameConfig())
        self.process_manager = process.GameProcessManager(
            self.profile,
            timeout=gc.launch_timeout,
        )
        self.window_service = window.WindowService()
        self.capture_service = capture.CaptureService(self.window_service)
        self.input_service = input_mod.InputService(self.window_service)

        self.max_dim = MAX_DIM
        self.ui_parser = UIParser(config.workspace.weights_dir)

        self.game_hwnd: int | None = None
        self.launcher_hwnd: int | None = None
        self._latest_state: analyzer.GameState | None = None
        self._lock = threading.Lock()
        self.stop_event = threading.Event()

        # Compatibility attributes for older call sites.
        self.proc_mgr = self.process_manager
        self.capture = self.capture_service
        self.input = self.input_service

        self._ws_server: WsServer | None = None
        self._agent_manager: AgentManager | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws_clients: set[ServerConnection] = set()

    def stop(self):
        logger.info("Stop requested, shutting down...")
        self.stop_event.set()

    def init(self, auto_launch: bool = False):
        if auto_launch:
            self.launch_and_wait()

    def get_game_hwnd(self) -> int | None:
        if self.window_service.is_valid(self.game_hwnd):
            return self.game_hwnd

        self.game_hwnd = self.window_service.find_by_path_and_class(
            self.profile.game_path,
            self.profile.game_window_class,
        )
        return self.game_hwnd

    def get_launcher_hwnd(self) -> int | None:
        if not self.profile.launcher_path:
            return None
        if self.window_service.is_valid(self.launcher_hwnd):
            return self.launcher_hwnd

        self.launcher_hwnd = self.window_service.find_by_path_and_class(
            self.profile.launcher_path,
            self.profile.launcher_window_class,
        )
        return self.launcher_hwnd

    def launch_and_wait(self) -> bool:
        pm = self.process_manager
        pm._last_error = ""

        if pm.game.is_running():
            hwnd = self.get_game_hwnd()
            if hwnd:
                self.window_service.force_foreground(hwnd)
                return True
            pm._last_error = "Game running but window not found"
            logger.warning("Game running but window not found, restarting...")
            pm.stop_game()

        starter = pm.launcher or pm.game
        if not starter.is_running() and not starter.start():
            pm._last_error = f"{starter.name} failed to start"
            return False

        if starter is pm.launcher:
            launcher_hwnd = self._wait_until_value(self.get_launcher_hwnd, timeout=30)
            if launcher_hwnd:
                self.window_service.force_foreground(launcher_hwnd)

        gc = self.config.games.get("nikke", GameConfig())
        if not self._wait_until(pm.game.is_running, timeout=gc.launch_timeout):
            pm._last_error = "Timeout waiting for game process"
            logger.error(pm._last_error)
            return False

        game_hwnd = self._wait_until_value(self.get_game_hwnd, timeout=60)
        if not game_hwnd:
            pm._last_error = "Timeout waiting for game window"
            logger.error(pm._last_error)
            return False

        self.window_service.force_foreground(game_hwnd)
        logger.info("Game started successfully")
        return True

    def _wait_until(self, condition, timeout: int, period: float = 1.0) -> bool:
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.stop_event.is_set():
                self.process_manager._last_error = "Cancelled"
                return False
            if condition():
                return True
            time.sleep(period)
        return False

    def _wait_until_value(self, getter, timeout: int, period: float = 1.0):
        end_time = time.time() + timeout
        while time.time() < end_time:
            if self.stop_event.is_set():
                self.process_manager._last_error = "Cancelled"
                return None
            value = getter()
            if value:
                return value
            time.sleep(period)
        return None

    def analyze(self, frame: np.ndarray | None = None) -> analyzer.GameState:
        """Capture screenshot, compress, run UI parser, return structured state."""
        if frame is None:
            hwnd = self.get_game_hwnd()
            if not hwnd:
                raise ValueError("Game window not found")
            frame = self.capture_service.capture(hwnd)
        if frame is None:
            raise ValueError("Failed to capture screenshot")

        h, w = frame.shape[:2]
        max_dim = getattr(self, "max_dim", DEFAULT_MAX_DIM)
        if w > max_dim or h > max_dim:
            scale = max_dim / max(w, h)
            compressed = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            compressed = frame

        _, buf = cv2.imencode(".jpeg", compressed)
        image_b64 = base64.b64encode(buf.tobytes()).decode()
        parsed = self.ui_parser.parse(frame)
        bbox_desc = (
            "All element bbox coordinates are normalized to [0, 1000] as "
            "[x1, y1, x2, y2], where (x1,y1) is top-left and (x2,y2) is "
            "bottom-right, as percentages of screen width and height."
        )

        state = analyzer.GameState(
            image_b64=image_b64,
            width=compressed.shape[1],
            height=compressed.shape[0],
            ocr=parsed,
            bbox_desc=bbox_desc,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        with self._lock:
            self._latest_state = state
        return state

    def action_click(self, x: int, y: int) -> dict:
        """Click at normalized [0, 1000] coordinates."""
        hwnd = self.get_game_hwnd()
        if not hwnd:
            return {"success": False, "error": "Game window not available"}
        return self.input_service.click_normalized(hwnd, x, y)

    def action_exit(self) -> dict:
        result = self.process_manager.stop_game()
        self._latest_state = None
        self.game_hwnd = None
        return {"success": result, "message": "Game terminated" if result else "Failed"}

    def dispatch(self, req: dict) -> dict:
        rid = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {}) or {}

        fn = _rpc_registry.get(method)
        if fn is None:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"unknown method: {method}"},
            }

        try:
            result = fn(self, rid, params)
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32000, "message": str(exc)},
            }

    @rpc("ping")
    def _ping(self, rid, params):
        return "pong"

    @rpc("connect")
    def _connect(self, rid, params):
        session_id = uuid.uuid4().hex[:12]
        logger.info("[ws] Client authenticated: %s (role=%s)", session_id, params.get("role", "unknown"))
        return {"ok": True, "session_id": session_id, "protocol": 1, "tick_interval_ms": 30000}

    @rpc("session.list")
    def _session_list(self, rid, params):
        return {"agents": []}

    @rpc("session.status")
    def _session_status(self, rid, params):
        return {"status": "idle"}

    @rpc("session.run")
    def _session_run(self, rid, params):
        return {"run_id": "stub", "status": "accepted"}

    @rpc("session.stop")
    def _session_stop(self, rid, params):
        return {"status": "stopped"}

    def start_ws(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._agent_manager = AgentManager(self, loop)
        self._agent_manager._ws_clients = self._ws_clients  # type: ignore[attr-defined]
        ws_port = self.config.server.ws_port

        async def _on_connect(ws: ServerConnection):
            self._ws_clients.add(ws)
            logger.info("[ws] Client registered (%d total)", len(self._ws_clients))

        async def _on_disconnect(ws: ServerConnection):
            self._ws_clients.discard(ws)
            logger.info("[ws] Client unregistered (%d total)", len(self._ws_clients))

        self._ws_server = WsServer(
            dispatcher=self,
            port=ws_port,
            on_connect=_on_connect,
            on_disconnect=_on_disconnect,
        )

        try:
            loop.run_until_complete(self._ws_server.serve_forever())
        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        self.stop_event.set()
        if self._agent_manager:
            self._agent_manager.shutdown()
        if self._ws_server:
            self._ws_server.shutdown()
        logger.info("Runtime shut down")


# Compatibility alias while callers migrate from daemon.Daemon.
Daemon = GameRuntime
