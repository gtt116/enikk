import pytest
from enikk.daemon import Daemon, _rpc_registry, rpc


class TestRpcRegistry:
    def test_known_methods_registered(self):
        methods = list(_rpc_registry)
        assert "ping" in methods
        assert "session.run" in methods
        assert "session.stop" in methods
        assert "session.status" in methods
        assert "session.list" in methods

    def test_handlers_are_callable(self):
        for method in ("ping", "session.run", "session.list"):
            assert callable(_rpc_registry[method]), f"{method} not callable"


class TestDispatch:
    @pytest.fixture
    def daemon(self):
        d = Daemon.__new__(Daemon)
        d.agent_mgr = None
        return d

    def test_ping(self, daemon):
        resp = daemon.dispatch({"method": "ping", "id": "1"})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == "1"
        assert resp["result"] == "pong"

    def test_session_list(self, daemon):
        resp = daemon.dispatch({"method": "session.list", "id": "2"})
        assert resp["result"] == {"agents": []}

    def test_session_status(self, daemon):
        resp = daemon.dispatch({"method": "session.status", "id": "3", "params": {"session_id": "nikke"}})
        assert resp["result"] == {"status": "idle"}

    def test_session_run(self, daemon):
        resp = daemon.dispatch({"method": "session.run", "id": "4", "params": {"session_id": "nikke", "prompt": "test"}})
        assert resp["result"] == {"run_id": "stub", "status": "accepted"}

    def test_session_stop(self, daemon):
        resp = daemon.dispatch({"method": "session.stop", "id": "5", "params": {"session_id": "nikke"}})
        assert resp["result"] == {"status": "stopped"}

    def test_unknown_method(self, daemon):
        resp = daemon.dispatch({"method": "bad", "id": "1"})
        assert resp["error"]["code"] == -32601
        assert "bad" in resp["error"]["message"]

    def test_handler_exception(self, daemon):
        @rpc("test.broken")
        def _broken(self, rid, params):
            raise RuntimeError("boom")

        try:
            resp = daemon.dispatch({"method": "test.broken", "id": "1"})
            assert resp["error"]["code"] == -32000
            assert "boom" in resp["error"]["message"]
        finally:
            del _rpc_registry["test.broken"]