"""Hermes agent tools: screenshot, click, and wait via daemon HTTP API."""
import base64
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from tools.registry import registry

# Suppress noisy logging from hermes tool registry during import
import logging
logging.getLogger().setLevel(logging.CRITICAL)

SERVER_URL = ""

SCREENSHOT_DIR = Path("screenshots")


def _save_screenshot(image_b64: str) -> str:
    """Decode base64 image and save to disk. Returns absolute path."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    screenshot_file = SCREENSHOT_DIR / f"{ts}.jpeg"
    image_bytes = base64.b64decode(image_b64)
    screenshot_file.write_bytes(image_bytes)
    return str(screenshot_file.resolve())


def _screenshot(_args, **_kw) -> str:
    """Capture the game screen, save image, return analysis + file path."""
    url = urljoin(SERVER_URL, "/api/screenshot")
    resp = urlopen(Request(url), timeout=120)
    data = json.loads(resp.read())

    image_b64 = data.pop("image_b64", "")
    if image_b64:
        data["image_path"] = _save_screenshot(image_b64)

    return json.dumps(data, ensure_ascii=False)


def _click(args, **kw) -> str:
    """Click at normalized [0,1000] coordinates."""
    x = args.get("x")
    y = args.get("y")
    url = urljoin(SERVER_URL, f"/api/action/click?x={x}&y={y}")
    resp = urlopen(url, timeout=10)
    data = json.loads(resp.read())
    return json.dumps(data, ensure_ascii=False)


def _wait(args, **_) -> str:
    """Wait for a specified number of seconds."""
    seconds = args.get("seconds", 1)
    time.sleep(seconds)
    return json.dumps({"waited": seconds}, ensure_ascii=False)


def register_tools(server_url: str):
    """Register screenshot, click, and wait tools with Hermes registry."""
    global SERVER_URL
    SERVER_URL = server_url

    registry.register(
        name="screenshot",
        toolset="enikk",
        schema={
            "name": "screenshot",
            "description": (
                "Capture the game screen. Saves the screenshot to disk and "
                "returns OCR text, UI element labels, bounding boxes [x1,y1,x2,y2] "
                "in [0,1000] normalized coordinates, and 'image_path' — the saved "
                "image file path. Use image_path to send the screenshot image to "
                "the LLM for visual analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        handler=_screenshot,
        is_async=False,
    )

    registry.register(
        name="click",
        toolset="enikk",
        schema={
            "name": "click",
            "description": (
                "Click at normalized [0,1000] coordinates. "
                "Calculate center from bbox: x=(x1+x2)/2, y=(y1+y2)/2."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "Normalized X coordinate [0,1000]",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Normalized Y coordinate [0,1000]",
                    },
                },
                "required": ["x", "y"],
            },
        },
        handler=_click,
        is_async=False,
    )

    registry.register(
        name="wait",
        toolset="enikk",
        schema={
            "name": "wait",
            "description": (
                "Wait for a specified number of seconds. "
                "Do NOT use wait after normal UI clicks — only use it during battles or loading screens "
                "when animations or transitions take time to complete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {
                        "type": "number",
                        "description": "Number of seconds to wait (default: 1)",
                    },
                },
                "required": [],
            },
        },
        handler=_wait,
        is_async=False,
    )
