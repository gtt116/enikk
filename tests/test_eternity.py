"""Unit tests for enikk.eternity module."""
from __future__ import annotations

import asyncio
import json
import queue
from unittest.mock import Mock, patch

import pytest

from enikk.events import (
    EVT_DELTA,
    EVT_SESSION,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_config():
    """Create a minimal mock Config."""
    cfg = Mock()
    cfg.model = Mock()
    cfg.model.base_url = "http://test"
    cfg.model.api_key = "sk-test"
    cfg.model.default = "test-model"
    cfg.model.max_tokens = 4096
    cfg.workspace = Mock()
    cfg.workspace.screenshot_dir = "/tmp/screenshots"
    cfg.workspace.weights_dir = "/tmp/weights"
    cfg.workspace.screenshot_max_dim = 1366
    cfg.apps = {}
    cfg.load_custom_apps = Mock()
    return cfg


def _make_session_db():
    """Create a mock SessionDB."""
    db = Mock()
    db.list_sessions_rich = Mock(return_value=[])
    db.get_messages = Mock(return_value=[])
    db.get_messages_as_conversation = Mock(return_value=[])
    db.delete_session = Mock()
    return db


def _make_handle(session_id="abc123", alive=True):
    """Create a mock SessionHandle."""
    from enikk.eternity import SessionHandle, StreamChannel
    handle = SessionHandle.__new__(SessionHandle)
    handle.session_id = session_id
    handle.thread = Mock()
    handle.thread.is_alive = Mock(return_value=alive)
    handle.thread.join = Mock()
    handle.agent = Mock()
    handle.agent.steer = Mock()
    handle.agent.interrupt = Mock()
    handle.stream = StreamChannel()
    handle.result = None
    return handle


# ── Tests: StreamChannel ──────────────────────────────────────────────

class TestStreamChannel:
    """Test StreamChannel pub/sub."""

    def test_subscribe_returns_queue(self):
        from enikk.eternity import StreamChannel
        ch = StreamChannel()
        q = ch.subscribe()
        assert isinstance(q, queue.Queue)
        assert len(ch.subscribers) == 1

    def test_unsubscribe_removes_queue(self):
        from enikk.eternity import StreamChannel
        ch = StreamChannel()
        q = ch.subscribe()
        ch.unsubscribe(q)
        assert len(ch.subscribers) == 0

    def test_unsubscribe_unknown_queue_is_noop(self):
        from enikk.eternity import StreamChannel
        ch = StreamChannel()
        q = queue.Queue()
        ch.unsubscribe(q)
        assert len(ch.subscribers) == 0

    def test_publish_to_all_subscribers(self):
        from enikk.eternity import StreamChannel
        ch = StreamChannel()
        q1 = ch.subscribe()
        q2 = ch.subscribe()
        event = {"event": "test", "data": {"key": "val"}}
        ch.publish(event)
        assert q1.get_nowait() == event
        assert q2.get_nowait() == event

    def test_close_sends_none_sentinel(self):
        from enikk.eternity import StreamChannel
        ch = StreamChannel()
        q = ch.subscribe()
        ch.close()
        assert q.get_nowait() is None
        assert len(ch.subscribers) == 0

    def test_multiple_subscribers_independent(self):
        from enikk.eternity import StreamChannel
        ch = StreamChannel()
        q1 = ch.subscribe()
        q2 = ch.subscribe()
        ch.unsubscribe(q1)
        ch.publish({"event": "test", "data": {}})
        assert q1.empty()
        assert not q2.empty()


# ── Tests: SessionHandle.publish ──────────────────────────────────────

class TestSessionHandle:
    """Test SessionHandle.publish()."""

    def test_publish_inserts_session_id(self):
        from enikk.eternity import SessionHandle, StreamChannel
        handle = SessionHandle.__new__(SessionHandle)
        handle.session_id = "test-id"
        handle.stream = StreamChannel()
        q = handle.stream.subscribe()

        handle.publish("delta", {"text": "hello"})

        event = q.get_nowait()
        assert event["event"] == "delta"
        assert event["data"]["session_id"] == "test-id"
        assert event["data"]["text"] == "hello"


# ── Tests: Eternity ──────────────────────────────────────────────────

class TestEternity:
    """Test Eternity session manager."""

    @pytest.fixture
    def eternity(self):
        from enikk.eternity import Eternity
        cfg = _make_config()
        e = Eternity(cfg)
        e._session_db = _make_session_db()
        return e

    # ── is_running ─────────────────────────────────────────────────────

    def test_is_running_unknown_session(self, eternity):
        assert eternity.is_running("nonexistent") is False

    def test_is_running_alive(self, eternity):
        handle = _make_handle("s1", alive=True)
        eternity._sessions["s1"] = handle
        assert eternity.is_running("s1") is True

    def test_is_running_dead(self, eternity):
        handle = _make_handle("s1", alive=False)
        eternity._sessions["s1"] = handle
        assert eternity.is_running("s1") is False

    # ── stop_session ───────────────────────────────────────────────────

    def test_stop_session_unknown(self, eternity):
        assert eternity.stop_session("nonexistent") is False

    def test_stop_session_dead_thread(self, eternity):
        handle = _make_handle("s1", alive=False)
        eternity._sessions["s1"] = handle
        assert eternity.stop_session("s1") is False

    def test_stop_session_interrupts_agent(self, eternity):
        handle = _make_handle("s1", alive=True)
        eternity._sessions["s1"] = handle
        assert eternity.stop_session("s1") is True
        handle.agent.interrupt.assert_called_once()

    # ── delete_session ─────────────────────────────────────────────────

    def test_delete_session_removes_from_db_and_memory(self, eternity):
        handle = _make_handle("s1", alive=False)
        eternity._sessions["s1"] = handle
        assert eternity.delete_session("s1") is True
        eternity._session_db.delete_session.assert_called_once_with("s1")
        assert "s1" not in eternity._sessions

    def test_delete_session_unknown_still_calls_db(self, eternity):
        assert eternity.delete_session("nonexistent") is True
        eternity._session_db.delete_session.assert_called_once_with("nonexistent")

    # ── rename_session ─────────────────────────────────────────────────

    def test_rename_session_success(self, eternity):
        eternity._session_db.set_session_title = Mock(return_value=True)
        assert eternity.rename_session("s1", "New Title") is True
        eternity._session_db.set_session_title.assert_called_once_with("s1", "New Title")

    def test_rename_session_not_found(self, eternity):
        eternity._session_db.set_session_title = Mock(return_value=False)
        assert eternity.rename_session("nonexistent", "Title") is False

    def test_rename_session_duplicate_raises(self, eternity):
        eternity._session_db.set_session_title = Mock(
            side_effect=ValueError("Title 'Foo' is already in use by session abc")
        )
        with pytest.raises(ValueError, match="already in use"):
            eternity.rename_session("s1", "Foo")

    # ── steer_session ──────────────────────────────────────────────────

    def test_steer_session_running(self, eternity):
        handle = _make_handle("s1", alive=True)
        eternity._sessions["s1"] = handle
        assert eternity.steer_session("s1", "go left") is True
        handle.agent.steer.assert_called_once_with("go left")

    def test_steer_session_not_in_memory_exists_in_db(self, eternity):
        eternity._session_db.get_messages = Mock(return_value=[{"id": 1, "role": "user", "content": "hi"}])
        with patch.object(eternity, "create_session", return_value="s1") as mock_create:
            assert eternity.steer_session("s1", "continue") is True
            mock_create.assert_called_once_with(task="continue", session_id="s1")

    def test_steer_session_not_in_memory_not_in_db(self, eternity):
        eternity._session_db.get_messages = Mock(return_value=[])
        assert eternity.steer_session("nonexistent", "hello") is False

    def test_steer_session_dead_thread_exists_in_db(self, eternity):
        handle = _make_handle("s1", alive=False)
        eternity._sessions["s1"] = handle
        eternity._session_db.get_messages = Mock(return_value=[{"id": 1}])
        with patch.object(eternity, "create_session", return_value="s1") as mock_create:
            assert eternity.steer_session("s1", "retry") is True
            mock_create.assert_called_once_with(task="retry", session_id="s1")

    # ── list_sessions ──────────────────────────────────────────────────

    def test_list_sessions_adds_is_running(self, eternity):
        eternity._session_db.list_sessions_rich = Mock(return_value=[
            {"id": "s1", "task": "test"},
            {"id": "s2", "task": "test2"},
        ])
        handle = _make_handle("s1", alive=True)
        eternity._sessions["s1"] = handle

        result = eternity.list_sessions()
        assert len(result) == 2
        assert result[0]["is_running"] is True
        assert result[1]["is_running"] is False

    # ── get_session_messages ───────────────────────────────────────────

    def test_get_session_messages_empty(self, eternity):
        eternity._session_db.get_messages = Mock(return_value=[])
        result = eternity.get_session_messages("s1")
        assert result == {"messages": [], "has_more": False}

    def test_get_session_messages_pagination(self, eternity):
        messages = [{"id": i, "role": "user", "content": f"msg{i}"} for i in range(10)]
        eternity._session_db.get_messages = Mock(return_value=messages)

        result = eternity.get_session_messages("s1", limit=3)
        assert len(result["messages"]) == 3
        assert result["has_more"] is True
        assert result["messages"][0]["id"] == 7

    def test_get_session_messages_before_id(self, eternity):
        messages = [{"id": i, "role": "user", "content": f"msg{i}"} for i in range(5)]
        eternity._session_db.get_messages = Mock(return_value=messages)

        result = eternity.get_session_messages("s1", limit=10, before_id="3")
        assert len(result["messages"]) == 3
        assert result["has_more"] is False
        assert all(m["id"] < 3 for m in result["messages"])

    def test_get_session_messages_invalid_before_id(self, eternity):
        messages = [{"id": i, "role": "user", "content": f"msg{i}"} for i in range(3)]
        eternity._session_db.get_messages = Mock(return_value=messages)

        result = eternity.get_session_messages("s1", limit=10, before_id="invalid")
        assert len(result["messages"]) == 3

    def test_get_session_messages_enriches_tool_image(self, eternity):
        messages = [
            {"id": 1, "role": "tool", "content": json.dumps({"image_path": "/tmp/test.png"})},
            {"id": 2, "role": "assistant", "content": "done"},
        ]
        eternity._session_db.get_messages = Mock(return_value=messages)

        result = eternity.get_session_messages("s1")
        assert result["messages"][0].get("imageUrl") is not None
        assert result["messages"][1].get("imageUrl") is None

    # ── _get_context_usage ─────────────────────────────────────────────

    def test_get_context_usage_no_compressor(self, eternity):
        handle = _make_handle("s1")
        handle.agent = Mock(spec=[])
        assert eternity._get_context_usage(handle) == {}

    def test_get_context_usage_with_compressor(self, eternity):
        handle = _make_handle("s1")
        cc = Mock()
        cc.last_prompt_tokens = 5000
        cc.context_length = 128000
        handle.agent = Mock()
        handle.agent.context_compressor = cc
        result = eternity._get_context_usage(handle)
        assert result["context_usage"]["current"] == 5000
        assert result["context_usage"]["limit"] == 128000

    # ── shutdown ───────────────────────────────────────────────────────

    def test_shutdown_stops_all_sessions(self, eternity):
        h1 = _make_handle("s1", alive=True)
        h2 = _make_handle("s2", alive=False)
        eternity._sessions = {"s1": h1, "s2": h2}

        eternity.shutdown(timeout=0.1)

        h1.agent.interrupt.assert_called_once()
        h1.thread.join.assert_called_once()
        assert len(eternity._sessions) == 0
        assert eternity._shutdown is True

    def test_shutdown_idempotent(self, eternity):
        eternity.shutdown()
        eternity.shutdown()
        assert eternity._shutdown is True

    # ── get_session_stream ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_session_stream_unknown_session(self, eternity):
        events = []
        async for event in eternity.get_session_stream("nonexistent"):
            events.append(event)
        assert events == []

    @pytest.mark.asyncio
    async def test_get_session_stream_yields_events(self, eternity):
        handle = _make_handle("s1", alive=True)
        eternity._sessions["s1"] = handle

        async def feed_events():
            await asyncio.sleep(0.1)
            handle.stream.publish({"event": EVT_DELTA, "data": {"text": "hi"}})
            await asyncio.sleep(0.05)
            handle.stream.publish({"event": EVT_SESSION, "data": {"status": "completed"}})
            await asyncio.sleep(0.05)
            handle.stream.close()

        asyncio.create_task(feed_events())

        events = []
        async for event in eternity.get_session_stream("s1"):
            events.append(event)

        assert len(events) == 2
        assert events[0]["event"] == EVT_DELTA
        assert events[1]["event"] == EVT_SESSION

    @pytest.mark.asyncio
    async def test_get_session_stream_stops_when_session_dies(self, eternity):
        handle = _make_handle("s1", alive=True)
        eternity._sessions["s1"] = handle

        async def feed_and_die():
            await asyncio.sleep(0.05)
            handle.stream.publish({"event": EVT_DELTA, "data": {"text": "hello"}})
            await asyncio.sleep(0.1)
            handle.thread.is_alive = Mock(return_value=False)
            await asyncio.sleep(0.1)
            handle.stream.close()

        asyncio.create_task(feed_and_die())

        events = []
        async for event in eternity.get_session_stream("s1"):
            events.append(event)

        assert len(events) >= 1
        assert events[0]["data"]["text"] == "hello"

    # ── wait_for_session ───────────────────────────────────────────────

    def test_wait_for_session_unknown(self, eternity):
        assert eternity.wait_for_session("nonexistent") is None

    def test_wait_for_session_returns_result(self, eternity):
        handle = _make_handle("s1", alive=False)
        handle.result = {"final_response": "done"}
        eternity._sessions["s1"] = handle

        result = eternity.wait_for_session("s1", timeout=0.1)
        assert result == {"final_response": "done"}
        handle.thread.join.assert_called_once()
