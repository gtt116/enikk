"""FastAPI HTTP server for Enikk."""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from hermes_cli.auth import PROVIDER_REGISTRY
from pydantic import BaseModel, Field, field_validator

from .config import enikk_home
from .eternity import Eternity
from .updater import UpdateInfo
from .version import __version__, __description__

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



def create_app(
    eternity: Eternity,
    im_bridge=None,
    get_update_info: Callable[[], UpdateInfo | None] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Enikk API",
        description=__description__,
        version=__version__,
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

    @app.get("/api/version")
    def get_version():
        return {"version": __version__}

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

    class RenameSessionRequest(BaseModel):
        title: str = Field(min_length=1, max_length=100)

        @field_validator("title")
        @classmethod
        def title_not_blank(cls, v: str) -> str:
            if not v.strip():
                raise ValueError("title must not be blank")
            return v

    @app.patch("/api/sessions/{session_id}")
    def rename_session(session_id: str, req: RenameSessionRequest):
        try:
            if not eternity.rename_session(session_id, req.title):
                raise HTTPException(status_code=404, detail="Session not found")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "renamed"}

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

        # Icon finder status
        icon_finder_available = eternity.get_icon_finder_available()
        icon_finder_dml = eternity.get_icon_finder_dml_enabled()

        # OCR status
        ocr_available = eternity.get_ocr_available()
        ocr_dml = eternity.get_ocr_dml_enabled()

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
                "dml": icon_finder_dml,
                "message": f"Icon finder ready ({'DML' if icon_finder_dml else 'CPU'})" if icon_finder_available else "Icon finder model not loaded - icon detection disabled",
            },
            "ocr": {
                "available": ocr_available,
                "dml": ocr_dml,
                "message": f"OCR ready ({'DML' if ocr_dml else 'CPU'})" if ocr_available else "OCR not loaded",
            },
            "im": im_status,
        }

    @app.get("/api/config")
    def get_config():
        """Get current configuration."""
        return eternity.config.to_dict()

    @app.get("/api/providers")
    def list_providers():
        """List available providers from hermes-agent."""
        providers = []
        # Built-in providers with api_key auth only
        for name, cfg in sorted(PROVIDER_REGISTRY.items()):
            if cfg.auth_type != "api_key":
                continue
            # Note: hermes builtin 'alibaba' uses international dashscope (dashscope-intl.aliyuncs.com)
            providers.append({
                "name": name,
                "display_name": name.replace("-", " ").title(),
                "base_url": cfg.inference_base_url or "",
                "auth_type": cfg.auth_type,
                "builtin": True,
            })

        # Add alibaba-cn (China region) after alibaba
        alibaba_cn = {
            "name": "alibaba-cn",
            "display_name": "Alibaba Cn",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "auth_type": "api_key",
            "builtin": True,
        }
        # Find position after alibaba
        insert_pos = None
        for i, p in enumerate(providers):
            if p["name"] == "alibaba":
                insert_pos = i + 1
                break
        if insert_pos is not None:
            providers.insert(insert_pos, alibaba_cn)
        else:
            providers.append(alibaba_cn)

        # Add Custom option at the end
        providers.append({
            "name": "custom",
            "display_name": "Custom",
            "base_url": "",
            "auth_type": "api_key",
            "builtin": False,
        })

        return {"providers": providers}

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
            ac = eternity.config.register_app(
                name,
                app_path,
                launcher_path=data.get("launcher_path") or None,
                launch_timeout=int(data["launch_timeout"]) if "launch_timeout" in data else 120,
            )
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

    # ── Window picker ──────────────────────────────────────────────

    @app.get("/api/windows")
    def list_windows():
        """Enumerate all visible windows."""
        ctrl = eternity.controller
        if not ctrl:
            raise HTTPException(status_code=503, detail="Controller not ready")
        return ctrl.list_windows()

    class PickRequest(BaseModel):
        hwnd: int

    @app.post("/api/pick")
    def pick_window(req: PickRequest):
        """Bind to a specific window."""
        ctrl = eternity.controller
        if not ctrl:
            raise HTTPException(status_code=503, detail="Controller not ready")
        result = ctrl.pick_window(req.hwnd)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Pick failed"))
        return result

    @app.post("/api/unpick")
    def unpick_window():
        """Unbind the currently picked window."""
        ctrl = eternity.controller
        if not ctrl:
            raise HTTPException(status_code=503, detail="Controller not ready")
        return ctrl.unpick_window()

    @app.get("/api/pick")
    def get_pick_status():
        """Get info about the currently picked window."""
        ctrl = eternity.controller
        if not ctrl:
            raise HTTPException(status_code=503, detail="Controller not ready")
        picked = ctrl.get_picked_window()
        overlay_active = ctrl.overlay_active
        return {"picked": picked is not None, "window": picked, "overlay_active": overlay_active}

    @app.post("/api/pick/overlay")
    def show_overlay_picker():
        """Launch the interactive fullscreen window picker overlay."""
        ctrl = eternity.controller
        if not ctrl:
            raise HTTPException(status_code=503, detail="Controller not ready")
        result = ctrl.show_overlay_picker()
        if not result.get("success"):
            raise HTTPException(status_code=409, detail=result.get("error", "Failed"))
        return result



    @app.post("/api/model/test")
    async def test_model_connection(req: dict):
        """Test LLM API connection with given credentials."""
        api_key = req.get("api_key", "")
        model_name = req.get("default", "")
        base_url = req.get("base_url", "")
        provider = req.get("provider", "")

        if not api_key:
            return {"status": "failed", "message": "API Key is required"}
        if not model_name:
            return {"status": "failed", "message": "Model name is required"}

        try:
            # Detect API mode based on provider and base_url
            api_mode = "chat_completions"  # default

            # Check if it's Anthropic Messages API
            if provider == "anthropic" or base_url.rstrip("/").endswith("/anthropic"):
                api_mode = "anthropic_messages"

            if api_mode == "anthropic_messages":
                try:
                    from anthropic import AsyncAnthropic
                except ImportError:
                    return {"status": "failed", "message": "anthropic package not installed"}

                anthropic_client = AsyncAnthropic(
                    api_key=api_key,
                    base_url=base_url if base_url else None,
                )

                await anthropic_client.messages.create(
                    model=model_name,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "Hi"}],
                )
            else:
                # OpenAI Chat Completions API (most providers)
                try:
                    from openai import AsyncOpenAI
                except ImportError:
                    return {"status": "failed", "message": "openai package not installed"}

                openai_client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url if base_url else None,
                )

                await openai_client.chat.completions.create(
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
        from .im_bridge import IMBridge
        result = await IMBridge.test_connection(req.platform, req.token, req.extra)
        if result["status"] == "error":
            status_code = 400 if "Unknown platform" in result["message"] or "Unsupported" in result["message"] else 500
            raise HTTPException(status_code=status_code, detail=result["message"])
        elif result["status"] == "failed":
            return result
        return result

    @app.get("/api/update")
    def get_update_status():
        """Check if a newer version is available."""
        if get_update_info:
            info = get_update_info()
            if info:
                return {
                    "available": True,
                    "version": info.version,
                    "release_notes": info.release_notes,
                    "html_url": info.html_url,
                    "download_url": info.download_url,
                }
        return {"available": False}

    return app