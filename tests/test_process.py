"""Tests for process lifecycle management with graceful shutdown."""
from unittest.mock import MagicMock, patch

import psutil
import pytest

from enikk.game.process import ManagedProcess


@pytest.fixture
def managed_process():
    """Create a ManagedProcess instance for testing."""
    return ManagedProcess("TestApp", r"C:\fake\path\testapp.exe")


class TestFindWindowsByPid:
    """Tests for _find_windows_by_pid."""

    def test_returns_empty_when_no_windows(self, managed_process):
        """Return empty list when process has no visible windows."""
        with patch("enikk.game.process.win32gui.EnumWindows") as mock_enum:
            mock_enum.return_value = None  # EnumWindows doesn't return anything

            result = managed_process._find_windows_by_pid(12345)

            assert result == []

    def test_finds_visible_windows(self, managed_process):
        """Find visible windows owned by the process."""
        hwnds = []

        def fake_enum_windows(callback, _):
            # Simulate finding windows
            callback(0x1001, None)  # Window owned by target PID
            callback(0x1002, None)  # Another window owned by target PID
            callback(0x1003, None)  # Window owned by different PID

        with patch("enikk.game.process.win32gui.EnumWindows", side_effect=fake_enum_windows):
            with patch("enikk.game.process.win32process.GetWindowThreadProcessId") as mock_getpid:
                with patch("enikk.game.process.win32gui.IsWindowVisible") as mock_visible:
                    mock_getpid.side_effect = [(0, 12345), (0, 12345), (0, 99999)]
                    mock_visible.side_effect = [True, True, True]

                    result = managed_process._find_windows_by_pid(12345)

                    assert result == [0x1001, 0x1002]

    def test_ignores_invisible_windows(self, managed_process):
        """Ignore windows that are not visible."""
        def fake_enum_windows(callback, _):
            callback(0x1001, None)
            callback(0x1002, None)

        with patch("enikk.game.process.win32gui.EnumWindows", side_effect=fake_enum_windows):
            with patch("enikk.game.process.win32process.GetWindowThreadProcessId") as mock_getpid:
                with patch("enikk.game.process.win32gui.IsWindowVisible") as mock_visible:
                    mock_getpid.side_effect = [(0, 12345), (0, 12345)]
                    mock_visible.side_effect = [True, False]

                    result = managed_process._find_windows_by_pid(12345)

                    assert result == [0x1001]


class TestSendCloseMessage:
    """Tests for _send_close_message."""

    def test_returns_false_when_no_windows(self, managed_process):
        """Return False when process has no windows."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345

        with patch.object(managed_process, "_find_windows_by_pid", return_value=[]):
            result = managed_process._send_close_message(mock_proc)

            assert result is False

    def test_sends_wm_close_to_all_windows(self, managed_process):
        """Send WM_CLOSE to all windows owned by process."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.name.return_value = "testapp.exe"

        with patch.object(managed_process, "_find_windows_by_pid", return_value=[0x1001, 0x1002]):
            with patch("enikk.game.process.win32gui.PostMessage") as mock_post:
                result = managed_process._send_close_message(mock_proc)

                assert result is True
                assert mock_post.call_count == 2
                # Verify WM_CLOSE was sent
                for call in mock_post.call_args_list:
                    assert call.args[1] == 0x0010  # WM_CLOSE

    def test_continues_on_post_message_failure(self, managed_process):
        """Continue sending to other windows even if one fails."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.name.return_value = "testapp.exe"

        with patch.object(managed_process, "_find_windows_by_pid", return_value=[0x1001, 0x1002]):
            with patch("enikk.game.process.win32gui.PostMessage") as mock_post:
                mock_post.side_effect = [Exception("Access denied"), None]

                result = managed_process._send_close_message(mock_proc)

                assert result is True  # At least one succeeded
                assert mock_post.call_count == 2


class TestStop:
    """Tests for stop() with graceful degradation."""

    def test_returns_false_when_not_running(self, managed_process):
        """Return False when process is not running."""
        with patch.object(managed_process, "get_process", return_value=None):
            result = managed_process.stop()

            assert result is False

    def test_wm_close_success(self, managed_process):
        """Return True when WM_CLOSE succeeds."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.wait.return_value = None

        with patch.object(managed_process, "get_process", return_value=mock_proc):
            with patch.object(managed_process, "_send_close_message", return_value=True):
                result = managed_process.stop()

                assert result is True
                mock_proc.wait.assert_called_once()

    def test_escalates_to_terminate_after_wm_close_timeout(self, managed_process):
        """Escalate to terminate() when WM_CLOSE times out."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [psutil.TimeoutExpired(10), None]
        mock_proc.terminate.return_value = None

        with patch.object(managed_process, "get_process", return_value=mock_proc):
            with patch.object(managed_process, "_send_close_message", return_value=True):
                with patch("enikk.game.process.psutil.Process", return_value=mock_proc):
                    result = managed_process.stop(graceful_timeout=1.0)

                    assert result is True
                    mock_proc.terminate.assert_called_once()

    def test_escalates_to_kill_after_terminate_timeout(self, managed_process):
        """Escalate to kill() when terminate() times out."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [
            psutil.TimeoutExpired(10),  # WM_CLOSE timeout
            psutil.TimeoutExpired(5),   # terminate timeout
            None,                        # kill success
        ]
        mock_proc.terminate.return_value = None
        mock_proc.kill.return_value = None

        with patch.object(managed_process, "get_process", return_value=mock_proc):
            with patch.object(managed_process, "_send_close_message", return_value=True):
                with patch("enikk.game.process.psutil.Process", return_value=mock_proc):
                    result = managed_process.stop()

                    assert result is True
                    mock_proc.kill.assert_called_once()

    def test_kill_when_no_windows(self, managed_process):
        """Skip WM_CLOSE when process has no windows, go straight to terminate/kill."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.terminate.return_value = None
        mock_proc.wait.return_value = None

        with patch.object(managed_process, "get_process", return_value=mock_proc):
            with patch.object(managed_process, "_send_close_message", return_value=False):
                with patch("enikk.game.process.psutil.Process", return_value=mock_proc):
                    result = managed_process.stop()

                    assert result is True
                    mock_proc.terminate.assert_called_once()

    def test_handles_process_already_dead(self, managed_process):
        """Handle NoSuchProcess gracefully."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = psutil.NoSuchProcess(12345)

        with patch.object(managed_process, "get_process", return_value=mock_proc):
            with patch.object(managed_process, "_send_close_message", return_value=True):
                result = managed_process.stop()

                assert result is True  # Process is already dead, consider it stopped

    def test_returns_false_on_kill_failure(self, managed_process):
        """Return False when even kill() fails."""
        mock_proc = MagicMock(spec=psutil.Process)
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = [
            psutil.TimeoutExpired(10),  # WM_CLOSE timeout
            psutil.TimeoutExpired(5),   # terminate timeout
            psutil.AccessDenied(12345), # kill denied
        ]
        mock_proc.terminate.return_value = None
        mock_proc.kill.side_effect = psutil.AccessDenied(12345)

        with patch.object(managed_process, "get_process", return_value=mock_proc):
            with patch.object(managed_process, "_send_close_message", return_value=True):
                with patch("enikk.game.process.psutil.Process", return_value=mock_proc):
                    result = managed_process.stop()

                    assert result is False


class TestAppProcessManager:
    """Tests for AppProcessManager."""

    def test_stop_app_delegates_to_game(self):
        """stop_app() should call game.stop()."""
        from enikk.config import AppConfig
        from enikk.game.process import AppProcessManager

        config = AppConfig(app_path=r"C:\fake\game.exe")
        manager = AppProcessManager(config)

        with patch.object(manager.game, "stop", return_value=True) as mock_stop:
            result = manager.stop_app()

            assert result is True
            mock_stop.assert_called_once()

    def test_stop_launcher_delegates_to_launcher(self):
        """stop_launcher() should call launcher.stop() if launcher exists."""
        from enikk.config import AppConfig
        from enikk.game.process import AppProcessManager

        config = AppConfig(app_path=r"C:\fake\game.exe", launcher_path=r"C:\fake\launcher.exe")
        manager = AppProcessManager(config)

        with patch.object(manager.launcher, "stop", return_value=True) as mock_stop:
            result = manager.stop_launcher()

            assert result is True
            mock_stop.assert_called_once()

    def test_stop_launcher_returns_false_when_no_launcher(self):
        """stop_launcher() should return False when no launcher configured."""
        from enikk.config import AppConfig
        from enikk.game.process import AppProcessManager

        config = AppConfig(app_path=r"C:\fake\game.exe")
        manager = AppProcessManager(config)

        result = manager.stop_launcher()

        assert result is False
