"""Test file tool improvements: encoding detection, line-ending preservation, read-before-write."""
import tempfile
import os
from pathlib import Path
import pytest

from enikk.config import Config
from enikk.controller import AppController, _detect_encoding, _detect_line_ending, _normalize_line_endings


@pytest.fixture
def controller():
    """Create a fresh AppController for each test."""
    cfg = Config()
    return AppController(cfg)


class TestEncodingDetection:
    """Test encoding auto-detection."""

    def test_detect_utf8_bom(self):
        """UTF-8 BOM should be detected."""
        raw = b'\xef\xbb\xbfhello world'
        assert _detect_encoding(raw) == 'utf-8-sig'

    def test_detect_utf16_le_bom(self):
        """UTF-16 LE BOM should be detected."""
        raw = b'\xff\xfeh\x00e\x00l\x00l\x00o\x00'
        assert _detect_encoding(raw) == 'utf-16-le'

    def test_detect_utf16_be_bom(self):
        """UTF-16 BE BOM should be detected."""
        raw = b'\xfe\xff\x00h\x00e\x00l\x00l\x00o'
        assert _detect_encoding(raw) == 'utf-16-be'

    def test_detect_utf8_no_bom(self):
        """Plain UTF-8 should be detected."""
        raw = b'hello world'
        assert _detect_encoding(raw) == 'utf-8'

    def test_detect_gbk(self):
        """GBK content should be detected when UTF-8 fails."""
        raw = '你好世界'.encode('gbk')
        enc = _detect_encoding(raw)
        assert enc in ('gbk', 'gb2312', 'gb18030')


class TestLineEndingDetection:
    """Test line ending detection."""

    def test_detect_crlf(self):
        """CRLF should be detected."""
        content = 'hello\r\nworld\r\n'
        assert _detect_line_ending(content) == '\r\n'

    def test_detect_lf(self):
        """LF should be detected."""
        content = 'hello\nworld\n'
        assert _detect_line_ending(content) == '\n'

    def test_detect_cr(self):
        """CR should be detected."""
        content = 'hello\rworld\r'
        assert _detect_line_ending(content) == '\r'

    def test_detect_default_lf(self):
        """No line endings should default to LF."""
        content = 'hello world'
        assert _detect_line_ending(content) == '\n'


class TestLineEndingNormalization:
    """Test line ending normalization."""

    def test_normalize_to_crlf(self):
        """LF should be converted to CRLF."""
        content = 'a\nb\nc'
        assert _normalize_line_endings(content, '\r\n') == 'a\r\nb\r\nc'

    def test_normalize_to_lf(self):
        """CRLF should be converted to LF."""
        content = 'a\r\nb\r\nc'
        assert _normalize_line_endings(content, '\n') == 'a\nb\nc'

    def test_normalize_mixed(self):
        """Mixed line endings should be normalized."""
        content = 'a\r\nb\nc\rd'
        assert _normalize_line_endings(content, '\n') == 'a\nb\nc\nd'


class TestReadBeforeWrite:
    """Test read-before-write requirement."""

    def test_edit_requires_read(self, controller):
        """edit_file should fail if file was not read first."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write('hello world')
            tmp = f.name

        try:
            result = controller.write_file(tmp, old_string='hello', new_string='goodbye')
            assert result.get('success') is False
            assert 'not been read' in result.get('error', '')
        finally:
            os.unlink(tmp)

    def test_write_requires_read_for_existing(self, controller):
        """write_file should fail for existing files if not read first."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write('existing content')
            tmp = f.name

        try:
            result = controller.write_file(tmp, 'new content')
            assert result.get('success') is False
            assert 'not been read' in result.get('error', '')
        finally:
            os.unlink(tmp)

    def test_write_new_file_without_read(self, controller):
        """write_file should work for new files without read."""
        new_tmp = os.path.join(tempfile.gettempdir(), f'test_new_{os.getpid()}.txt')
        if os.path.exists(new_tmp):
            os.unlink(new_tmp)

        try:
            result = controller.write_file(new_tmp, 'brand new file')
            assert result.get('success') is True
            assert Path(new_tmp).read_text() == 'brand new file'
        finally:
            if os.path.exists(new_tmp):
                os.unlink(new_tmp)


class TestReadFile:
    """Test read_file improvements."""

    def test_read_returns_encoding(self, controller):
        """read_file should return detected encoding."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write('hello world')
            tmp = f.name

        try:
            result = controller.read_file(tmp)
            assert result.get('success') is not False
            assert result.get('encoding') == 'utf-8'
        finally:
            os.unlink(tmp)

    def test_read_gbk_file(self, controller):
        """read_file should auto-detect GBK encoding."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write('你好世界'.encode('gbk'))
            tmp = f.name

        try:
            result = controller.read_file(tmp)
            assert result.get('success') is not False
            assert '你好世界' in result.get('content', '')
            enc = result.get('encoding', '')
            assert enc in ('gbk', 'gb2312', 'gb18030')
        finally:
            os.unlink(tmp)

    def test_read_utf8_bom_strips_bom(self, controller):
        """read_file should strip UTF-8 BOM."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'\xef\xbb\xbfhello world')
            tmp = f.name

        try:
            result = controller.read_file(tmp)
            assert result.get('success') is not False
            content = result.get('content', '')
            assert content == 'hello world'
            assert result.get('encoding') == 'utf-8-sig'
        finally:
            os.unlink(tmp)


class TestEditFile:
    """Test edit_file improvements."""

    def test_edit_preserves_crlf(self, controller):
        """edit_file should preserve CRLF line endings."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'hello\r\nworld\r\n')
            tmp = f.name

        try:
            # Read first
            result = controller.read_file(tmp)
            assert result.get('success') is not False

            # Edit
            result = controller.write_file(tmp, old_string='hello', new_string='goodbye')
            assert result.get('success') is True

            # Verify CRLF preserved
            raw = Path(tmp).read_bytes()
            assert b'\r\n' in raw
            assert b'goodbye\r\nworld\r\n' == raw
        finally:
            os.unlink(tmp)

    def test_edit_preserves_lf(self, controller):
        """edit_file should preserve LF line endings."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'hello\nworld\n')
            tmp = f.name

        try:
            # Read first
            result = controller.read_file(tmp)
            assert result.get('success') is not False

            # Edit
            result = controller.write_file(tmp, old_string='hello', new_string='goodbye')
            assert result.get('success') is True

            # Verify LF preserved (no CRLF introduced)
            raw = Path(tmp).read_bytes()
            assert b'\r\n' not in raw
            assert b'goodbye\nworld\n' == raw
        finally:
            os.unlink(tmp)

    def test_edit_gbk_file(self, controller):
        """edit_file should handle GBK encoded files."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write('你好世界'.encode('gbk'))
            tmp = f.name

        try:
            # Read first
            result = controller.read_file(tmp)
            assert result.get('success') is not False

            # Edit
            result = controller.write_file(tmp, old_string='世界', new_string='Python')
            assert result.get('success') is True

            # Verify content
            raw = Path(tmp).read_bytes()
            content = raw.decode('gbk')
            assert content == '你好Python'
        finally:
            os.unlink(tmp)


class TestWriteFile:
    """Test write_file improvements."""

    def test_write_preserves_crlf(self, controller):
        """write_file should preserve CRLF from original file."""
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'original\r\ncontent\r\n')
            tmp = f.name

        try:
            # Read first
            result = controller.read_file(tmp)
            assert result.get('success') is not False

            # Write new content with LF
            result = controller.write_file(tmp, 'new\ncontent\n')
            assert result.get('success') is True

            # Verify CRLF was restored
            raw = Path(tmp).read_bytes()
            assert b'\r\n' in raw
            assert b'new\r\ncontent\r\n' == raw
        finally:
            os.unlink(tmp)

    def test_write_new_file_uses_lf(self, controller):
        """write_file for new files should use LF by default."""
        new_tmp = os.path.join(tempfile.gettempdir(), f'test_new_{os.getpid()}.txt')
        if os.path.exists(new_tmp):
            os.unlink(new_tmp)

        try:
            result = controller.write_file(new_tmp, 'new\ncontent\n')
            assert result.get('success') is True

            raw = Path(new_tmp).read_bytes()
            assert b'\r\n' not in raw
            assert b'new\ncontent\n' == raw
        finally:
            if os.path.exists(new_tmp):
                os.unlink(new_tmp)

    def test_write_new_file_then_edit(self, controller):
        """After creating a file, editing it should not require a prior read."""
        new_tmp = os.path.join(tempfile.gettempdir(), f'test_seq_{os.getpid()}.txt')
        if os.path.exists(new_tmp):
            os.unlink(new_tmp)

        try:
            result = controller.write_file(new_tmp, 'hello world')
            assert result.get('success') is True

            result = controller.write_file(new_tmp, old_string='hello', new_string='goodbye')
            assert result.get('success') is True
            assert Path(new_tmp).read_text() == 'goodbye world'
        finally:
            if os.path.exists(new_tmp):
                os.unlink(new_tmp)
