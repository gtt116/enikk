"""Enikk CLI — single entrypoint for daemon."""
import argparse
import io
import logging
import os
import sys

import uvicorn

from .config import Config
from .eternity import Eternity
from .server import create_app


logger = logging.getLogger(__name__)


# ── HTTP daemon command ───────────────────────────────────────────────

def cmd_daemon(args):
    """Start the Enikk daemon process (HTTP mode)."""
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    if args.config:
        cfg = Config.from_yaml(args.config)
    else:
        cfg = Config()

    eternity = Eternity(cfg)
    eternity.setup()

    logger.info(f"Starting API server on {cfg.server.host}:{cfg.server.port}")
    try:
        uvicorn.run(
            create_app(eternity), host=cfg.server.host, port=cfg.server.port,
            log_level="info", timeout_graceful_shutdown=5,
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        logger.info("Shutting down...")
        eternity.shutdown()
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