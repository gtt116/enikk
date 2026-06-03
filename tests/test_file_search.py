"""Tests for file_search module."""
from enikk.file_search import search_files, _search_powershell


class TestFileSearch:
    """Test file search functionality."""

    def test_powershell_fallback_basic(self, tmp_path):
        """Test PowerShell search finds files."""
        # Create test files
        (tmp_path / "test1.txt").write_text("content1")
        (tmp_path / "test2.txt").write_text("content2")
        (tmp_path / "other.log").write_text("log")

        result = search_files("*.txt", str(tmp_path), limit=10)

        assert result["count"] == 2
        assert result["method"] == "powershell"
        assert len(result["files"]) == 2
        assert all(f.endswith(".txt") for f in result["files"])

    def test_search_with_wildcard(self, tmp_path):
        """Test search with wildcard pattern."""
        (tmp_path / "config.yaml").write_text("key: value")
        (tmp_path / "config-dev.yaml").write_text("key: dev")
        (tmp_path / "readme.md").write_text("# Readme")

        result = search_files("config*", str(tmp_path), limit=10)

        assert result["count"] == 2
        assert all("config" in f for f in result["files"])

    def test_search_with_limit(self, tmp_path):
        """Test search respects limit."""
        # Create 10 files
        for i in range(10):
            (tmp_path / f"file{i}.txt").write_text(f"content{i}")

        result = search_files("*.txt", str(tmp_path), limit=3)

        assert result["count"] == 3
        assert len(result["files"]) == 3

    def test_search_empty_result(self, tmp_path):
        """Test search returns empty list when no matches."""
        (tmp_path / "file.txt").write_text("content")

        result = search_files("*.nonexistent", str(tmp_path), limit=10)

        assert result["count"] == 0
        assert result["files"] == []

    def test_search_recursive(self, tmp_path):
        """Test search finds files in subdirectories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "root.txt").write_text("root")
        (subdir / "nested.txt").write_text("nested")

        result = search_files("*.txt", str(tmp_path), limit=10)

        assert result["count"] == 2
        assert any("nested.txt" in f for f in result["files"])

    def test_search_returns_correct_format(self, tmp_path):
        """Test search returns expected dict format."""
        (tmp_path / "test.txt").write_text("test")

        result = search_files("*.txt", str(tmp_path), limit=10)

        assert isinstance(result, dict)
        assert "files" in result
        assert "method" in result
        assert "count" in result
        assert isinstance(result["files"], list)
        assert isinstance(result["method"], str)
        assert isinstance(result["count"], int)


class TestPowerShellSearch:
    """Test PowerShell search directly."""

    def test_powershell_direct(self, tmp_path):
        """Test _search_powershell function directly."""
        (tmp_path / "direct.txt").write_text("direct")

        files = _search_powershell("*.txt", str(tmp_path), limit=10)

        assert len(files) == 1
        assert files[0].endswith("direct.txt")

    def test_powershell_empty(self, tmp_path):
        """Test _search_powershell with no matches."""
        files = _search_powershell("*.xyz", str(tmp_path), limit=10)

        assert files == []


class TestFallbackBehavior:
    """Test fallback when Windows Search is unavailable."""

    def test_fallback_to_powershell(self, tmp_path, monkeypatch):
        """Test that search falls back to PowerShell when WSearch fails."""
        from enikk import file_search

        # Mock Windows Search to always fail
        def mock_wsearch(query, path, limit):
            raise RuntimeError("Windows Search unavailable")

        monkeypatch.setattr(file_search, "_search_windows_search", mock_wsearch)

        (tmp_path / "test.txt").write_text("test")
        result = file_search.search_files("*.txt", str(tmp_path), limit=10)

        assert result["method"] == "powershell"
        assert result["count"] == 1
        assert len(result["files"]) == 1
