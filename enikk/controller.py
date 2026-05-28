"""App controller — multi-app agent-facing services."""
from __future__ import annotations

import base64
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from tools.registry import registry, tool_result

from .config import Config, AppConfig
from .game import capture, input as input_mod, process, window
from .ui_parser import UIParser


logger = logging.getLogger(__name__)

IMAGE_PATH_KEY = "image_path"
SOM_IMAGE_PATH_KEY = "SoM_image_path"


class AppController:
    """Bundled app services for multiple app instances.

    Usage:
        ac = AppController(config)"""

    TOOLSET = "app_controller"

    def __init__(self, config: Config):
        self.config = config
        self.window = window.WindowService()
        self.capture = capture.CaptureService(self.window)
        self.input = input_mod.InputService(self.window)
        self.ui_parser = UIParser(config.workspace.weights_dir, screenshot_max_dim=config.workspace.screenshot_max_dim)
        self._screenshot_dir = Path(config.workspace.screenshot_dir)
        self._processes: dict[str, process.AppProcessManager] = {}

    # ── Per-app helpers ────────────────────────────────────────────────

    def _get_process(self, app: str) -> process.AppProcessManager:
        if app not in self._processes:
            ac = self.config.apps.get(app, AppConfig())
            self._processes[app] = process.AppProcessManager(
                self.config.build_profile(app), timeout=ac.launch_timeout,
            )
        return self._processes[app]

    # ── Process status ─────────────────────────────────────────────────

    def is_app_running(self, app: str) -> bool:
        return self._get_process(app).is_app_running

    def is_launcher_running(self, app: str) -> bool:
        return self._get_process(app).is_launcher_running

    # ── Window discovery ────────────────────────────────────────────────

    def find_app_window(self, app: str) -> int | None:
        p = self.config.build_profile(app)
        return self.window.find_by_path_and_class(p.app_path)

    def find_launcher_window(self, app: str) -> int | None:
        p = self.config.build_profile(app)
        if not p.launcher_path:
            return None
        return self.window.find_by_path_and_class(p.launcher_path)

    # ── Agent tool primitives ──────────────────────────────────────────

    def list_apps(self) -> dict:
        """Return the list of configured app names available for use."""
        return {"apps": sorted(self.config.apps.keys())}

    def analyze(self, app: str, target: str = "app") -> dict:
        """Capture window, run OCR + YOLO, return structured state."""
        t0 = time.time()
        logger.info("analyze(app=%s, target=%s) start", app, target)

        hwnd = self._find_window(app, target)
        if hwnd is None:
            logger.info("analyze: %s window not found", target)
            return {"error": f"{target} window not found for '{app}'"}

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
        path = str(date_dir / f"{app}_{ts}.jpeg")
        cv2.imwrite(path, compressed)

        parsed = self.ui_parser.parse(frame)
        logger.info("analyze: found %d ui_elements", len(parsed))

        bbox_path = str(date_dir / f"{app}_{ts}_bbox.jpeg")
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

    def click(self, x: int, y: int, app: str, target: str = "app") -> dict:
        """Click at normalized [0, 1000] coordinates."""
        t0 = time.time()
        logger.info("click(x=%d, y=%d, app=%s, target=%s)", x, y, app, target)

        hwnd = self._find_window(app, target)
        if hwnd is None:
            logger.info("click: %s window not found", target)
            return {"success": False, "error": f"{target} window not found for '{app}'"}

        result = self.input.click_normalized(hwnd, x, y)
        elapsed = time.time() - t0
        logger.info("click: done in %.2fs, success=%s", elapsed, result.get("success"))
        return result

    def press_key(self, key: str, app: str, target: str = "app", wait_time: float = 0.2) -> dict:
        """Press a key on the app or launcher window."""
        t0 = time.time()
        logger.info("press_key(key=%s, app=%s, target=%s)", key, app, target)

        hwnd = self._find_window(app, target)
        if hwnd is None:
            logger.info("press_key: %s window not found", target)
            return {"success": False, "error": f"{target} window not found for '{app}'"}

        self._force_foreground(hwnd)
        self.input.press_key(key, wait_time)
        elapsed = time.time() - t0
        logger.info("press_key: done in %.2fs", elapsed)
        return {"success": True, "key": key}

    def swipe_screen(self, x1: int, y1: int, x2: int, y2: int, app: str, target: str = "app", speed: float = 1.0) -> dict:
        """Swipe from (x1,y1) to (x2,y2) in normalized [0,1000] coordinates."""
        t0 = time.time()
        logger.info("swipe_screen(%d,%d -> %d,%d, speed=%.1f, app=%s, target=%s)", x1, y1, x2, y2, speed, app, target)

        hwnd = self._find_window(app, target)
        if hwnd is None:
            logger.info("swipe_screen: %s window not found", target)
            return {"success": False, "error": f"{target} window not found for '{app}'"}

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

    def launch(self, app: str | None = None, exe: str | None = None) -> dict:
        """Start the launcher and wait for its window.

        If exe is provided without app, auto-register the app and derive the key from the exe filename.
        If both app and exe are provided, use the specified app key.
        """
        t0 = time.time()

        # Auto-register if exe provided without app
        if exe and not app:
            app = Path(exe).stem  # e.g., "cloudmusic" from "cloudmusic.exe"
            self.config.register_app(app, exe)
            logger.info("Auto-registered app: %s from exe: %s", app, exe)

        if not app:
            return {"error": "Either 'app' or 'exe' must be provided"}

        logger.info("launch(app=%s, exe=%s) start", app, exe)

        if self.is_app_running(app):
            logger.info("launch: %s already running", app)
            return {"status": "already_running", "message": f"{app} is already running"}

        if exe and not self.is_launcher_running(app):
            logger.info("launch: starting custom exe: %s", exe)
            try:
                subprocess.Popen([exe])
            except Exception as e:
                logger.error("launch: failed to start exe %s: %s", exe, e)
                return {"error": f"Failed to start executable: {e}"}
        elif not self.is_launcher_running(app):
            logger.info("launch: starting launcher for %s", app)
            if not self._start_launcher(app):
                logger.info("launch: failed to start launcher")
                return {"status": "error", "message": "Failed to start launcher"}

        hwnd = self._wait_for_launcher_window(app, timeout=30)
        if hwnd is None:
            logger.info("launch: launcher window not found within 30s")
            return {"status": "error", "message": "Launcher window not found"}

        self._force_foreground(hwnd)
        elapsed = time.time() - t0
        logger.info("launch: launcher ready in %.2fs", elapsed)
        return {
            "status": "launcher_ready",
            "message": "Launcher is ready. Use analyze() to find Start Game button, click it, then wait and analyze(target='app') to check if app loaded.",
        }

    def wait(self, seconds: float) -> dict:
        """Wait for a specified duration."""
        logger.info("wait(%.1fs)", seconds)
        time.sleep(seconds)
        logger.info("wait: done")
        return {"status": "waited", "seconds": seconds}

    def stop(self, app: str) -> dict:
        """Stop both app and launcher processes."""
        logger.info("stop(app=%s)", app)
        pm = self._get_process(app)
        result = {
            "app_stopped": pm.stop_app(),
            "launcher_stopped": pm.stop_launcher(),
        }
        logger.info("stop: %s", result)
        return result

    # ── Tool registration ───────────────────────────────────────────────

    def register_tools(self) -> None:
        """Register all tool primitives into the hermes tool registry."""
        registry.register(
            name="analyze",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Capture the app or launcher window, run OCR text detection + YOLO icon detection, and save a compressed screenshot to disk. Returns structured state including image_path (for use with read_image), OCR text elements with normalized bbox [0,1000] coordinates, and screen dimensions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {
                            "type": "string",
                            "description": "Which app to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["app", "launcher"],
                            "description": "Which window to capture: 'app' (default) or 'launcher'.",
                        },
                    },
                    "required": ["app"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.analyze(app=args["app"], target=args.get("target", "app"))
            ),
        )

        registry.register(
            name="list_apps",
            toolset=AppController.TOOLSET,
            schema={
                "description": "List the names of all configured apps that are available to operate on. Use this first if you need to know which app names are valid for the 'app' parameter in other tools.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            handler=lambda args, **kw: tool_result(self.list_apps()),
        )

        registry.register(
            name="read_image",
            toolset=AppController.TOOLSET,
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
            toolset=AppController.TOOLSET,
            schema={
                "description": "Click at normalized [0, 1000] coordinates on the app or launcher window. Coordinates are percentages of screen width/height where (0,0) is top-left and (1000,1000) is bottom-right.",
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
                        "app": {
                            "type": "string",
                            "description": "Which app to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["app", "launcher"],
                            "description": "Which window to click on: 'app' (default) or 'launcher'.",
                        },
                    },
                    "required": ["x", "y", "app", "target"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.click(x=args["x"], y=args["y"], app=args["app"], target=args.get("target", "app"))
            ),
        )

        registry.register(
            name="press_key",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Press a key on the app or launcher window. Brings the target window to foreground before sending the key press. Supports pyautogui key names (e.g. 'enter', 'escape', 'w', 'f1', 'space').",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key name to press (e.g. 'enter', 'escape', 'w', 'f1', 'space', 'tab').",
                        },
                        "app": {
                            "type": "string",
                            "description": "Which app to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["app", "launcher"],
                            "description": "Which window to send the key to: 'app' (default) or 'launcher'.",
                        },
                        "wait_time": {
                            "type": "number",
                            "description": "How long to hold the key down in seconds (default 0.2).",
                        },
                    },
                    "required": ["key", "app"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.press_key(key=args["key"], app=args["app"], target=args.get("target", "app"), wait_time=args.get("wait_time", 0.2))
            ),
        )

        registry.register(
            name="swipe_screen",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Swipe from one point to another on the app or launcher window using natural touch simulation. Brings the target window to foreground before swiping. Coordinates are normalized [0,1000]. Use for scrolling lists, panning maps, or dragging UI elements.",
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
                        "app": {
                            "type": "string",
                            "description": "Which app to operate on, e.g. 'nikke' or 'wutheringwave'.",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["app", "launcher"],
                            "description": "Which window to swipe in: 'app' (default) or 'launcher'.",
                        },
                        "speed": {
                            "type": "number",
                            "description": "Swipe speed multiplier (default 1.0). Higher values = faster swipe.",
                        },
                    },
                    "required": ["x1", "y1", "x2", "y2", "app"],
                },
            },
            handler=lambda args, **kw: tool_result(
                self.swipe_screen(x1=args["x1"], y1=args["y1"], x2=args["x2"], y2=args["y2"], app=args["app"], target=args.get("target", "app"), speed=args.get("speed", 1.0))
            ),
        )

        registry.register(
            name="launch",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Start the app launcher and wait for its window to appear. Optionally pass an exe path to launch a custom executable directly (auto-registers the app). After this returns 'launcher_ready', use analyze(target='launcher') to see the launcher UI, find the Start button via vision, click it with click(x, y, target='launcher'), then wait and analyze(target='app') to check if app loaded.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {
                            "type": "string",
                            "description": "Which app to launch, e.g. 'nikke' or 'wutheringwave'. Optional if 'exe' is provided.",
                        },
                        "exe": {
                            "type": "string",
                            "description": "Optional: absolute path to an executable to launch directly (e.g. 'D:\\\\Program Files\\\\Netease\\\\CloudMusic\\\\cloudmusic.exe'). If provided without 'app', auto-registers with key derived from filename.",
                        },
                    },
                    "required": [],
                },
            },
            handler=lambda args, **kw: tool_result(self.launch(app=args.get("app"), exe=args.get("exe"))),
        )

        registry.register(
            name="wait",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Wait/sleep for a specified duration. Use for app animations, loading screens, or waiting for UI transitions to complete.",
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
            name="app_running",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Check whether the app process is currently running.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {
                            "type": "string",
                            "description": "Which app to check, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["app"],
                },
            },
            handler=lambda args, **kw: tool_result(
                {"running": self.is_app_running(app=args["app"])}
            ),
        )

        registry.register(
            name="launcher_running",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Check whether the launcher process is currently running.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {
                            "type": "string",
                            "description": "Which app to check, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["app"],
                },
            },
            handler=lambda args, **kw: tool_result(
                {"running": self.is_launcher_running(app=args["app"])}
            ),
        )

        registry.register(
            name="stop",
            toolset=AppController.TOOLSET,
            schema={
                "description": "Stop both the app and launcher processes for a given app.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "app": {
                            "type": "string",
                            "description": "Which app to stop, e.g. 'nikke' or 'wutheringwave'.",
                        },
                    },
                    "required": ["app"],
                },
            },
            handler=lambda args, **kw: tool_result(self.stop(app=args["app"])),
        )

    # ── Private helpers ─────────────────────────────────────────────────

    def _find_window(self, app: str, target: str) -> int | None:
        if target == "launcher":
            return self.find_launcher_window(app)
        return self.find_app_window(app)

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

    def _start_launcher(self, app: str) -> bool:
        pm = self._get_process(app)
        if not pm.launcher:
            logger.error("No launcher configured for '%s'", app)
            return False
        return pm.launcher.start()

    def _wait_for_launcher_window(self, app: str, timeout: float = 30) -> int | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self.find_launcher_window(app)
            if hwnd:
                return hwnd
            time.sleep(1)
        return None
