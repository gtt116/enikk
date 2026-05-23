"""FastAPI HTTP server for Enikk."""
import logging
from fastapi import FastAPI

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Enikk API",
        description="Enikk: AI Agent that helps you test video games.",
        version="0.1.0",
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app