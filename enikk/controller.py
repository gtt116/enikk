"""App controller — multi-app agent-facing services."""
from __future__ import annotations

import base64
import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import psutil
import win32gui
import win32process

from .tool_decorator import tool, register_all_tools

from .config import Config, AppConfig
from .file_search import search_files
from .game import capture, input as input_mod, process, window
from .game.window_picker import WindowPicker, _resolve_real_pid, WindowPickerOverlay
from .ui_parser import UIParser


logger = logging.getLogger(__name__)

IMAGE_PATH_KEY = "image_path"
SOM_IMAGE_PATH_KEY = "SoM_image_path"


def extract_image_path(result) -> str | None:
    """Extract local image path from a tool result (dict or JSON string)."""
    obj = None
    if isinstance(result, dict):
        obj = result
    elif isinstance(result, str):
        try:
            obj = json.loads(result)
        except (ValueError, TypeError):
            pass
    if obj and isinstance(obj, dict):
        path = obj.get(SOM_IMAGE_PATH_KEY) or obj.get(IMAGE_PATH_KEY)
        if path:
            return path
    return None




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
        self._input_lock = threading.Lock()  # Protects foreground+input operations
        self._window_picker = WindowPicker()
        self._window_picker_overlay = WindowPickerOverlay(self._window_picker)
        self._picked_hwnd: int | None = None
        self._picked_info: dict | None = None

    # ── Per-app helpers ────────────────────────────────────────────────

    def _get_process(self, app: str) -> process.AppProcessManager:
        if app not in self._processes:
            ac = self.config.apps.get(app, AppConfig())
            self._processes[app] = process.AppProcessManager(
                self.config.get_app_config(app), timeout=ac.launch_timeout,
            )
        return self._processes[app]

    # ── Process status ─────────────────────────────────────────────────

    def is_app_running(self, app: str) -> bool:
        return self._get_process(app).is_app_running

    def is_launcher_running(self, app: str) -> bool:
        return self._get_process(app).is_launcher_running

    # ── Window discovery ────────────────────────────────────────────────

    def find_app_window(self, app: str) -> int | None:
        p = self.config.get_app_config(app)
        return self.window.find_by_path_and_class(p.app_path)

    def find_launcher_window(self, app: str) -> int | None:
        p = self.config.get_app_config(app)
        if not p.launcher_path:
            return None
        return self.window.find_by_path_and_class(p.launcher_path)

    # ── Window picker ───────────────────────────────────────────────────

    @tool("List all visible windows on the desktop. Returns hwnd, title, exe, pid, and rect for each window.")
    def list_windows(self) -> dict:
        windows = self._window_picker.enum_visible_windows()
        return {"windows": windows, "count": len(windows)}

    @tool("Find a visible window by title or exe name (fuzzy match). Returns the first matching window.")
    def find_window(self, title: str = "", exe: str = "") -> dict:
        """
        Args:
            title: Window title to search for (case-insensitive substring).
            exe: Executable name to search for, e.g. 'chrome.exe'.
        """
        if not title and not exe:
            return {"error": "Provide title or exe to search for"}
        result = self._window_picker.find_window(title=title, exe=exe)
        if result is None:
            return {"found": False, "error": f"No window found matching title='{title}' exe='{exe}'"}
        return {"found": True, "window": result}

    @tool("Close a window. Sends WM_CLOSE first (graceful), then terminates, then kills as last resort.")
    def close_window(self, hwnd: int) -> dict:
        """
        Args:
            hwnd: Window handle to close.
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)

        # Stage 1: WM_CLOSE
        try:
            win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            logger.info("close_window: WM_CLOSE sent to hwnd=%d '%s'", hwnd, title)
        except Exception:
            pass

        # Wait for graceful close
        for _ in range(20):
            time.sleep(0.25)
            if not self.window.is_valid(hwnd):
                return {"success": True, "method": "wm_close", "title": title, "pid": pid}

        # Stage 2: terminate process
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
            logger.info("close_window: terminated pid=%d", pid)
            return {"success": True, "method": "terminate", "title": title, "pid": pid}
        except psutil.TimeoutExpired:
            pass
        except Exception as e:
            logger.warning("close_window: terminate failed: %s", e)

        # Stage 3: kill
        try:
            proc = psutil.Process(pid)
            proc.kill()
            proc.wait(timeout=3)
            logger.info("close_window: killed pid=%d", pid)
            return {"success": True, "method": "kill", "title": title, "pid": pid}
        except Exception as e:
            return {"success": False, "error": f"Failed to close: {e}"}

    def pick_window(self, hwnd: int) -> dict:
        """Bind to a specific window by HWND."""
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        # Resolve real PID for UWP/hosted windows
        pid = _resolve_real_pid(hwnd, pid)
        exe = ""
        try:
            exe = psutil.Process(pid).name()
        except Exception:
            pass

        self._picked_hwnd = hwnd
        exe_path = ""
        try:
            exe_path = psutil.Process(pid).exe()
        except Exception:
            pass
        self._picked_info = {
            "hwnd": hwnd,
            "title": title,
            "pid": pid,
            "exe": exe,
            "exe_path": exe_path,
        }
        logger.info("Picked window: hwnd=%d, title=%r, exe=%r, exe_path=%r", hwnd, title, exe, exe_path)
        return {"success": True, "window": self._picked_info}

    def unpick_window(self) -> dict:
        """Unbind the currently picked window."""
        if self._picked_hwnd is None:
            return {"success": True, "message": "No window was picked"}

        prev = self._picked_info
        self._picked_hwnd = None
        self._picked_info = None
        logger.info("Unpicked window: %r", prev)
        return {"success": True, "window": prev}

    def get_picked_window(self) -> dict | None:
        """Return info about the currently picked window, or None."""
        if self._picked_hwnd is None:
            return None
        # Check if still valid
        if not self.window.is_valid(self._picked_hwnd):
            logger.info("Picked window hwnd=%d is no longer valid, auto-unpicking", self._picked_hwnd)
            self._picked_hwnd = None
            self._picked_info = None
            return None
        return self._picked_info

    @property
    def overlay_active(self) -> bool:
        """Whether the overlay picker is currently running."""
        return self._window_picker_overlay.is_active

    def show_overlay_picker(self) -> dict:
        """Launch the interactive overlay window picker.

        Non-blocking: runs in a background thread. When the user picks a window,
        it is automatically bound via pick_window(). The frontend should poll
        GET /api/pick to detect the result.
        """
        if self._window_picker_overlay.is_active:
            return {"success": False, "error": "Picker overlay already active"}

        def on_picked(hwnd: int | None):
            if hwnd:
                self.pick_window(hwnd)
            logger.info("Overlay picker finished: hwnd=%s", hwnd)

        self._window_picker_overlay.show(callback=on_picked)
        return {"success": True, "message": "Overlay picker launched"}

    # ── Agent tool primitives ──────────────────────────────────────────

    @tool("List all configured apps with their details (name, app_path, launcher_path, launch_timeout). Use before launch(app=...).")
    def list_apps(self) -> dict:
        apps = []
        for name, ac in self.config.apps.items():
            apps.append({
                "name": name,
                "app_path": ac.app_path,
                "launcher_path": ac.launcher_path,
                "launch_timeout": ac.launch_timeout,
            })
        apps.sort(key=lambda a: str(a["name"]))
        return {"apps": apps}

    @tool("Capture a window, run OCR + YOLO detection, save screenshot. Returns image_path, OCR elements with normalized [0,1000] bbox, and dimensions.")
    def analyze(self, hwnd: int) -> dict:
        """
        Args:
            hwnd: Window handle to capture.
        """
        if not self.window.is_valid(hwnd):
            return {"error": f"Invalid window handle: {hwnd}"}

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
        title = win32gui.GetWindowText(hwnd) or f"hwnd{hwnd}"
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in title)[:40]
        path = str(date_dir / f"{safe}_{ts}.jpeg")
        cv2.imwrite(path, compressed)

        parsed = self.ui_parser.parse(frame)
        logger.info("analyze: found %d ui_elements", len(parsed))

        bbox_path = str(date_dir / f"{safe}_{ts}_bbox.jpeg")
        self._save_bbox_overlay(compressed, parsed, bbox_path, hwnd=hwnd)

        # Get mouse position relative to window client area
        mouse_pos = self._get_mouse_position(hwnd)

        return {
            "width": compressed.shape[1],
            "height": compressed.shape[0],
            "ui_elements": parsed,
            IMAGE_PATH_KEY: path,
            SOM_IMAGE_PATH_KEY: bbox_path,
            "mouse_position": mouse_pos,
            "bbox_desc": (
                "All element bbox coordinates are normalized to [0, 1000] as "
                "[x1, y1, x2, y2], where (x1,y1) is top-left and (x2,y2) is "
                "bottom-right. Each element also has a 'center' [cx, cy] field "
                "already pre-computed — use center directly for click coordinates."
            ),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    @tool("Read an image file from disk and return base64 content for vision model analysis. Use with image_path from analyze().")
    def read_image(self, path: str) -> dict:
        """
        Args:
            path: Path to the image file.
        """
        p = Path(path)
        if not p.exists():
            logger.info("read_image: file not found")
            return {"error": f"File not found: {path}"}

        image_bytes = p.read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode()
        suffix = p.suffix.lower().lstrip(".")
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        logger.info("read_image: mime=%s, size=%d bytes", mime, len(image_bytes))

        return {
            "_multimodal": True,
            "text_summary": f"{path}",
            "content": [
                {"type": "text", "text": f"Screenshot from path: {path}"},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{image_b64}"}},
            ],
        }

    @tool("Click at normalized [0,1000] coordinates. (0,0)=top-left, (1000,1000)=bottom-right. Set clicks=2 for double-click.")
    def click(self, x: int, y: int, hwnd: int, clicks: int = 1, reason: str = "") -> dict:
        """
        Args:
            x: X coordinate in [0, 1000].
            y: Y coordinate in [0, 1000].
            hwnd: Window handle.
            clicks: Number of clicks (default 1, 2 for double-click).
            reason: Optional reason for logging.
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        with self._input_lock:
            result = self.input.click_normalized(hwnd, x, y, clicks=clicks)
        return result

    @tool("Press a key. Brings the window to foreground first. Supports pyautogui key names.")
    def press_key(self, key: str, hwnd: int, wait_time: float = 0.2) -> dict:
        """
        Args:
            key: Key name (e.g. 'enter', 'escape', 'w', 'f1', 'space').
            hwnd: Window handle.
            wait_time: How long to hold the key in seconds (default 0.2).
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        with self._input_lock:
            self._force_foreground(hwnd)
            self.input.press_key(key, wait_time)
        return {"success": True, "key": key}

    @tool("Press a combination of keys simultaneously (e.g. Alt+Left, Ctrl+C).")
    def hotkey(self, keys: list[str], hwnd: int) -> dict:
        """
        Args:
            keys: List of key names, e.g. ['alt', 'left'] or ['ctrl', 'c'].
            hwnd: Window handle.
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        with self._input_lock:
            self._force_foreground(hwnd)
            self.input.hotkey(*keys)
        return {"success": True, "keys": keys}

    @tool("Scroll the mouse wheel at a position. Coordinates normalized [0,1000]. Positive=up/right, negative=down/left.")
    def scroll(self, x: int, y: int, clicks: int, hwnd: int,
               direction: str = "vertical", reason: str = "") -> dict:
        """
        Args:
            x: X coordinate in [0, 1000].
            y: Y coordinate in [0, 1000].
            clicks: Scroll amount. Positive=up/right, negative=down/left.
            hwnd: Window handle.
            direction: 'vertical' (default) or 'horizontal'.
            reason: Optional reason.
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        region = self.window.get_client_region(hwnd)
        if region is None:
            return {"success": False, "error": "Window client region not available"}

        abs_x = region.left + int(x / 1000 * region.width)
        abs_y = region.top + int(y / 1000 * region.height)

        with self._input_lock:
            self._force_foreground(hwnd)
            result = self.input.scroll(abs_x, abs_y, clicks, direction)
        return result

    @tool("Type text into the focused input field via clipboard paste (Ctrl+V). Supports Unicode/CJK.")
    def type_text(self, text: str, hwnd: int) -> dict:
        """
        Args:
            text: The text string to type.
            hwnd: Window handle.
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        with self._input_lock:
            self._force_foreground(hwnd)
            time.sleep(0.1)
            result = self.input.type_text(text)
        return result

    @tool("Drag from one point to another using natural mouse simulation. Coordinates normalized [0,1000].", name="drag")
    def swipe_screen(self, x1: int, y1: int, x2: int, y2: int, hwnd: int, speed: float = 1.0) -> dict:
        """
        Args:
            x1: Start X coordinate (0-1000).
            y1: Start Y coordinate (0-1000).
            x2: End X coordinate (0-1000).
            y2: End Y coordinate (0-1000).
            hwnd: Window handle.
            speed: Swipe speed multiplier (default 1.0).
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        region = self.window.get_client_region(hwnd)
        if region is None:
            return {"success": False, "error": "Window client region not available"}

        with self._input_lock:
            self._force_foreground(hwnd)
            abs_x1 = region.left + int(x1 / 1000 * region.width)
            abs_y1 = region.top + int(y1 / 1000 * region.height)
            abs_x2 = region.left + int(x2 / 1000 * region.width)
            abs_y2 = region.top + int(y2 / 1000 * region.height)
            self.input.swipe_screen((abs_x1, abs_y1), (abs_x2, abs_y2), speed=speed)
        return {"success": True, "from": [x1, y1], "to": [x2, y2]}

    @tool("Move mouse cursor to normalized [0,1000] coordinates. Brings the window to foreground.")
    def move_mouse(self, x: int, y: int, hwnd: int) -> dict:
        """
        Args:
            x: X coordinate in [0, 1000].
            y: Y coordinate in [0, 1000].
            hwnd: Window handle.
        """
        if not self.window.is_valid(hwnd):
            return {"success": False, "error": f"Invalid window handle: {hwnd}"}

        region = self.window.get_client_region(hwnd)
        if region is None:
            return {"success": False, "error": "Window client region not available"}

        with self._input_lock:
            self._force_foreground(hwnd)
            abs_x = region.left + int(x / 1000 * region.width)
            abs_y = region.top + int(y / 1000 * region.height)
            self.input.mouse_move_screen(abs_x, abs_y)
        return {"success": True, "x": x, "y": y}

    @tool("Start a program and wait for its window. Returns hwnd. Use app='name' for registered apps or exe='path' for direct launch.")
    def launch(self, app: str | None = None, exe: str | None = None) -> dict:
        """
        Args:
            app: Registered app name (uses launcher flow).
            exe: Absolute path to an executable to start directly.
        """
        if exe and not app:
            # Direct exe mode: start and find window by exe name
            exe_name = Path(exe).name
            logger.info("launch: starting exe directly: %s", exe)
            try:
                subprocess.Popen([exe])
            except Exception as e:
                return {"error": f"Failed to start executable: {e}"}

            # Wait for a window with matching exe
            deadline = time.time() + 30
            while time.time() < deadline:
                result = self._window_picker.find_window(exe=exe_name)
                if result:
                    hwnd = result["hwnd"]
                    self._force_foreground(hwnd)
                    return {"status": "ready", "hwnd": hwnd, "title": result["title"], "exe": exe_name}
                time.sleep(1)
            return {"error": f"Process started but no window found within 30s for '{exe_name}'"}

        if not app:
            return {"error": "Either 'app' or 'exe' must be provided"}

        # App mode: launcher flow
        if self.is_app_running(app):
            # App already running, find its window
            hwnd = self.find_app_window(app)
            if hwnd:
                return {"status": "already_running", "hwnd": hwnd, "message": f"{app} is already running"}
            return {"status": "already_running", "message": f"{app} process is running but window not found"}

        if not self.is_launcher_running(app):
            logger.info("launch: starting launcher for %s", app)
            err = self._start_launcher(app)
            if err is not None:
                return {"error": f"Failed to start launcher: {err}"}

        hwnd = self._wait_for_launcher_window(app, timeout=30)
        if hwnd is None:
            return {"error": f"Launcher started but window not detected within 30s for '{app}'"}

        self._force_foreground(hwnd)
        title = win32gui.GetWindowText(hwnd)
        return {
            "status": "launcher_ready",
            "hwnd": hwnd,
            "title": title,
            "message": "Launcher is ready. Use analyze(hwnd) to find Start button, click it, then use find_window(exe=...) to find the app window.",
        }

    @tool("Wait/sleep for a specified duration.")
    def wait(self, seconds: float, reason: str = "") -> dict:
        """
        Args:
            seconds: Number of seconds to wait.
            reason: Optional reason for logging.
        """
        time.sleep(seconds)
        return {"status": "waited", "seconds": seconds}

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Simple character-level similarity ratio (0.0-1.0)."""
        if not a or not b:
            return 0.0
        a_lower, b_lower = a.lower(), b.lower()
        if a_lower in b_lower or b_lower in a_lower:
            return 1.0
        matches = sum(1 for x, y in zip(a_lower, b_lower) if x == y)
        return matches / max(len(a_lower), len(b_lower))

    @tool("Poll the screen via OCR until text appears or timeout. More efficient than wait()+analyze() loops.")
    def wait_for(self, text: str, hwnd: int,
                 timeout: float = 90, interval: float = 5,
                 threshold: float = 0.7) -> dict:
        """
        Args:
            text: Target text to search for (fuzzy match).
            hwnd: Window handle to poll.
            timeout: Maximum seconds to wait (default 90).
            interval: Seconds between polls (default 5).
            threshold: Minimum similarity ratio for fuzzy match (default 0.7).
        """
        t0 = time.time()

        while True:
            result = self.analyze(hwnd=hwnd)

            if "error" not in result:
                elements = result.get("ui_elements", [])
                best_match = None
                best_score = 0.0
                for item in elements:
                    detected = item.get("text", "")
                    if not detected:
                        continue
                    score = self._text_similarity(text, detected)
                    if score > best_score:
                        best_score = score
                        best_match = item

                if best_match and best_score >= threshold:
                    elapsed = time.time() - t0
                    return {
                        "found": True,
                        "text": best_match.get("text"),
                        "similarity": round(best_score, 3),
                        "element": best_match,
                        "elapsed": round(elapsed, 1),
                    }

            elapsed = time.time() - t0
            if elapsed >= timeout:
                return {"found": False, "error": f"timeout after {elapsed:.0f}s", "elapsed": round(elapsed, 1)}

            time.sleep(interval)

    @tool("Search for files on the system by name. Supports wildcards (* and ?).", name="find_files")
    def search_files(self, query: str, path: str | None = None, limit: int = 20) -> dict:
        """
        Args:
            query: Filename pattern, e.g. '*.exe', 'config*'.
            path: Directory to search in (default: user home).
            limit: Maximum results to return (default 20).
        """
        return search_files(query=query, path=path, limit=limit)

    @tool("Register an app executable for future use with launch(app=...). Persisted to config.", name="register_app")
    def register_app_tool(
        self,
        name: str,
        app_path: str,
        launcher_path: str | None = None,
        launch_timeout: int = 120,
    ) -> dict:
        """
        Args:
            name: Unique identifier for the app (e.g. 'nikke', 'mygame').
            app_path: Absolute path to the executable.
            launcher_path: Optional path to the launcher executable.
            launch_timeout: Timeout in seconds for launch (default 120).
        """
        ac = self.config.register_app(name, app_path, launcher_path, launch_timeout)
        return {
            "success": True,
            "name": name,
            "app_path": ac.app_path,
            "launcher_path": ac.launcher_path,
            "launch_timeout": ac.launch_timeout,
            "message": f"App '{name}' registered and persisted",
        }

    @tool("Remove a previously registered app.", name="unregister_app")
    def unregister_app_tool(self, name: str) -> dict:
        """
        Args:
            name: Name of the app to remove.
        """
        if self.config.delete_app(name):
            return {"success": True, "name": name, "message": f"App '{name}' removed"}
        return {"success": False, "error": f"App '{name}' not found"}

    # ── Tool registration ───────────────────────────────────────────────

    def register_tools(self) -> None:
        """Register all @tool-decorated methods into the hermes tool registry."""
        register_all_tools(self)

    # ── Private helpers ─────────────────────────────────────────────────

    def _get_mouse_position(self, hwnd: int) -> dict:
        """Get normalized mouse position [0,1000] relative to window client area."""
        try:
            sx, sy = win32gui.GetCursorPos()
            if not self.window.is_valid(hwnd):
                return {"normalized": None, "error": "Invalid window"}

            ox, oy = win32gui.ClientToScreen(hwnd, (0, 0))
            rect = win32gui.GetClientRect(hwnd)
            width = rect[2]
            height = rect[3]

            if width <= 0 or height <= 0:
                return {"normalized": None, "error": "Zero-size window"}

            # Cursor relative to client area
            cx = sx - ox
            cy = sy - oy

            # Normalize to [0, 1000]
            nx = int(cx / width * 1000) if width > 0 else None
            ny = int(cy / height * 1000) if height > 0 else None

            return {"normalized": [nx, ny] if nx is not None and ny is not None else None}
        except Exception as e:
            logger.debug("Failed to get mouse position: %s", e)
            return {"normalized": None, "error": str(e)}

    def _save_bbox_overlay(self, image, elements: list, path: str, *,
                           hwnd: int | None = None) -> None:
        """Draw normalized [0,1000] bboxes onto image and save to path."""
        from PIL import Image, ImageDraw, ImageFont
        import colorsys

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

        # Track placed labels to avoid overlaps
        placed_labels: list[tuple[int, int, int, int]] = []

        def get_text_size(text):
            """Get text width and height."""
            if hasattr(font, 'getbbox'):
                bbox = font.getbbox(text)
                return bbox[2] - bbox[0], bbox[3] - bbox[1]
            else:
                # Fallback for older PIL versions
                return font.getsize(text)

        def check_overlap(rect1, rect2):
            """Check if two rectangles overlap."""
            x1, y1, x2, y2 = rect1
            x3, y3, x4, y4 = rect2
            return not (x2 < x3 or x4 < x1 or y2 < y3 or y4 < y1)

        def find_label_position(px1, py1, px2, py2, text_w, text_h):
            """Find a non-overlapping position for the label."""
            # Try positions: above, below, right, left of bbox
            positions = [
                (px1, max(py1 - text_h - 2, 0)),  # Above
                (px1, min(py2 + 2, h - text_h)),  # Below
                (px2 + 2, py1),  # Right
                (max(px1 - text_w - 2, 0), py1),  # Left
            ]

            for label_x, label_y in positions:
                label_rect = (label_x, label_y, label_x + text_w, label_y + text_h)
                # Check if this position overlaps with any placed label
                overlap = False
                for placed_rect in placed_labels:
                    if check_overlap(label_rect, placed_rect):
                        overlap = True
                        break

                if not overlap:
                    # Also check if label goes outside image bounds
                    if 0 <= label_x and label_x + text_w <= w and 0 <= label_y and label_y + text_h <= h:
                        return label_x, label_y, label_rect

            # If all positions overlap, skip this label
            return None

        def generate_color(index, total):
            """Generate distinct colors using HSL color space."""
            if total <= 1:
                # Single element: use green
                return (0, 255, 0)
            # Distribute hues evenly around the color wheel
            hue = index / total
            # Use high saturation and lightness for visibility
            r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
            return (int(r * 255), int(g * 255), int(b * 255))

        # Generate colors for all elements
        total_elements = len(elements)
        for idx, el in enumerate(elements):
            x1, y1, x2, y2 = el["bbox"]
            px1, py1 = int(x1 / 1000 * w), int(y1 / 1000 * h)
            px2, py2 = int(x2 / 1000 * w), int(y2 / 1000 * h)

            # Generate a distinct color for this element
            color = generate_color(idx, total_elements)
            draw.rectangle([px1, py1, px2, py2], outline=color, width=1)

            label = el.get("text") or el.get("label", "")
            center = el.get("center")
            if label or center:
                # Truncate long text to avoid clutter
                display = label[:12] if label else ""
                if center:
                    cx, cy = center
                    center_text = f"({cx}, {cy})"
                    display = f"{display} {center_text}" if display else center_text

                if display:
                    text_w, text_h = get_text_size(display)
                    result = find_label_position(px1, py1, px2, py2, text_w, text_h)

                    if result:
                        label_x, label_y, label_rect = result
                        draw.text((label_x, label_y), display, fill=color, font=font)
                        placed_labels.append(label_rect)

        # Draw mouse cursor position as red crosshair
        if hwnd is not None and self.window.is_valid(hwnd):
            try:
                mouse = self._get_mouse_position(hwnd)
                nx, ny = mouse.get("normalized", (None, None))
                if nx is not None and ny is not None:
                    # Convert normalized [0,1000] to compressed image coords
                    cx = int(nx / 1000 * w)
                    cy = int(ny / 1000 * h)
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

    def _start_launcher(self, app: str) -> str | None:
        """Start the launcher process.

        Returns:
            None on success, or an error message string on failure.
        """
        pm = self._get_process(app)
        if not pm.launcher:
            return "No launcher configured"
        return pm.launcher.start()

    def _wait_for_launcher_window(self, app: str, timeout: float = 30) -> int | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnd = self.find_launcher_window(app)
            if hwnd:
                return hwnd
            time.sleep(1)
        return None
