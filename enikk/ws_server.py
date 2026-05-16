"""WebSocket server — JSON-RPC over WebSocket.

WsServer accepts connections and delegates every inbound JSON-RPC frame to a
:class:`Dispatcher` implementation.  Dispatch runs in a thread pool so the
event loop stays free for I/O.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Protocol, runtime_checkable

import websockets
from websockets import ServerConnection

logger = logging.getLogger(__name__)


# ── Dispatcher Protocol ──────────────────────────────────────────────────


@runtime_checkable
class Dispatcher(Protocol):
    """Interface for JSON-RPC request handlers."""

    def dispatch(self, req: dict) -> dict:
        """Handle one JSON-RPC request and return a response."""


# ── WebSocket Server ────────────────────────────────────────────────────


class WsServer:
    """WebSocket JSON-RPC server.

    Parameters
    ----------
    dispatcher:
        Implements :class:`Dispatcher` — ``dispatch(req) -> dict``.
    """

    def __init__(
        self,
        dispatcher: Dispatcher,
        host: str = "127.0.0.1",
        port: int = 18932,
    ) -> None:
        self._dispatcher = dispatcher
        self._host = host
        self._port = port
        self._server = None

    async def serve_forever(self) -> None:
        """Start the WebSocket server and block until cancelled."""
        async with websockets.serve(
            self._handle,
            self._host,
            self._port,
            max_size=10 * 1024 * 1024,
            ping_interval=30,
            ping_timeout=10,
        ) as server:
            self._server = server
            logger.info("[ws] Listening on %s:%s", self._host, self._port)
            await server.serve_forever()

    async def _handle(self, ws: ServerConnection) -> None:
        """Per-connection handler."""
        remote = ws.remote_address
        logger.info("[ws] Client connected: %s", remote)

        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "method": "event",
            "params": {
                "type": "gateway.ready",
                "session_id": "",
                "payload": {"protocol": 1},
            },
        }))

        try:
            async for raw in ws:
                line = raw.strip() if isinstance(raw, str) else ""
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": "Parse error"},
                        "id": None,
                    }))
                    continue

                resp = await asyncio.to_thread(self._dispatcher.dispatch, req)
                await ws.send(json.dumps(resp))
        except websockets.ConnectionClosed:
            logger.debug("[ws] Connection closed: %s", remote)
        except Exception:
            logger.debug("[ws] Connection error: %s", remote, exc_info=True)
        finally:
            logger.info("[ws] Client disconnected: %s", remote)

    def shutdown(self) -> None:
        """Request server shutdown.  Safe to call from any thread."""
        if self._server:
            self._server.get_loop().call_soon_threadsafe(self._server.close)
            self._server = None
            logger.info("[ws] Shutdown requested")
