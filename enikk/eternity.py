"""Eternity — agent session manager backed by hermes AIAgent."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import run_agent
from hermes_state import SessionDB

from .prompts import AGENT_SYSTEM_PROMPT
from .config import Config
from .game_controller import GameController

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    AGENT_SYSTEM_PROMPT
    + "\n\nAvailable games are discoverable via the list_games() tool. "
    + "Use the 'game' parameter on every tool call to select the target game."
)


@dataclass
class SessionHandle:
    """Track one agent session."""

    session_id: str
    thread: threading.Thread
    agent: run_agent.AIAgent
    result: dict | None = field(default=None)


class Eternity:
    """Manages AI agent sessions backed by hermes SessionDB + AIAgent."""

    def __init__(self, config: Config):
        self.config = config
        self._controller: GameController | None = None
        self._sessions: dict[str, SessionHandle] = {}
        self._registered = False

    # ── Setup ──────────────────────────────────────────────────────────

    def setup(self) -> None:
        """One-time init: set HERMES_HOME, create SessionDB, GameController, register tools."""
        enikk_home = Path.home() / ".enikk"
        enikk_home.mkdir(parents=True, exist_ok=True)
        logger.info("Enikk home: %s", enikk_home)
        os.environ.setdefault("HERMES_HOME", str(enikk_home))
        db_path = enikk_home / "sessions.db"
        self._session_db = SessionDB(db_path)
        logger.info("SessionDB at %s", db_path)

        self._controller = GameController(self.config)
        if not self._registered:
            self._controller.register_tools()
            self._registered = True

    # ── Session management ─────────────────────────────────────────────

    def create_session(
        self,
        task: str,
        *,
        model: str | None = None,
        system_message: str | None = None,
        max_iterations: int = 500,
        session_id: str | None = None,
    ) -> str:
        """Create a session and start the agent in a background thread.

        Returns the session_id immediately.
        """
        if session_id is None:
            session_id = uuid.uuid4().hex[:12]

        mc = self.config.model
        agent = run_agent.AIAgent(
            base_url=mc.base_url or None,
            api_key=mc.api_key or None,
            model=model or mc.default,
            max_tokens=mc.max_tokens,
            enabled_toolsets=[GameController.TOOLSET],
            quiet_mode=False,
            save_trajectories=False,
            max_iterations=max_iterations,
            session_id=session_id,
            session_db=self._session_db,
        )

        handle = SessionHandle(session_id=session_id, thread=None, agent=agent)  # type: ignore[arg-type]
        thread = threading.Thread(
            target=self._run_agent,
            args=(handle, task, system_message or DEFAULT_SYSTEM_PROMPT),
            daemon=True,
        )
        handle.thread = thread
        self._sessions[session_id] = handle
        thread.start()

        logger.info("Session %s started (task=%r)", session_id, task[:80])
        return session_id

    def _run_agent(self, handle: SessionHandle, task: str, system_message: str) -> None:
        """Thread target: run the agent conversation, store result on completion."""
        try:
            history = self._session_db.get_messages_as_conversation(handle.session_id)
            if history:
                logger.info("Session %s loaded %d history messages", handle.session_id, len(history))
            result = handle.agent.run_conversation(
                task, system_message=system_message, conversation_history=history,
            )
            handle.result = result
        except Exception:
            logger.exception("Session %s failed", handle.session_id)
            handle.result = {"error": "agent exception"}
        finally:
            logger.info("Session %s finished", handle.session_id)

    def list_sessions(self, limit: int = 20, offset: int = 0) -> list[dict]:
        """List sessions from SessionDB."""
        return self._session_db.list_sessions_rich(limit=limit, offset=offset)

    def steer_session(self, session_id: str, message: str) -> bool:
        """Inject a message mid-conversation via agent.steer()."""
        handle = self._sessions.get(session_id)
        if handle is None:
            return False
        handle.agent.steer(message)
        logger.info("Session %s steered: %s", session_id, message[:80])
        return True

    def delete_session(self, session_id: str) -> bool:
        """Delete session from memory and SessionDB."""
        self._session_db.delete_session(session_id)
        self._sessions.pop(session_id, None)
        logger.info("Session %s deleted", session_id)
        return True

    def get_session_messages(self, session_id: str) -> list[dict]:
        """Get messages for a session from SessionDB."""
        messages = self._session_db.get_messages(session_id)
        for m in messages:
            if m.get("role") == "tool" and m.get("content"):
                try:
                    obj = json.loads(m["content"])
                    path = obj.get("SOM_image_path") or obj.get("image_path")
                    if path:
                        m["imageUrl"] = "/api/images?path=" + quote(path, safe="")
                except (json.JSONDecodeError, TypeError):
                    pass
        return messages

    def wait_for_session(self, session_id: str, timeout: float | None = None) -> dict | None:
        """Block until a session completes. Returns the result dict, or None on timeout."""
        handle = self._sessions.get(session_id)
        if handle is None:
            return None
        handle.thread.join(timeout=timeout)
        return handle.result