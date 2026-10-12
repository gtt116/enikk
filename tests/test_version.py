"""Tests for git-tag based version resolution."""
from enikk import version as version_mod
from enikk.version import format_describe


class TestFormatDescribe:
    def test_commit_after_tag(self):
        assert format_describe("v0.11.1-35-g8807ed1") == "0.11.1+35.g8807ed1"

    def test_exact_tag_match(self):
        assert format_describe("v0.12.0-0-g1a2b3c4") == "0.12.0"

    def test_tag_without_v_prefix(self):
        assert format_describe("0.11.1-5-ge0b1a2c") == "0.11.1+5.ge0b1a2c"

    def test_tag_containing_hyphens(self):
        assert (
            format_describe("v0.12.0-beta.1-2-gabc1234")
            == "0.12.0-beta.1+2.gabc1234"
        )


class TestResolveVersion:
    def test_git_version_wins_in_repo(self):
        # This test suite always runs from a git checkout.
        assert version_mod._git_version() is not None
        assert version_mod.__version__ == version_mod._git_version()

    def test_falls_back_without_git(self, monkeypatch):
        monkeypatch.setattr(version_mod, "_stamped_version", lambda: None)
        monkeypatch.setattr(version_mod, "_git_version", lambda: None)
        assert version_mod.resolve_version() == version_mod._FALLBACK_VERSION

    def test_stamp_ignored_when_not_frozen(self, monkeypatch):
        # The stamp only applies to frozen builds so source checkouts always
        # report their live git version.
        assert version_mod._stamped_version() is None
