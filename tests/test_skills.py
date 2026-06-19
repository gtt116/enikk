"""Unit tests for skills browser API endpoints."""
from __future__ import annotations

from pathlib import Path
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
    eternity.rename_session = Mock(return_value=True)
    eternity.get_session_messages = Mock(return_value={"messages": [], "has_more": False})
    eternity.get_session_stream = AsyncMock(return_value=iter([]))
    eternity.config = Mock()
    eternity.config.workspace = Mock()
    eternity.config.workspace.screenshot_dir = "/tmp/screenshots"
    return eternity


def _create_skill_dir(base: Path, name: str, content: str, refs: dict | None = None) -> None:
    """Create a skill directory with SKILL.md and optional references."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    if refs:
        refs_dir = skill_dir / "references"
        refs_dir.mkdir(exist_ok=True)
        for ref_name, ref_content in refs.items():
            (refs_dir / ref_name).write_text(ref_content, encoding="utf-8")


SKILL_WITH_FRONTMATTER = """\
---
name: test-skill
description: "A test skill for unit testing"
tags: [test, automation]
platforms: [windows]
---
# Test Skill

This is a test skill.
"""

SKILL_WITHOUT_FRONTMATTER = """\
# Simple Skill

No frontmatter here.
"""


@pytest.fixture
def skills_home(tmp_path):
    """Create a temp skills directory with test skills."""
    home = tmp_path / ".enikk"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)

    # Create a root-level skill
    _create_skill_dir(skills_dir, "simple", SKILL_WITHOUT_FRONTMATTER)

    # Create a skill with frontmatter and references
    _create_skill_dir(
        skills_dir,
        "game",
        SKILL_WITH_FRONTMATTER,
        refs={"guide.md": "# Game Guide\n\nSome guide content."},
    )

    # Create a category with a nested skill
    _create_skill_dir(skills_dir / "gaming", "nested-game", "---\nname: nested\ndescription: nested skill\n---\n# Nested", None)

    return home


@pytest.fixture
def client(skills_home):
    """Create a test client with mocked enikk_home."""
    eternity = _make_eternity()
    app = create_app(eternity)
    with patch("enikk.server.enikk_home", return_value=skills_home):
        yield TestClient(app), skills_home


# ── Tests: GET /api/skills ──────────────────────────────────────────────


class TestListSkills:
    """Test GET /api/skills endpoint."""

    def test_list_skills_returns_tree(self, client):
        c, _ = client
        resp = c.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data
        skills = data["skills"]
        assert len(skills) > 0

    def test_list_skills_includes_root_skill(self, client):
        c, _ = client
        resp = c.get("/api/skills")
        skills = resp.json()["skills"]
        simple = [s for s in skills if s.get("path") == "simple"]
        assert len(simple) == 1
        assert simple[0]["type"] == "skill"
        assert simple[0]["name"] == "simple"

    def test_list_skills_parses_frontmatter(self, client):
        c, _ = client
        resp = c.get("/api/skills")
        skills = resp.json()["skills"]
        game = [s for s in skills if s.get("path") == "game"]
        assert len(game) == 1
        assert game[0]["name"] == "test-skill"
        assert game[0]["description"] == "A test skill for unit testing"
        assert game[0]["tags"] == ["test", "automation"]

    def test_list_skills_includes_references(self, client):
        c, _ = client
        resp = c.get("/api/skills")
        skills = resp.json()["skills"]
        game = [s for s in skills if s.get("path") == "game"]
        assert len(game) == 1
        assert game[0]["references"] == ["references/guide.md"]

    def test_list_skills_includes_category(self, client):
        c, _ = client
        resp = c.get("/api/skills")
        skills = resp.json()["skills"]
        gaming = [s for s in skills if s.get("name") == "gaming"]
        assert len(gaming) == 1
        assert gaming[0]["type"] == "category"
        assert len(gaming[0]["children"]) == 1
        assert gaming[0]["children"][0]["name"] == "nested"

    def test_list_skills_empty_dir(self, tmp_path):
        """Test with empty skills directory."""
        home = tmp_path / ".enikk"
        (home / "skills").mkdir(parents=True)
        eternity = _make_eternity()
        app = create_app(eternity)
        with patch("enikk.server.enikk_home", return_value=home):
            c = TestClient(app)
            resp = c.get("/api/skills")
            assert resp.status_code == 200
            assert resp.json()["skills"] == []

    def test_list_skills_no_dir(self, tmp_path):
        """Test with no skills directory at all."""
        home = tmp_path / ".enikk"
        home.mkdir(parents=True)
        eternity = _make_eternity()
        app = create_app(eternity)
        with patch("enikk.server.enikk_home", return_value=home):
            c = TestClient(app)
            resp = c.get("/api/skills")
            assert resp.status_code == 200
            assert resp.json()["skills"] == []

    def test_list_skills_ignores_non_skill_dirs(self, client):
        """Directories without SKILL.md and without children are excluded."""
        _, skills_home = client
        # Create an empty directory (not a skill, not a category)
        (skills_home / "skills" / "empty-dir").mkdir()
        c = TestClient(create_app(_make_eternity()))
        with patch("enikk.server.enikk_home", return_value=skills_home):
            resp = c.get("/api/skills")
            paths = [s.get("path") for s in resp.json()["skills"]]
            assert "empty-dir" not in paths

    def test_list_skills_handles_invalid_frontmatter(self, client):
        """Invalid YAML in frontmatter should not crash."""
        _, skills_home = client
        bad_skill = skills_home / "skills" / "bad-yaml"
        bad_skill.mkdir()
        (bad_skill / "SKILL.md").write_text("---\nname: [invalid\n---\n# Bad\n", encoding="utf-8")
        c = TestClient(create_app(_make_eternity()))
        with patch("enikk.server.enikk_home", return_value=skills_home):
            resp = c.get("/api/skills")
            assert resp.status_code == 200
            bad = [s for s in resp.json()["skills"] if s.get("path") == "bad-yaml"]
            assert len(bad) == 1
            assert bad[0]["name"] == "bad-yaml"  # falls back to dir name


# ── Tests: GET /api/skills/{path} ───────────────────────────────────────


class TestGetSkillContent:
    """Test GET /api/skills/{path} endpoint."""

    def test_get_skill_md(self, client):
        c, _ = client
        resp = c.get("/api/skills/simple/SKILL.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "simple/SKILL.md"
        assert "# Simple Skill" in data["content"]

    def test_get_reference_file(self, client):
        c, _ = client
        resp = c.get("/api/skills/game/references/guide.md")
        assert resp.status_code == 200
        data = resp.json()
        assert "# Game Guide" in data["content"]

    def test_get_nonexistent_file(self, client):
        c, _ = client
        resp = c.get("/api/skills/simple/nonexistent.md")
        assert resp.status_code == 404

    def test_get_non_md_file(self, client):
        """Only .md files are allowed."""
        _, skills_home = client
        (skills_home / "skills" / "simple" / "data.txt").write_text("secret", encoding="utf-8")
        c = TestClient(create_app(_make_eternity()))
        with patch("enikk.server.enikk_home", return_value=skills_home):
            resp = c.get("/api/skills/simple/data.txt")
            assert resp.status_code == 400

    def test_path_traversal_blocked(self, client):
        """Path traversal attempts are blocked."""
        c, _ = client
        resp = c.get("/api/skills/../../etc/passwd")
        assert resp.status_code in (403, 404, 422)


# ── Tests: PUT /api/skills/{path} ───────────────────────────────────────


class TestSaveSkillContent:
    """Test PUT /api/skills/{path} endpoint."""

    def test_save_skill_md(self, client):
        c, skills_home = client
        new_content = "---\nname: updated\n---\n# Updated Skill\n\nNew content."
        resp = c.put("/api/skills/simple/SKILL.md", json={"content": new_content})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"
        # Verify file was actually written
        saved = (skills_home / "skills" / "simple" / "SKILL.md").read_text(encoding="utf-8")
        assert saved == new_content

    def test_save_reference_file(self, client):
        c, skills_home = client
        new_content = "# Updated Guide\n\nUpdated content."
        resp = c.put("/api/skills/game/references/guide.md", json={"content": new_content})
        assert resp.status_code == 200
        saved = (skills_home / "skills" / "game" / "references" / "guide.md").read_text(encoding="utf-8")
        assert saved == new_content

    def test_save_nonexistent_file(self, client):
        c, _ = client
        resp = c.put("/api/skills/simple/nonexistent.md", json={"content": "data"})
        assert resp.status_code == 404

    def test_save_non_md_file(self, client):
        """Only .md files are allowed."""
        _, skills_home = client
        (skills_home / "skills" / "simple" / "data.txt").write_text("original", encoding="utf-8")
        c = TestClient(create_app(_make_eternity()))
        with patch("enikk.server.enikk_home", return_value=skills_home):
            resp = c.put("/api/skills/simple/data.txt", json={"content": "hacked"})
            assert resp.status_code == 400
            # Verify file was NOT modified
            assert (skills_home / "skills" / "simple" / "data.txt").read_text(encoding="utf-8") == "original"

    def test_save_path_traversal_blocked(self, client):
        """Path traversal attempts are blocked."""
        c, _ = client
        resp = c.put("/api/skills/../../etc/passwd", json={"content": "hacked"})
        assert resp.status_code in (403, 404, 422)

    def test_save_missing_content_field(self, client):
        """Request without content field should fail."""
        c, _ = client
        resp = c.put("/api/skills/simple/SKILL.md", json={})
        assert resp.status_code == 422
