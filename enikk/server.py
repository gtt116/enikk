"""FastAPI HTTP server for Enikk."""
import json
import logging
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import enikk_home
from .eternity import Eternity

logger = logging.getLogger(__name__)


class Non200AccessFilter(logging.Filter):
    """Filter to only show non-200 access logs."""
    def filter(self, record):
        msg = record.getMessage()
        # Check if message ends with " 200" (200 status at end of line)
        return not msg.endswith(" 200")


class IMTestRequest(BaseModel):
    """Request model for IM connection test."""
    platform: str
    token: str
    extra: dict = {}


def start_server(
    app: FastAPI,
    host: str = "127.0.0.1",
    port: int = 0,
    timeout_graceful_shutdown: int = 2,
) -> tuple[threading.Thread, int]:
    """Start uvicorn in a background thread and return (thread, actual_port).

    When port=0 the OS assigns a random available port. This function blocks
    until the server is ready before returning.
    """
    # Filter out 200 status access logs to reduce noise
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(Non200AccessFilter())

    server = uvicorn.Server(
        config=uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="info",
            timeout_graceful_shutdown=timeout_graceful_shutdown,
            log_config=None,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    while not server.started:
        time.sleep(0.1)

    actual_port = server.servers[0].sockets[0].getsockname()[1]
    return thread, actual_port



def create_app(eternity: Eternity, im_bridge=None) -> FastAPI:
    app = FastAPI(
        title="Enikk API",
        description="Enikk: Self-improving GUI Agent.",
        version="0.1.0",
    )

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/")
        def index():
            return FileResponse(str(static_dir / "index.html"))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/sessions")
    def list_sessions(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return eternity.list_sessions(limit=limit, offset=offset)

    class CreateSessionRequest(BaseModel):
        task: str

    class SteerRequest(BaseModel):
        message: str

    @app.post("/api/sessions")
    def create_session(req: CreateSessionRequest):
        try:
            session_id = eternity.create_session(task=req.task)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"session_id": session_id}

    @app.post("/api/sessions/{session_id}/steer")
    def steer_session(session_id: str, req: SteerRequest):
        try:
            if not eternity.steer_session(session_id, req.message):
                raise HTTPException(status_code=404, detail="Session not found")
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "steered"}

    @app.post("/api/sessions/{session_id}/stop")
    def stop_session(session_id: str):
        if not eternity.stop_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found or not running")
        return {"status": "stopped"}

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str):
        if not eternity.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "deleted"}

    @app.get("/api/sessions/{session_id}/messages")
    def get_session_messages(
        session_id: str,
        limit: int = Query(100, ge=1, le=500),
        before_id: str | None = Query(None),
    ):
        return eternity.get_session_messages(session_id, limit=limit, before_id=before_id)

    @app.get("/api/sessions/{session_id}/stream")
    async def stream_session(session_id: str):
        async def event_generator():
            try:
                async for event in eternity.get_session_stream(session_id):
                    yield f"data: {json.dumps(event)}\n\n"
            except Exception as e:
                logger.error(f"Stream error for session {session_id}: {e}")
                yield f"data: {json.dumps({'event': 'error', 'data': {'message': str(e)}})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    @app.get("/api/images")
    def get_image(path: str = Query(...)):
        p = Path(path).resolve()
        allowed_root = Path(eternity.config.workspace.screenshot_dir).resolve()
        if not p.is_relative_to(allowed_root):
            raise HTTPException(status_code=403, detail="Access denied")
        if not p.exists():
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(str(p))

    @app.get("/api/open_dir")
    def open_dir(name: str = Query(None, description="Directory name: 'home' or 'logs'"), path: str = Query(None, description="Arbitrary directory path to open")):
        """Open a directory in file explorer."""
        import os
        import subprocess
        import platform

        if path:
            target = Path(path).resolve()
            if not target.is_dir():
                raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
        else:
            base_dir = enikk_home()
            dirs = {
                "home": base_dir,
                "logs": base_dir / "logs",
            }
            result = dirs.get(name)
            if not result:
                raise HTTPException(status_code=400, detail=f"Unknown directory: {name}. Available: {list(dirs.keys())}")
            target = result
            target.mkdir(parents=True, exist_ok=True)

        if platform.system() == "Windows":
            os.startfile(str(target))
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(target)])
        else:
            subprocess.run(["xdg-open", str(target)])

        return {"status": "opened", "path": str(target)}

    @app.get("/api/status")
    async def status():
        """Get system status (icon finder, IM, etc.)."""
        # Icon finder status
        icon_finder_available = eternity.get_icon_finder_available()

        # OCR status
        ocr_available = eternity.get_ocr_available()

        # IM status
        if im_bridge is None:
            im_status = {"enabled": False, "connected": False, "platform": None, "message": "IM bridge not configured"}
        else:
            connected = im_bridge.is_connected()
            platform_name = im_bridge.get_platform_name()
            message = "IM connected" if connected else "IM disconnected"
            im_status = {
                "enabled": im_bridge.is_enabled(),
                "connected": connected,
                "platform": platform_name,
                "message": message,
            }

        return {
            "icon_finder": {
                "available": icon_finder_available,
                "message": "Icon finder ready" if icon_finder_available else "Icon finder model not loaded - icon detection disabled",
            },
            "ocr": {
                "available": ocr_available,
                "message": "OCR ready" if ocr_available else "OCR not loaded",
            },
            "im": im_status,
        }

    @app.get("/api/config")
    def get_config():
        """Get current configuration."""
        return eternity.config.to_dict()

    @app.put("/api/config")
    def update_config(data: dict):
        """Update configuration."""
        try:
            eternity.config.update_from_dict(data)
            eternity.config.save()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "updated"}

    @app.get("/api/apps")
    def list_apps():
        """List all registered apps."""
        apps = []
        for name, ac in eternity.config.apps.items():
            apps.append({
                "name": name,
                "app_path": ac.app_path,
                "launcher_path": ac.launcher_path,
                "launch_timeout": ac.launch_timeout,
            })
        return {"apps": apps}

    @app.post("/api/apps")
    def register_app(data: dict):
        """Register or update an app."""
        name = data.get("name", "").strip()
        app_path = data.get("app_path", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        if not app_path:
            raise HTTPException(status_code=400, detail="app_path is required")

        # Check if app already exists
        if name in eternity.config.apps:
            # Update existing app
            update_data = {"app_path": app_path}
            if "launcher_path" in data:
                update_data["launcher_path"] = data["launcher_path"]
            if "launch_timeout" in data:
                update_data["launch_timeout"] = int(data["launch_timeout"])
            ac = eternity.config.update_app(name, **update_data)
            if not ac:
                raise HTTPException(status_code=404, detail=f"App not found: {name}")
            return {"status": "updated", "app": {
                "name": ac.name,
                "app_path": ac.app_path,
                "launcher_path": ac.launcher_path,
                "launch_timeout": ac.launch_timeout,
            }}
        else:
            # Register new app
            ac = eternity.config.register_app(name, app_path)
            if "launcher_path" in data and data["launcher_path"]:
                ac.launcher_path = data["launcher_path"]
            if "launch_timeout" in data:
                ac.launch_timeout = int(data["launch_timeout"])
            return {"status": "registered", "app": {
                "name": ac.name,
                "app_path": ac.app_path,
                "launcher_path": ac.launcher_path,
                "launch_timeout": ac.launch_timeout,
            }}

    @app.delete("/api/apps/{name}")
    def delete_app(name: str):
        """Delete an app."""
        if eternity.config.delete_app(name):
            return {"status": "deleted", "name": name}
        raise HTTPException(status_code=404, detail=f"App not found: {name}")

    @app.put("/api/apps/{name}")
    def update_app(name: str, data: dict):
        """Update an existing app."""
        if name not in eternity.config.apps:
            raise HTTPException(status_code=404, detail=f"App not found: {name}")
        update_data = {}
        if "app_path" in data:
            update_data["app_path"] = data["app_path"].strip()
        if "launcher_path" in data:
            update_data["launcher_path"] = data["launcher_path"]
        if "launch_timeout" in data:
            update_data["launch_timeout"] = int(data["launch_timeout"])
        ac = eternity.config.update_app(name, **update_data)
        if not ac:
            raise HTTPException(status_code=400, detail="Update failed")
        return {"status": "updated", "app": {
            "name": ac.name,
            "app_path": ac.app_path,
            "launcher_path": ac.launcher_path,
            "launch_timeout": ac.launch_timeout,
        }}



    @app.post("/api/model/test")
    async def test_model_connection(req: dict):
        """Test LLM API connection with given credentials."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise HTTPException(status_code=500, detail="openai not installed")

        api_key = req.get("api_key", "")
        model_name = req.get("default", "")
        if not api_key:
            return {"status": "failed", "message": "API Key is required"}
        if not model_name:
            return {"status": "failed", "message": "Model name is required"}

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=req.get("base_url") or None,
        )

        try:
            await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=1,
            )
            return {"status": "success", "message": f"Connected to {model_name}"}
        except Exception as e:
            return {"status": "failed", "message": str(e)}

    @app.post("/api/im/test")
    async def test_im_connection(req: IMTestRequest):
        """Test IM platform connection with given credentials."""
        try:
            from gateway.config import Platform, PlatformConfig
        except ImportError:
            raise HTTPException(status_code=500, detail="hermes gateway not available")

        try:
            platform = Platform(req.platform)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown platform: {req.platform}")

        pcfg = PlatformConfig(
            enabled=True,
            token=req.token,
            extra=req.extra,
        )

        # Create adapter using same logic as IMBridge
        from .im_bridge import IMBridge
        temp_bridge = IMBridge(eternity.config, eternity)
        adapter = temp_bridge._create_adapter(platform, pcfg)
        if not adapter:
            raise HTTPException(status_code=400, detail=f"Unsupported platform: {req.platform}")

        try:
            connected = await adapter.connect()
            if connected:
                await adapter.disconnect()
                return {"status": "success", "message": f"Connected to {req.platform}"}
            else:
                # Read error info stored by adapter
                err_msg = getattr(adapter, '_fatal_error_message', '') or 'Connection failed'
                return {"status": "failed", "message": err_msg}
        except Exception as e:
            logger.warning("IM test connection error: %s", e)
            return {"status": "error", "message": str(e)}

    return app