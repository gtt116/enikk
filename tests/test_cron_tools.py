"""Tests for cron management tools."""
from unittest.mock import patch

import pytest

from enikk.cron.tools import register_cron_tools, TOOLSET


@pytest.fixture
def cron_dir(tmp_path):
    """Patch cron directories to use a temp path."""
    cron_dir = tmp_path / "cron"
    output_dir = cron_dir / "output"
    cron_dir.mkdir()
    output_dir.mkdir()

    with patch("enikk.cron.store.CRON_DIR", cron_dir), \
         patch("enikk.cron.store.JOBS_FILE", cron_dir / "jobs.json"), \
         patch("enikk.cron.store.OUTPUT_DIR", output_dir):
        yield cron_dir


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure clean tool registry for each test."""
    from tools.registry import registry
    # Record existing tools before test
    before = set(registry._tools.keys()) if hasattr(registry, '_tools') else set()
    yield
    # Clean up tools registered during test
    if hasattr(registry, '_tools'):
        after = set(registry._tools.keys())
        for name in after - before:
            registry._tools.pop(name, None)


class TestRegisterCronTools:
    def test_registers_all_tools(self):
        from tools.registry import registry
        register_cron_tools()

        expected_tools = [
            "cron_create", "cron_list", "cron_get", "cron_update",
            "cron_delete", "cron_pause", "cron_resume", "cron_trigger",
        ]
        for name in expected_tools:
            assert name in registry._tools, f"Tool {name} not registered"

    def test_toolset_name(self):
        assert TOOLSET == "enikk_cron"

    def test_cron_create_tool(self, cron_dir):
        register_cron_tools()
        from tools.registry import registry

        result = registry._tools["cron_create"].handler({
            "prompt": "Test task",
            "schedule": "every 1h",
            "name": "Test Job",
        })
        import json
        data = json.loads(result)
        assert data["status"] == "created"
        assert data["job"]["name"] == "Test Job"

    def test_cron_list_tool(self, cron_dir):
        from enikk.cron.store import create_job
        create_job(prompt="Job 1", schedule="every 1h")
        create_job(prompt="Job 2", schedule="every 2h")

        register_cron_tools()
        from tools.registry import registry

        result = registry._tools["cron_list"].handler({})
        import json
        data = json.loads(result)
        assert data["count"] == 2

    def test_cron_pause_resume(self, cron_dir):
        from enikk.cron.store import create_job
        job = create_job(prompt="Test", schedule="every 1h")

        register_cron_tools()
        from tools.registry import registry

        # Pause
        result = registry._tools["cron_pause"].handler({"job_id": job.id})
        import json
        data = json.loads(result)
        assert data["status"] == "paused"

        # Resume
        result = registry._tools["cron_resume"].handler({"job_id": job.id})
        data = json.loads(result)
        assert data["status"] == "resumed"

    def test_cron_delete_tool(self, cron_dir):
        from enikk.cron.store import create_job, get_job
        job = create_job(prompt="Test", schedule="every 1h")

        register_cron_tools()
        from tools.registry import registry

        result = registry._tools["cron_delete"].handler({"job_id": job.id})
        import json
        data = json.loads(result)
        assert data["status"] == "deleted"
        assert get_job(job.id) is None

    def test_cron_get_not_found(self, cron_dir):
        register_cron_tools()
        from tools.registry import registry

        result = registry._tools["cron_get"].handler({"job_id": "nonexistent"})
        import json
        data = json.loads(result)
        assert "error" in data
