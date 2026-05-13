"""WebSocket server — JSON-RPC over WebSocket."""
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

try:
    import websockets
    from websockets.asyncio.server import serve as ws_serve
except ImportError:
    websockets = None
    ws_serve = None

if TYPE_CHECKING:
    from .agent.manager import AgentManager

logger = logging.getLogger("enikk")


class WsServer:
    """WebSocket JSON-RPC server."""

    def __init__(self, agent_manager: "AgentManager", host: str = "127.0.0.1", port: int = 18932):
        self.agent_manager = agent_manager
        self.host = host
        self.port = port
        self._server = None

    async def start(self):
        """Start the WebSocket server."""
        if websockets is None:
            logger.error("websockets not installed. Run: pip install websockets")
            return

        # Register ws_clients on agent_manager for broadcast
        self.agent_manager._ws_clients = set()

        async with ws_serve(
            self._handle_connection,
            self.host,
            self.port,
            max_size=10 * 1024 * 1024,  # 10MB
            ping_interval=30,
            ping_timeout=10,
        ) as server:
            self._server = server
            logger.info(f"[ws] Listening on {self.host}:{self.port}")
            await server.serve_forever()

    async def _handle_connection(self, websocket):
        """Handle a single WebSocket connection."""
        self.agent_manager._ws_clients.add(websocket)
        remote = websocket.remote_address
        logger.info(f"[ws] Client connected: {remote}")

        try:
            async for message in websocket:
                await self._process_message(websocket, message)
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"[ws] Error from {remote}: {e}", exc_info=True)
        finally:
            self.agent_manager._ws_clients.discard(websocket)
            logger.info(f"[ws] Client disconnected: {remote}")

    async def _process_message(self, websocket, raw: str):
        """Process a single JSON-RPC message."""
        start = time.time()
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            })
            return

        method = req.get("method")
        params = req.get("params", {})
        req_id = req.get("id")

        logger.debug(f"[ws] -> {method} (id={req_id})")

        result = await self._route(method, params, websocket)
        elapsed = (time.time() - start) * 1000
        logger.info(f"[ws] {method} -> {elapsed:.0f}ms")

        if req_id is not None:
            await websocket.send_json({
                "jsonrpc": "2.0",
                "result": result,
                "id": req_id,
            })

    async def _route(self, method: str, params: dict, websocket):
        """Route a JSON-RPC method call."""
        am = self.agent_manager

        routes = {
            "chat.send": lambda: am.chat_send(
                params.get("content", ""), ws=websocket
            ),
            "chat.abort": lambda: am.chat_abort(params.get("runId", "")),
            "chat.history": lambda: am.chat_history(),
            "screenshot": lambda: am.screenshot(ws=websocket),
            "click": lambda: am.click(
                params.get("x", 0),
                params.get("y", 0),
                target=params.get("target", ""),
                reason=params.get("reason", ""),
            ),
        }

        handler = routes.get(method)
        if handler is None:
            return {"error": f"Unknown method: {method}"}

        return await handler()

    def shutdown(self):
        """Shutdown the WebSocket server."""
        if self._server:
            self._server.close()
