"""Pytest configuration — mock heavy native dependencies for unit tests."""
import sys

import pytest
from unittest.mock import MagicMock

# Mock modules that aren't available in test environments.
# Only mock if the module can't be imported — preserves real numpy/cv2
# for test_ui_parser which needs them.
_candidates = [
    "cv2", "win32gui", "numpy", "pyautogui", "pynput", "mss",
    "enikk.game", "enikk.game.capture", "enikk.game.input",
    "enikk.game.process", "enikk.game.window",
    "run_agent", "tools", "tools.registry", "tools.skills_sync", "hermes_state",
    "tools.memory_tool", "tools.session_search_tool", "tools.skill_manager_tool",
    "tools.skills_tool", "tools.todo_tool",
    "enikk.prompts", "rapidocr_onnxruntime",
]
for mod_name in _candidates:
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except (ImportError, ModuleNotFoundError):
            sys.modules[mod_name] = MagicMock()


@pytest.fixture(autouse=True)
def _isolated_enikk_home(tmp_path, monkeypatch):
    """Point ENIKK_HOME at a temp dir so tests never touch real user data."""
    home = tmp_path / "enikk-home"
    home.mkdir()
    monkeypatch.setenv("ENIKK_HOME", str(home))
    return home
