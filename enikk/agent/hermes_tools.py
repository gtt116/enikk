"""Hermes agent tools: screenshot, read_image, click, and wait via daemon HTTP API."""
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
SCREENSHOT_MAX_FILES = 1024


def _rotate_screenshots():
    """Delete oldest screenshots if directory exceeds max file count."""
    if not SCREENSHOT_DIR.exists():
        return
    files = sorted(SCREENSHOT_DIR.glob("*.jpeg"))
    if len(files) > SCREENSHOT_MAX_FILES:
        remove = files[:len(files) - SCREENSHOT_MAX_FILES]
        for f in remove:
            try:
                f.unlink()
            except OSError:
                pass
        print(f"[rotate] Removed {len(remove)} screenshots ({len(files)} -> {SCREENSHOT_MAX_FILES})")


def _save_screenshot(image_b64: str) -> str:
    """Decode base64 image and save to disk. Returns absolute path."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _rotate_screenshots()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    screenshot_file = SCREENSHOT_DIR / f"{ts}.jpeg"
    image_bytes = base64.b64decode(image_b64)
    screenshot_file.write_bytes(image_bytes)
    return str(screenshot_file.resolve())


def _screenshot(_args, **_kw) -> str:
    """Capture the game screen, save image, return text summary.

    Returns OCR text, UI element labels, and image_path.
    The model can decide to call read_image() later if it needs
    to see the raw screenshot for visual analysis.
    """
    url = urljoin(SERVER_URL, "/api/screenshot")
    resp = urlopen(Request(url), timeout=120)
    data = json.loads(resp.read())

    image_b64 = data.pop("image_b64", "")
    image_path = ""
    if image_b64:
        image_path = _save_screenshot(image_b64)

    data['image_path'] = image_path
    return json.dumps(data, ensure_ascii=False)


def _read_image(args, **_kw) -> str:
    """Read an image file and return it to the LLM for visual analysis."""
    path = args.get("path", "")
    if not path or not Path(path).exists():
        return json.dumps({"error": f"Screenshot file not found: {path}"}, ensure_ascii=False)

    image_bytes = Path(path).read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode()

    return json.dumps({
        "_multimodal": True,
        "content": [
            {
                "type": "text",
                "text": f"Raw screenshot loaded from: {path}",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{image_b64}",
                },
            },
        ],
        "text_summary": f"Loaded screenshot: {path}",
    }, ensure_ascii=False)


def _click(args, **kw) -> str:
    """Click at normalized [0,1000] coordinates."""
    x = args.get("x")
    y = args.get("y")
    target = args.get("target", "")
    reason = args.get("reason", "")
    url = urljoin(SERVER_URL, f"/api/action/click?x={x}&y={y}")
    resp = urlopen(url, timeout=10)
    data = json.loads(resp.read())
    data["target"] = target
    data["reason"] = reason
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
                "Capture the game screen. Returns OCR text, UI element labels with "
                "bounding boxes [x1,y1,x2,y2] in [0,1000] normalized coordinates, "
                "and 'image_path' (saved file path). "
                "Most decisions can be made from this text info alone. "
                "If you need to see the raw screenshot (colors, layout, visual details), "
                "call read_image with the image_path afterwards."
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
        name="read_image",
        toolset="enikk",
        schema={
            "name": "read_image",
            "description": (
                "Read a screenshot file and return the image to the LLM for visual analysis. "
                "Use this after screenshot when you need to see the raw image — "
                "for checking colors, layouts, button styles, or any visual detail "
                "that OCR text cannot convey."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Path to the screenshot image file. "
                            "Get this from the screenshot tool's image_path field."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
        handler=_read_image,
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
                    "reason": {
                        "type": "string",
                        "description": (
                            "Why you are clicking here — what this click is meant to achieve "
                            "or what state you expect after the click."
                        ),
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "Human-readable name of what you are clicking (e.g. "
                            "\"confirm button\", \"daily mission icon\", \"close popup\"). "
                            "Helps track actions and debug."
                        ),
                    },
                },
                "required": ["x", "y", "target", "reason"],
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
