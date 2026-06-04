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


class TestScroll:
    def test_scroll_vertical(self):
        """scroll() should call pyautogui.scroll for vertical direction."""
        svc = InputService.__new__(InputService)
        with patch("enikk.game.input.pyautogui") as mock_pag, \
             patch("enikk.game.input.time"):
            result = svc.scroll(500, 300, 3, "vertical")
            assert result["success"] is True
            assert result["x"] == 500
            assert result["y"] == 300
            assert result["clicks"] == 3
            mock_pag.moveTo.assert_called_once()
            mock_pag.scroll.assert_called_once_with(3)

    def test_scroll_horizontal(self):
        """scroll() should call pyautogui.hscroll for horizontal direction."""
        svc = InputService.__new__(InputService)
        with patch("enikk.game.input.pyautogui") as mock_pag, \
             patch("enikk.game.input.time"):
            result = svc.scroll(500, 300, -2, "horizontal")
            assert result["success"] is True
            mock_pag.hscroll.assert_called_once_with(-2)

    def test_scroll_default_direction(self):
        """scroll() should default to vertical direction."""
        svc = InputService.__new__(InputService)
        with patch("enikk.game.input.pyautogui") as mock_pag, \
             patch("enikk.game.input.time"):
            result = svc.scroll(500, 300, 5)
            assert result["success"] is True
            mock_pag.scroll.assert_called_once_with(5)
