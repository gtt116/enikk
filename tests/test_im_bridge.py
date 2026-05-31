"""Unit tests for enikk.im_bridge module."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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
        assert "Enikk" in result
        assert "/new" in result
        assert "/stop" in result

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

        with patch.object(bridge, "_create_adapter", return_value=mock_adapter):
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
