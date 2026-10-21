"""Unit tests for enikk.controller."""

from unittest.mock import MagicMock, patch

import pytest

from enikk.controller import AppController


@pytest.fixture
def controller():
    """Create AppController with mocked dependencies."""
    with patch("enikk.controller.capture"), \
         patch("enikk.controller.input_mod"), \
         patch("enikk.controller.window"), \
         patch("enikk.controller.UIParser"):
        config = MagicMock()
        config.workspace.weights_dir = None
        config.workspace.screenshot_max_dim = 1366
        config.workspace.screenshot_dir = "/tmp/screenshots"
        config.apps = {}
        ac = AppController(config)
        return ac


# ── click with reason ─────────────────────────────────────────────────


class TestClickWithReason:
    def test_click_with_reason(self, controller, caplog):
        controller.window.is_valid = MagicMock(return_value=True)
        controller.input.click_normalized = MagicMock(return_value={"success": True})

        with caplog.at_level("INFO", logger="enikk.controller"):
            result = controller.click(x=100, y=200, hwnd=12345, reason="Clicking start button")

        assert result["success"] is True
        controller.input.click_normalized.assert_called_once()
        assert "Clicking start button" in caplog.text

    def test_click_without_reason(self, controller):
        controller.window.is_valid = MagicMock(return_value=True)
        controller.input.click_normalized = MagicMock(return_value={"success": True})

        result = controller.click(x=100, y=200, hwnd=12345)

        assert result["success"] is True

    def test_click_invalid_hwnd(self, controller):
        controller.window.is_valid = MagicMock(return_value=False)

        result = controller.click(x=100, y=200, hwnd=99999)

        assert result["success"] is False
        assert "Invalid window handle" in result["error"]


# ── scroll ────────────────────────────────────────────────────────────


class TestScroll:
    def test_invalid_hwnd(self, controller):
        controller.window.is_valid = MagicMock(return_value=False)

        result = controller.scroll(x=500, y=500, clicks=3, hwnd=99999)

        assert result["success"] is False
        assert "Invalid window handle" in result["error"]

    def test_region_not_available(self, controller):
        controller.window.is_valid = MagicMock(return_value=True)
        controller.window.get_client_region = MagicMock(return_value=None)

        result = controller.scroll(x=500, y=500, clicks=3, hwnd=12345)

        assert result["success"] is False
        assert "client region not available" in result["error"]

    def test_success(self, controller, caplog):
        controller.window.is_valid = MagicMock(return_value=True)
        controller.window.get_client_region = MagicMock(
            return_value=MagicMock(left=100, top=100, width=800, height=600)
        )
        controller._force_foreground = MagicMock(return_value=True)
        controller.input.scroll = MagicMock(return_value={"success": True})

        with caplog.at_level("INFO", logger="enikk.controller"):
            result = controller.scroll(
                x=500, y=500, clicks=3, hwnd=12345, reason="Scroll down to view list"
            )

        assert result["success"] is True
        assert "Scroll down to view list" in caplog.text
        controller._force_foreground.assert_called_once_with(12345)
        # Verify coordinate conversion: 500/1000 * 800 + 100 = 500
        controller.input.scroll.assert_called_once_with(500, 400, 3, "vertical")

    def test_horizontal_scroll(self, controller):
        controller.window.is_valid = MagicMock(return_value=True)
        controller.window.get_client_region = MagicMock(
            return_value=MagicMock(left=0, top=0, width=1000, height=1000)
        )
        controller._force_foreground = MagicMock(return_value=True)
        controller.input.scroll = MagicMock(return_value={"success": True})

        result = controller.scroll(
            x=500, y=500, clicks=-2, hwnd=12345, direction="horizontal"
        )

        assert result["success"] is True
        controller.input.scroll.assert_called_once_with(500, 500, -2, "horizontal")


# ── hotkey ────────────────────────────────────────────────────────────


class TestHotkey:
    def test_invalid_hwnd(self, controller):
        controller.window.is_valid = MagicMock(return_value=False)

        result = controller.hotkey(keys=["alt", "left"], hwnd=99999)

        assert result["success"] is False
        assert "Invalid window handle" in result["error"]

    def test_success(self, controller):
        controller.window.is_valid = MagicMock(return_value=True)
        controller._force_foreground = MagicMock(return_value=True)
        controller.input.hotkey = MagicMock()

        result = controller.hotkey(keys=["alt", "left"], hwnd=12345)

        assert result["success"] is True
        assert result["keys"] == ["alt", "left"]
        controller._force_foreground.assert_called_once_with(12345)
        controller.input.hotkey.assert_called_once_with("alt", "left")

    def test_triple_key_combo(self, controller):
        controller.window.is_valid = MagicMock(return_value=True)
        controller._force_foreground = MagicMock(return_value=True)
        controller.input.hotkey = MagicMock()

        result = controller.hotkey(keys=["ctrl", "shift", "escape"], hwnd=12345)

        assert result["success"] is True
        assert result["keys"] == ["ctrl", "shift", "escape"]
        controller.input.hotkey.assert_called_once_with("ctrl", "shift", "escape")