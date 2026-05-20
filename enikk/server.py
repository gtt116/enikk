"""FastAPI HTTP server for Enikk."""
import asyncio
import json
import logging
import threading
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from typing import TYPE_CHECKING
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from .runtime import GameRuntime

logger = logging.getLogger(__name__)


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = (time.time() - start) * 1000
        logger.info(f"{request.method} {request.url.path} -> {response.status_code} {elapsed:.0f}ms")
        return response


def create_app(daemon: "GameRuntime") -> FastAPI:
    app = FastAPI(
        title="Enikk API",
        description="NIKKE 游戏状态监控 | NIKKE: Goddess of Victory Game State Monitor",
        version="0.1.0",
    )

    state = {"_launching": False}

    app.add_middleware(TimingMiddleware)

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
    def get_screenshot():
        """Compress screenshot, run UI parser, return base64 + structured data."""
        try:
            state = daemon.analyze()
        except ValueError:
            raise HTTPException(500, {
                "error": "capture_failed",
                "message": "Game window not found — is the game running and in the foreground?",
            })
        return {**_state_to_dict(state), "format": "jpeg"}

    # ── Process Info ──
    @app.get("/api/process")
    def get_process_info():
        pm = daemon.proc_mgr
        proc = pm.game.get_process()
        info = {
            "is_running": pm.is_game_running,
            "game_path": daemon.profile.game_path,
            "window_class": daemon.profile.game_window_class,
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

    @app.get("/api/action/click")
    def action_click(x: int = Query(), y: int = Query()):
        """Click at normalized [0, 1000] coordinates."""
        return daemon.action_click(x, y)

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
                "GET /api/screenshot": "Screenshot base64 + OCR + YOLO UI elements",
                "GET /api/process": "Game process info",
                "POST /api/action/launch": "Launch game",
                "POST /api/action/click": "Click at (x, y)",
                "POST /api/action/exit": "Terminate game",
            },
        }

    return app


def _state_to_dict(state):
    """Convert GameState to dict (handles both dataclass and dict)."""
    if hasattr(state, '__dict__'):
        return {k: v for k, v in state.__dict__.items() if not k.startswith('_')}
    return state
