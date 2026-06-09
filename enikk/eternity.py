"""Eternity — agent session manager backed by hermes AIAgent."""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from urllib.parse import quote

import run_agent
import tools.skills_sync
from hermes_state import SessionDB

from .prompts import DEFAULT_SYSTEM_PROMPT
from .config import Config
from .controller import AppController, extract_image_path
from .events import EVT_DELTA, EVT_TOOL_CALL, EVT_TOOL_RESULT, EVT_REASONING, EVT_STEP_CONTEXT, EVT_ERROR, EVT_SESSION

logger = logging.getLogger(__name__)


@dataclass
class StreamChannel:
    """Pub/sub channel for streaming events from agent to SSE clients."""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: list[queue.Queue] = field(default_factory=list)

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
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
        self._controller: AppController | None = None
        self._sessions: dict[str, SessionHandle] = {}
        self._lock = threading.RLock()
        self._registered = False
        self._shutdown = False

    # ── Setup ──────────────────────────────────────────────────────────

    def setup(self) -> None:
        """One-time init: sync bundled skills, create SessionDB, AppController, register tools."""
        logging.getLogger("run_agent").setLevel(logging.WARNING)

        tools.skills_sync.sync_skills(quiet=True)
        self.config.load_apps()

        self._session_db = SessionDB()
        logger.info("SessionDB at %s", self._session_db.db_path)

        self._controller = AppController(self.config)
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
        max_iterations: int | None = None,
        session_id: str | None = None,
    ) -> str:
        """Create a session and start the agent in a background thread.

        Returns the session_id immediately.
        """
        if session_id is None:
            session_id = uuid.uuid4().hex[:12]

        # Create handle first so callbacks can reference stream
        handle = SessionHandle(session_id=session_id, thread=None, agent=None)  # type: ignore[arg-type]

        def _publish(event: str, data: dict) -> None:
            """Publish an SSE event, logging only important events."""
            if event in (EVT_TOOL_CALL, EVT_TOOL_RESULT, EVT_SESSION):
                logger.debug("SSE [%s/%s] %s", session_id, event, json.dumps(data, default=str)[:200])
            handle.publish(event, data)

        def _publish_tool_result(tc_id: str, name: str, result) -> None:
            """Publish tool_result event, enriching with imageUrl if result contains image path."""
            data = {"call_id": tc_id, "name": name, "result": result}
            # Extract duration_ms from result (may be dict or JSON string from tool_result())
            result_obj = result
            if isinstance(result, str):
                try:
                    result_obj = json.loads(result)
                except (ValueError, TypeError):
                    result_obj = None
            if isinstance(result_obj, dict) and "duration_ms" in result_obj:
                data["duration_ms"] = result_obj["duration_ms"]
            img_path = extract_image_path(result)
            if img_path:
                data["imageUrl"] = f"/api/images?path={quote(img_path, safe='')}"
            _publish(EVT_TOOL_RESULT, data)

        mc = self.config.model
        if max_iterations is None:
            max_iterations = self.config.workspace.max_iterations
        try:
            agent = run_agent.AIAgent(
                base_url=mc.effective_base_url or None,
                api_key=mc.api_key or None,
                provider=mc.effective_provider or None,
                model=model or mc.default,
                max_tokens=mc.max_tokens,
                enabled_toolsets=[AppController.TOOLSET, "skills", "memory", "session_search", "todo"],
                quiet_mode=True,
                save_trajectories=False,
                max_iterations=max_iterations,
                session_id=session_id,
                session_db=self._session_db,
                tool_start_callback=lambda tc_id, name, args: _publish(EVT_TOOL_CALL, {"call_id": tc_id, "name": name, "args": args}),
                tool_complete_callback=lambda tc_id, name, _args, result: _publish_tool_result(tc_id, name, result),
                stream_delta_callback=lambda delta: _publish(EVT_DELTA, {"text": delta}) if delta is not None else None,
                reasoning_callback=lambda text: _publish(EVT_REASONING, {"text": text}),
                step_callback=lambda _count, _tools: _publish(EVT_STEP_CONTEXT, {"step": _count, **self._get_context_usage(handle).get("context_usage", {})}),
            )
        except RuntimeError as e:
            if "No LLM provider" in str(e):
                raise RuntimeError(
                    "LLM provider not configured. Please set model.base_url and model.api_key in config.yaml"
                ) from None
            raise

        handle.agent = agent
        thread = threading.Thread(
            target=self._run_agent,
            args=(handle, task, system_message or DEFAULT_SYSTEM_PROMPT),
            daemon=True,
        )
        handle.thread = thread
        with self._lock:
            self._sessions[session_id] = handle
        thread.start()

        logger.info("Session %s started (task=%r)", session_id, task[:80])
        return session_id

    def _run_agent(self, handle: SessionHandle, task: str, system_message: str) -> None:
        """Thread target: run the agent conversation, store result on completion."""
        try:
            handle.publish(EVT_SESSION, {"status": "running"})
            history = self._session_db.get_messages_as_conversation(handle.session_id)
            if history:
                logger.info("Session %s loaded %d history messages", handle.session_id, len(history))
            result = handle.agent.run_conversation(
                task, system_message=system_message, conversation_history=history,
            )
            handle.result = result
            final_response = result.get("final_response")
            handle.publish(EVT_SESSION, {
                "status": "completed",
                "final_response": final_response,
                **self._get_context_usage(handle),
            })
        except InterruptedError:
            logger.info("Session %s interrupted", handle.session_id)
            handle.result = {"status": "interrupted"}
            handle.publish(EVT_SESSION, {"status": "stopped", **self._get_context_usage(handle)})
        except Exception:
            logger.exception("Session %s failed", handle.session_id)
            handle.result = {"error": "agent exception"}
            handle.publish(EVT_SESSION, {"status": "error", **self._get_context_usage(handle)})
            handle.publish(EVT_ERROR, {"message": "agent exception"})
        finally:
            logger.info("Session %s finished", handle.session_id)
            handle.stream.close()

    def _get_context_usage(self, handle: SessionHandle) -> dict:
        """Read context usage from the live agent's context compressor."""
        cc = getattr(handle.agent, "context_compressor", None)
        if not cc:
            return {}
        return {
            "context_usage": {
                "current": getattr(cc, "last_prompt_tokens", 0),
                "limit": getattr(cc, "context_length", 0),
            }
        }

    def list_sessions(self, limit: int = 20, offset: int = 0) -> list[dict]:
        """List sessions from SessionDB, ordered by last activity."""
        sessions = self._session_db.list_sessions_rich(
            limit=limit, offset=offset, order_by_last_active=True
        )
        for s in sessions:
            s["is_running"] = self.is_running(s["id"])
        return sessions

    def is_running(self, session_id: str) -> bool:
        """Check if a session is currently running."""
        handle = self._sessions.get(session_id)
        return handle is not None and handle.thread is not None and handle.thread.is_alive()

    def steer_session(self, session_id: str, message: str) -> bool:
        """Inject a message mid-conversation via agent.steer().

        If session is not loaded or has finished, auto-loads it and uses message as task.
        """
        with self._lock:
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
        with self._lock:
            handle = self._sessions.get(session_id)
            if not handle or not handle.thread.is_alive():
                return False
            if handle.agent:
                handle.agent.interrupt()
                logger.info("Session %s interrupted", session_id)
            return True

    def delete_session(self, session_id: str) -> bool:
        """Delete session from memory and SessionDB."""
        with self._lock:
            self._session_db.delete_session(session_id)
            handle = self._sessions.pop(session_id, None)
            if handle:
                handle.stream.close()
            logger.info("Session %s deleted", session_id)
            return True

    # ── Lifecycle ───────────────────────────────────────────────────────

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop all running sessions and clean up resources."""
        if self._shutdown:
            return
        self._shutdown = True

        with self._lock:
            sessions = list(self._sessions.items())

        logger.info("Shutting down Eternity, stopping %d sessions...", len(sessions))
        for session_id, handle in sessions:
            logger.info("Stopping session %s", session_id)
            handle.stream.close()
            if handle.thread and handle.thread.is_alive():
                if handle.agent:
                    handle.agent.interrupt()
                handle.thread.join(timeout=timeout)
                if handle.thread.is_alive():
                    logger.debug("Thread %s did not stop within timeout (will be killed on exit)", handle.thread.name)

        with self._lock:
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
                img_path = extract_image_path(m["content"])
                if img_path:
                    m["imageUrl"] = f"/api/images?path={quote(img_path, safe='')}"

        return {"messages": result, "has_more": has_more}

    async def get_session_stream(self, session_id: str):
        """Async generator that yields SSE events from the agent's StreamChannel."""
        handle = self._sessions.get(session_id)
        if not handle:
            logger.warning("get_session_stream: session %s not found", session_id)
            return

        q = handle.stream.subscribe()
        logger.info("SSE stream started for session %s", session_id)
        try:
            while True:
                # Use asyncio.to_thread for non-blocking queue.get() with timeout
                try:
                    event = await asyncio.to_thread(q.get, timeout=5.0)
                except queue.Empty:
                    # No event for 5 seconds, check if session still running
                    if not self.is_running(session_id):
                        # Drain any remaining events
                        while not q.empty():
                            event = q.get_nowait()
                            if event is not None:
                                yield event
                        logger.info("SSE stream: session %s finished", session_id)
                        break
                    # Session still running, continue waiting
                    continue

                if event is None:
                    logger.info("SSE stream closed for session %s", session_id)
                    break
                yield event
        except asyncio.CancelledError:
            logger.info("SSE stream cancelled for session %s", session_id)
            raise
        finally:
            handle.stream.unsubscribe(q)

    def wait_for_session(self, session_id: str, timeout: float | None = None) -> dict | None:
        """Block until a session completes. Returns the result dict, or None on timeout."""
        handle = self._sessions.get(session_id)
        if handle is None:
            return None
        handle.thread.join(timeout=timeout)
        return handle.result

    # ── Public status API ────────────────────────────────────────────────

    def get_icon_finder_available(self) -> bool:
        """Check if YOLO icon finder is ready."""
        if self._controller and self._controller.ui_parser:
            return self._controller.ui_parser.yolo_session is not None
        return False

    def get_icon_finder_dml_enabled(self) -> bool:
        """Check if DirectML is enabled for icon finder."""
        if self._controller and self._controller.ui_parser:
            return getattr(self._controller.ui_parser, 'use_dml', False)
        return False

    def get_ocr_available(self) -> bool:
        """Check if OCR engine is ready."""
        if self._controller and self._controller.ui_parser:
            return hasattr(self._controller.ui_parser, 'ocr') and self._controller.ui_parser.ocr is not None
        return False

    def get_ocr_dml_enabled(self) -> bool:
        """Check if DirectML is enabled for OCR."""
        if self._controller and self._controller.ui_parser:
            return getattr(self._controller.ui_parser, 'use_dml_ocr', False)
        return False

