"""Tests for cron job runner."""
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from enikk.cron.runner import CronRunner
from enikk.cron.store import create_job, load_jobs, save_jobs


def _make_due(job_id: str):
    """Set a job's next_run_at to just past so it's due."""
    jobs = load_jobs()
    for j in jobs:
        if j["id"] == job_id:
            j["next_run_at"] = (datetime.now().astimezone() - timedelta(seconds=60)).isoformat()
    save_jobs(jobs)


@pytest.fixture
def cron_dir(tmp_path):
    """Patch cron directories to use a temp path."""
    cron_dir = tmp_path / "cron"
    output_dir = cron_dir / "output"
    cron_dir.mkdir()
    output_dir.mkdir()

    with patch("enikk.cron.store.CRON_DIR", cron_dir), \
         patch("enikk.cron.store.JOBS_FILE", cron_dir / "jobs.json"), \
         patch("enikk.cron.store.OUTPUT_DIR", output_dir), \
         patch("enikk.cron.runner.save_job_output") as mock_save:
        mock_save.return_value = output_dir / "test_output.md"
        yield cron_dir


@pytest.fixture
def mock_config():
    """Create a mock config with cron settings."""
    config = MagicMock()
    config.cron = MagicMock()
    config.cron.tick_interval = 1
    config.cron.max_run_time = 10
    return config


@pytest.fixture
def mock_eternity():
    """Create a mock Eternity session manager."""
    eternity = MagicMock()
    eternity.create_session.return_value = "test_session_id"
    eternity.wait_for_session.return_value = {
        "final_response": "Task completed successfully",
        "status": "completed",
    }
    eternity.stop_session.return_value = True
    return eternity


class TestCronRunner:
    def test_start_stop(self, cron_dir, mock_config, mock_eternity):
        runner = CronRunner(mock_config, mock_eternity)
        runner.start()
        assert runner._thread is not None
        assert runner._thread.is_alive()

        runner.stop(timeout=2.0)
        assert runner._thread is None

    def test_tick_no_jobs(self, cron_dir, mock_config, mock_eternity):
        runner = CronRunner(mock_config, mock_eternity)
        count = runner.tick()
        assert count == 0
        mock_eternity.create_session.assert_not_called()

    def test_tick_executes_due_job(self, cron_dir, mock_config, mock_eternity):
        job = create_job(prompt="Test task", schedule="every 1h")
        _make_due(job.id)

        runner = CronRunner(mock_config, mock_eternity)
        count = runner.tick()

        assert count == 1
        mock_eternity.create_session.assert_called_once()
        call_kwargs = mock_eternity.create_session.call_args
        assert call_kwargs.kwargs["task"] == "Test task"
        assert call_kwargs.kwargs["session_id"].startswith("cron_")
        mock_eternity.wait_for_session.assert_called_once()

    def test_tick_skips_future_jobs(self, cron_dir, mock_config, mock_eternity):
        create_job(prompt="Future task", schedule="2h")  # 2 hours from now

        runner = CronRunner(mock_config, mock_eternity)
        count = runner.tick()

        assert count == 0
        mock_eternity.create_session.assert_not_called()

    def test_job_timeout(self, cron_dir, mock_config, mock_eternity):
        job = create_job(prompt="Slow task", schedule="every 1h")
        _make_due(job.id)

        # Simulate timeout: wait_for_session returns None
        mock_eternity.wait_for_session.return_value = None

        runner = CronRunner(mock_config, mock_eternity)
        runner.tick()

        mock_eternity.stop_session.assert_called_once()
        # Job should be marked as failed
        from enikk.cron.store import get_job
        updated = get_job(job.id)
        assert updated.last_status == "error"
        assert "timed out" in updated.last_error

    def test_job_error(self, cron_dir, mock_config, mock_eternity):
        job = create_job(prompt="Failing task", schedule="every 1h")
        _make_due(job.id)

        # Simulate agent error
        mock_eternity.wait_for_session.return_value = {
            "error": "agent exception",
            "status": "error",
        }

        runner = CronRunner(mock_config, mock_eternity)
        runner.tick()

        from enikk.cron.store import get_job
        updated = get_job(job.id)
        assert updated.last_status == "error"
        assert "agent exception" in updated.last_error

    def test_job_empty_response(self, cron_dir, mock_config, mock_eternity):
        job = create_job(prompt="Empty task", schedule="every 1h")
        _make_due(job.id)

        # Simulate empty response
        mock_eternity.wait_for_session.return_value = {
            "final_response": "",
            "status": "completed",
        }

        runner = CronRunner(mock_config, mock_eternity)
        runner.tick()

        from enikk.cron.store import get_job
        updated = get_job(job.id)
        assert updated.last_status == "error"
        assert "empty" in updated.last_error

    def test_deliver_local(self, cron_dir, mock_config, mock_eternity):
        job = create_job(prompt="Local task", schedule="every 1h", deliver="local")
        _make_due(job.id)

        runner = CronRunner(mock_config, mock_eternity)
        runner.tick()

        # Should complete successfully without IM delivery
        from enikk.cron.store import get_job
        updated = get_job(job.id)
        assert updated.last_status == "ok"

    def test_deliver_im_no_bridge(self, cron_dir, mock_config, mock_eternity):
        job = create_job(prompt="IM task", schedule="every 1h", deliver="im")
        _make_due(job.id)

        # No IM bridge configured
        runner = CronRunner(mock_config, mock_eternity, im_bridge=None)
        runner.tick()

        # Should still complete (with warning logged)
        from enikk.cron.store import get_job
        updated = get_job(job.id)
        assert updated.last_status == "ok"

    def test_session_creation_failure(self, cron_dir, mock_config, mock_eternity):
        job = create_job(prompt="Fail task", schedule="every 1h")
        _make_due(job.id)

        # Simulate session creation failure
        mock_eternity.create_session.side_effect = RuntimeError("No LLM provider")

        runner = CronRunner(mock_config, mock_eternity)
        runner.tick()

        from enikk.cron.store import get_job
        updated = get_job(job.id)
        assert updated.last_status == "error"
        assert "No LLM provider" in updated.last_error

    def test_runner_loop_stops_on_event(self, cron_dir, mock_config, mock_eternity):
        runner = CronRunner(mock_config, mock_eternity)
        runner.start()

        # Let it tick a couple times
        time.sleep(0.5)
        runner.stop(timeout=2.0)

        assert runner._thread is None
