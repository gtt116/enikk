"""FastAPI HTTP server for Enikk."""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .eternity import Eternity

logger = logging.getLogger(__name__)


def create_app(eternity: Eternity) -> FastAPI:
    app = FastAPI(
        title="Enikk API",
        description="Enikk: AI Agent that helps you test video games.",
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

    @app.get("/api/sessions/{session_id}/messages")
    def get_session_messages(session_id: str):
        return eternity.get_session_messages(session_id)

    @app.get("/api/images")
    def get_image(path: str = Query(...)):
        p = Path(path).resolve()
        allowed_root = Path(eternity.config.workspace.screenshot_dir).resolve()
        if not p.is_relative_to(allowed_root):
            raise HTTPException(status_code=403, detail="Access denied")
        if not p.exists():
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(str(p))

    return app