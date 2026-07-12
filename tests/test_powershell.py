"""Tests for powershell module."""
from unittest.mock import patch

from enikk.powershell import (
    PowerShellService,
    resolve_powershell_path,
    _sanitize_output,
    _truncate,
)


class TestResolvePowerShellPath:

    @patch("enikk.powershell.os.path.isfile")
    @patch("enikk.powershell.os.environ", {"ProgramFiles": r"C:\Program Files"})
    def test_prefers_pwsh7_in_program_files(self, mock_isfile):
        mock_isfile.side_effect = lambda p: p == r"C:\Program Files\PowerShell\7\pwsh.exe"
        result = resolve_powershell_path()
        assert result == r"C:\Program Files\PowerShell\7\pwsh.exe"

    @patch("enikk.powershell.shutil.which", return_value=r"C:\tools\pwsh.exe")
    @patch("enikk.powershell.os.path.isfile", return_value=False)
    @patch("enikk.powershell.os.environ", {"ProgramFiles": r"C:\Program Files"})
    def test_falls_back_to_path(self, mock_isfile, mock_which):
        result = resolve_powershell_path()
        assert result == r"C:\tools\pwsh.exe"

    @patch("enikk.powershell.shutil.which", return_value=None)
    @patch("enikk.powershell.os.path.isfile")
    @patch("enikk.powershell.os.environ", {
        "ProgramFiles": r"C:\Program Files",
        "SystemRoot": r"C:\Windows",
    })
    def test_falls_back_to_system_powershell(self, mock_isfile, mock_which):
        mock_isfile.side_effect = lambda p: p == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        result = resolve_powershell_path()
        assert result == r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

    @patch("enikk.powershell.shutil.which", return_value=None)
    @patch("enikk.powershell.os.path.isfile", return_value=False)
    @patch("enikk.powershell.os.environ", {"ProgramFiles": r"C:\Program Files"})
    def test_final_fallback(self, mock_isfile, mock_which):
        result = resolve_powershell_path()
        assert result == "powershell.exe"


class TestSanitizeOutput:

    def test_preserves_tabs_and_newlines(self):
        assert _sanitize_output("hello\tworld\nline2\r\n") == "hello\tworld\nline2\r\n"

    def test_removes_control_characters(self):
        assert _sanitize_output("hello\x00\x01\x02world") == "helloworld"

    def test_removes_null_bytes(self):
        assert _sanitize_output("a\x00b") == "ab"

    def test_empty_string(self):
        assert _sanitize_output("") == ""

    def test_preserves_unicode(self):
        assert _sanitize_output("你好世界") == "你好世界"


class TestTruncate:

    def test_no_truncation_needed(self):
        text, truncated = _truncate("short", 100)
        assert text == "short"
        assert truncated is False

    def test_exact_limit(self):
        text, truncated = _truncate("12345", 5)
        assert text == "12345"
        assert truncated is False

    def test_truncation_keeps_tail(self):
        text, truncated = _truncate("abcdefgh", 5)
        assert text == "...gh"
        assert truncated is True
        assert len(text) == 5


class TestPowerShellService:

    def test_execute_simple_command(self):
        svc = PowerShellService()
        result = svc.execute('Write-Output "hello"')
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]
        assert result["stderr"] == ""
        assert result["truncated"] is False

    def test_execute_nonzero_exit(self):
        svc = PowerShellService()
        result = svc.execute("exit 42")
        assert result["exit_code"] == 42

    def test_execute_stderr(self):
        svc = PowerShellService()
        result = svc.execute("Write-Error 'test error'")
        assert result["exit_code"] == 1
        assert "test error" in result["stderr"]

    def test_execute_timeout(self):
        svc = PowerShellService()
        result = svc.execute("Start-Sleep -Seconds 10", timeout=0.5)
        assert result["exit_code"] == -1
        assert "timed out" in result["stderr"].lower()

    def test_execute_unicode_output(self):
        svc = PowerShellService()
        result = svc.execute('Write-Output "こんにちは"')
        assert result["exit_code"] == 0
        assert "こんにちは" in result["stdout"]
