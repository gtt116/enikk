"""Enikk CLI — single entrypoint for daemon."""
import argparse
import asyncio
import io
import logging
import os
import sys
import threading
from pathlib import Path

from . import __version__

# Must be set BEFORE importing enikk modules (which import hermes at module level)
if os.name == "nt":
    _enikk_home = Path(os.environ["LOCALAPPDATA"]) / "Enikk"
else:
    _enikk_home = Path.home() / ".enikk"
_enikk_home.mkdir(parents=True, exist_ok=True)
os.environ["HERMES_HOME"] = str(_enikk_home)
os.environ["HERMES_BUNDLED_SKILLS"] = str(Path(__file__).parent / "skills")


logger = logging.getLogger(__name__)


async def _run_im_bridge(im_bridge) -> None:
    """Start IM bridge with exponential backoff retry."""
    retry_delay = 5
    max_delay = 60
    attempt = 0
    while True:
        try:
            await im_bridge.start()
            logger.info("IM bridge started successfully")
            break
        except Exception as e:
            attempt += 1
            delay = min(retry_delay * (2 ** (attempt - 1)), max_delay)
            logger.error("IM bridge start failed (attempt %d), retrying in %ds: %s",
                        attempt, delay, e)
            await asyncio.sleep(delay)


# ── HTTP daemon command ───────────────────────────────────────────────

def cmd_daemon(args):
    """Start the Enikk daemon process (HTTP mode)."""
    # Lazy imports: keep lightweight commands (version, --help) fast by
    # deferring heavy deps (hermes, ultralytics, fastapi) until daemon starts.
    import uvicorn
    import webview

    from .config import Config
    from .eternity import Eternity
    from .server import create_app

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

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()

    logo = r"""
  _____   _   _  _____  _  __  _  __
 |  ___| | \ | ||_   _|| |/ / | |/ /
 | |__   |  \| |  | |  | ' /  | ' /
 |  __|  | . ` |  | |  |  <   |  <
 | |___  | |\  | _| |_ | . \  | . \
 |_____| |_| \_||_____||_|\_\ |_|\_\

 Enikk - Self-improving GUI Agent

 Dashboard: http://{host}:{port}/
"""
    logger.info(logo.format(host=cfg.server.host, port=cfg.server.port))

    eternity = Eternity(cfg)
    eternity.setup()

    im_loop = None
    im_thread = None
    im_bridge = None
    active = cfg.im and cfg.im.active_platform
    if active:
        from .im_bridge import IMBridge
        im_loop = asyncio.new_event_loop()
        im_bridge = IMBridge(cfg, eternity)

        def _run_im():
            asyncio.set_event_loop(im_loop)
            im_loop.create_task(_run_im_bridge(im_bridge))
            im_loop.run_forever()

        im_thread = threading.Thread(target=_run_im, daemon=True, name="im-bridge")
        im_thread.start()
        platform_name, _ = active
        logger.info("IM bridge started (%s)", platform_name)

    timeout = 2
    logger.info(f"Starting API server on {cfg.server.host}:{cfg.server.port}")

    # Start uvicorn in background thread
    uvicorn_thread = threading.Thread(
        target=uvicorn.run,
        kwargs={
            "app": create_app(eternity),
            "host": cfg.server.host,
            "port": cfg.server.port,
            "log_level": "info",
            "timeout_graceful_shutdown": timeout,
            "log_config": None,
        },
        daemon=True,
    )
    uvicorn_thread.start()

    # Open webview in main thread
    try:
        webview.create_window(
            "Enikk Dashboard",
            url=f"http://{cfg.server.host}:{cfg.server.port}",
            width=1280,
            height=800,
        )
        _icon = Path(__file__).parent / "static" / "enikk-logo.ico"
        webview.start(icon=str(_icon) if _icon.exists() else None)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception:
        logger.exception("Webview failed")
    finally:
        logger.info("Shutting down...")
        if im_bridge and im_loop:
            logger.info("Stopping IM bridge...")
            future = asyncio.run_coroutine_threadsafe(im_bridge.stop(), im_loop)
            try:
                future.result(timeout=3.0)
            except Exception:
                logger.warning("IM bridge stop timed out")
            im_loop.call_soon_threadsafe(im_loop.stop)
            if im_thread:
                im_thread.join(timeout=3.0)
            im_loop.close()
            logger.info("IM bridge stopped")
        eternity.shutdown(timeout=timeout)
        os._exit(0)


# ── Version command ───────────────────────────────────────────────────

def cmd_version(args):
    """Show version information."""
    print(f"Enikk v{__version__}")


# ── Main entrypoint ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="enikk", description="Enikk: Self-improving GUI Agent."
    )
    sub = parser.add_subparsers(dest="command")

    daemon_p = sub.add_parser("daemon", help="Start the game monitor daemon (HTTP)")
    daemon_p.add_argument("--config", type=str, help="Path to YAML config file")
    daemon_p.set_defaults(func=cmd_daemon)

    version_p = sub.add_parser("version", help="Show version information")
    version_p.set_defaults(func=cmd_version)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
