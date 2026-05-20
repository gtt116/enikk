"""Agent manager — embedded agent lifecycle within the daemon process."""
import asyncio
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runtime import GameRuntime

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages embedded agent sessions with WebSocket event broadcasting."""

    def __init__(self, daemon: "GameRuntime", loop: asyncio.AbstractEventLoop):
        self.daemon = daemon
        self._loop = loop
        self._stop_events: dict[str, threading.Event] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._sessions: dict[str, list[dict]] = {}  # run_id -> message history
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")

    async def chat_send(self, content: str, ws=None) -> dict:
        """Start a new agent conversation."""
        run_id = str(uuid.uuid4())[:12]
        stop_event = threading.Event()
        self._stop_events[run_id] = stop_event
        self._sessions[run_id] = [
            {"role": "user", "content": content, "timestamp": datetime.now().isoformat()},
        ]

        task = asyncio.create_task(
            asyncio.to_thread(self._run_agent, content, run_id, ws)
        )
        self._active_tasks[run_id] = task
        task.add_done_callback(lambda t: self._on_done(run_id, t))

        logger.info(f"[agent] Run {run_id} started: {content[:80]}")
        await self._emit({"type": "agent.started", "runId": run_id, "content": content[:80]})

        return {"runId": run_id, "status": "started"}

    async def chat_abort(self, run_id: str) -> dict:
        """Interrupt an active agent run."""
        stop_event = self._stop_events.pop(run_id, None)
        task = self._active_tasks.pop(run_id, None)

        if stop_event:
            stop_event.set()
        if task:
            task.cancel()

        logger.info(f"[agent] Run {run_id} aborted")
        await self._emit({"type": "agent.aborted", "runId": run_id})
        return {"status": "aborted", "runId": run_id}

    async def chat_history(self) -> dict:
        """Return accumulated conversation history."""
        messages = []
        for run_messages in self._sessions.values():
            messages.extend(run_messages)
        return {"count": len(messages), "messages": messages}

    async def screenshot(self, ws=None) -> Any:
        """On-demand screenshot + analysis."""
        return await asyncio.to_thread(self.daemon.analyze)

    async def click(self, x: int, y: int, target: str = "", reason: str = "") -> dict:
        """Click at normalized coordinates."""
        result = self.daemon.action_click(x, y)
        result["target"] = target
        result["reason"] = reason
        await self._emit({"type": "action.click", "x": x, "y": y, "target": target})
        return result

    def _run_agent(self, content: str, run_id: str, ws=None):
        """Blocking agent execution in a worker thread."""
        stop_event = self._stop_events.get(run_id)
        if stop_event and stop_event.is_set():
            return

        try:
            # Direct internal call — no HTTP round-trip
            from .hermes_tools import InternalToolContext

            _ctx = InternalToolContext(self, self.daemon, run_id, stop_event)
            # TODO: Implement actual agent loop here
            # For now, this is a placeholder that will be wired to Hermes AIAgent
            # when the tool registration is migrated from HTTP to internal calls.
            logger.info(f"[agent] Running {run_id} with content: {content[:80]}")
            
            # Placeholder: simulate agent steps
            self._add_message(run_id, "assistant", f"Agent received: {content}")
            asyncio.run_coroutine_threadsafe(
                self._emit({"type": "agent.done", "runId": run_id, "text": f"Agent received: {content}"}),
                self._loop,
            )
        except asyncio.CancelledError:
            logger.info(f"[agent] Run {run_id} cancelled")
        except Exception as e:
            logger.error(f"[agent] Run {run_id} failed: {e}", exc_info=True)
            asyncio.run_coroutine_threadsafe(
                self._emit({"type": "agent.error", "runId": run_id, "error": str(e)}),
                self._loop,
            )

    def _add_message(self, run_id: str, role: str, content: str):
        """Add a message to the session history."""
        if run_id in self._sessions:
            self._sessions[run_id].append({
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            })

    def _on_done(self, run_id: str, task: asyncio.Task):
        """Cleanup after agent run completes."""
        self._active_tasks.pop(run_id, None)
        self._stop_events.pop(run_id, None)

    async def _emit(self, event: dict):
        """Broadcast an event to all connected WebSocket clients."""
        asyncio.run_coroutine_threadsafe(
            self._broadcast(event),
            self._loop,
        )

    async def _broadcast(self, event: dict):
        """Actual broadcast — must run on the event loop."""
        if hasattr(self, "_ws_clients"):
            dead = set()
            for ws in self._ws_clients:
                try:
                    await ws.send(json.dumps(event))
                except Exception:
                    dead.add(ws)
            self._ws_clients -= dead

    def shutdown(self):
        """Shut down the agent manager."""
        for stop_event in self._stop_events.values():
            stop_event.set()
        for task in self._active_tasks.values():
            task.cancel()
        self._executor.shutdown(wait=False)
        logger.info("[agent] Manager shut down")
