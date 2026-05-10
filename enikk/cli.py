"""Enikk CLI — single entrypoint for daemon, screenshot, and click commands."""
import argparse
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


# ── Daemon command ────────────────────────────────────────────────────

def cmd_daemon(args):
    """Start the Enikk daemon process."""
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
        save_dir.mkdir(exist_ok=True)
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


# ── Agent command ───────────────────────────────────────────────────

def cmd_agent(args):
    """Start Hermes AI agent with screenshot/click tools."""
    from .agent.runner import AgentRunner

    if args.config:
        cfg = Config.from_yaml(args.config)
    else:
        cfg = Config()

    model = args.model or cfg.agent_model
    base_url = args.base_url or cfg.agent_base_url or None
    api_key = args.api_key or cfg.agent_api_key or None

    runner = AgentRunner(args.server, model, base_url, api_key)
    runner.run(args.prompt)


# ── Main entrypoint ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="enikk", description="Enikk — The CLI for NIKKE: Goddess of Victory"
    )
    parser.add_argument("--server", default="127.0.0.1:18931", help="Daemon server address")
    sub = parser.add_subparsers(dest="command")

    # Daemon subcommand
    daemon_p = sub.add_parser("daemon", help="Start the game monitor daemon")
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

    agent_p = sub.add_parser("agent", help="AI agent with screenshot/click tools")
    agent_p.add_argument("prompt", help="Instruction for the agent")
    agent_p.add_argument("--config", type=str, help="Path to YAML config file")
    agent_p.add_argument("--server", default="http://127.0.0.1:18931", help="Daemon server URL")
    agent_p.add_argument("--model", default=None, help="LLM model name (overrides config)")
    agent_p.add_argument("--base-url", help="LLM API base URL (overrides config/env)")
    agent_p.add_argument("--api-key", help="LLM API key (overrides config/env)")
    agent_p.add_argument("--memory-dir", default=".", help="Hermes home dir; memories are stored in {dir}/memories/ (default: current dir)")
    agent_p.set_defaults(func=cmd_agent)

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
