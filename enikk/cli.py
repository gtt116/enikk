"""Enikk CLI — single entrypoint for daemon and client commands."""
import argparse
import io
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, quote
from urllib.request import urlopen, Request, urlretrieve

from .config import Config
from .daemon import Daemon
from .server import create_app
from .account import save_account, ACCOUNT_DIR
import uvicorn


# ── HTTP helpers ──────────────────────────────────────────────────────

def build_url(base: str) -> str:
    if not base.startswith("http"):
        base = f"http://{base}"
    return base


def api_get(base: str, path: str) -> dict:
    url = urljoin(build_url(base), path)
    resp = urlopen(url, timeout=10)
    return json.loads(resp.read())


def api_post(base: str, path: str) -> dict:
    url = urljoin(build_url(base), path)
    req = Request(url, method="POST", data=b"")
    resp = urlopen(req, timeout=10)
    return json.loads(resp.read())


# ── Client commands ───────────────────────────────────────────────────

def cmd_state(args):
    data = api_get(args.server, "/api/state")
    if args.short:
        data.pop("ocr_text", None)
        data.pop("template_matches", None)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_process(args):
    data = api_get(args.server, "/api/process")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_health(args):
    data = api_get(args.server, "/health")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_screenshot(args):
    fmt = args.format or "jpeg"
    ext = "jpg" if fmt == "jpeg" else "png"
    save_dir_param = getattr(args, "save_dir", "") or ""
    width_param = getattr(args, "width", "") or ""
    if args.output:
        out = args.output
    else:
        save_dir = Path("screenshots")
        save_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = str(save_dir / f"{ts}.{ext}")
    qs = f"format={fmt}&debug={args.debug}&save_dir={quote(save_dir_param)}"
    if width_param:
        qs += f"&width={width_param}"
    urlretrieve(urljoin(build_url(args.server), f"/api/screenshot?{qs}"), out)
    print(f"Screenshot saved to {out}")


def cmd_launch(args):
    data = api_post(args.server, "/api/action/launch")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if data.get("success"):
        print("Launch started in background. Run 'enikk state' to check progress.")


def cmd_capture(args):
    data = api_post(args.server, "/api/action/screenshot")
    print(json.dumps(data["state"], indent=2, ensure_ascii=False))


def _print_action_result(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if data.get("success"):
        text = data.get("text")
        if text:
            print(f"Clicked '{text}' at ({data.get('x')},{data.get('y')})")
        else:
            print(f"Clicked at ({data.get('x')},{data.get('y')})")


def cmd_action_confirm(args):
    data = api_post(args.server, "/api/action/confirm")
    _print_action_result(data)


def cmd_action_connect(args):
    data = api_post(args.server, "/api/action/connect")
    _print_action_result(data)


def cmd_action_click(args):
    data = api_post(args.server, f"/api/action/click?x={args.x}&y={args.y}")
    _print_action_result(data)


def cmd_action_esc(args):
    data = api_post(args.server, "/api/action/esc")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_action_exit(args):
    data = api_post(args.server, "/api/action/exit")
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ── Account commands ──────────────────────────────────────────────────

def cmd_account_save(args):
    """Save encrypted account credentials."""
    path = save_account(args.config, args.account, args.password)
    print(f"✅ Account saved to {path}")


def cmd_account_list(args):
    """List saved account configs."""
    if not ACCOUNT_DIR.exists():
        print("No saved accounts")
        return
    for f in ACCOUNT_DIR.glob("*.json"):
        print(f"  {f.stem}")


def cmd_account_delete(args):
    """Delete a saved account config."""
    path = ACCOUNT_DIR / f"{args.config}.json"
    if path.exists():
        path.unlink()
        print(f"✅ Deleted {path}")
    else:
        print(f"Account '{args.config}' not found")


# ── Daemon command ────────────────────────────────────────────────────

logger = logging.getLogger("enikk")


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
    if args.fps:
        cfg.fps = args.fps
    if args.debug:
        cfg.save_screenshots = True

    daemon = Daemon(cfg)

    if sys.platform == 'win32':
        def handler(sig, frame):
            daemon.stop()
            os._exit(0)
        signal.signal(signal.SIGINT, handler)

    daemon.init(auto_launch=args.launch)

    logger.info(f"Starting API server on {cfg.host}:{cfg.port}")
    try:
        uvicorn.run(create_app(daemon), host=cfg.host, port=cfg.port, log_level="info")
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()


# ── Main entrypoint ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="enikk", description="Enikk — The CLI for NIKKE: Goddess of Victory"
    )
    parser.add_argument("--server", default="127.0.0.1:18931", help="Daemon server address")
    sub = parser.add_subparsers(dest="command")

    # Account subcommand
    account_p = sub.add_parser("account", help="Manage encrypted account credentials")
    account_sub = account_p.add_subparsers(dest="account_action")

    save_p = account_sub.add_parser("save", help="Save encrypted account")
    save_p.add_argument("--config", default="enikk", help="Config name")
    save_p.add_argument("--account", required=True, help="Email/account")
    save_p.add_argument("--password", required=True, help="Password")
    save_p.set_defaults(func=cmd_account_save)

    list_p = account_sub.add_parser("list", help="List saved accounts")
    list_p.set_defaults(func=cmd_account_list)

    delete_p = account_sub.add_parser("delete", help="Delete saved account")
    delete_p.add_argument("--config", required=True, help="Config name")
    delete_p.set_defaults(func=cmd_account_delete)

    # Daemon subcommand
    daemon_p = sub.add_parser("daemon", help="Start the game monitor daemon")
    daemon_p.add_argument("--config", type=str, help="Path to YAML config file")
    daemon_p.add_argument("--launcher-path", type=str, help="Path to NIKKE launcher")
    daemon_p.add_argument("--game-path", type=str, help="Path to NIKKE game exe")
    daemon_p.add_argument("--launch", action="store_true", help="Auto-launch game via launcher")
    daemon_p.add_argument("--port", type=int, help="API port")
    daemon_p.add_argument("--fps", type=int, help="Capture FPS")
    daemon_p.add_argument("--debug", action="store_true", help="Save debug screenshots")
    daemon_p.set_defaults(func=cmd_daemon)

    # Client subcommands
    state_p = sub.add_parser("state", help="Get current game state")
    state_p.add_argument("--short", action="store_true", help="Omit ocr_text and template_matches")
    state_p.set_defaults(func=cmd_state)
    sub.add_parser("process", help="Get game process info").set_defaults(func=cmd_process)
    sub.add_parser("health", help="Health check").set_defaults(func=cmd_health)
    sub.add_parser("launch", help="Launch game").set_defaults(func=cmd_launch)
    sub.add_parser("capture", help="Force capture + analyze").set_defaults(func=cmd_capture)

    screenshot_p = sub.add_parser("screenshot", help="Download latest screenshot")
    screenshot_p.add_argument("-f", "--format", choices=["jpeg", "png"], default="jpeg")
    screenshot_p.add_argument("-o", "--output", help="Output file path")
    screenshot_p.add_argument("-d", "--save-dir", help="Directory to save screenshot")
    screenshot_p.add_argument("--debug", action="store_true", help="Add debug overlay")
    screenshot_p.add_argument("-w", "--width", type=int, help="Resize width")
    screenshot_p.set_defaults(func=cmd_screenshot)

    # Action subcommand
    action_p = sub.add_parser("do", help="Trigger OCR-based actions")
    action_sub = action_p.add_subparsers(dest="action_command")

    confirm_p = action_sub.add_parser("confirm", help="OCR find '确认' and click")
    confirm_p.set_defaults(func=cmd_action_confirm)

    connect_p = action_sub.add_parser("connect", help="OCR find '点击连接' and click")
    connect_p.set_defaults(func=cmd_action_connect)

    click_p = action_sub.add_parser("click", help="Click at screen coordinates")
    click_p.add_argument("x", type=int, help="Screen X")
    click_p.add_argument("y", type=int, help="Screen Y")
    click_p.set_defaults(func=cmd_action_click)

    esc_p = action_sub.add_parser("esc", help="Send ESC key")
    esc_p.set_defaults(func=cmd_action_esc)

    exit_p = action_sub.add_parser("exit", help="Force-terminate game")
    exit_p.set_defaults(func=cmd_action_exit)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "do" and not getattr(args, "action_command", None):
        action_p.print_help()
        sys.exit(1)

    if args.command == "account" and not getattr(args, "account_action", None):
        account_p.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except URLError as e:
        print(f"Error: cannot connect to {getattr(args, 'server', 'unknown')} — {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
