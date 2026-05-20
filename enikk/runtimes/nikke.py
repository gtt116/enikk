"""NIKKE runtime — profile, services, and convenience facade."""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

import cv2

from tools.registry import registry, tool_result

from ..config import GameConfig
from ..game import capture, input as input_mod, process, window
from ..ui_parser import MAX_DIM, UIParser
from .profile import GameProfile

if TYPE_CHECKING:
    from ..config import Config

logger = logging.getLogger(__name__)

# ── NIKKE profile ──────────────────────────────────────────────────────

NIKKE_NAME = "nikke"
NIKKE_DEFAULT_GAME_PATH = r"C:\Program Files\NIKKE\NIKKE.exe"
NIKKE_DEFAULT_LAUNCHER_PATH = r"C:\Program Files\NIKKE\launcher\nikke_launcher.exe"
NIKKE_GAME_WINDOW_CLASS = "UnityWndClass"
NIKKE_LAUNCHER_WINDOW_CLASS = "TWINCONTROL"


def create_nikke_profile(
    *,
    game_path: str = NIKKE_DEFAULT_GAME_PATH,
    launcher_path: str | None = NIKKE_DEFAULT_LAUNCHER_PATH,
    game_window_class: str = NIKKE_GAME_WINDOW_CLASS,
    launcher_window_class: str | None = NIKKE_LAUNCHER_WINDOW_CLASS,
) -> GameProfile:
    """Create a NIKKE profile."""
    return GameProfile(
        name=NIKKE_NAME,
        game_path=game_path,
        launcher_path=launcher_path,
        game_window_class=game_window_class,
        launcher_window_class=launcher_window_class,
    )


def nikke_profile_from_config(config: Config) -> GameProfile:
    """Create a NIKKE profile from the application config."""
    gc = config.games.get(NIKKE_NAME)
    if gc is None:
        return create_nikke_profile()
    return create_nikke_profile(
        game_path=gc.game_path,
        launcher_path=gc.launcher_path,
        game_window_class=gc.game_window_class,
        launcher_window_class=gc.launcher_window_class,
    )


# ── NikkeRuntime ───────────────────────────────────────────────────────

class NikkeRuntime:
    """Bundled game services for one NIKKE instance (profile, window, capture, input, process)."""

    def __init__(self, config: Config):
        self.config = config
        self.profile: GameProfile = nikke_profile_from_config(config)
        gc = config.games.get(NIKKE_NAME, GameConfig())

        self.window = window.WindowService()
        self.capture = capture.CaptureService(self.window)
        self.input = input_mod.InputService(self.window)
        self.process = process.GameProcessManager(self.profile, timeout=gc.launch_timeout)
        self.max_dim = MAX_DIM
        self.ui_parser = UIParser(config.workspace.weights_dir)
        self._screenshot_dir = Path(config.workspace.screenshot_dir)
        self._screenshot_counter = 0

    # ── Process status ─────────────────────────────────────────────────

    @property
    def is_game_running(self) -> bool:
        return self.process.is_game_running

    @property
    def is_launcher_running(self) -> bool:
        return self.process.is_launcher_running

    # ── Window discovery ────────────────────────────────────────────────

    def find_game_window(self) -> int | None:
        return self.window.find_by_path_and_class(
            self.profile.game_path, self.profile.game_window_class,
        )

    def find_launcher_window(self) -> int | None:
        if not self.profile.launcher_path:
            return None
        return self.window.find_by_path_and_class(
            self.profile.launcher_path, self.profile.launcher_window_class,
        )

    # ── Agent tool primitives ──────────────────────────────────────────

    def analyze(self, *, target: str = "game") -> dict:
        """Capture window, run OCR + YOLO, return structured state.

        *target*: 'game' or 'launcher'.
        Saves the compressed screenshot to disk automatically. Use read_image()
        to load the image for vision model analysis.
        """
        if target == "launcher":
            hwnd = self.find_launcher_window()
        else:
            hwnd = self.find_game_window()
        if hwnd is None:
            return {"error": f"{target} window not found"}

        frame = self.capture.capture(hwnd)
        if frame is None:
            return {"error": "Capture failed"}

        h, w = frame.shape[:2]
        if w > self.max_dim or h > self.max_dim:
            scale = self.max_dim / max(w, h)
            compressed = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            compressed = frame

        self._screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter += 1
        path = str(self._screenshot_dir / f"agent_{self._screenshot_counter:04d}.jpeg")
        cv2.imwrite(path, compressed)

        parsed = self.ui_parser.parse(frame)

        return {
            "image_path": path,
            "width": compressed.shape[1],
            "height": compressed.shape[0],
            "ocr": parsed,
            "bbox_desc": (
                "All element bbox coordinates are normalized to [0, 1000] as "
                "[x1, y1, x2, y2], where (x1,y1) is top-left and (x2,y2) is "
                "bottom-right. Each element also has a 'center' [cx, cy] field "
                "already pre-computed — use center directly for click coordinates."
            ),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def read_image(self, path: str) -> dict:
        """Read an image file and return base64 content for vision model analysis.

        Returns a multimodal dict the agent can pass to a vision-capable model.
        """
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}

        image_bytes = p.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode()
        suffix = p.suffix.lower().lstrip(".")
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix

        return {
            "path": str(p.absolute()),
            "size": len(image_bytes),
            "_multimodal": True,
            "content": [
                {"type": "text", "text": f"Screenshot from path: {path}"},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_b64}"}},
            ],
        }

    def click(self, x: int, y: int, *, target: str = "game") -> dict:
        """Click at normalized [0, 1000] coordinates. *target*: 'game' or 'launcher'."""
        if target == "launcher":
            hwnd = self.find_launcher_window()
        else:
            hwnd = self.find_game_window()
        if hwnd is None:
            return {"success": False, "error": f"{target} window not found"}
        return self.input.click_normalized(hwnd, x, y)

    def launch(self) -> dict:
        """Start the launcher and wait for its window.

        After this returns 'launcher_ready', the agent should:
        1. analyze() or screenshot() to see the launcher UI
        2. Find the Start Game button via vision
        3. click(x, y, target='launcher')
        4. wait_for_game()
        """
        if self.is_game_running:
            return {"status": "already_running", "message": "Game is already running"}

        if not self.is_launcher_running:
            if not self._start_launcher():
                return {"status": "error", "message": "Failed to start launcher"}

        hwnd = self._wait_for_launcher_window(timeout=30)
        if hwnd is None:
            return {"status": "error", "message": "Launcher window not found"}

        self._force_foreground(hwnd)
        return {
            "status": "launcher_ready",
            "message": "Launcher is ready. Use screenshot+vision to find Start Game button, click it, then wait_for_game().",
        }

    def wait_for_game(self) -> dict:
        """Wait for the game process and window after clicking Start Game in launcher."""
        if not self._wait_for_game_process(timeout=120):
            return {"status": "timeout", "message": "Game process did not start"}

        hwnd = self._wait_for_game_window(timeout=60)
        if hwnd is None:
            return {"status": "error", "message": "Game window not found"}

        self._force_foreground(hwnd)
        time.sleep(2)
        return {"status": "game_ready", "message": "Game window is ready"}

    def wait(self, seconds: float) -> dict:
        """Wait for a duration, e.g. for game animations or loading screens."""
        time.sleep(seconds)
        return {"status": "waited", "seconds": seconds}

    def stop(self) -> dict:
        """Stop both game and launcher processes."""
        return {
            "game_stopped": self._stop_game(),
            "launcher_stopped": self._stop_launcher(),
        }

    # ── Tool registration ───────────────────────────────────────────────

    def register_tools(self) -> None:
        """Register all tool primitives into the hermes tool registry singleton."""
        registry.register(
            name="analyze",
            toolset="enikk",
            schema={
                "description": "Capture the game or launcher window, run OCR text detection + YOLO icon detection, and save a compressed screenshot to disk. Returns structured state including image_path (for use with read_image), OCR text elements with normalized bbox [0,1000] coordinates, and screen dimensions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "enum": ["game", "launcher"],
                            "description": "Which window to capture: 'game' (default) or 'launcher'.",
                        },
                    },
                },
            },
            handler=lambda args, **kw: tool_result(
                self.analyze(target=args.get("target", "game"))
            ),
        )

        registry.register(
            name="read_image",
            toolset="enikk",
            schema={
                "description": "Read an image file from disk and return base64-encoded content for vision model analysis. Use this after analyze() to visually inspect the screenshot with a vision-capable model.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute or relative path to the image file (e.g. the image_path returned by analyze).",
                        },
                    },
                    "required": ["path"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.read_image(path=args["path"])
            ),
        )

        registry.register(
            name="click",
            toolset="enikk",
            schema={
                "description": "Click at normalized [0, 1000] coordinates on the game or launcher window. Coordinates are percentages of screen width/height where (0,0) is top-left and (1000,1000) is bottom-right.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "description": "X coordinate in normalized [0, 1000] range.",
                        },
                        "y": {
                            "type": "integer",
                            "description": "Y coordinate in normalized [0, 1000] range.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["game", "launcher"],
                            "description": "Which window to click on: 'game' (default) or 'launcher'.",
                        },
                    },
                    "required": ["x", "y"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.click(x=args["x"], y=args["y"], target=args.get("target", "game"))
            ),
        )

        registry.register(
            name="launch",
            toolset="enikk",
            schema={
                "description": "Start the NIKKE launcher and wait for its window to appear. After this returns 'launcher_ready', use analyze(target='launcher') to see the launcher UI, find the Start Game button via vision, click it with click(x, y, target='launcher'), then call wait_for_game.",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda args, **kw: tool_result(self.launch()),
        )

        registry.register(
            name="wait_for_game",
            toolset="enikk",
            schema={
                "description": "Wait for the game process and window to be ready after clicking Start Game in the launcher. Polls for up to 3 minutes total (120s for process + 60s for window). Returns 'game_ready' when the game window is in the foreground.",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda args, **kw: tool_result(self.wait_for_game()),
        )

        registry.register(
            name="wait",
            toolset="enikk",
            schema={
                "description": "Wait/sleep for a specified duration. Use for game animations, loading screens, or waiting for UI transitions to complete.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seconds": {
                            "type": "number",
                            "description": "Number of seconds to wait.",
                        },
                    },
                    "required": ["seconds"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.wait(seconds=args["seconds"])
            ),
        )

        registry.register(
            name="stop",
            toolset="enikk",
            schema={
                "description": "Stop both the game and launcher processes. Use at the end of a session to clean up.",
                "parameters": {"type": "object", "properties": {}},
            },
            handler=lambda args, **kw: tool_result(self.stop()),
        )

        logger.info("Registered %d enikk tools in hermes registry", 7)

    # ── Private helpers ─────────────────────────────────────────────────

    def _force_foreground(self, hwnd: int) -> bool:
        return self.window.force_foreground(hwnd)

    def _start_launcher(self) -> bool:
        if not self.process.launcher:
            logger.error("No launcher configured")
            return False
        return self.process.launcher.start()

    def _stop_game(self) -> bool:
        return self.process.stop_game()

    def _stop_launcher(self) -> bool:
        return self.process.stop_launcher()

    def _wait_for_launcher_window(self, timeout: float = 30) -> int | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self.find_launcher_window()
            if hwnd:
                return hwnd
            time.sleep(1)
        return None

    def _wait_for_game_window(self, timeout: float = 60) -> int | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self.find_game_window()
            if hwnd:
                return hwnd
            time.sleep(1)
        return None

    def _wait_for_game_process(self, timeout: float = 120) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_game_running:
                return True
            time.sleep(1)
        return False