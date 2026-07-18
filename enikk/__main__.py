"""Enikk daemon entry point."""
import argparse
import asyncio
import copy
import ctypes
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

# Parse --home-dir FIRST, before any other enikk imports
from .version import __version__, __description__  # noqa: E402

_parser = argparse.ArgumentParser(prog="enikk", description=__description__)
_parser.add_argument("--home-dir", type=str, help="Override Enikk home directory")
_parser.add_argument("--start-minimized", action="store_true", help="Start minimized to system tray")
_args, _ = _parser.parse_known_args()

if _args.home_dir:
    os.environ["ENIKK_HOME"] = _args.home_dir

# Now safe to import enikk modules (they'll use the overridden home dir)
from .config import enikk_home  # noqa: E402

# Must be set BEFORE importing enikk modules (which import hermes at module level)
_enikk_home_path = enikk_home()
_enikk_home_path.mkdir(parents=True, exist_ok=True)
os.environ["HERMES_HOME"] = str(_enikk_home_path)
os.environ["HERMES_BUNDLED_SKILLS"] = str(Path(__file__).parent / "skills")


logger = logging.getLogger(__name__)


class _ColoredFormatter(logging.Formatter):
    """Formatter that colors the level name by severity using ANSI codes."""

    _COLORS = {
        logging.DEBUG: "\033[36m",     # cyan
        logging.INFO: "\033[32m",      # green
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
        logging.CRITICAL: "\033[35m",  # magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelno, "")
        if color:
            record = copy.copy(record)
            record.levelname = f"{color}{record.levelname}{self._RESET}"
        return super().format(record)


def _setup_logging(log_dir: Path) -> None:
    """Initialize logging with colored console output and plain file output."""
    # Console handler: colored output
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_ColoredFormatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)

    # File handler: plain output (no color codes)
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
    root_logger.addHandler(file_handler)


async def _run_im_bridge(im_bridge) -> None:
    """Run IM bridge lifecycle supervisor."""
    await im_bridge.run()


# ── Single instance guard ──────────────────────────────────────────────

_MUTEX_NAME = "Global\\Enikk_Single_Instance"
_mutex_handle = None


def _ensure_single_instance() -> None:
    """Prevent multiple Enikk instances.

    Creates a named mutex. If it already exists, activates the existing
    window and exits the current process.
    """
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    global _mutex_handle
    _mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)

    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        # Activate the existing window
        hwnd = user32.FindWindowW(None, "Enikk Dashboard")
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        sys.exit(0)


def main():
    """Start the Enikk daemon process."""
    # Lazy imports: keep --help fast by deferring heavy deps until daemon starts.

    import time as _time
    _start_time = _time.time()

    _ensure_single_instance()

    # ── DPI awareness (must be set before any window creation) ──────────
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        pass

    # ── Logging (configured early so startup timing is captured) ──────────
    _setup_logging(_enikk_home_path / "logs")
    logger.info("Home directory: %s", _enikk_home_path)

    # ── Splash screen (shown immediately for user feedback) ─────────────
    from .splash import SplashScreen
    _splash_icon = Path(__file__).parent / "static" / "enikk-logo.png"
    _splash = SplashScreen(_splash_icon, __version__)
    _splash.show()

    # ── Startup timing helper ───────────────────────────────────────────
    _phase_start = _time.time()

    def _phase(name: str) -> None:
        nonlocal _phase_start
        elapsed = _time.time() - _phase_start
        logger.info("Startup %s: %.2fs", name, elapsed)
        _phase_start = _time.time()

    _phase("init")

    from .config import Config
    from .eternity import Eternity
    from .mem_track import mem_tag
    from .server import create_app, start_server
    from .tray import TrayManager
    from . import telemetry
    from .webview_api import start_webview
    from .weights import ensure_weights_ready

    _phase("imports")
    mem_tag("after imports")

    logo = (r"""
  _____   _   _  _____  _  __  _  __
 |  ___| | \ | ||_   _|| |/ / | |/ /
 | |__   |  \| |  | |  | ' /  | ' /
 |  __|  | . ` |  | |  |  <   |  <
 | |___  | |\  | _| |_ | . \  | . \
 |_____| |_| \_||_____||_|\_\ |_|\_\

 Enikk v""" + __version__ + r""" - """ + __description__.replace("Enikk: ", "") + """
""")
    print(logo, flush=True)

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

    _phase("config")

    # Set telemetry enabled from config
    telemetry.enabled = cfg.telemetry_enabled

    # Ensure workspace directories exist
    Path(cfg.workspace.screenshot_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.workspace.weights_dir).mkdir(parents=True, exist_ok=True)

    # Ensure weights are ready (copy from bundle if needed)
    _splash.update_status("Preparing models...")
    ensure_weights_ready(Path(cfg.workspace.weights_dir))

    _phase("weights")

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()

    _splash.update_status("Initializing...")
    eternity = Eternity(cfg)
    eternity.setup()
    mem_tag("after eternity.setup")

    _phase("eternity")

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
        telemetry.track_im_connected(__version__, platform_name)

    # Start cron runner if enabled
    cron_runner = None
    if cfg.cron.enabled:
        from .cron import CronRunner
        cron_runner = CronRunner(cfg, eternity, im_bridge, im_loop=im_loop)
        cron_runner.start()
        logger.info("Cron runner started (interval=%ds)", cfg.cron.tick_interval)

    timeout = 2
    server_host = "127.0.0.1"
    logger.info("Starting API server on %s (random port)", server_host)

    # Background update check (non-blocking)
    from .updater import check_for_update, UpdateInfo
    _update_state: list[UpdateInfo | None] = [None]
    _update_done = threading.Event()

    def _check_update():
        try:
            _update_state[0] = check_for_update(__version__)
        finally:
            _update_done.set()

    def get_update_info() -> UpdateInfo | None:
        return _update_state[0]

    update_thread = threading.Thread(target=_check_update, daemon=True, name="update-check")
    update_thread.start()

    _splash.update_status("Starting server...")
    app = create_app(eternity, im_bridge=im_bridge, get_update_info=get_update_info, cron_runner=cron_runner)
    _, actual_port = start_server(
        app,
        host=server_host,
        timeout_graceful_shutdown=timeout,
    )
    logger.info("API server started on http://%s:%s/", server_host, actual_port)
    mem_tag("after server start")

    _phase("server")

    # Track app start
    _features = []
    if active:
        _features.append("im_bridge")
    if cfg.cron.enabled:
        _features.append("cron")
    if cfg.memory.memory_enabled:
        _features.append("memory")
    telemetry.track_start(__version__, _features)

    # Tray manager reference for cleanup
    tray = None

    import webview as _wv

    def _on_closing() -> bool:
        """Handle window close: ask, minimize to tray, or close."""
        # Force exit (user clicked "Exit" in the tray) bypasses the prompt.
        if tray is not None and tray.force_exit:
            return True
        behavior = cfg.close_behavior
        if behavior == "close":
            return True
        if behavior == "minimize":
            try:
                _wv.windows[0].hide()
            except Exception:
                logger.exception("Failed to hide window")
            return False
        # behavior == "ask": show native dialog
        import ctypes
        if cfg.language.startswith("zh"):
            msg = "关闭程序还是最小化到托盘？\n\n点击「是」关闭程序\n点击「否」最小化到托盘"
        else:
            msg = "Close the app or minimize to tray?\n\nClick Yes to close\nClick No to minimize to tray"
        MB_YESNO = 0x4
        MB_ICONQUESTION = 0x20
        IDYES = 6
        result = ctypes.windll.user32.MessageBoxW(
            0, msg, "Enikk", MB_YESNO | MB_ICONQUESTION,
        )
        if result == IDYES:
            return True
        try:
            _wv.windows[0].hide()
        except Exception:
            logger.exception("Failed to hide window")
        return False

    def _on_ready(window) -> None:
        """Set up system tray icon after window creation."""
        nonlocal tray
        _splash.close()
        logger.info("Startup total: %.2fs", _time.time() - _start_time)
        try:
            tray = TrayManager(window, _icon, update_thread=_update_done, get_update_info=get_update_info)
            tray.start()
        except Exception:
            logger.exception("Failed to start system tray icon")

    # Open webview in main thread
    mem_tag("before webview")
    try:
        _icon = Path(__file__).parent / "static" / "enikk-logo.ico"
        start_webview(
            url=f"http://{server_host}:{actual_port}?lang={cfg.language}",
            icon_path=_icon,
            debug=True,
            minimized=_args.start_minimized,
            on_closing=_on_closing,
            on_ready=_on_ready,
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception:
        logger.exception("Webview failed")
    finally:
        logger.info("Shutting down...")
        _splash.close()
        telemetry.track_exit(__version__, round((_time.time() - _start_time) / 3600, 2))
        if tray:
            tray.stop()
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
        if cron_runner:
            logger.info("Stopping cron runner...")
            cron_runner.stop(timeout=timeout)
            logger.info("Cron runner stopped")
        eternity.shutdown(timeout=timeout)
        os._exit(0)


if __name__ == "__main__":
    main()
