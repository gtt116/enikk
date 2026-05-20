"""Hermes agent tools: internal calls (no HTTP)."""
import base64
import json
import logging
from datetime import datetime
from pathlib import Path

SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_MAX_FILES = 1024

logger = logging.getLogger(__name__)


class InternalToolContext:
    """Provides internal tool implementations that call daemon methods directly."""

    def __init__(self, manager, daemon, run_id: str, stop_event):
        self.manager = manager
        self.daemon = daemon
        self.run_id = run_id
        self.stop_event = stop_event

    def _rotate_screenshots(self):
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
            logger.info(f"[rotate] Removed {len(remove)} screenshots ({len(files)} -> {SCREENSHOT_MAX_FILES})")

    def _save_screenshot(self, image_b64: str) -> str:
        """Decode base64 image and save to disk. Returns absolute path."""
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        self._rotate_screenshots()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        screenshot_file = SCREENSHOT_DIR / f"{ts}.jpeg"
        image_bytes = base64.b64decode(image_b64)
        screenshot_file.write_bytes(image_bytes)
        return str(screenshot_file.absolute())

    def screenshot(self):
        """Capture the game screen, save image, return text summary."""
        state = self.daemon.analyze()
        image_b64 = state.get("image_b64", "")
        image_path = ""
        if image_b64:
            image_path = self._save_screenshot(image_b64)
        return json.dumps({
            **state,
            "image_path": image_path,
        }, ensure_ascii=False)

    def read_image(self, path: str):
        """Read an image file and return it to the LLM for visual analysis."""
        if not path or not Path(path).exists():
            return json.dumps({"error": f"Screenshot file not found: {path}"}, ensure_ascii=False)

        image_bytes = Path(path).read_bytes()
        image_b64 = base64.b64encode(image_bytes).decode()

        return json.dumps({
            "_multimodal": True,
            "content": [
                {"type": "text", "text": f"Raw screenshot loaded from: {path}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
            "text_summary": f"Loaded screenshot: {path}",
        }, ensure_ascii=False)

    def click(self, x: int, y: int, target: str = "", reason: str = ""):
        """Click at normalized [0, 1000] coordinates."""
        result = self.daemon.action_click(x, y)
        result["target"] = target
        result["reason"] = reason
        return json.dumps(result, ensure_ascii=False)

    def check_stop(self) -> bool:
        """Check if the current agent run has been interrupted."""
        return self.stop_event.is_set()
