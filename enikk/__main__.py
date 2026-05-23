"""Enikk CLI — single entrypoint for daemon, screenshot, and click commands."""
import argparse
import base64
import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import uvicorn

from .config import Config
from .server import create_app


# ── HTTP helpers ──────────────────────────────────────────────────────

def build_url(base: str) -> str:
    if not base.startswith("http"):
        base = f"http://{base}"
    return base


logger = logging.getLogger(__name__)


# ── HTTP daemon command ───────────────────────────────────────────────

def cmd_daemon(args):
    """Start the Enikk daemon process (HTTP mode)."""
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

    if args.port:
        cfg.server.port = args.port

    logger.info(f"Starting API server on {cfg.server.host}:{cfg.server.port}")
    uvicorn.run(create_app(), host=cfg.server.host, port=cfg.server.port, log_level="info")


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
        prog="enikk", description="Enikk: AI Agent that helps you test video games."
    )
    parser.add_argument("--server", default="127.0.0.1:18931", help="Daemon server address")
    sub = parser.add_subparsers(dest="command")

    # HTTP daemon
    daemon_p = sub.add_parser("daemon", help="Start the game monitor daemon (HTTP)")
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