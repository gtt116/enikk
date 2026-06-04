"""Unit tests for enikk.game.input — InputService."""

from unittest.mock import patch

from enikk.game.input import InputService


class TestHotkey:
    def test_hotkey_calls_pyautogui(self):
        """hotkey() should delegate to pyautogui.hotkey with all keys."""
        svc = InputService.__new__(InputService)
        with patch("enikk.game.input.pyautogui") as mock_pag:
            svc.hotkey("alt", "left")
            mock_pag.hotkey.assert_called_once_with("alt", "left")

    def test_hotkey_multiple_keys(self):
        """hotkey() should pass all arguments through."""
        svc = InputService.__new__(InputService)
        with patch("enikk.game.input.pyautogui") as mock_pag:
            svc.hotkey("ctrl", "shift", "escape")
            mock_pag.hotkey.assert_called_once_with("ctrl", "shift", "escape")

    def test_hotkey_single_key(self):
        """hotkey() with a single key should still work."""
        svc = InputService.__new__(InputService)
        with patch("enikk.game.input.pyautogui") as mock_pag:
            svc.hotkey("enter")
            mock_pag.hotkey.assert_called_once_with("enter")
