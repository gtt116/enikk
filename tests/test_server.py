"""Unit tests for enikk.server module."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from enikk.server import create_app


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_eternity():
    """Create a minimal mock Eternity."""
    eternity = Mock()
    eternity.list_sessions = Mock(return_value=[])
    eternity.create_session = Mock(return_value="session-123")
    eternity.steer_session = Mock(return_value=True)
    eternity.stop_session = Mock(return_value=True)
    eternity.delete_session = Mock(return_value=True)
    eternity.get_session_messages = Mock(return_value={"messages": [], "has_more": False})
    eternity.get_session_stream = AsyncMock(return_value=iter([]))
    eternity.config = Mock()
    eternity.config.workspace = Mock()
    eternity.config.workspace.screenshot_dir = "/tmp/screenshots"
    return eternity


@pytest.fixture
def client():
    """Create a test client with mocked Eternity."""
    eternity = _make_eternity()
    app = create_app(eternity)
    return TestClient(app), eternity


# ── Tests: Health endpoint ──────────────────────────────────────────────

class TestHealth:
    """Test /health endpoint."""

    def test_health_check(self, client):
        c, _ = client
        response = c.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ── Tests: Sessions list ────────────────────────────────────────────────

class TestListSessions:
    """Test GET /api/sessions endpoint."""

    def test_list_sessions_empty(self, client):
        c, eternity = client
        response = c.get("/api/sessions")
        assert response.status_code == 200
        assert response.json() == []
        eternity.list_sessions.assert_called_once_with(limit=20, offset=0)

    def test_list_sessions_with_pagination(self, client):
        c, eternity = client
        eternity.list_sessions.return_value = [
            {"id": "s1", "task": "test1"},
            {"id": "s2", "task": "test2"},
        ]
        response = c.get("/api/sessions?limit=10&offset=5")
        assert response.status_code == 200
        assert len(response.json()) == 2
        eternity.list_sessions.assert_called_once_with(limit=10, offset=5)

    def test_list_sessions_invalid_limit(self, client):
        c, _ = client
        response = c.get("/api/sessions?limit=0")
        assert response.status_code == 422  # Validation error

    def test_list_sessions_limit_too_high(self, client):
        c, _ = client
        response = c.get("/api/sessions?limit=200")
        assert response.status_code == 422


# ── Tests: Create session ───────────────────────────────────────────────

class TestCreateSession:
    """Test POST /api/sessions endpoint."""

    def test_create_session(self, client):
        c, eternity = client
        response = c.post("/api/sessions", json={"task": "test task"})
        assert response.status_code == 200
        assert response.json() == {"session_id": "session-123"}
        eternity.create_session.assert_called_once_with(task="test task")

    def test_create_session_missing_task(self, client):
        c, _ = client
        response = c.post("/api/sessions", json={})
        assert response.status_code == 422

    def test_create_session_empty_task(self, client):
        c, eternity = client
        response = c.post("/api/sessions", json={"task": ""})
        assert response.status_code == 200
        eternity.create_session.assert_called_once_with(task="")


# ── Tests: Steer session ────────────────────────────────────────────────

class TestSteerSession:
    """Test POST /api/sessions/{id}/steer endpoint."""

    def test_steer_session_success(self, client):
        c, eternity = client
        response = c.post("/api/sessions/session-123/steer", json={"message": "continue"})
        assert response.status_code == 200
        assert response.json() == {"status": "steered"}
        eternity.steer_session.assert_called_once_with("session-123", "continue")

    def test_steer_session_not_found(self, client):
        c, eternity = client
        eternity.steer_session.return_value = False
        response = c.post("/api/sessions/unknown/steer", json={"message": "test"})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_steer_session_missing_message(self, client):
        c, _ = client
        response = c.post("/api/sessions/session-123/steer", json={})
        assert response.status_code == 422


# ── Tests: Stop session ─────────────────────────────────────────────────

class TestStopSession:
    """Test POST /api/sessions/{id}/stop endpoint."""

    def test_stop_session_success(self, client):
        c, eternity = client
        response = c.post("/api/sessions/session-123/stop")
        assert response.status_code == 200
        assert response.json() == {"status": "stopped"}
        eternity.stop_session.assert_called_once_with("session-123")

    def test_stop_session_not_found(self, client):
        c, eternity = client
        eternity.stop_session.return_value = False
        response = c.post("/api/sessions/unknown/stop")
        assert response.status_code == 404


# ── Tests: Delete session ───────────────────────────────────────────────

class TestDeleteSession:
    """Test DELETE /api/sessions/{id} endpoint."""

    def test_delete_session_success(self, client):
        c, eternity = client
        response = c.delete("/api/sessions/session-123")
        assert response.status_code == 200
        assert response.json() == {"status": "deleted"}
        eternity.delete_session.assert_called_once_with("session-123")

    def test_delete_session_not_found(self, client):
        c, eternity = client
        eternity.delete_session.return_value = False
        response = c.delete("/api/sessions/unknown")
        assert response.status_code == 404


# ── Tests: Get session messages ─────────────────────────────────────────

class TestGetSessionMessages:
    """Test GET /api/sessions/{id}/messages endpoint."""

    def test_get_messages_empty(self, client):
        c, eternity = client
        response = c.get("/api/sessions/session-123/messages")
        assert response.status_code == 200
        assert response.json() == {"messages": [], "has_more": False}
        eternity.get_session_messages.assert_called_once_with(
            "session-123", limit=100, before_id=None
        )

    def test_get_messages_with_pagination(self, client):
        c, eternity = client
        eternity.get_session_messages.return_value = {
            "messages": [{"id": 1, "content": "test"}],
            "has_more": True,
        }
        response = c.get("/api/sessions/session-123/messages?limit=50&before_id=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["messages"]) == 1
        assert data["has_more"] is True
        eternity.get_session_messages.assert_called_once_with(
            "session-123", limit=50, before_id="10"
        )

    def test_get_messages_invalid_limit(self, client):
        c, _ = client
        response = c.get("/api/sessions/session-123/messages?limit=0")
        assert response.status_code == 422

    def test_get_messages_limit_too_high(self, client):
        c, _ = client
        response = c.get("/api/sessions/session-123/messages?limit=600")
        assert response.status_code == 422


# ── Tests: Stream session ───────────────────────────────────────────────

class TestStreamSession:
    """Test GET /api/sessions/{id}/stream endpoint."""

    def test_stream_session_empty(self, client):
        c, eternity = client

        async def empty_stream(session_id):
            return
            yield  # Make it an async generator

        eternity.get_session_stream = empty_stream

        with c.stream("GET", "/api/sessions/session-123/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
            # Read all chunks
            chunks = list(response.iter_lines())
            assert len(chunks) == 0

    def test_stream_session_with_events(self, client):
        c, eternity = client

        async def mock_stream(session_id):
            yield {"event": "delta", "data": {"text": "hello"}}
            yield {"event": "session", "data": {"status": "completed"}}

        eternity.get_session_stream = mock_stream

        with c.stream("GET", "/api/sessions/session-123/stream") as response:
            assert response.status_code == 200
            chunks = list(response.iter_lines())
            assert len(chunks) >= 2
            # Parse first event
            first_line = chunks[0]
            assert first_line.startswith("data: ")
            event = json.loads(first_line[6:])
            assert event["event"] == "delta"
            assert event["data"]["text"] == "hello"

    def test_stream_session_error_handling(self, client):
        c, eternity = client

        async def error_stream(session_id):
            raise RuntimeError("Test error")
            yield  # Never reached

        eternity.get_session_stream = error_stream

        with c.stream("GET", "/api/sessions/session-123/stream") as response:
            assert response.status_code == 200
            chunks = list(response.iter_lines())
            # Should have error event
            assert len(chunks) >= 1
            error_line = chunks[0]
            assert error_line.startswith("data: ")
            event = json.loads(error_line[6:])
            assert event["event"] == "error"
            assert "Test error" in event["data"]["message"]


# ── Tests: Serve images ─────────────────────────────────────────────────

class TestServeImages:
    """Test GET /api/images endpoint."""

    def test_serve_image_success(self, client, tmp_path):
        c, eternity = client
        # Create a test image
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake image data")

        # Update screenshot_dir to tmp_path
        eternity.config.workspace.screenshot_dir = str(tmp_path)

        response = c.get(f"/api/images?path={img_path}")
        assert response.status_code == 200
        assert response.content == b"fake image data"

    def test_serve_image_path_traversal_blocked(self, client):
        c, _ = client
        # Try to access file outside screenshot_dir
        response = c.get("/api/images?path=/etc/passwd")
        assert response.status_code == 403
        assert "access denied" in response.json()["detail"].lower()

    def test_serve_image_not_found(self, client, tmp_path):
        c, eternity = client
        eternity.config.workspace.screenshot_dir = str(tmp_path)

        response = c.get(f"/api/images?path={tmp_path}/nonexistent.png")
        assert response.status_code == 404

    def test_serve_image_missing_path(self, client):
        c, _ = client
        response = c.get("/api/images")
        assert response.status_code == 422


# ── Tests: Open directory ───────────────────────────────────────────────

class TestOpenDir:
    """Test GET /api/open_dir endpoint."""

    def test_open_home_dir(self, client, tmp_path):
        c, _ = client
        with patch("enikk.server.enikk_home", return_value=tmp_path):
            with patch("platform.system", return_value="Linux"):
                with patch("subprocess.run") as mock_run:
                    response = c.get("/api/open_dir?name=home")
                    assert response.status_code == 200
                    assert response.json()["status"] == "opened"
                    assert response.json()["path"] == str(tmp_path)
                    mock_run.assert_called_once()

    def test_open_logs_dir(self, client, tmp_path):
        c, _ = client
        logs_dir = tmp_path / "logs"
        with patch("enikk.server.enikk_home", return_value=tmp_path):
            with patch("platform.system", return_value="Linux"):
                with patch("subprocess.run") as mock_run:
                    response = c.get("/api/open_dir?name=logs")
                    assert response.status_code == 200
                    assert response.json()["path"] == str(logs_dir)
                    assert logs_dir.exists()
                    mock_run.assert_called_once()

    def test_open_dir_windows(self, client, tmp_path):
        c, _ = client
        with patch("enikk.server.enikk_home", return_value=tmp_path):
            with patch("platform.system", return_value="Windows"):
                with patch("os.startfile") as mock_start:
                    response = c.get("/api/open_dir?name=home")
                    assert response.status_code == 200
                    mock_start.assert_called_once_with(str(tmp_path))

    def test_open_dir_unknown_name(self, client):
        c, _ = client
        response = c.get("/api/open_dir?name=unknown")
        assert response.status_code == 400
        assert "unknown directory" in response.json()["detail"].lower()

    def test_open_dir_missing_name(self, client):
        c, _ = client
        response = c.get("/api/open_dir")
        assert response.status_code == 400


# ── Tests: Static files ─────────────────────────────────────────────────

class TestStaticFiles:
    """Test static file serving."""

    def test_index_serves_frontend(self, client):
        c, _ = client
        response = c.get("/")
        # Should either serve index.html or return 404 if static dir doesn't exist
        assert response.status_code in (200, 404)

    def test_static_mount(self, client):
        c, _ = client
        # Try to access a static file (may 404 if file doesn't exist)
        response = c.get("/static/nonexistent.js")
        assert response.status_code in (200, 404)
