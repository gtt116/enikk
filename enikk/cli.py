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

from .config import Config
from .daemon import Daemon
from .server import create_app
import uvicorn


# ── HTTP helpers ──────────────────────────────────────────────────────

def build_url(base: str) -> str:
    if not base.startswith("http"):
        base = f"http://{base}"
    return base


logger = logging.getLogger("enikk")


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
        cfg = Config.from_env()

    if args.launcher_path:
        cfg.launcher_path = args.launcher_path
    if args.game_path:
        cfg.game_path = args.game_path
    if args.ws_port:
        cfg.ws_port = args.ws_port
        logger.info(f"WebSocket port overridden: {args.ws_port}")

    daemon = Daemon(cfg)

    if sys.platform == 'win32':
        def handler(sig, frame):
            daemon.stop()
            os._exit(0)
        signal.signal(signal.SIGINT, handler)

    daemon.init()

    logger.info(f"Starting WebSocket server on {cfg.host}:{cfg.ws_port}")
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
        cfg = Config.from_env()

    if args.launcher_path:
        cfg.launcher_path = args.launcher_path
    if args.game_path:
        cfg.game_path = args.game_path
    if args.port:
        cfg.port = args.port

    daemon = Daemon(cfg)

    if sys.platform == 'win32':
        def handler(sig, frame):
            daemon.stop()
            os._exit(0)
        signal.signal(signal.SIGINT, handler)

    daemon.init()

    logger.info(f"Starting API server on {cfg.host}:{cfg.port}")
    try:
        uvicorn.run(create_app(daemon), host=cfg.host, port=cfg.port, log_level="info")
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

    screenshot_p = sub.add_parser("screenshot", help="Download structured screenshot (base64 + OCR + YOLO)")
    screenshot_p.add_argument("-o", "--output", help="Output file path")
    screenshot_p.set_defaults(func=cmd_screenshot)

    click_p = sub.add_parser("click", help="Click at normalized bbox center")
    click_p.add_argument("x", type=int, help="Normalized X (0-1000)")
    click_p.add_argument("y", type=int, help="Normalized Y (0-1000)")
    click_p.set_defaults(func=cmd_click)

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
