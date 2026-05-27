"""Eternity — agent session manager backed by hermes AIAgent."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import run_agent
from hermes_state import SessionDB

from .prompts import AGENT_SYSTEM_PROMPT
from .config import Config
from .controller import GameController, IMAGE_PATH_KEY, SOM_IMAGE_PATH_KEY

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    AGENT_SYSTEM_PROMPT
    + "\n\nAvailable games are discoverable via the list_games() tool. "
    + "Use the 'game' parameter on every tool call to select the target game."
)


def _extract_image_url(result) -> str | None:
    """Extract image URL from a tool result (dict or JSON string)."""
    obj = None
    if isinstance(result, dict):
        obj = result
    elif isinstance(result, str):
        try:
            obj = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            pass
    if obj and isinstance(obj, dict):
        path = obj.get(SOM_IMAGE_PATH_KEY) or obj.get(IMAGE_PATH_KEY)
        if path:
            return "/api/images?path=" + quote(path, safe="")
    return None


@dataclass
class StreamChannel:
    """Pub/sub channel for streaming events from agent to SSE clients."""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: list[queue.Queue] = field(default_factory=list)

    def subscribe(self) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            self.subscribers.append(q)
        logger.debug("StreamChannel subscribed (%d subscribers)", len(self.subscribers))
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self.subscribers:
                self.subscribers.remove(q)
        logger.debug("StreamChannel unsubscribed (%d subscribers)", len(self.subscribers))

    def publish(self, event: dict):
        with self._lock:
            subs = list(self.subscribers)
        for q in subs:
            q.put(event)
        logger.debug("StreamChannel published %s to %d subscribers", event.get("event", "?"), len(subs))

    def close(self):
        with self._lock:
            for q in self.subscribers:
                q.put(None)  # sentinel
            self.subscribers.clear()
        logger.debug("StreamChannel closed")


@dataclass
class SessionHandle:
    """Track one agent session."""

    session_id: str
    thread: threading.Thread
    agent: run_agent.AIAgent
    stream: StreamChannel = field(default_factory=StreamChannel)
    result: dict | None = field(default=None)

    def publish(self, event: str, data: dict) -> None:
        """Publish an SSE event, auto-inserting session_id into data."""
        data = {"session_id": self.session_id, **data}
        self.stream.publish({"event": event, "data": data})


class Eternity:
    """Manages AI agent sessions backed by hermes SessionDB + AIAgent."""

    def __init__(self, config: Config):
        self.config = config
        self._controller: GameController | None = None
        self._sessions: dict[str, SessionHandle] = {}
        self._registered = False
        self._shutdown = False

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

        # Create handle first so callbacks can reference stream
        handle = SessionHandle(session_id=session_id, thread=None, agent=None)  # type: ignore[arg-type]

        def _log_publish(event: str, data: dict) -> None:
            logger.debug("SSE publish [%s] %s", event, json.dumps(data, default=str)[:200])

        def _publish_tool_result(tc_id: str, name: str, result) -> None:
            """Publish tool_result event, enriching with imageUrl if result contains image path."""
            data = {"call_id": tc_id, "name": name, "result": result}
            img_url = _extract_image_url(result)
            if img_url:
                data["imageUrl"] = img_url
            _log_publish("tool_result", data)
            handle.publish("tool_result", data)

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
            tool_start_callback=lambda tc_id, name, args: _log_publish("tool_call", {"call_id": tc_id, "name": name, "args": args}) or handle.publish("tool_call", {"call_id": tc_id, "name": name, "args": args}),
            tool_complete_callback=lambda tc_id, name, _args, result: _publish_tool_result(tc_id, name, result),
            stream_delta_callback=lambda delta: (
                delta is not None and (_log_publish("delta", {"text": delta}), handle.publish("delta", {"text": delta}))
            ),
            reasoning_callback=lambda text: _log_publish("reasoning", {"text": text}) or handle.publish("reasoning", {"text": text}),
        )

        handle.agent = agent
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
            handle.publish("session", {"status": "running"})
            history = self._session_db.get_messages_as_conversation(handle.session_id)
            if history:
                logger.info("Session %s loaded %d history messages", handle.session_id, len(history))
            result = handle.agent.run_conversation(
                task, system_message=system_message, conversation_history=history,
            )
            handle.result = result
            handle.publish("session", {"status": "completed"})
        except Exception:
            logger.exception("Session %s failed", handle.session_id)
            handle.result = {"error": "agent exception"}
            handle.publish("session", {"status": "error"})
            handle.publish("error", {"message": "agent exception"})
        finally:
            logger.info("Session %s finished", handle.session_id)
            handle.stream.close()

    def list_sessions(self, limit: int = 20, offset: int = 0) -> list[dict]:
        """List sessions from SessionDB, ordered by last activity."""
        return self._session_db.list_sessions_rich(
            limit=limit, offset=offset, order_by_last_active=True
        )

    def steer_session(self, session_id: str, message: str) -> bool:
        """Inject a message mid-conversation via agent.steer().

        If session is not loaded or has finished, auto-loads it and uses message as task.
        """
        handle = self._sessions.get(session_id)

        # Session not in memory or thread finished — auto-load it
        if handle is None or not handle.thread.is_alive():
            # Check if session exists in database
            messages = self._session_db.get_messages(session_id)
            if not messages:
                return False  # Session doesn't exist at all

            # Reload session with the new message as task
            logger.info("Session %s not loaded, auto-loading with message: %s", session_id, message[:80])
            self.create_session(task=message, session_id=session_id)
            return True

        # Session is running — steer it
        handle.agent.steer(message)
        logger.info("Session %s steered: %s", session_id, message[:80])
        return True

    def stop_session(self, session_id: str) -> bool:
        """Interrupt a running session's agent."""
        handle = self._sessions.get(session_id)
        if not handle or not handle.thread.is_alive():
            return False
        if handle.agent:
            handle.agent.interrupt()
            logger.info("Session %s interrupted", session_id)
        return True

    def delete_session(self, session_id: str) -> bool:
        """Delete session from memory and SessionDB."""
        self._session_db.delete_session(session_id)
        handle = self._sessions.pop(session_id, None)
        if handle:
            handle.stream.close()
        logger.info("Session %s deleted", session_id)
        return True

    # ── Lifecycle ───────────────────────────────────────────────────────

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop all running sessions and clean up resources."""
        if self._shutdown:
            return
        self._shutdown = True

        logger.info("Shutting down Eternity, stopping %d sessions...", len(self._sessions))
        for session_id, handle in list(self._sessions.items()):
            logger.info("Stopping session %s", session_id)
            handle.stream.close()
            if handle.thread and handle.thread.is_alive():
                if handle.agent:
                    handle.agent.interrupt()
                handle.thread.join(timeout=timeout)
                if handle.thread.is_alive():
                    logger.debug("Thread %s did not stop within timeout (will be killed on exit)", handle.thread.name)

        self._sessions.clear()
        logger.info("Eternity shutdown complete")

    def get_session_messages(
        self, session_id: str, limit: int = 100, before_id: str | None = None
    ) -> dict:
        """Get messages for a session, paginated (latest first).

        Returns {"messages": [...], "has_more": bool}.
        """
        messages = self._session_db.get_messages(session_id)
        total = len(messages)

        if before_id:
            # Find index of message with given id, return older ones
            # Convert to int for comparison (DB ids are integers)
            try:
                before_id_int = int(before_id)
            except (ValueError, TypeError):
                before_id_int = -1
            idx = next((i for i, m in enumerate(messages) if m.get("id") == before_id_int), total)
            end = idx
        else:
            end = total

        start = max(0, end - limit)
        result = messages[start:end]
        has_more = start > 0

        for m in result:
            if m.get("role") == "tool" and m.get("content"):
                img_url = _extract_image_url(m["content"])
                if img_url:
                    m["imageUrl"] = img_url

        return {"messages": result, "has_more": has_more}

    async def get_session_stream(self, session_id: str):
        """Async generator that yields SSE events from the agent's StreamChannel."""
        handle = self._sessions.get(session_id)
        if not handle:
            logger.warning("get_session_stream: session %s not found", session_id)
            return

        q = handle.stream.subscribe()
        logger.info("SSE stream started for session %s", session_id)
        loop = asyncio.get_event_loop()
        try:
            while True:
                event = await loop.run_in_executor(None, q.get)
                if event is None:
                    logger.info("SSE stream closed for session %s", session_id)
                    break
                logger.debug("SSE stream yielding %s", event.get("event", "?"))
                yield event
        finally:
            handle.stream.unsubscribe(q)

    def wait_for_session(self, session_id: str, timeout: float | None = None) -> dict | None:
        """Block until a session completes. Returns the result dict, or None on timeout."""
        handle = self._sessions.get(session_id)
        if handle is None:
            return None
        handle.thread.join(timeout=timeout)
        return handle.result