"""FastAPI HTTP server for Enikk."""
import asyncio
import base64
import json
import logging
import threading
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from typing import TYPE_CHECKING

import cv2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

if TYPE_CHECKING:
    from .daemon import Daemon

logger = logging.getLogger("enikk")


class ReadyMiddleware(BaseHTTPMiddleware):
    """Block requests while daemon is in launch+connect sequence."""
    _EXEMPT = {"/health", "/api/state", "/api/action/launch", "/api/action/exit"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path not in self._EXEMPT:
            # Check if daemon has captured at least once
            if not getattr(daemon, '_latest_state', None):
                return Response(
                    content=json.dumps({"error": "daemon not ready — waiting for game launch"}),
                    status_code=503,
                    media_type="application/json",
                )
        return await call_next(request)


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = (time.time() - start) * 1000
        logger.info(f"{request.method} {request.url.path} -> {response.status_code} {elapsed:.0f}ms")
        return response


def create_app(daemon: "Daemon") -> FastAPI:
    app = FastAPI(
        title="Enikk API",
        description="NIKKE 游戏状态监控 | NIKKE: Goddess of Victory Game State Monitor",
        version="0.1.0",
    )

    state = {"_launching": False}

    app.add_middleware(TimingMiddleware)
    app.add_middleware(ReadyMiddleware)

    # ── Health ──
    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ── State ──
    @app.get("/api/state")
    def get_state():
        """Get current game state (on-demand capture + analyze)."""
        state = daemon.analyze()
        return _state_to_dict(state)

    @app.get("/api/state/stream")
    async def state_stream():
        """Server-sent events for state updates."""
        last_state = None

        async def event_generator():
            nonlocal last_state
            while True:
                state = daemon.analyze()
                data = _state_to_dict(state)
                if data != last_state:
                    yield f"data: {json.dumps(data)}\n\n"
                    last_state = data
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # ── Screenshot ──
    @app.get("/api/screenshot")
    def get_screenshot(
        quality: int = Query(85, ge=1, le=100),
        format: str = Query("jpeg", pattern="^(jpeg|png)$"),
        debug: bool = Query(False),
    ):
        """Get latest captured screenshot."""
        frame = daemon.capture.capture()
        if frame is None:
            raise HTTPException(404, "No screenshot available")

        ext = ".jpg" if format == "jpeg" else ".png"
        encode_args = [cv2.IMWRITE_JPEG_QUALITY, quality] if format == "jpeg" else []
        _, buf = cv2.imencode(f".{ext.replace('.', '')}", frame, encode_args)
        return Response(buf.tobytes(), media_type=f"image/{ext.replace('.', '')}")

    @app.get("/api/screenshot/raw")
    def get_screenshot_raw():
        """Get raw screenshot as base64."""
        frame = daemon.capture.capture()
        if frame is None:
            raise HTTPException(404, "No screenshot available")
        _, buf = cv2.imencode(".png", frame)
        b64 = base64.b64encode(buf.tobytes()).decode()
        state = _state_to_dict(daemon.analyze(frame))
        return {"image": b64, "format": "png", "width": frame.shape[1], "height": frame.shape[0], "state": state}

    # ── Process Info ──
    @app.get("/api/process")
    def get_process_info():
        pm = daemon.proc_mgr
        proc = pm.get_process(pm.game_process)
        info = {
            "is_running": pm.is_game_running,
            "exe_path": pm.game_path,
            "window_class": pm.window_class,
        }
        if pm.is_game_running and proc:
            try:
                info["pid"] = proc.pid
                info["name"] = proc.name()
                info["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
            except Exception as e:
                info["error"] = str(e)
        return info

    # ── Actions ──
    @app.post("/api/action/launch")
    def launch_game():
        """Launch the game asynchronously."""
        if state["_launching"]:
            return {"success": False, "message": "Launch already in progress"}
        if daemon.proc_mgr.is_game_running:
            return {"success": False, "message": "Game already running"}

        state["_launching"] = True

        def _do_launch():
            try:
                result = daemon.launch_and_wait()
                if result:
                    logger.info("Game launched successfully")
                else:
                    logger.error(f"Game launch failed: {daemon.proc_mgr.last_error or 'unknown'}")
            finally:
                state["_launching"] = False

        thread = threading.Thread(target=_do_launch, daemon=True)
        thread.start()
        return {"success": True, "message": "Launch started"}

    @app.post("/api/action/screenshot")
    def trigger_screenshot():
        """Force a single screenshot capture + analyze."""
        frame = daemon.capture.capture()
        if frame is None:
            raise HTTPException(404, "Capture failed")
        analysis = _state_to_dict(daemon.analyze(frame))
        return {"success": True, "state": analysis}

    @app.post("/api/action/confirm")
    def action_confirm():
        """OCR find '确认' and click."""
        return daemon.action_confirm()

    @app.post("/api/action/connect")
    def action_connect():
        """OCR find '点击连接' and click."""
        return daemon.action_connect()

    @app.post("/api/action/click")
    def action_click(x: int = Query(), y: int = Query()):
        """Click at screen coordinates."""
        return daemon.action_click(x, y)

    @app.post("/api/action/esc")
    def action_esc():
        """Send ESC key."""
        return daemon.action_esc()

    @app.post("/api/action/exit")
    def action_exit():
        """Terminate game process."""
        return daemon.action_exit()

    # ── API Info ──
    @app.get("/api/info")
    def api_info():
        return {
            "name": "Enikk API",
            "version": "0.1.0",
            "endpoints": {
                "GET /health": "Health check",
                "GET /api/state": "Current game state",
                "GET /api/state/stream": "SSE state stream",
                "GET /api/screenshot": "Latest screenshot (JPEG)",
                "GET /api/screenshot/raw": "Raw screenshot base64",
                "GET /api/process": "Game process info",
                "POST /api/action/launch": "Launch game",
                "POST /api/action/screenshot": "Force capture + analyze",
                "POST /api/action/confirm": "OCR click '确认'",
                "POST /api/action/connect": "OCR click '点击连接'",
                "POST /api/action/click": "Click at (x, y)",
                "POST /api/action/esc": "Send ESC key",
                "POST /api/action/exit": "Terminate game",
            },
        }

    return app


def _state_to_dict(state):
    """Convert GameState to dict (handles both dataclass and dict)."""
    if hasattr(state, '__dict__'):
        return {k: v for k, v in state.__dict__.items() if not k.startswith('_')}
    return state
