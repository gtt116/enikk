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
    # Suppress all library logging — use print for output only
    logging.getLogger().setLevel(logging.CRITICAL)

    # Memory: default to ./memories/ via HERMES_HOME="."
    os.environ["HERMES_HOME"] = args.memory_dir
    mem_dir = Path(args.memory_dir) / "memories"

    from .agent.hermes_tools import register_tools, AGENT_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, build_memory_block
    from run_agent import AIAgent

    register_tools(args.server)

    system_prompt = AGENT_SYSTEM_PROMPT
    mem_block = build_memory_block(mem_dir)
    if mem_block:
        system_prompt += "\n\n<memory_context>\n" + mem_block + "\n</memory_context>"

    agent = AIAgent(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        enabled_toolsets=["enikk", "memory", "todo"],
        quiet_mode=False,
        ephemeral_system_prompt=system_prompt,
    )

    # Manually initialize MemoryStore so the memory tool works outside standard Hermes config
    try:
        from tools.memory_tool import MemoryStore
        agent._memory_store = MemoryStore(memory_char_limit=200000, user_char_limit=100000)
        agent._memory_store.load_from_disk()
        agent._memory_enabled = True
        agent._user_profile_enabled = True
    except Exception:
        pass

    response = agent.chat(args.prompt)
    print(response)

    # Post-session review: extract lessons to make next operations smoother
    try:
        import copy as _copy
        messages = _copy.deepcopy(agent._session_messages)
        review_messages = [m for m in messages if m.get("role") in ("user", "assistant")]
        review_user_msg = "Review this session and save lessons to memory:\n" + "\n".join(
            f"[{m['role']}] {m['content'][:200]}" for m in review_messages[-20:]
        )
        print("\n--- Reviewing session ---")
        review_agent = AIAgent(
            base_url=args.base_url,
            api_key=args.api_key,
            model=args.model,
            enabled_toolsets=["memory"],
            quiet_mode=False,
            ephemeral_system_prompt=REVIEW_SYSTEM_PROMPT,
        )
        # Share the same MemoryStore so review writes to the same memory files
        review_agent._memory_store = agent._memory_store
        review_agent._memory_enabled = True
        review_agent._user_profile_enabled = True
        review_result = review_agent.run_conversation(review_user_msg)
        review_text = review_result.get("final_response", "")
        if review_text:
            print(review_text)
        review_agent._sync_external_memory_for_turn(
            original_user_message=review_user_msg,
            final_response=review_text,
            interrupted=False,
        )
    except Exception as e:
        print(f"[warn] Session review failed (non-fatal): {e}")


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
    agent_p.add_argument("--server", default="http://127.0.0.1:18931", help="Daemon server URL")
    agent_p.add_argument("--model", default="qwen3.6-plus", help="LLM model name")
    agent_p.add_argument("--base-url", help="LLM API base URL (default: DASHSCOPE_BASE_URL)")
    agent_p.add_argument("--api-key", help="LLM API key (default: DASHSCOPE_API_KEY)")
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
