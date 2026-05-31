"""Pytest configuration — mock heavy native dependencies for unit tests."""
import sys
from unittest.mock import MagicMock

# Mock modules that aren't available in test environments.
# Only mock if the module can't be imported — preserves real numpy/cv2
# for test_ui_parser which needs them.
_candidates = [
    "cv2", "win32gui", "numpy", "pyautogui", "pynput", "mss",
    "enikk.game", "enikk.game.capture", "enikk.game.input",
    "enikk.game.process", "enikk.game.window",
    "run_agent", "tools", "tools.registry", "tools.skills_sync", "hermes_state",
    "enikk.prompts", "rapidocr_onnxruntime",
]
for mod_name in _candidates:
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except (ImportError, ModuleNotFoundError):
            sys.modules[mod_name] = MagicMock()
