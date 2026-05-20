"""Enikk CLI — single entrypoint for daemon, ws-server, screenshot, and click commands."""
import argparse
import asyncio
import base64
import io
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import websockets

from .config import Config, GameConfig
from .runtime import GameRuntime
from .server import create_app
import uvicorn


# ── HTTP helpers ──────────────────────────────────────────────────────

def build_url(base: str) -> str:
    if not base.startswith("http"):
        base = f"http://{base}"
    return base


logger = logging.getLogger(__name__)


# ── WebSocket daemon command ─────────────────────────────────────────

def cmd_ws_daemon(args):
    """Start the Enikk daemon with WebSocket + embedded agent."""
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.config:
        cfg = Config.from_yaml(args.config)
    else:
        cfg = Config()

    gc = cfg.games.setdefault("nikke", GameConfig)

    if args.launcher_path:
        gc.launcher_path = args.launcher_path
    if args.game_path:
        gc.game_path = args.game_path
    if args.ws_port:
        cfg.server.ws_port = args.ws_port
        logger.info(f"WebSocket port overridden: {args.ws_port}")

    daemon = GameRuntime(cfg)

    if sys.platform == 'win32':
        def handler(sig, frame):
            daemon.stop()
            os._exit(0)
        signal.signal(signal.SIGINT, handler)

    daemon.init()

    logger.info(f"Starting WebSocket server on {cfg.server.host}:{cfg.server.ws_port}")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        daemon.start_ws(loop)
    except KeyboardInterrupt:
        pass
    finally:
        daemon.shutdown()


# ── HTTP daemon command (legacy) ─────────────────────────────────────

def cmd_daemon(args):
    """Start the Enikk daemon process (HTTP mode, legacy)."""
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.config:
        cfg = Config.from_yaml(args.config)
    else:
        cfg = Config()

    gc = cfg.games.setdefault("nikke", GameConfig)

    if args.launcher_path:
        gc.launcher_path = args.launcher_path
    if args.game_path:
        gc.game_path = args.game_path
    if args.port:
        cfg.server.port = args.port

    daemon = GameRuntime(cfg)

    if sys.platform == 'win32':
        def handler(sig, frame):
            daemon.stop()
            os._exit(0)
        signal.signal(signal.SIGINT, handler)

    daemon.init()

    logger.info(f"Starting API server on {cfg.server.host}:{cfg.server.port}")
    try:
        uvicorn.run(create_app(daemon), host=cfg.server.host, port=cfg.server.port, log_level="info")
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()


# ── Client commands ───────────────────────────────────────────────────

def cmd_screenshot(args):
    url = urljoin(build_url(args.server), "/api/screenshot")
    req = Request(url, method="GET")
    resp = urlopen(req, timeout=120)
    data = json.loads(resp.read())

    # Save image
    ext = data.get("format", "jpeg")
    if args.output:
        out = args.output
    else:
        save_dir = Path("screenshots")
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = str(save_dir / f"{ts}.{ext}")

    img_bytes = base64.b64decode(data["image_b64"])
    with open(out, "wb") as f:
        f.write(img_bytes)

    # Print structured data with saved file path
    output = {k: v for k, v in data.items() if k != "image_b64"}
    output["path"] = out
    print(json.dumps(output, indent=2, ensure_ascii=False))


def cmd_click(args):
    url = urljoin(build_url(args.server), f"/api/action/click?x={args.x}&y={args.y}")
    resp = urlopen(url, timeout=10)
    data = json.loads(resp.read())
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if data.get("success"):
        print(f"Clicked at ({data.get('x')},{data.get('y')})")


# ── WebSocket test commands ─────────────────────────────────────────────

def _ws_request(server: str, req: dict, port: int = 18932) -> dict:
    """Send one JSON-RPC request via WebSocket and return the response."""

    async def _go():
        host = server
        for prefix in ("ws://", "wss://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
        host = host.rsplit(":", 1)[0]
        ws_url = f"ws://{host}:{port}"
        async with websockets.connect(ws_url) as ws:
            raw = await ws.recv()  # gateway.ready
            ready = json.loads(raw)
            print(f"gateway.ready: protocol={ready['params']['payload']['protocol']}")

            await ws.send(json.dumps(req))
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("method") == "event":
                    print(f"event: {msg['params']['type']} {json.dumps(msg['params'].get('payload', {}))}")
                elif msg.get("id") == req.get("id"):
                    return msg
                else:
                    print(f"unexpected: {json.dumps(msg)}")

    return asyncio.run(_go())


def cmd_ws_ping(args):
    resp = _ws_request(args.server, {"jsonrpc": "2.0", "id": "1", "method": "ping"})
    print(json.dumps(resp, indent=2, ensure_ascii=False))


def cmd_ws_list(args):
    resp = _ws_request(args.server, {"jsonrpc": "2.0", "id": "1", "method": "session.list"})
    print(json.dumps(resp, indent=2, ensure_ascii=False))


def cmd_ws_run(args):
    resp = _ws_request(args.server, {
        "jsonrpc": "2.0", "id": "1", "method": "session.run",
        "params": {"session_id": args.game, "prompt": args.prompt},
    })
    print(json.dumps(resp, indent=2, ensure_ascii=False))


def cmd_ws_status(args):
    resp = _ws_request(args.server, {
        "jsonrpc": "2.0", "id": "1", "method": "session.status",
        "params": {"session_id": args.game},
    })
    print(json.dumps(resp, indent=2, ensure_ascii=False))


def cmd_ws_connect(args):
    resp = _ws_request(args.server, {
        "jsonrpc": "2.0", "id": "1", "method": "connect",
        "params": {"role": args.role, "client": {"id": "cli", "version": "1.0"}},
    })
    print(json.dumps(resp, indent=2, ensure_ascii=False))


# ── TUI command ──────────────────────────────────────────────────────

def cmd_tui(args):
    """Launch the Textual TUI dashboard."""
    from .tui.app import EnikkTui

    host = args.server
    for prefix in ("ws://", "wss://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.rsplit(":", 1)[0]

    app = EnikkTui(server=host, port=args.ws_port)
    app.run()


# ── Main entrypoint ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="enikk", description="Enikk — The CLI for NIKKE: Goddess of Victory"
    )
    parser.add_argument("--server", default="127.0.0.1:18931", help="Daemon server address")
    sub = parser.add_subparsers(dest="command")

    # WebSocket daemon (new)
    ws_p = sub.add_parser("ws-daemon", help="Start daemon with WebSocket + embedded agent")
    ws_p.add_argument("--config", type=str, help="Path to YAML config file")
    ws_p.add_argument("--launcher-path", type=str, help="Path to NIKKE launcher")
    ws_p.add_argument("--game-path", type=str, help="Path to NIKKE game exe")
    ws_p.add_argument("--ws-port", type=int, help="WebSocket port (default: 18932)")
    ws_p.set_defaults(func=cmd_ws_daemon)

    # HTTP daemon (legacy)
    daemon_p = sub.add_parser("daemon", help="Start the game monitor daemon (HTTP, legacy)")
    daemon_p.add_argument("--config", type=str, help="Path to YAML config file")
    daemon_p.add_argument("--launcher-path", type=str, help="Path to NIKKE launcher")
    daemon_p.add_argument("--game-path", type=str, help="Path to NIKKE game exe")
    daemon_p.add_argument("--port", type=int, help="API port")
    daemon_p.set_defaults(func=cmd_daemon)

    # WebSocket test commands
    ws_ping = sub.add_parser("ws-ping", help="Test WS connectivity (ping)")
    ws_ping.set_defaults(func=cmd_ws_ping)

    ws_list = sub.add_parser("ws-list", help="List sessions via WebSocket")
    ws_list.set_defaults(func=cmd_ws_list)

    ws_run = sub.add_parser("ws-run", help="Send session.run via WebSocket")
    ws_run.add_argument("game", type=str, help="Game ID (e.g., nikke)")
    ws_run.add_argument("prompt", type=str, help="Agent prompt")
    ws_run.set_defaults(func=cmd_ws_run)

    ws_status = sub.add_parser("ws-status", help="Query session status via WebSocket")
    ws_status.add_argument("game", type=str, help="Game ID (e.g., nikke)")
    ws_status.set_defaults(func=cmd_ws_status)

    ws_connect = sub.add_parser("ws-connect", help="Send connect handshake via WebSocket")
    ws_connect.add_argument("--role", type=str, default="dashboard", help="Client role")
    ws_connect.set_defaults(func=cmd_ws_connect)

    screenshot_p = sub.add_parser("screenshot", help="Download structured screenshot (base64 + OCR + YOLO)")
    screenshot_p.add_argument("-o", "--output", help="Output file path")
    screenshot_p.set_defaults(func=cmd_screenshot)

    click_p = sub.add_parser("click", help="Click at normalized bbox center")
    click_p.add_argument("x", type=int, help="Normalized X (0-1000)")
    click_p.add_argument("y", type=int, help="Normalized Y (0-1000)")
    click_p.set_defaults(func=cmd_click)

    tui_p = sub.add_parser("tui", help="Launch Textual TUI dashboard")
    tui_p.add_argument("--ws-port", type=int, default=18932, help="WebSocket port")
    tui_p.set_defaults(func=cmd_tui)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except URLError as e:
        print(f"Error: cannot connect to {getattr(args, 'server', 'unknown')} — {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
