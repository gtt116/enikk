"""Tests for Windows CRLF/LF normalization in file tools."""
import os
import tempfile
from pathlib import Path

import pytest

from enikk.config import Config
from enikk.controller import AppController


@pytest.fixture
def controller():
    """Create an AppController instance for testing."""
    config = Config()
    return AppController(config)


class TestWindowsLineEndingNormalization:
    """Test Windows CRLF/LF normalization for read_file and write_file."""

    def test_read_file_normalizes_crlf_on_windows(self, controller):
        """read_file should convert CRLF to LF on Windows."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'line1\r\nline2\r\nline3\r\n')
            tmp = f.name

        try:
            # We're on Windows, so os.name == 'nt' is true
            result = controller.read_file(tmp)
            assert 'error' not in result
            content = result.get('content', '')
            # Should be normalized to LF
            assert '\r\n' not in content
            assert content == 'line1\nline2\nline3\n'
        finally:
            os.unlink(tmp)

    def test_write_file_matches_lf_against_crlf_on_windows(self, controller):
        """write_file should match LF old_string against CRLF file on Windows."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'hello\r\nworld\r\n')
            tmp = f.name

        try:
            # Read first (required before write)
            result = controller.read_file(tmp)
            assert 'error' not in result

            # Edit with LF old_string against CRLF file
            result = controller.write_file(tmp, old_string='hello\n', new_string='goodbye\n')
            assert result.get('success') is True

            # Verify file still has CRLF (original line ending preserved)
            raw = Path(tmp).read_bytes()
            assert b'\r\n' in raw
            assert b'goodbye\r\nworld\r\n' == raw
        finally:
            os.unlink(tmp)

    def test_write_file_preserves_crlf_on_windows(self, controller):
        """write_file should preserve CRLF line endings on Windows after edit."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'line1\r\nline2\r\nline3\r\n')
            tmp = f.name

        try:
            # Read first
            result = controller.read_file(tmp)
            assert 'error' not in result

            # Edit
            result = controller.write_file(tmp, old_string='line2', new_string='modified')
            assert result.get('success') is True

            # Verify CRLF preserved
            raw = Path(tmp).read_bytes()
            assert b'\r\n' in raw
            assert b'line1\r\nmodified\r\nline3\r\n' == raw
        finally:
            os.unlink(tmp)

    def test_write_file_multiline_match_on_windows(self, controller):
        """write_file should match multiline LF patterns against CRLF on Windows."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'def foo():\r\n    pass\r\n\r\ndef bar():\r\n    pass\r\n')
            tmp = f.name

        try:
            # Read first
            result = controller.read_file(tmp)
            assert 'error' not in result

            # Edit with LF multiline pattern
            result = controller.write_file(
                tmp,
                old_string='def foo():\n    pass',
                new_string='def foo():\n    return 42'
            )
            assert result.get('success') is True

            # Verify content and line endings
            raw = Path(tmp).read_bytes()
            assert b'def foo():\r\n    return 42\r\n' in raw
            assert b'def bar():\r\n    pass\r\n' in raw
        finally:
            os.unlink(tmp)

    def test_write_file_no_false_positives_on_windows(self, controller):
        """write_file should not match incorrectly when old_string doesn't exist."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'hello\r\nworld\r\n')
            tmp = f.name

        try:
            # Read first
            result = controller.read_file(tmp)
            assert 'error' not in result

            # Try to match non-existent pattern
            result = controller.write_file(tmp, old_string='nonexistent', new_string='replacement')
            assert result.get('success') is False
            assert 'not found' in result.get('error', '')
        finally:
            os.unlink(tmp)

    def test_read_then_edit_roundtrip(self, controller):
        """Full roundtrip: read CRLF file, edit with LF strings, verify CRLF preserved."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.py', delete=False) as f:
            f.write(b'import os\r\n\r\ndef main():\r\n    print("hello")\r\n\r\nif __name__ == "__main__":\r\n    main()\r\n')
            tmp = f.name

        try:
            # Read - should return LF-normalized content
            result = controller.read_file(tmp)
            assert 'error' not in result
            content = result['content']
            assert '\r\n' not in content  # normalized to LF
            assert 'def main():\n    print("hello")' in content

            # Edit using LF strings (as LLM would)
            result = controller.write_file(
                tmp,
                old_string='    print("hello")',
                new_string='    print("world")'
            )
            assert result.get('success') is True

            # Verify file still has CRLF
            raw = Path(tmp).read_bytes()
            assert b'\r\n' in raw
            assert b'    print("world")\r\n' in raw
            # No bare LF should exist (all LF converted back to CRLF)
            text = raw.decode('utf-8')
            assert '\r\n' in text
            # Remove all CRLF, check no bare LF remains
            assert '\n' not in text.replace('\r\n', '')
        finally:
            os.unlink(tmp)
