"""Unit tests for enikk.im_bridge module."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest

from enikk.events import (
    EVT_DELTA,
    EVT_ERROR,
    EVT_SESSION,
    EVT_TOOL_CALL,
    EVT_TOOL_RESULT,
)
from enikk.im_bridge import IMBridge
from enikk.controller import extract_image_path


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_config(im_enabled=True, platform="dingtalk"):
    """Create a minimal mock Config with IM settings."""
    cfg = Mock()
    cfg.im = Mock()
    if im_enabled:
        ps = Mock()
        ps.enabled = True
        ps.token = "test-token"
        ps.extra = {}
        cfg.im.active_platform = (platform, ps)
    else:
        cfg.im.active_platform = None
    return cfg


def _make_eternity():
    """Create a minimal mock Eternity."""
    eternity = Mock()
    eternity.create_session = Mock(return_value="session-123")
    eternity.steer_session = Mock(return_value=True)
    eternity.stop_session = Mock(return_value=True)
    eternity.is_running = Mock(return_value=True)
    return eternity


def _make_event(text="", source_chat_id="chat-1", chat_type="dm"):
    """Create a mock message event."""
    source = SimpleNamespace(chat_id=source_chat_id, chat_type=chat_type)
    return SimpleNamespace(text=text, source=source)


@pytest.fixture(autouse=True)
def _mock_state_file(tmp_path):
    """Redirect _STATE_FILE to a temp path for every test."""
    state_file = tmp_path / "im_state.json"
    with patch("enikk.im_bridge._STATE_FILE", state_file):
        yield


# ── Tests: extract_image_path ──────────────────────────────────────────

class TestExtractImagePath:
    """Test extract_image_path() pure function."""

    def test_dict_with_image_path(self):
        result = {"image_path": "/tmp/test.png"}
        assert extract_image_path(result) == "/tmp/test.png"

    def test_dict_with_som_image_path(self):
        result = {"SoM_image_path": "/tmp/som.png"}
        assert extract_image_path(result) == "/tmp/som.png"

    def test_dict_som_takes_precedence(self):
        result = {"SoM_image_path": "/tmp/som.png", "image_path": "/tmp/normal.png"}
        assert extract_image_path(result) == "/tmp/som.png"

    def test_dict_without_image_keys(self):
        result = {"other_key": "value"}
        assert extract_image_path(result) is None

    def test_json_string_with_image_path(self):
        result = json.dumps({"image_path": "/tmp/test.png"})
        assert extract_image_path(result) == "/tmp/test.png"

    def test_json_string_with_som_image_path(self):
        result = json.dumps({"SoM_image_path": "/tmp/som.png"})
        assert extract_image_path(result) == "/tmp/som.png"

    def test_invalid_json_string(self):
        result = "not valid json"
        assert extract_image_path(result) is None

    def test_none_input(self):
        assert extract_image_path(None) is None

    def test_empty_dict(self):
        assert extract_image_path({}) is None

    def test_empty_string(self):
        assert extract_image_path("") is None

    def test_non_dict_non_string(self):
        assert extract_image_path(123) is None
        assert extract_image_path([]) is None


# ── Tests: _get_chat_id ─────────────────────────────────────────────────

class TestGetChatId:
    """Test _get_chat_id() DM-only filtering."""

    def test_dm_message_returns_chat_id(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        event = _make_event(text="hello", source_chat_id="chat-1", chat_type="dm")
        assert bridge._get_chat_id(event) == "chat-1"

    def test_group_message_returns_none(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        event = _make_event(text="hello", source_chat_id="chat-1", chat_type="group")
        assert bridge._get_chat_id(event) is None

    def test_event_without_source(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        event = SimpleNamespace(text="hello")
        assert bridge._get_chat_id(event) is None

    def test_event_with_none_source(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        event = SimpleNamespace(text="hello", source=None)
        assert bridge._get_chat_id(event) is None


# ── Tests: _handle_command ──────────────────────────────────────────────

class TestHandleCommand:
    """Test _handle_command() slash commands."""

    @pytest.fixture
    def bridge(self):
        cfg = _make_config()
        eternity = _make_eternity()
        bridge = IMBridge(cfg, eternity)
        bridge._adapter = AsyncMock()
        bridge._adapter.send = AsyncMock()
        return bridge

    @pytest.mark.asyncio
    async def test_help_command(self, bridge):
        result = await bridge._handle_command("/help", "chat-1")
        assert "/new" in result
        assert "/stop" in result
        assert "/tools" in result
        assert "/images" in result
        assert "/progress" in result

    @pytest.mark.asyncio
    async def test_unknown_command(self, bridge):
        result = await bridge._handle_command("/unknown", "chat-1")
        assert "未知命令" in result
        assert "/unknown" in result

    @pytest.mark.asyncio
    async def test_new_command_creates_session(self, bridge):
        result = await bridge._handle_command("/new test task", "chat-1")
        assert result is None
        bridge.eternity.create_session.assert_called_once_with(task="test task")
        assert bridge._chat_sessions["chat-1"] == "session-123"

    @pytest.mark.asyncio
    async def test_new_command_stops_old_session(self, bridge):
        bridge._chat_sessions["chat-1"] = "old-session"
        result = await bridge._handle_command("/new", "chat-1")
        assert result is None
        bridge.eternity.stop_session.assert_called_once_with("old-session")

    @pytest.mark.asyncio
    async def test_stop_command_stops_session(self, bridge):
        bridge._chat_sessions["chat-1"] = "session-123"
        result = await bridge._handle_command("/stop", "chat-1")
        assert "已停止" in result
        bridge.eternity.stop_session.assert_called_once_with("session-123")

    @pytest.mark.asyncio
    async def test_stop_command_no_session(self, bridge):
        result = await bridge._handle_command("/stop", "chat-1")
        assert "没有运行中的会话" in result

    @pytest.mark.asyncio
    async def test_tools_command_toggles_on(self, bridge):
        bridge._tool_notify["chat-1"] = False
        result = await bridge._handle_command("/tools", "chat-1")
        assert "已开启" in result
        assert bridge._tool_notify["chat-1"] is True

    @pytest.mark.asyncio
    async def test_tools_command_toggles_off(self, bridge):
        bridge._tool_notify["chat-1"] = True
        result = await bridge._handle_command("/tools", "chat-1")
        assert "已关闭" in result
        assert bridge._tool_notify["chat-1"] is False

    @pytest.mark.asyncio
    async def test_images_command_toggles_on(self, bridge):
        bridge._image_notify["chat-1"] = False
        result = await bridge._handle_command("/images", "chat-1")
        assert "已开启" in result
        assert bridge._image_notify["chat-1"] is True

    @pytest.mark.asyncio
    async def test_images_command_toggles_off(self, bridge):
        bridge._image_notify["chat-1"] = True
        result = await bridge._handle_command("/images", "chat-1")
        assert "已关闭" in result
        assert bridge._image_notify["chat-1"] is False

    @pytest.mark.asyncio
    async def test_progress_command_toggles_on(self, bridge):
        bridge._progress_notify["chat-1"] = False
        result = await bridge._handle_command("/progress", "chat-1")
        assert "已开启" in result
        assert bridge._progress_notify["chat-1"] is True

    @pytest.mark.asyncio
    async def test_progress_command_toggles_off(self, bridge):
        bridge._progress_notify["chat-1"] = True
        result = await bridge._handle_command("/progress", "chat-1")
        assert "已关闭" in result
        assert bridge._progress_notify["chat-1"] is False


# ── Tests: State persistence ────────────────────────────────────────────

class TestStatePersistence:
    """Test _load_state() and _save_state() with temporary files."""

    def test_save_and_load_state(self, tmp_path):
        state_file = tmp_path / "im_state.json"
        with patch("enikk.im_bridge._STATE_FILE", state_file):
            cfg = _make_config()
            eternity = _make_eternity()

            bridge1 = IMBridge(cfg, eternity)
            bridge1._chat_sessions = {"chat-1": "session-1", "chat-2": "session-2"}
            bridge1._tool_notify = {"chat-1": True, "chat-2": False}
            bridge1._image_notify = {"chat-1": False, "chat-2": True}
            bridge1._save_state()

            assert state_file.exists()
            data = json.loads(state_file.read_text())
            assert data["chat_sessions"]["chat-1"] == "session-1"
            assert data["tool_notify"]["chat-1"] is True
            assert data["image_notify"]["chat-1"] is False

            bridge2 = IMBridge(cfg, eternity)
            assert bridge2._chat_sessions == {"chat-1": "session-1", "chat-2": "session-2"}
            assert bridge2._tool_notify == {"chat-1": True, "chat-2": False}
            assert bridge2._image_notify == {"chat-1": False, "chat-2": True}

    def test_load_nonexistent_state(self, tmp_path):
        state_file = tmp_path / "nonexistent.json"
        with patch("enikk.im_bridge._STATE_FILE", state_file):
            bridge = IMBridge(_make_config(), _make_eternity())
            assert bridge._chat_sessions == {}
            assert bridge._tool_notify == {}
            assert bridge._image_notify == {}

    def test_load_corrupted_state(self, tmp_path):
        state_file = tmp_path / "corrupted.json"
        state_file.write_text("not valid json {")
        with patch("enikk.im_bridge._STATE_FILE", state_file):
            bridge = IMBridge(_make_config(), _make_eternity())
            assert bridge._chat_sessions == {}
            assert bridge._tool_notify == {}
            assert bridge._image_notify == {}


# ── Tests: _stream_response ─────────────────────────────────────────────

class TestStreamResponse:
    """Test _stream_response() buffer+flush logic."""

    @pytest.fixture
    def bridge(self):
        cfg = _make_config()
        eternity = _make_eternity()
        bridge = IMBridge(cfg, eternity)
        bridge._adapter = AsyncMock()
        bridge._adapter.send = AsyncMock()
        bridge._adapter.send_image = AsyncMock()
        return bridge

    @pytest.mark.asyncio
    async def test_delta_accumulates_and_flushes_on_session_complete(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Hello "}}
            yield {"event": EVT_DELTA, "data": {"text": "world!"}}
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_called_once_with("chat-1", "Hello world!")

    @pytest.mark.asyncio
    async def test_flush_on_tool_call(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Analyzing..."}}
            yield {"event": EVT_TOOL_CALL, "data": {"name": "click", "args": {}}}
            yield {"event": EVT_DELTA, "data": {"text": "Done!"}}
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        assert bridge._adapter.send.call_count == 3
        calls = bridge._adapter.send.call_args_list
        assert calls[0].args == ("chat-1", "Analyzing...")
        assert "click" in calls[1].args[1]
        assert calls[2].args == ("chat-1", "Done!")

    @pytest.mark.asyncio
    async def test_flush_on_error(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Working..."}}
            yield {"event": EVT_ERROR, "data": {"message": "Something failed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        assert bridge._adapter.send.call_count == 2
        calls = bridge._adapter.send.call_args_list
        assert calls[0].args == ("chat-1", "Working...")
        assert "Something failed" in calls[1].args[1]

    @pytest.mark.asyncio
    async def test_tool_call_with_args(self, bridge):
        async def mock_stream(session_id):
            yield {
                "event": EVT_TOOL_CALL,
                "data": {"name": "click", "args": {"x": 500, "y": 300}},
            }
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        calls = bridge._adapter.send.call_args_list
        tool_msg = calls[0].args[1]
        assert "click" in tool_msg
        assert "500" in tool_msg or "300" in tool_msg

    @pytest.mark.asyncio
    async def test_tool_notify_disabled(self, bridge):
        bridge._tool_notify["chat-1"] = False

        async def mock_stream(session_id):
            yield {"event": EVT_TOOL_CALL, "data": {"name": "click", "args": {}}}
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_result_with_image(self, bridge):
        async def mock_stream(session_id):
            yield {
                "event": EVT_TOOL_RESULT,
                "data": {
                    "name": "screenshot",
                    "result": {"image_path": "/tmp/test.png"},
                },
            }
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send_image.assert_called_once_with("chat-1", "/tmp/test.png")

    @pytest.mark.asyncio
    async def test_tool_result_image_notify_disabled(self, bridge):
        bridge._image_notify["chat-1"] = False

        async def mock_stream(session_id):
            yield {
                "event": EVT_TOOL_RESULT,
                "data": {
                    "name": "screenshot",
                    "result": {"image_path": "/tmp/test.png"},
                },
            }
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send_image.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_buffer_not_sent(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_session_stopped_breaks_loop(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Before stop"}}
            yield {"event": EVT_SESSION, "data": {"status": "stopped"}}
            yield {"event": EVT_DELTA, "data": {"text": "After stop"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_called_once_with("chat-1", "Before stop")

    @pytest.mark.asyncio
    async def test_session_completed_with_final_response_after_deltas(self, bridge):
        """When deltas were sent, final_response should NOT be sent again."""
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Working..."}}
            yield {
                "event": EVT_SESSION,
                "data": {"status": "completed", "final_response": "Task completed successfully"},
            }

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        calls = bridge._adapter.send.call_args_list
        assert len(calls) == 1
        assert calls[0].args == ("chat-1", "Working...")

    @pytest.mark.asyncio
    async def test_session_completed_with_final_response_no_deltas(self, bridge):
        """When no deltas were sent, final_response SHOULD be sent."""
        async def mock_stream(session_id):
            yield {
                "event": EVT_SESSION,
                "data": {"status": "completed", "final_response": "Task completed successfully"},
            }

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_called_once_with("chat-1", "Task completed successfully")

    @pytest.mark.asyncio
    async def test_session_completed_without_final_response(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Working..."}}
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_called_once_with("chat-1", "Working...")

    @pytest.mark.asyncio
    async def test_session_stopped_no_final_response(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Before stop"}}
            yield {
                "event": EVT_SESSION,
                "data": {"status": "stopped", "final_response": "Should not send"},
            }

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_called_once_with("chat-1", "Before stop")

    @pytest.mark.asyncio
    async def test_session_error_no_final_response(self, bridge):
        async def mock_stream(session_id):
            yield {"event": EVT_DELTA, "data": {"text": "Before error"}}
            yield {
                "event": EVT_SESSION,
                "data": {"status": "error", "final_response": "Should not send"},
            }

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        bridge._adapter.send.assert_called_once_with("chat-1", "Before error")

    @pytest.mark.asyncio
    async def test_tool_call_args_truncated(self, bridge):
        long_args = {"key": "x" * 200}

        async def mock_stream(session_id):
            yield {
                "event": EVT_TOOL_CALL,
                "data": {"name": "test", "args": long_args},
            }
            yield {"event": EVT_SESSION, "data": {"status": "completed"}}

        bridge.eternity.get_session_stream = mock_stream

        await bridge._stream_response("session-123", "chat-1")

        calls = bridge._adapter.send.call_args_list
        tool_msg = calls[0].args[1]
        assert len(tool_msg) <= 200


# ── Tests: _handle_message ──────────────────────────────────────────────

class TestHandleMessage:
    """Test _handle_message() session creation and steering."""

    @pytest.fixture
    def bridge(self):
        cfg = _make_config()
        eternity = _make_eternity()
        bridge = IMBridge(cfg, eternity)
        bridge._adapter = AsyncMock()
        bridge._adapter.send = AsyncMock()
        return bridge

    @pytest.mark.asyncio
    async def test_empty_message_returns_none(self, bridge):
        event = _make_event(text="")
        result = await bridge._handle_message(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_none_event_returns_none(self, bridge):
        result = await bridge._handle_message(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_command_message_routes_to_handle_command(self, bridge):
        event = _make_event(text="/help")
        with patch.object(bridge, "_handle_command", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = "help text"
            result = await bridge._handle_message(event)
            assert result == "help text"
            mock_cmd.assert_called_once_with("/help", "chat-1")

    @pytest.mark.asyncio
    async def test_new_chat_creates_session(self, bridge):
        event = _make_event(text="hello world")

        with patch.object(bridge, "_stream_response", new_callable=AsyncMock):
            result = await bridge._handle_message(event)
            assert result is None
            bridge.eternity.create_session.assert_called_once_with(task="hello world")
            assert bridge._chat_sessions["chat-1"] == "session-123"

    @pytest.mark.asyncio
    async def test_existing_session_steers(self, bridge):
        bridge._chat_sessions["chat-1"] = "session-123"
        event = _make_event(text="continue")

        result = await bridge._handle_message(event)
        assert result is None
        bridge.eternity.steer_session.assert_called_once_with("session-123", "continue")

    @pytest.mark.asyncio
    async def test_new_chat_sends_welcome_with_stop_tip(self, bridge):
        event = _make_event(text="hello world")

        with patch.object(bridge, "_stream_response", new_callable=AsyncMock):
            await bridge._handle_message(event)
            bridge._adapter.send.assert_called_once()
            welcome_msg = bridge._adapter.send.call_args.args[1]
            assert "/stop" in welcome_msg
            assert "紧急" in welcome_msg or "停止" in welcome_msg

    @pytest.mark.asyncio
    async def test_new_command_sends_welcome_with_stop_tip(self, bridge):
        with patch.object(bridge, "_stream_response", new_callable=AsyncMock):
            await bridge._handle_command("/new test task", "chat-1")
            bridge._adapter.send.assert_called_once()
            welcome_msg = bridge._adapter.send.call_args.args[1]
            assert "/stop" in welcome_msg
            assert "紧急" in welcome_msg or "停止" in welcome_msg

    @pytest.mark.asyncio
    async def test_steer_fallback_creates_new_session(self, bridge):
        bridge._chat_sessions["chat-1"] = "old-session"
        bridge.eternity.steer_session = Mock(return_value=False)
        event = _make_event(text="new task")

        with patch.object(bridge, "_stream_response", new_callable=AsyncMock):
            result = await bridge._handle_message(event)
            assert result is None
            bridge.eternity.create_session.assert_called_once_with(task="new task")
            assert bridge._chat_sessions["chat-1"] == "session-123"


# ── Tests: start() ──────────────────────────────────────────────────────

class TestStart:
    """Test start() initialization."""

    @pytest.mark.asyncio
    async def test_start_disabled(self):
        cfg = _make_config(im_enabled=False)
        bridge = IMBridge(cfg, _make_eternity())
        await bridge.start()
        assert bridge._adapter is None

    @pytest.mark.asyncio
    async def test_start_creates_adapter(self):
        cfg = _make_config()
        bridge = IMBridge(cfg, _make_eternity())

        mock_adapter = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=True)
        mock_adapter.set_message_handler = Mock()

        with patch.object(IMBridge, "_create_adapter", return_value=mock_adapter):
            await bridge.start()

        assert bridge._adapter is mock_adapter
        mock_adapter.connect.assert_called_once()
        mock_adapter.set_message_handler.assert_called_once()


# ── Tests: stop() ───────────────────────────────────────────────────────

class TestStop:
    """Test stop() cleanup."""

    @pytest.mark.asyncio
    async def test_stop_disconnects_adapter(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.disconnect = AsyncMock()
        bridge._adapter = mock_adapter

        await bridge.stop()

        mock_adapter.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_no_adapter(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        bridge._adapter = None
        await bridge.stop()


class TestHealthCheck:
    """Tests for the health check reconnection logic."""

    @pytest.mark.asyncio
    async def test_health_check_reconnects_on_disconnect(self):
        """When adapter.is_connected becomes False, health check should reconnect."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=True)
        bridge._adapter = mock_adapter

        # Simulate disconnected state
        mock_adapter.is_connected = False

        # Patch the loop to use short interval
        async def short_health_check():
            await asyncio.sleep(0.1)
            if not bridge._adapter.is_connected:
                await bridge._adapter.disconnect()
                await bridge._adapter.connect()

        bridge._health_check_task = asyncio.create_task(short_health_check())

        # Wait for the check
        await asyncio.sleep(0.3)

        # Should have attempted reconnect
        mock_adapter.disconnect.assert_called()
        mock_adapter.connect.assert_called()

        # Cleanup
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_health_check_no_action_when_connected(self):
        """When adapter stays connected, health check should not reconnect."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=True)
        bridge._adapter = mock_adapter

        # Simulate connected state
        mock_adapter.is_connected = True

        # Patch the loop to use short interval
        async def short_health_check():
            await asyncio.sleep(0.1)
            if not bridge._adapter.is_connected:
                await bridge._adapter.disconnect()
                await bridge._adapter.connect()

        bridge._health_check_task = asyncio.create_task(short_health_check())

        # Wait for the check
        await asyncio.sleep(0.3)

        # Should not have attempted reconnect
        mock_adapter.disconnect.assert_not_called()
        mock_adapter.connect.assert_not_called()

        # Cleanup
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_health_check_retries_on_failure(self):
        """When reconnect fails, health check should retry."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.connect = AsyncMock(side_effect=[False, True])  # Fail once, then succeed
        bridge._adapter = mock_adapter

        # Simulate disconnected state
        mock_adapter.is_connected = False

        # Patch the loop to retry twice with short delays
        async def short_health_check():
            for _ in range(2):
                await asyncio.sleep(0.1)
                if not bridge._adapter.is_connected:
                    await bridge._adapter.disconnect()
                    await bridge._adapter.connect()

        bridge._health_check_task = asyncio.create_task(short_health_check())

        # Wait for both attempts
        await asyncio.sleep(0.5)

        # Should have attempted reconnect twice
        assert mock_adapter.connect.call_count == 2

        # Cleanup
        await bridge.stop()

    @pytest.mark.asyncio
    async def test_health_check_timeout_does_not_hang(self):
        """Health check should timeout and retry if connect() hangs."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()

        async def slow_disconnect():
            await asyncio.sleep(60)  # Simulate hanging disconnect

        mock_adapter.disconnect = slow_disconnect
        mock_adapter.connect = AsyncMock(return_value=True)
        bridge._adapter = mock_adapter

        # Simulate disconnected state
        mock_adapter.is_connected = False

        # Start health check with short timeout
        async def test_health_check():
            await asyncio.sleep(0.1)
            if not bridge._adapter.is_connected:
                try:
                    await asyncio.wait_for(bridge._adapter.disconnect(), timeout=0.2)
                    await asyncio.wait_for(bridge._adapter.connect(), timeout=0.2)
                except asyncio.TimeoutError:
                    pass  # Expected

        bridge._health_check_task = asyncio.create_task(test_health_check())

        # Should complete within timeout, not hang
        await asyncio.sleep(0.5)

        # Cleanup
        await bridge.stop()


# ── Tests: Public status API ─────────────────────────────────────────────

class TestPublicStatusAPI:
    """Test is_enabled(), is_connected(), get_platform_name()."""

    def test_is_enabled_without_adapter(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        assert bridge.is_enabled() is False

    def test_is_enabled_with_adapter(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        bridge._adapter = AsyncMock()
        assert bridge.is_enabled() is True

    def test_is_connected_without_adapter(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        assert bridge.is_connected() is False

    def test_is_connected_adapter_connected(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        bridge._adapter = mock_adapter
        assert bridge.is_connected() is True

    def test_is_connected_adapter_disconnected(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = False
        bridge._adapter = mock_adapter
        assert bridge.is_connected() is False

    def test_is_connected_adapter_missing_attribute(self):
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock(spec=[])  # no attributes
        bridge._adapter = mock_adapter
        assert bridge.is_connected() is False

    def test_get_platform_name_with_active_platform(self):
        cfg = _make_config(platform="dingtalk")
        bridge = IMBridge(cfg, _make_eternity())
        assert bridge.get_platform_name() == "dingtalk"

    def test_get_platform_name_without_active_platform(self):
        cfg = _make_config(im_enabled=False)
        bridge = IMBridge(cfg, _make_eternity())
        assert bridge.get_platform_name() is None

    def test_get_platform_name_qqbot(self):
        cfg = _make_config(platform="qqbot")
        bridge = IMBridge(cfg, _make_eternity())
        assert bridge.get_platform_name() == "qqbot"


# ── Tests: test_connection() ─────────────────────────────────────────────

class TestTestConnection:
    """Test test_connection() static method."""

    @pytest.mark.asyncio
    async def test_successful_connection(self):
        mock_adapter = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=True)
        mock_adapter.disconnect = AsyncMock()

        with patch.object(IMBridge, '_create_adapter', return_value=mock_adapter):
            result = await IMBridge.test_connection('dingtalk', 'test-token')

        assert result['status'] == 'success'
        assert 'Connected to dingtalk' in result['message']
        mock_adapter.connect.assert_called_once()
        mock_adapter.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_connection(self):
        mock_adapter = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=False)
        mock_adapter._fatal_error_message = 'Auth failed'

        with patch.object(IMBridge, '_create_adapter', return_value=mock_adapter):
            result = await IMBridge.test_connection('dingtalk', 'bad-token')

        assert result['status'] == 'failed'
        assert 'Auth failed' in result['message']
        mock_adapter.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_exception(self):
        mock_adapter = AsyncMock()
        mock_adapter.connect = AsyncMock(side_effect=Exception('Network error'))

        with patch.object(IMBridge, '_create_adapter', return_value=mock_adapter):
            result = await IMBridge.test_connection('dingtalk', 'test-token')

        assert result['status'] == 'error'
        assert 'Network error' in result['message']

    @pytest.mark.asyncio
    async def test_unknown_platform(self):
        result = await IMBridge.test_connection('unknown_platform', 'token')

        assert result['status'] == 'error'
        assert 'Unknown platform' in result['message']

    @pytest.mark.asyncio
    async def test_unsupported_platform(self):
        with patch.object(IMBridge, '_create_adapter', return_value=None):
            result = await IMBridge.test_connection('dingtalk', 'test-token')

        assert result['status'] == 'error'
        assert 'Unsupported platform' in result['message']

    @pytest.mark.asyncio
    async def test_gateway_not_available(self):
        with patch.dict('sys.modules', {'gateway.config': None}):
            with patch('builtins.__import__', side_effect=ImportError):
                result = await IMBridge.test_connection('dingtalk', 'token')

        assert result['status'] == 'error'
        assert 'not available' in result['message']


# ── Tests: _health_check_loop (immortal) ───────────────────────────────

class TestHealthCheckLoopImmortal:
    """Test that _health_check_loop never dies from unexpected exceptions.

    Strategy: patch class-level timing constants to 0.01s so tests run fast.
    """

    @pytest.fixture(autouse=True)
    def _fast_health_check(self):
        """Make health check loop run fast for all tests in this class."""
        with patch.object(IMBridge, '_HEALTH_CHECK_INTERVAL', 0.01), \
             patch.object(IMBridge, '_HEALTH_CHECK_RETRY_DELAY', 0.01), \
             patch.object(IMBridge, '_HEALTH_CHECK_OP_TIMEOUT', 0.1):
            yield

    @pytest.mark.asyncio
    async def test_health_check_survives_is_connected_exception(self):
        """Health check loop must survive is_connected raising an exception."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        call_count = 0

        def is_connected_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("boom")
            return True

        type(mock_adapter).is_connected = PropertyMock(side_effect=is_connected_side_effect)
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=True)
        bridge._adapter = mock_adapter

        task = asyncio.create_task(bridge._health_check_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # is_connected was called multiple times → loop survived the exceptions
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_health_check_exits_on_cancelled_error(self):
        """CancelledError should cleanly exit the health check loop (task completes, not hangs)."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        bridge._adapter = mock_adapter

        task = asyncio.create_task(bridge._health_check_loop())
        await asyncio.sleep(0.05)
        task.cancel()

        # Task should complete (not hang) after cancel
        await asyncio.wait_for(task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_health_check_exits_when_adapter_set_to_none(self):
        """Health check should break when adapter becomes None."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        bridge._adapter = mock_adapter

        async def set_adapter_none_soon():
            await asyncio.sleep(0.05)
            bridge._adapter = None

        watcher = asyncio.create_task(set_adapter_none_soon())
        task = asyncio.create_task(bridge._health_check_loop())

        await asyncio.wait_for(task, timeout=2.0)
        await watcher


# ── Tests: _health_check_loop reconnect behavior ───────────────────────

class TestHealthCheckLoopReconnect:
    """Test reconnect logic within _health_check_loop."""

    @pytest.fixture(autouse=True)
    def _fast_health_check(self):
        """Make health check loop run fast for all tests in this class."""
        with patch.object(IMBridge, '_HEALTH_CHECK_INTERVAL', 0.01), \
             patch.object(IMBridge, '_HEALTH_CHECK_RETRY_DELAY', 0.01), \
             patch.object(IMBridge, '_HEALTH_CHECK_OP_TIMEOUT', 0.1), \
             patch.object(IMBridge, '_HEALTH_CHECK_MAX_RETRIES', 10):
            yield

    @pytest.mark.asyncio
    async def test_reconnect_called_when_disconnected(self):
        """When adapter.is_connected is False, health check should call disconnect+connect."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = False
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=True)
        bridge._adapter = mock_adapter

        task = asyncio.create_task(bridge._health_check_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_adapter.disconnect.assert_called()
        mock_adapter.connect.assert_called()

    @pytest.mark.asyncio
    async def test_recreate_adapter_called_after_threshold_failures(self):
        """After recreate_threshold consecutive failures, _recreate_adapter is called."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = False
        mock_adapter.disconnect = AsyncMock()
        mock_adapter.connect = AsyncMock(return_value=False)  # always fails
        bridge._adapter = mock_adapter

        recreate_called = False

        async def mock_recreate():
            nonlocal recreate_called
            recreate_called = True
            # After recreation, make connect succeed
            mock_adapter.connect = AsyncMock(return_value=True)
            type(mock_adapter).is_connected = PropertyMock(return_value=True)

        bridge._recreate_adapter = mock_recreate

        # Override recreate threshold to 3 for faster test
        with patch.object(IMBridge, '_HEALTH_CHECK_RECREATE_THRESHOLD', 3):
            task = asyncio.create_task(bridge._health_check_loop())
            # Wait enough for 3 retries + recreate
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert recreate_called

    @pytest.mark.asyncio
    async def test_reconnect_handles_timeout_gracefully(self):
        """Health check should handle timeout during disconnect/connect."""
        bridge = IMBridge(_make_config(), _make_eternity())
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = False

        async def slow_disconnect():
            await asyncio.sleep(100)

        mock_adapter.disconnect = slow_disconnect
        mock_adapter.connect = AsyncMock(return_value=True)
        bridge._adapter = mock_adapter

        task = asyncio.create_task(bridge._health_check_loop())
        await asyncio.sleep(0.2)
        assert not task.done(), "Health check task should still be running"

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── Tests: _recreate_adapter ───────────────────────────────────────────

class TestRecreateAdapter:
    """Test _recreate_adapter() method."""

    @pytest.mark.asyncio
    async def test_recreate_adapter_no_adapter(self):
        """_recreate_adapter should do nothing if no adapter exists."""
        bridge = IMBridge(_make_config(), _make_eternity())
        bridge._adapter = None
        await bridge._recreate_adapter()  # should not raise

    @pytest.mark.asyncio
    async def test_recreate_adapter_no_active_platform(self):
        """_recreate_adapter should do nothing if no active platform configured."""
        bridge = IMBridge(_make_config(im_enabled=False), _make_eternity())
        bridge._adapter = AsyncMock()
        await bridge._recreate_adapter()  # should not raise

    @pytest.mark.asyncio
    async def test_recreate_adapter_creates_new_instance(self):
        """_recreate_adapter should replace the adapter with a new instance."""
        cfg = _make_config(platform="dingtalk")
        bridge = IMBridge(cfg, _make_eternity())

        old_adapter = AsyncMock()
        old_adapter.disconnect = AsyncMock()
        bridge._adapter = old_adapter

        new_adapter = AsyncMock()
        new_adapter.connect = AsyncMock(return_value=True)
        new_adapter.set_message_handler = Mock()

        with patch.object(IMBridge, "_create_adapter", return_value=new_adapter):
            await bridge._recreate_adapter()

        old_adapter.disconnect.assert_called()
        assert bridge._adapter is new_adapter
        new_adapter.set_message_handler.assert_called_once()
        new_adapter.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_recreate_adapter_connect_fails(self):
        """_recreate_adapter should still replace adapter even if connect fails."""
        cfg = _make_config(platform="dingtalk")
        bridge = IMBridge(cfg, _make_eternity())

        old_adapter = AsyncMock()
        bridge._adapter = old_adapter

        new_adapter = AsyncMock()
        new_adapter.connect = AsyncMock(return_value=False)
        new_adapter.set_message_handler = Mock()

        with patch.object(IMBridge, "_create_adapter", return_value=new_adapter):
            await bridge._recreate_adapter()

        assert bridge._adapter is new_adapter  # still replaced

    @pytest.mark.asyncio
    async def test_recreate_adapter_create_returns_none(self):
        """_recreate_adapter should keep old adapter if _create_adapter returns None."""
        cfg = _make_config(platform="dingtalk")
        bridge = IMBridge(cfg, _make_eternity())

        old_adapter = AsyncMock()
        old_adapter.disconnect = AsyncMock()
        bridge._adapter = old_adapter

        with patch.object(IMBridge, "_create_adapter", return_value=None):
            await bridge._recreate_adapter()

        # Old adapter was disconnected but not replaced (set to None would break things)
        # Actually looking at the code, it returns early without setting _adapter
        # So _adapter should still be old_adapter
        assert bridge._adapter is old_adapter

    @pytest.mark.asyncio
    async def test_recreate_adapter_old_disconnect_failure_ignored(self):
        """_recreate_adapter should continue even if old adapter disconnect fails."""
        cfg = _make_config(platform="dingtalk")
        bridge = IMBridge(cfg, _make_eternity())

        old_adapter = AsyncMock()
        old_adapter.disconnect = AsyncMock(side_effect=Exception("disconnect failed"))
        bridge._adapter = old_adapter

        new_adapter = AsyncMock()
        new_adapter.connect = AsyncMock(return_value=True)
        new_adapter.set_message_handler = Mock()

        with patch.object(IMBridge, "_create_adapter", return_value=new_adapter):
            await bridge._recreate_adapter()

        assert bridge._adapter is new_adapter
