"""Enikk CLI — single entrypoint for daemon."""
import argparse
import io
import logging
import os
import sys
from pathlib import Path

# Must be set BEFORE importing enikk modules (which import hermes at module level)
_enikk_home = Path.home() / ".enikk"
_enikk_home.mkdir(parents=True, exist_ok=True)
os.environ["HERMES_HOME"] = str(_enikk_home)
os.environ["HERMES_BUNDLED_SKILLS"] = str(Path(__file__).parent / "skills")

import uvicorn  # noqa: E402

from .config import Config  # noqa: E402
from .eternity import Eternity  # noqa: E402
from .server import create_app  # noqa: E402


logger = logging.getLogger(__name__)


# ── HTTP daemon command ───────────────────────────────────────────────

def cmd_daemon(args):
    """Start the Enikk daemon process (HTTP mode)."""
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    if args.config:
        cfg = Config.from_yaml(args.config)
    else:
        cfg = Config()

    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    eternity = Eternity(cfg)
    eternity.setup()

    timeout = 2
    logger.info(f"Starting API server on {cfg.server.host}:{cfg.server.port}")
    try:
        uvicorn.run(
            create_app(eternity), host=cfg.server.host, port=cfg.server.port,
            log_level="info", timeout_graceful_shutdown=timeout,
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        logger.info("Shutting down...")
        eternity.shutdown(timeout=timeout)
        os._exit(0)


# ── Main entrypoint ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="enikk", description="Enikk: AI Agent that helps you test video games."
    )
    sub = parser.add_subparsers(dest="command")

    daemon_p = sub.add_parser("daemon", help="Start the game monitor daemon (HTTP)")
    daemon_p.add_argument("--config", type=str, help="Path to YAML config file")
    daemon_p.set_defaults(func=cmd_daemon)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()