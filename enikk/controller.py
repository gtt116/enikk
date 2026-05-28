"""Game controller — multi-game agent-facing services."""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from tools.registry import registry, tool_result

from .config import Config, GameConfig
from .game import capture, input as input_mod, process, window
from .ui_parser import UIParser


logger = logging.getLogger(__name__)

IMAGE_PATH_KEY = "image_path"
SOM_IMAGE_PATH_KEY = "SoM_image_path"


class GameController:
    """Bundled game services for multiple game instances.

    Usage:
        gc = GameController(config)"""

    TOOLSET = "game_controller"

    def __init__(self, config: Config):
        self.config = config
        self.window = window.WindowService()
        self.capture = capture.CaptureService(self.window)
        self.input = input_mod.InputService(self.window)
        self.ui_parser = UIParser(config.workspace.weights_dir, screenshot_max_dim=config.workspace.screenshot_max_dim)
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
        t0 = time.time()
        logger.info("analyze(game=%s, target=%s) start", game, target)

        hwnd = self._find_window(game, target)
        if hwnd is None:
            logger.info("analyze: %s window not found", target)
            return {"error": f"{target} window not found for '{game}'"}

        frame = self.capture.capture(hwnd)
        if frame is None:
            logger.info("analyze: capture failed")
            return {"error": "Capture failed"}

        h, w = frame.shape[:2]
        max_dim = self.config.workspace.screenshot_max_dim
        if w > max_dim or h > max_dim:
            scale = max_dim / max(w, h)
            compressed = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            compressed = frame

        date_dir = self._screenshot_dir / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = str(date_dir / f"{game}_{ts}.jpeg")
        cv2.imwrite(path, compressed)

        parsed = self.ui_parser.parse(frame)
        logger.info("analyze: found %d ui_elements", len(parsed))

        bbox_path = str(date_dir / f"{game}_{ts}_bbox.jpeg")
        self._save_bbox_overlay(compressed, parsed, bbox_path, hwnd=hwnd, orig_size=(h, w))

        elapsed = time.time() - t0
        logger.info("analyze: done in %.2fs", elapsed)

        return {
            "width": compressed.shape[1],
            "height": compressed.shape[0],
            "ui_elements": parsed,
            IMAGE_PATH_KEY: path,
            SOM_IMAGE_PATH_KEY: bbox_path,
            "bbox_desc": (
                "All element bbox coordinates are normalized to [0, 1000] as "
                "[x1, y1, x2, y2], where (x1,y1) is top-left and (x2,y2) is "
                "bottom-right. Each element also has a 'center' [cx, cy] field "
                "already pre-computed — use center directly for click coordinates."
            ),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    def read_image(self, path: str) -> dict:
        """Read an image file and return base64 content for vision model analysis."""
        logger.info("read_image(path=%s)", path)
        p = Path(path)
        if not p.exists():
            logger.info("read_image: file not found")
            return {"error": f"File not found: {path}"}

        image_bytes = p.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode()
        suffix = p.suffix.lower().lstrip(".")
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        logger.info("read_image: done, mime=%s, size=%d bytes", mime, len(image_bytes))

        return {
            "_multimodal": True,
            "text_summary": f"{path}",
            "content": [
                {"type": "text", "text": f"Screenshot from path: {path}"},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_b64}"}},
            ],
        }

    def click(self, x: int, y: int, game: str, target: str = "game") -> dict:
        """Click at normalized [0, 1000] coordinates."""
        t0 = time.time()
        logger.info("click(x=%d, y=%d, game=%s, target=%s)", x, y, game, target)

        hwnd = self._find_window(game, target)
        if hwnd is None:
            logger.info("click: %s window not found", target)
            return {"success": False, "error": f"{target} window not found for '{game}'"}

        result = self.input.click_normalized(hwnd, x, y)
        elapsed = time.time() - t0
        logger.info("click: done in %.2fs, success=%s", elapsed, result.get("success"))
        return result

    def press_key(self, key: str, game: str, target: str = "game", wait_time: float = 0.2) -> dict:
        """Press a key on the game or launcher window."""
        t0 = time.time()
        logger.info("press_key(key=%s, game=%s, target=%s)", key, game, target)

        hwnd = self._find_window(game, target)
        if hwnd is None:
            logger.info("press_key: %s window not found", target)
            return {"success": False, "error": f"{target} window not found for '{game}'"}

        self._force_foreground(hwnd)
        self.input.press_key(key, wait_time)
        elapsed = time.time() - t0
        logger.info("press_key: done in %.2fs", elapsed)
        return {"success": True, "key": key}

    def swipe_screen(self, x1: int, y1: int, x2: int, y2: int, game: str, target: str = "game", speed: float = 1.0) -> dict:
        """Swipe from (x1,y1) to (x2,y2) in normalized [0,1000] coordinates."""
        t0 = time.time()
        logger.info("swipe_screen(%d,%d -> %d,%d, speed=%.1f, game=%s, target=%s)", x1, y1, x2, y2, speed, game, target)

        hwnd = self._find_window(game, target)
        if hwnd is None:
            logger.info("swipe_screen: %s window not found", target)
            return {"success": False, "error": f"{target} window not found for '{game}'"}

        region = self.window.get_client_region(hwnd)
        if region is None:
            return {"success": False, "error": "Window client region not available"}

        self._force_foreground(hwnd)
        abs_x1 = region.left + int(x1 / 1000 * region.width)
        abs_y1 = region.top + int(y1 / 1000 * region.height)
        abs_x2 = region.left + int(x2 / 1000 * region.width)
        abs_y2 = region.top + int(y2 / 1000 * region.height)

        self.input.swipe_screen((abs_x1, abs_y1), (abs_x2, abs_y2), speed=speed)
        elapsed = time.time() - t0
        logger.info("swipe_screen: done in %.2fs", elapsed)
        return {"success": True, "from": [x1, y1], "to": [x2, y2]}

    def launch(self, game: str) -> dict:
        """Start the launcher and wait for its window."""
        t0 = time.time()
        logger.info("launch(game=%s) start", game)

        if self.is_game_running(game):
            logger.info("launch: %s already running", game)
            return {"status": "already_running", "message": f"{game} is already running"}

        if not self.is_launcher_running(game):
            logger.info("launch: starting launcher for %s", game)
            if not self._start_launcher(game):
                logger.info("launch: failed to start launcher")
                return {"status": "error", "message": "Failed to start launcher"}

        hwnd = self._wait_for_launcher_window(game, timeout=30)
        if hwnd is None:
            logger.info("launch: launcher window not found within 30s")
            return {"status": "error", "message": "Launcher window not found"}

        self._force_foreground(hwnd)
        elapsed = time.time() - t0
        logger.info("launch: launcher ready in %.2fs", elapsed)
        return {
            "status": "launcher_ready",
            "message": "Launcher is ready. Use analyze() to find Start Game button, click it, then wait_for_game().",
        }

    def wait_for_game(self, game: str) -> dict:
        """Wait for the game process and window after clicking Start Game in launcher."""
        t0 = time.time()
        logger.info("wait_for_game(game=%s) start", game)

        if not self._wait_for_game_process(game, timeout=120):
            logger.info("wait_for_game: process timeout")
            return {"status": "timeout", "message": "Game process did not start"}

        hwnd = self._wait_for_game_window(game, timeout=60)
        if hwnd is None:
            logger.info("wait_for_game: window timeout")
            return {"status": "error", "message": "Game window not found"}

        self._force_foreground(hwnd)
        time.sleep(2)
        elapsed = time.time() - t0
        logger.info("wait_for_game: ready in %.2fs", elapsed)
        return {"status": "game_ready", "message": "Game window is ready"}

    def wait(self, seconds: float) -> dict:
        """Wait for a duration."""
        logger.info("wait(%.1fs)", seconds)
        time.sleep(seconds)
        logger.info("wait: done")
        return {"status": "waited", "seconds": seconds}

    def stop(self, game: str) -> dict:
        """Stop both game and launcher processes."""
        logger.info("stop(game=%s)", game)
        pm = self._get_process(game)
        result = {
            "game_stopped": pm.stop_game(),
            "launcher_stopped": pm.stop_launcher(),
        }
        logger.info("stop: %s", result)
        return result

    # ── Tool registration ───────────────────────────────────────────────

    def register_tools(self) -> None:
        """Register all tool primitives into the hermes tool registry."""
        registry.register(
            name="analyze",
            toolset=GameController.TOOLSET,
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
            toolset=GameController.TOOLSET,
            schema={
                "description": "List the names of all configured games that are available to operate on. Use this first if you need to know which game names are valid for the 'game' parameter in other tools.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            handler=lambda args, **kw: tool_result(self.list_games()),
        )

        registry.register(
            name="read_image",
            toolset=GameController.TOOLSET,
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
            toolset=GameController.TOOLSET,
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
                    "required": ["x", "y", "game", "target"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.click(x=args["x"], y=args["y"], game=args["game"], target=args.get("target", "game"))
            ),
        )

        registry.register(
            name="press_key",
            toolset=GameController.TOOLSET,
            schema={
                "description": "Press a key on the game or launcher window. Brings the target window to foreground before sending the key press. Supports pyautogui key names (e.g. 'enter', 'escape', 'w', 'f1', 'space').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key name to press (e.g. 'enter', 'escape', 'w', 'f1', 'space', 'tab').",
                        },
                        "game": {
                            "type": "string",
                            "description": "Which game to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["game", "launcher"],
                            "description": "Which window to send the key to: 'game' (default) or 'launcher'.",
                        },
                        "wait_time": {
                            "type": "number",
                            "description": "How long to hold the key down in seconds (default 0.2).",
                        },
                    },
                    "required": ["key", "game"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.press_key(key=args["key"], game=args["game"], target=args.get("target", "game"), wait_time=args.get("wait_time", 0.2))
            ),
        )

        registry.register(
            name="swipe_screen",
            toolset=GameController.TOOLSET,
            schema={
                "description": "Swipe from one point to another on the game or launcher window using natural touch simulation. Brings the target window to foreground before swiping. Coordinates are normalized [0,1000]. Use for scrolling lists, panning maps, or dragging UI elements.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "x1": {
                            "type": "integer",
                            "description": "Start X coordinate (0-1000, normalized).",
                        },
                        "y1": {
                            "type": "integer",
                            "description": "Start Y coordinate (0-1000, normalized).",
                        },
                        "x2": {
                            "type": "integer",
                            "description": "End X coordinate (0-1000, normalized).",
                        },
                        "y2": {
                            "type": "integer",
                            "description": "End Y coordinate (0-1000, normalized).",
                        },
                        "game": {
                            "type": "string",
                            "description": "Which game to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["game", "launcher"],
                            "description": "Which window to swipe in: 'game' (default) or 'launcher'.",
                        },
                        "speed": {
                            "type": "number",
                            "description": "Swipe speed multiplier (default 1.0). Higher values = faster swipe.",
                        },
                    },
                    "required": ["x1", "y1", "x2", "y2", "game"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.swipe_screen(x1=args["x1"], y1=args["y1"], x2=args["x2"], y2=args["y2"], game=args["game"], target=args.get("target", "game"), speed=args.get("speed", 1.0))
            ),
        )

        registry.register(
            name="launch",
            toolset=GameController.TOOLSET,
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
            toolset=GameController.TOOLSET,
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
            toolset=GameController.TOOLSET,
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
            toolset=GameController.TOOLSET,
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
            toolset=GameController.TOOLSET,
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
            toolset=GameController.TOOLSET,
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

    # ── Private helpers ─────────────────────────────────────────────────

    def _find_window(self, game: str, target: str) -> int | None:
        if target == "launcher":
            return self.find_launcher_window(game)
        return self.find_game_window(game)

    def _save_bbox_overlay(self, image, elements: list, path: str, *,
                           hwnd: int | None = None, orig_size: tuple[int, int] | None = None) -> None:
        """Draw normalized [0,1000] bboxes onto image and save to path."""
        from PIL import Image, ImageDraw, ImageFont

        h, w = image.shape[:2]
        overlay = image.copy()

        # Try to load a font that supports CJK characters
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont
        try:
            font = ImageFont.truetype("msyh.ttc", 14)  # Microsoft YaHei on Windows
        except Exception:
            font = ImageFont.load_default()

        # Convert BGR to RGB for PIL
        rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        draw = ImageDraw.Draw(pil_img)

        for el in elements:
            x1, y1, x2, y2 = el["bbox"]
            px1, py1 = int(x1 / 1000 * w), int(y1 / 1000 * h)
            px2, py2 = int(x2 / 1000 * w), int(y2 / 1000 * h)
            color = (0, 255, 0) if "label" in el else (255, 200, 0)
            draw.rectangle([px1, py1, px2, py2], outline=color, width=1)

            label = el.get("text") or el.get("label", "")
            if label:
                text_y = max(py1 - 18, 0)
                draw.text((px1, text_y), label[:30], fill=color, font=font)

        # Draw mouse cursor position as red crosshair
        if hwnd is not None and self.window.is_valid(hwnd):
            try:
                import win32gui
                sx, sy = win32gui.GetCursorPos()
                ox, oy = win32gui.ClientToScreen(hwnd, (0, 0))
                # Cursor position relative to client area in original pixel coords
                cx, cy = sx - ox, sy - oy
                # Scale to compressed image coords
                if orig_size is not None:
                    oh, ow = orig_size
                    cx = int(cx * w / ow)
                    cy = int(cy * h / oh)
                if 0 <= cx < w and 0 <= cy < h:
                    cs = 10
                    draw.line([(cx - cs, cy), (cx + cs, cy)], fill=(255, 0, 0), width=2)
                    draw.line([(cx, cy - cs), (cx, cy + cs)], fill=(255, 0, 0), width=2)
                    draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 0, 0))
            except Exception:
                pass

        # Convert back to BGR for cv2.imwrite
        overlay = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        cv2.imwrite(path, overlay)

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