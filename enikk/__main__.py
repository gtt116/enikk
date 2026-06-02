"""Enikk daemon entry point."""
import argparse
import asyncio
import io
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

# Parse --home-dir FIRST, before any other enikk imports
_parser = argparse.ArgumentParser(prog="enikk", description="Enikk: Self-improving GUI Agent.")
_parser.add_argument("--home-dir", type=str, help="Override Enikk home directory")
_args, _ = _parser.parse_known_args()

if _args.home_dir:
    os.environ["ENIKK_HOME"] = _args.home_dir

# Now safe to import enikk modules (they'll use the overridden home dir)
from .version import __version__  # noqa: E402
from .config import enikk_home  # noqa: E402

# Must be set BEFORE importing enikk modules (which import hermes at module level)
_enikk_home_path = enikk_home()
_enikk_home_path.mkdir(parents=True, exist_ok=True)
os.environ["HERMES_HOME"] = str(_enikk_home_path)
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


def main():
    """Start the Enikk daemon process."""
    # Lazy imports: keep --help fast by deferring heavy deps until daemon starts.

    from .config import Config
    from .eternity import Eternity
    from .server import create_app, start_server
    from .webview_api import start_webview

    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    logo = (r"""
  _____   _   _  _____  _  __  _  __
 |  ___| | \ | ||_   _|| |/ / | |/ /
 | |__   |  \| |  | |  | ' /  | ' /
 |  __|  | . ` |  | |  |  <   |  <
 | |___  | |\  | _| |_ | . \  | . \
 |_____| |_| \_||_____||_|\_\ |_|\_\

 Enikk v""" + __version__ + r""" - Self-improving GUI Agent
""")
    print(logo, flush=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logger.info("Home directory: %s", _enikk_home_path)

    # Load config from {home_dir}/config.yaml
    config_path = _enikk_home_path / "config.yaml"
    if config_path.exists():
        cfg = Config.from_yaml(str(config_path))
        # Adjust log level from config
        log_level = getattr(logging, cfg.log_level.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level)
    else:
        cfg = Config()
        logger.info("No config.yaml found at %s, using defaults", config_path)

    # Ensure workspace directories exist
    Path(cfg.workspace.screenshot_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.workspace.weights_dir).mkdir(parents=True, exist_ok=True)

    # Also write logs to home/logs/enikk.log (rotate 5 files × 10MB)
    log_dir = _enikk_home_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "enikk.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(file_handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()

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
    server_host = "127.0.0.1"
    logger.info("Starting API server on %s (random port)", server_host)

    app = create_app(eternity, im_bridge=im_bridge)
    _, actual_port = start_server(
        app,
        host=server_host,
        timeout_graceful_shutdown=timeout,
    )
    logger.info("API server started on http://%s:%s/", server_host, actual_port)

    # Open webview in main thread
    try:
        _icon = Path(__file__).parent / "static" / "enikk-logo.ico"
        start_webview(
            url=f"http://{server_host}:{actual_port}?lang={cfg.language}",
            icon_path=_icon,
            debug=True,
        )
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


if __name__ == "__main__":
    main()
