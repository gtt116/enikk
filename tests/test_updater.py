"""Unit tests for enikk.updater module."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from enikk.updater import UpdateInfo, _is_newer, check_for_update


# ── _is_newer ──────────────────────────────────────────────────────────


class TestIsNewer:
    def test_newer_version(self):
        assert _is_newer("0.6.0", "0.5.1") is True

    def test_older_version(self):
        assert _is_newer("0.4.0", "0.5.1") is False

    def test_same_version(self):
        assert _is_newer("0.5.1", "0.5.1") is False

    def test_major_bump(self):
        assert _is_newer("1.0.0", "0.9.9") is True

    def test_patch_bump(self):
        assert _is_newer("0.5.2", "0.5.1") is True

    def test_invalid_version_returns_false(self):
        assert _is_newer("not-a-version", "0.5.1") is False

    def test_both_invalid_returns_false(self):
        assert _is_newer("abc", "xyz") is False

    def test_prerelease(self):
        assert _is_newer("1.0.0", "1.0.0rc1") is True

    def test_prerelease_vs_prerelease(self):
        assert _is_newer("1.0.0rc2", "1.0.0rc1") is True


# ── check_for_update ───────────────────────────────────────────────────


def _mock_release(tag: str, body: str = "Release notes", assets: list | None = None) -> dict:
    """Build a fake GitHub release API response."""
    return {
        "tag_name": tag,
        "body": body,
        "html_url": f"https://github.com/gtt116/enikk/releases/tag/{tag}",
        "assets": assets if assets is not None else [
            {
                "name": "enikk.zip",
                "browser_download_url": f"https://github.com/gtt116/enikk/releases/download/{tag}/enikk.zip",
            }
        ],
    }


def _mock_urlopen(data: dict, status: int = 200):
    """Return a mock context manager that simulates urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestCheckForUpdate:
    @patch("enikk.updater.urllib.request.urlopen")
    def test_newer_version_found(self, mock_urlopen):
        release = _mock_release("v0.6.0", "New features!")
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")

        assert result is not None
        assert isinstance(result, UpdateInfo)
        assert result.version == "0.6.0"
        assert result.release_notes == "New features!"
        assert result.html_url == "https://github.com/gtt116/enikk/releases/tag/v0.6.0"
        assert "enikk.zip" in result.download_url

    @patch("enikk.updater.urllib.request.urlopen")
    def test_same_version_returns_none(self, mock_urlopen):
        release = _mock_release("v0.5.1")
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")
        assert result is None

    @patch("enikk.updater.urllib.request.urlopen")
    def test_older_version_returns_none(self, mock_urlopen):
        release = _mock_release("v0.4.0")
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")
        assert result is None

    @patch("enikk.updater.urllib.request.urlopen")
    def test_tag_without_v_prefix(self, mock_urlopen):
        release = _mock_release("0.6.0")
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")

        assert result is not None
        assert result.version == "0.6.0"

    @patch("enikk.updater.urllib.request.urlopen")
    def test_empty_tag_returns_none(self, mock_urlopen):
        release = _mock_release("")
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")
        assert result is None

    @patch("enikk.updater.urllib.request.urlopen")
    def test_no_zip_asset_empty_download_url(self, mock_urlopen):
        release = _mock_release("v0.6.0", assets=[])
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")

        assert result is not None
        assert result.download_url == ""

    @patch("enikk.updater.urllib.request.urlopen")
    def test_zip_among_multiple_assets(self, mock_urlopen):
        assets = [
            {"name": "enikk-debug.zip", "browser_download_url": "https://example.com/debug.zip"},
            {"name": "enikk.zip", "browser_download_url": "https://example.com/release.zip"},
            {"name": "checksums.txt", "browser_download_url": "https://example.com/checksums.txt"},
        ]
        release = _mock_release("v0.6.0", assets=assets)
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")

        assert result is not None
        assert result.download_url == "https://example.com/release.zip"

    @patch("enikk.updater.urllib.request.urlopen")
    def test_network_error_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = OSError("Connection refused")

        result = check_for_update("0.5.1")
        assert result is None

    @patch("enikk.updater.urllib.request.urlopen")
    def test_timeout_returns_none(self, mock_urlopen):
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")

        result = check_for_update("0.5.1")
        assert result is None

    @patch("enikk.updater.urllib.request.urlopen")
    def test_invalid_json_returns_none(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = check_for_update("0.5.1")
        assert result is None

    @patch("enikk.updater.urllib.request.urlopen")
    def test_missing_fields_handled_gracefully(self, mock_urlopen):
        release = {"tag_name": "v0.6.0"}  # missing body, html_url, assets
        mock_urlopen.return_value = _mock_urlopen(release)

        result = check_for_update("0.5.1")

        assert result is not None
        assert result.version == "0.6.0"
        assert result.release_notes == ""
        assert result.html_url == ""
        assert result.download_url == ""

    @patch("enikk.updater.urllib.request.urlopen")
    def test_request_uses_correct_headers(self, mock_urlopen):
        release = _mock_release("v0.5.1")
        mock_urlopen.return_value = _mock_urlopen(release)

        check_for_update("0.5.1")

        # Verify urlopen was called with a Request object that has the right headers
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.get_header("Accept") == "application/vnd.github+json"
