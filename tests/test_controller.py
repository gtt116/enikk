"""Unit tests for enikk.controller — wait_for and text matching."""

from unittest.mock import MagicMock, patch

import pytest

from enikk.controller import AppController


# ── _text_similarity ───────────────────────────────────────────────────


class TestTextSimilarity:
    def test_exact_match(self):
        assert AppController._text_similarity("hello", "hello") == 1.0

    def test_case_insensitive_substring(self):
        assert AppController._text_similarity("hello", "Hello World") == 1.0

    def test_substring_reverse(self):
        assert AppController._text_similarity("Hello World", "hello") == 1.0

    def test_empty_a(self):
        assert AppController._text_similarity("", "hello") == 0.0

    def test_empty_b(self):
        assert AppController._text_similarity("hello", "") == 0.0

    def test_both_empty(self):
        assert AppController._text_similarity("", "") == 0.0

    def test_partial_match(self):
        score = AppController._text_similarity("abc", "axc")
        assert 0.5 < score < 1.0

    def test_no_match(self):
        score = AppController._text_similarity("abc", "xyz")
        assert score == 0.0

    def test_cjk_substring(self):
        assert AppController._text_similarity("点击", "点击任意处") == 1.0

    def test_cjk_fuzzy(self):
        score = AppController._text_similarity("点击任意处", "点击任意赴")
        assert score >= 0.7


# ── wait_for ──────────────────────────────────────────────────────────


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


class TestWaitFor:
    def test_invalid_hwnd(self, controller):
        controller.analyze = MagicMock(return_value={"error": "Invalid window handle: 0"})
        result = controller.wait_for(text="hello", hwnd=0, timeout=0.3, interval=0.1)
        assert result["found"] is False
        assert "timeout" in result["error"]

    def test_found_on_first_poll(self, controller):
        controller.analyze = MagicMock(return_value={
            "ui_elements": [
                {"text": "Click anywhere", "bbox": [10, 20, 30, 40], "center": [20, 30], "confidence": 0.95},
            ],
            "image_path": "/tmp/test.jpeg",
        })

        result = controller.wait_for(text="Click anywhere", hwnd=12345, timeout=5)

        assert result["found"] is True
        assert result["text"] == "Click anywhere"
        assert result["similarity"] == 1.0
        assert "elapsed" in result
        assert "element" in result

    def test_found_after_multiple_polls(self, controller):
        poll_count = 0

        def mock_analyze(**_):
            nonlocal poll_count
            poll_count += 1
            if poll_count < 3:
                return {"ui_elements": [{"text": "Loading...", "bbox": [0, 0, 10, 10], "center": [5, 5]}]}
            return {"ui_elements": [{"text": "Complete", "bbox": [0, 0, 10, 10], "center": [5, 5]}]}

        controller.analyze = mock_analyze

        result = controller.wait_for(text="Complete", hwnd=12345, timeout=10, interval=0.1)

        assert result["found"] is True
        assert result["text"] == "Complete"
        assert poll_count == 3

    def test_timeout(self, controller):
        controller.analyze = MagicMock(return_value={
            "ui_elements": [{"text": "Loading...", "bbox": [0, 0, 10, 10], "center": [5, 5]}],
        })

        result = controller.wait_for(text="Complete", hwnd=12345, timeout=0.3, interval=0.1)

        assert result["found"] is False
        assert "timeout" in result["error"]
        assert "elapsed" in result

    def test_analyze_error_continues(self, controller):
        call_count = 0

        def mock_analyze(**_):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {"error": "window not found"}
            return {"ui_elements": [{"text": "Ready", "bbox": [0, 0, 10, 10], "center": [5, 5]}]}

        controller.analyze = mock_analyze

        result = controller.wait_for(text="Ready", hwnd=12345, timeout=5, interval=0.1)

        assert result["found"] is True
        assert call_count >= 3

    def test_fuzzy_match(self, controller):
        controller.analyze = MagicMock(return_value={
            "ui_elements": [{"text": "点击任意赴", "bbox": [0, 0, 10, 10], "center": [5, 5]}],
        })

        result = controller.wait_for(text="点击任意处", hwnd=12345, timeout=5, threshold=0.7)

        assert result["found"] is True
        assert result["text"] == "点击任意赴"
        assert result["similarity"] >= 0.7

    def test_no_match_below_threshold(self, controller):
        controller.analyze = MagicMock(return_value={
            "ui_elements": [{"text": "Completely different text", "bbox": [0, 0, 10, 10], "center": [5, 5]}],
        })

        result = controller.wait_for(text="hello", hwnd=12345, timeout=0.3, interval=0.1, threshold=0.7)

        assert result["found"] is False
        assert "timeout" in result["error"]

    def test_no_text_detected(self, controller):
        controller.analyze = MagicMock(return_value={"ui_elements": []})

        result = controller.wait_for(text="hello", hwnd=12345, timeout=0.3, interval=0.1)

        assert result["found"] is False
        assert "timeout" in result["error"]

    def test_custom_threshold(self, controller):
        controller.analyze = MagicMock(return_value={
            "ui_elements": [{"text": "helo", "bbox": [0, 0, 10, 10], "center": [5, 5]}],
        })

        result_low = controller.wait_for(text="hello", hwnd=12345, timeout=5, threshold=0.6)
        assert result_low["found"] is True

        result_high = controller.wait_for(text="hello", hwnd=12345, timeout=0.3, interval=0.1, threshold=0.95)
        assert result_high["found"] is False

    def test_skips_elements_without_text(self, controller):
        controller.analyze = MagicMock(return_value={
            "ui_elements": [
                {"label": "icon", "bbox": [0, 0, 10, 10], "center": [5, 5]},
                {"text": "Ready", "bbox": [10, 10, 20, 20], "center": [15, 15]},
            ],
        })

        result = controller.wait_for(text="Ready", hwnd=12345, timeout=5)

        assert result["found"] is True
        assert result["text"] == "Ready"


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


# ── wait with reason ──────────────────────────────────────────────────


class TestWaitWithReason:
    def test_wait_with_reason(self, controller, caplog):
        with caplog.at_level("INFO", logger="enikk.controller"):
            result = controller.wait(seconds=0.1, reason="Waiting for animation")

        assert result["status"] == "waited"
        assert result["seconds"] == 0.1
        assert "Waiting for animation" in caplog.text

    def test_wait_without_reason(self, controller):
        result = controller.wait(seconds=0.1)

        assert result["status"] == "waited"


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
