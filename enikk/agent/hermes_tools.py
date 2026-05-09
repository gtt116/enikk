"""Hermes agent tools: screenshot and click via daemon HTTP API."""
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

# Screenshot storage directory — timestamps ensure no overwrites.
SCREENSHOT_DIR = Path("screenshots")

# ── Memory integration ──────────────────────────────────────────────

def _get_hermes_mem_dir() -> Path:
    """Return the Hermes memory directory, defaulting to ./memories."""
    return Path.cwd() / "memories"


ENTRY_DELIMITER = "\n§\n"


def _read_memory_entries(path: Path) -> list[str]:
    """Read a MEMORY.md / USER.md file and return list of entries."""
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, IOError):
        return []
    if not raw.strip():
        return []
    entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
    return [e for e in entries if e]


def _render_block(target: str, entries: list[str]) -> str:
    """Render a memory block matching Hermes' built-in format."""
    if not entries:
        return ""
    content = ENTRY_DELIMITER.join(entries)
    current = len(content)
    limits = {"memory": 2200, "user": 1375}
    limit = limits.get(target, 2200)
    pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

    header = f"USER PROFILE (who the user is) [{pct}% — {current:,}/{limit:,} chars]" if target == "user" \
        else f"MEMORY (your personal notes) [{pct}% — {current:,}/{limit:,} chars]"
    separator = "═" * 46
    return f"{separator}\n{header}\n{separator}\n{content}"


def build_memory_block(mem_dir: Path = None) -> str:
    """Read Hermes memory files and return formatted block for system prompt."""
    try:
        if mem_dir is None:
            mem_dir = _get_hermes_mem_dir()
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_path = mem_dir / "MEMORY.md"
        user_path = mem_dir / "USER.md"
        print(f"[memory] Loading {mem_path} (exists={mem_path.exists()}), {user_path} (exists={user_path.exists()})")
        mem_entries = _read_memory_entries(mem_path)
        user_entries = _read_memory_entries(user_path)
        parts = []
        mem_block = _render_block("memory", mem_entries)
        if mem_block:
            parts.append(mem_block)
        user_block = _render_block("user", user_entries)
        if user_block:
            parts.append(user_block)
        return "\n\n".join(parts)
    except Exception:
        return ""


def _save_screenshot(image_b64: str) -> str:
    """Decode base64 image and save to disk. Returns absolute path."""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    screenshot_file = SCREENSHOT_DIR / f"{ts}.jpeg"
    image_bytes = base64.b64decode(image_b64)
    screenshot_file.write_bytes(image_bytes)
    return str(screenshot_file.resolve())


AGENT_SYSTEM_PROMPT = """You are an AI game assistant for NIKKE: Goddess of Victory. You control the game through screen analysis and input.

TOOLS:
- screenshot: Captures the game screen, saves the image to disk, and returns OCR text + UI element bounding boxes. The result includes an "image_path" field — use this path to send the image to the LLM for visual analysis.
- click: Clicks at normalized coordinates [0,1000]. Calculate center from bbox: x=(x1+x2)/2, y=(y1+y2)/2. Optionally waits after clicking.

WORKFLOW:
1. Always call screenshot first to analyze the current game state.
2. Use the "image_path" from the result to have the LLM visually analyze the screenshot.
3. Combine the OCR/UI data with the image to decide what to click.
4. Use click to interact by calculating bbox center coordinates.
5. After clicking, call screenshot again to verify the result.

COORDINATE SYSTEM:
- All coordinates are [0,1000] normalized (0=top/left, 1000=bottom/right).
- Bounding boxes: [x1, y1, x2, y2] as percentages of screen width/height.

RULES:
- Always screenshot before clicking.
- Use the image_path to send the screenshot image to the LLM for visual understanding.
- Report what you see and what you plan to click."""

REVIEW_SYSTEM_PROMPT = """You are reviewing a completed NIKKE game automation session. Your goal is to extract lessons that will make the next operation smoother.

Focus on:
- Wait timing: Were waits too short (racing animations) or too long (wasting turns)? What are the ideal wait durations for common transitions?
- Game UI awareness: Which UI elements were missed or misidentified? What visual cues reliably indicate state changes?
- Interaction techniques: Were clicks hitting the right targets? Are there better approaches (e.g. wait-then-click vs rapid clicks)?
- Error recovery: What went wrong and how could it have been avoided?

Save your findings to memory using the memory tool. Be specific and actionable — write what you'd want your future self to know before starting the next session."""


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
    """Click at normalized [0,1000] coordinates, optionally wait after."""
    x = args.get("x")
    y = args.get("y")
    url = urljoin(SERVER_URL, f"/api/action/click?x={x}&y={y}")
    resp = urlopen(url, timeout=10)
    data = json.loads(resp.read())
    wait_seconds = args.get("wait_after", 0)
    if wait_seconds:
        time.sleep(wait_seconds)
        data["waited"] = wait_seconds
    return json.dumps(data, ensure_ascii=False)


def register_tools(server_url: str):
    """Register screenshot and click tools with Hermes registry."""
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
