"""Game controller — multi-game agent-facing services."""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from pathlib import Path

import cv2

from tools.registry import registry, tool_result

from .config import Config, GameConfig
from .game import capture, input as input_mod, process, window
from .ui_parser import MAX_DIM, UIParser


logger = logging.getLogger(__name__)


class GameController:
    """Bundled game services for multiple game instances.

    Usage:
        gc = GameController(config)
        rt.register_tools()
        # Agent calls: analyze(game="nikke"), click(x=500, y=300, game="wuwa"), etc.
    """

    def __init__(self, config: Config):
        self.config = config
        self.window = window.WindowService()
        self.capture = capture.CaptureService(self.window)
        self.input = input_mod.InputService(self.window)
        self.max_dim = MAX_DIM
        self.ui_parser = UIParser(config.workspace.weights_dir)
        self._screenshot_dir = Path(config.workspace.screenshot_dir)
        self._processes: dict[str, process.GameProcessManager] = {}

    # ── Per-game helpers ────────────────────────────────────────────────

    def _get_process(self, game: str) -> process.GameProcessManager:
        if game not in self._processes:
            gc = self.config.games.get(game, GameConfig())
            self._processes[game] = process.GameProcessManager(
                self.config.build_profile(game), timeout=gc.launch_timeout,
            )
        return self._processes[game]

    # ── Process status ─────────────────────────────────────────────────

    def is_game_running(self, game: str) -> bool:
        return self._get_process(game).is_game_running

    def is_launcher_running(self, game: str) -> bool:
        return self._get_process(game).is_launcher_running

    # ── Window discovery ────────────────────────────────────────────────

    def find_game_window(self, game: str) -> int | None:
        p = self.config.build_profile(game)
        return self.window.find_by_path_and_class(p.game_path)

    def find_launcher_window(self, game: str) -> int | None:
        p = self.config.build_profile(game)
        if not p.launcher_path:
            return None
        return self.window.find_by_path_and_class(p.launcher_path)

    # ── Agent tool primitives ──────────────────────────────────────────

    def list_games(self) -> dict:
        """Return the list of configured game names available for use."""
        return {"games": sorted(self.config.games.keys())}

    def analyze(self, game: str, target: str = "game") -> dict:
        """Capture window, run OCR + YOLO, return structured state."""
        if target == "launcher":
            hwnd = self.find_launcher_window(game)
        else:
            hwnd = self.find_game_window(game)
        if hwnd is None:
            return {"error": f"{target} window not found for '{game}'"}

        frame = self.capture.capture(hwnd)
        if frame is None:
            return {"error": "Capture failed"}

        h, w = frame.shape[:2]
        if w > self.max_dim or h > self.max_dim:
            scale = self.max_dim / max(w, h)
            compressed = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            compressed = frame

        date_dir = self._screenshot_dir / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = str(date_dir / f"{game}_{ts}.jpeg")
        cv2.imwrite(path, compressed)

        parsed = self.ui_parser.parse(frame)

        bbox_path = str(date_dir / f"{game}_{ts}_bbox.jpeg")
        self._save_bbox_overlay(compressed, parsed, bbox_path)

        return {
            "width": compressed.shape[1],
            "height": compressed.shape[0],
            "ui_elements": parsed,
            "bbox_desc": (
                "All element bbox coordinates are normalized to [0, 1000] as "
                "[x1, y1, x2, y2], where (x1,y1) is top-left and (x2,y2) is "
                "bottom-right. Each element also has a 'center' [cx, cy] field "
                "already pre-computed — use center directly for click coordinates."
            ),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "image_path": path,
        }

    def read_image(self, path: str) -> dict:
        """Read an image file and return base64 content for vision model analysis."""
        p = Path(path)
        if not p.exists():
            return {"error": f"File not found: {path}"}

        image_bytes = p.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode()
        suffix = p.suffix.lower().lstrip(".")
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix

        return {
            "_multimodal": True,
            "content": [
                {"type": "text", "text": f"Screenshot from path: {path}"},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_b64}"}},
            ],
            "text_summary": f"{path}",
        }

    def click(self, x: int, y: int, game: str, target: str = "game") -> dict:
        """Click at normalized [0, 1000] coordinates."""
        if target == "launcher":
            hwnd = self.find_launcher_window(game)
        else:
            hwnd = self.find_game_window(game)
        if hwnd is None:
            return {"success": False, "error": f"{target} window not found for '{game}'"}
        return self.input.click_normalized(hwnd, x, y)

    def launch(self, game: str) -> dict:
        """Start the launcher and wait for its window."""
        if self.is_game_running(game):
            return {"status": "already_running", "message": f"{game} is already running"}

        if not self.is_launcher_running(game):
            if not self._start_launcher(game):
                return {"status": "error", "message": "Failed to start launcher"}

        hwnd = self._wait_for_launcher_window(game, timeout=30)
        if hwnd is None:
            return {"status": "error", "message": "Launcher window not found"}

        self._force_foreground(hwnd)
        return {
            "status": "launcher_ready",
            "message": "Launcher is ready. Use screenshot+vision to find Start Game button, click it, then wait_for_game().",
        }

    def wait_for_game(self, game: str) -> dict:
        """Wait for the game process and window after clicking Start Game in launcher."""
        if not self._wait_for_game_process(game, timeout=120):
            return {"status": "timeout", "message": "Game process did not start"}

        hwnd = self._wait_for_game_window(game, timeout=60)
        if hwnd is None:
            return {"status": "error", "message": "Game window not found"}

        self._force_foreground(hwnd)
        time.sleep(2)
        return {"status": "game_ready", "message": "Game window is ready"}

    def wait(self, seconds: float) -> dict:
        """Wait for a duration."""
        time.sleep(seconds)
        return {"status": "waited", "seconds": seconds}

    def stop(self, game: str) -> dict:
        """Stop both game and launcher processes."""
        pm = self._get_process(game)
        return {
            "game_stopped": pm.stop_game(),
            "launcher_stopped": pm.stop_launcher(),
        }

    # ── Tool registration ───────────────────────────────────────────────

    def register_tools(self) -> None:
        """Register all tool primitives into the hermes tool registry."""
        registry.register(
            name="analyze",
            toolset="game_controller",
            schema={
                "description": "Capture the game or launcher window, run OCR text detection + YOLO icon detection, and save a compressed screenshot to disk. Returns structured state including image_path (for use with read_image), OCR text elements with normalized bbox [0,1000] coordinates, and screen dimensions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "game": {
                            "type": "string",
                            "description": "Which game to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["game", "launcher"],
                            "description": "Which window to capture: 'game' (default) or 'launcher'.",
                        },
                    },
                    "required": ["game"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.analyze(game=args["game"], target=args.get("target", "game"))
            ),
        )

        registry.register(
            name="list_games",
            toolset="game_controller",
            schema={
                "description": "List the names of all configured games that are available to operate on. Use this first if you need to know which game names are valid for the 'game' parameter in other tools.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            handler=lambda _args, **kw: tool_result(self.list_games()),
        )

        registry.register(
            name="read_image",
            toolset="game_controller",
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
            toolset="game_controller",
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
                        "game": {
                            "type": "string",
                            "description": "Which game to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["game", "launcher"],
                            "description": "Which window to click on: 'game' (default) or 'launcher'.",
                        },
                    },
                    "required": ["x", "y", "game"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.click(x=args["x"], y=args["y"], game=args["game"], target=args.get("target", "game"))
            ),
        )

        registry.register(
            name="launch",
            toolset="game_controller",
            schema={
                "description": "Start the game launcher and wait for its window to appear. After this returns 'launcher_ready', use analyze(target='launcher') to see the launcher UI, find the Start Game button via vision, click it with click(x, y, target='launcher'), then call wait_for_game.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "game": {
                            "type": "string",
                            "description": "Which game to launch, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["game"],
                },
            },
            handler=lambda args, **kw: tool_result(self.launch(game=args["game"])),
        )

        registry.register(
            name="wait",
            toolset="game_controller",
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
            name="wait_for_game",
            toolset="game_controller",
            schema={
                "description": "Wait for the game process and window after clicking Start Game in the launcher.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "game": {
                            "type": "string",
                            "description": "Which game to wait for, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["game"],
                },
            },
            handler=lambda args, **kw: tool_result(self.wait_for_game(game=args["game"])),
        )

        registry.register(
            name="game_running",
            toolset="game_controller",
            schema={
                "description": "Check whether the game process is currently running.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "game": {
                            "type": "string",
                            "description": "Which game to check, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["game"],
                },
            },
            handler=lambda args, **kw: tool_result(
                {"running": self.is_game_running(game=args["game"])}
            ),
        )

        registry.register(
            name="launcher_running",
            toolset="game_controller",
            schema={
                "description": "Check whether the launcher process is currently running.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "game": {
                            "type": "string",
                            "description": "Which game to check, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["game"],
                },
            },
            handler=lambda args, **kw: tool_result(
                {"running": self.is_launcher_running(game=args["game"])}
            ),
        )

        registry.register(
            name="stop",
            toolset="game_controller",
            schema={
                "description": "Stop both the game and launcher processes for a given game.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "game": {
                            "type": "string",
                            "description": "Which game to stop, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["game"],
                },
            },
            handler=lambda args, **kw: tool_result(self.stop(game=args["game"])),
        )

        logger.info("Registered %d game_controller tools in hermes registry", 10)

    def _save_bbox_overlay(self, image, elements: list, path: str) -> None:
        """Draw normalized [0,1000] bboxes onto image and save to path."""
        h, w = image.shape[:2]
        overlay = image.copy()
        for el in elements:
            x1, y1, x2, y2 = el["bbox"]
            px1, py1 = int(x1 / 1000 * w), int(y1 / 1000 * h)
            px2, py2 = int(x2 / 1000 * w), int(y2 / 1000 * h)
            color = (0, 255, 0) if "label" in el else (255, 200, 0)
            cv2.rectangle(overlay, (px1, py1), (px2, py2), color, 1)
            label = el.get("text") or el.get("label", "")
            if label:
                cv2.putText(overlay, label[:30], (px1, max(py1 - 4, 12 )),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        cv2.imwrite(path, overlay)

    # ── Private helpers ─────────────────────────────────────────────────

    def _force_foreground(self, hwnd: int) -> bool:
        return self.window.force_foreground(hwnd)

    def _start_launcher(self, game: str) -> bool:
        pm = self._get_process(game)
        if not pm.launcher:
            logger.error("No launcher configured for '%s'", game)
            return False
        return pm.launcher.start()

    def _wait_for_launcher_window(self, game: str, timeout: float = 30) -> int | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self.find_launcher_window(game)
            if hwnd:
                return hwnd
            time.sleep(1)
        return None

    def _wait_for_game_window(self, game: str, timeout: float = 60) -> int | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self.find_game_window(game)
            if hwnd:
                return hwnd
            time.sleep(1)
        return None

    def _wait_for_game_process(self, game: str, timeout: float = 120) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_game_running(game):
                return True
            time.sleep(1)
        return False