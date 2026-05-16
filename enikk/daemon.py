"""Enikk daemon — game state capture, analysis, actions, agent + WebSocket."""
from __future__ import annotations

import asyncio
import base64
import logging
import threading
import time

import cv2
import numpy as np

from . import capture, process
from .config import Config
from . import analyzer
from . import input as input_mod
from .ui_parser import MAX_DIM, UIParser
from .ws_server import WsServer
from .agent.manager import AgentManager

logger = logging.getLogger("enikk")

# ── RPC registry ────────────────────────────────────────────────────────

_rpc_registry: dict[str, "callable"] = {}

def rpc(method: str):
    """Decorator: register a Daemon method as JSON-RPC handler."""
    def decorator(fn):
        _rpc_registry[method] = fn
        return fn
    return decorator


class Daemon:
    def __init__(self, config: Config):
        self.config = config
        self.proc_mgr = process.ProcessManager(
            launcher_path=config.launcher_path,
            game_path=config.game_path,
            launcher_process=config.launcher_process_name,
            game_process=config.game_process_name,
            window_class=config.window_class,
            timeout=config.launch_timeout,
        )
        self.capture = capture.CaptureMethod(config.window_class, config.game_path)
        self.input = input_mod.Input(hwnd=self.capture.hwnd)
        self.ui_parser = UIParser(getattr(config, 'weights_dir', None))
        self._latest_state: analyzer.GameState | None = None
        self._lock = threading.Lock()
        self.stop_event = threading.Event()

        # Subsystems (initialized in start())
        self._ws_server: WsServer | None = None
        self._agent_manager: AgentManager | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def stop(self):
        """Signal the daemon to stop."""
        logger.info("Stop requested, shutting down...")
        self.stop_event.set()

    def init(self, auto_launch: bool = False):
        """Initialize the daemon."""
        if auto_launch:
            self.launch_and_wait()

    def launch_and_wait(self) -> bool:
        """Full launch flow: Launcher → Login → Game."""
        return self.proc_mgr.app_start(stop_event=self.stop_event)

    def analyze(self, frame: np.ndarray | None = None) -> analyzer.GameState:
        """Capture screenshot, compress, run UI parser, return structured state."""
        h, w = frame.shape[:2]
        if w > MAX_DIM or h > MAX_DIM:
            scale = MAX_DIM / max(w, h)
            compressed = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            compressed = frame
        _, buf = cv2.imencode(".jpeg", compressed)
        image_b64 = base64.b64encode(buf.tobytes()).decode()

        parsed = self.ui_parser.parse(frame)

        bbox_desc = "All element bbox coordinates are normalized to [0, 1000] as [x1, y1, x2, y2], where (x1,y1) is top-left and (x2,y2) is bottom-right, as percentages of screen width and height."

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

    # ── Actions ──

    def action_click(self, x: int, y: int) -> dict:
        """Click at normalized [0, 1000] coordinates."""
        region = self.capture.get_region()
        if not region:
            return {"success": False, "error": "Game window region not available"}
        off_x, off_y, w, h = region
        self.input.set_hwnd(self.capture.hwnd)
        abs_x = off_x + int(x / 1000 * w)
        abs_y = off_y + int(y / 1000 * h)
        self.input.mouse_click(abs_x, abs_y)
        return {"success": True, "x": abs_x, "y": abs_y}

    def action_exit(self) -> dict:
        """Force-terminate the game process."""
        result = self.proc_mgr.game.stop()
        self._latest_state = None
        self.input.set_hwnd(None)
        return {"success": result, "message": "Game terminated" if result else "Failed"}

    # ── WebSocket + Agent ──

    def dispatch(self, req: dict) -> dict:
        """Handle one JSON-RPC request.  Implements :class:`ws_server.Dispatcher`."""
        rid = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {}) or {}

        fn = _rpc_registry.get(method)
        if fn is None:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"unknown method: {method}"}}

        try:
            result = fn(self, rid, params)
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": str(exc)}}

    @rpc("ping")
    def _ping(self, rid, params):
        return "pong"

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
        """Start WebSocket server and Agent manager (blocking)."""
        self._loop = loop
        self._agent_manager = AgentManager(self, loop)
        ws_port = getattr(self.config, 'ws_port', 18932)
        self._ws_server = WsServer(dispatcher=self, port=ws_port)

        try:
            loop.run_until_complete(self._ws_server.serve_forever())
        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        """Clean shutdown of all subsystems."""
        self.stop_event.set()
        if self._agent_manager:
            self._agent_manager.shutdown()
        if self._ws_server:
            self._ws_server.shutdown()
        logger.info("Daemon shut down")
