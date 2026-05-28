"""FastAPI HTTP server for Enikk."""
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .eternity import Eternity

logger = logging.getLogger(__name__)


def create_app(eternity: Eternity) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        eternity.shutdown()

    app = FastAPI(
        title="Enikk API",
        description="Enikk: AI Agent for desktop automation.",
        version="0.1.0",
        lifespan=lifespan,
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
        session_id = eternity.create_session(task=req.task)
        return {"session_id": session_id}

    @app.post("/api/sessions/{session_id}/steer")
    def steer_session(session_id: str, req: SteerRequest):
        if not eternity.steer_session(session_id, req.message):
            raise HTTPException(status_code=404, detail="Session not found")
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

    return app