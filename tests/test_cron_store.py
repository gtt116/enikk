"""Tests for cron job storage and schedule parsing."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from enikk.cron.store import (
    parse_duration,
    parse_schedule,
    compute_next_run,
    create_job,
    get_job,
    list_jobs,
    update_job,
    remove_job,
    pause_job,
    resume_job,
    trigger_job,
    mark_job_run,
    get_due_jobs,
    save_job_output,
    load_jobs,
    save_jobs,
)


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


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("30m") == 30
        assert parse_duration("5min") == 5
        assert parse_duration("1minute") == 1

    def test_hours(self):
        assert parse_duration("2h") == 120
        assert parse_duration("1hr") == 60
        assert parse_duration("3hours") == 180

    def test_days(self):
        assert parse_duration("1d") == 1440
        assert parse_duration("2days") == 2880

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_duration("abc")
        with pytest.raises(ValueError):
            parse_duration("30x")


class TestParseSchedule:
    def test_interval(self):
        result = parse_schedule("every 30m")
        assert result["kind"] == "interval"
        assert result["minutes"] == 30

    def test_interval_hours(self):
        result = parse_schedule("every 2h")
        assert result["kind"] == "interval"
        assert result["minutes"] == 120

    def test_duration_oneshot(self):
        result = parse_schedule("30m")
        assert result["kind"] == "once"
        assert "run_at" in result
        run_at = datetime.fromisoformat(result["run_at"])
        # Should be ~30 minutes from now
        expected = datetime.now().astimezone() + timedelta(minutes=30)
        assert abs((run_at - expected).total_seconds()) < 5

    def test_timestamp(self):
        result = parse_schedule("2026-12-25T14:00:00")
        assert result["kind"] == "once"
        assert "2026-12-25" in result["run_at"]

    def test_cron_expression(self):
        result = parse_schedule("0 9 * * *")
        assert result["kind"] == "cron"
        assert result["expr"] == "0 9 * * *"

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_schedule("invalid schedule")


class TestComputeNextRun:
    def test_interval_no_last_run(self):
        schedule = {"kind": "interval", "minutes": 60}
        result = compute_next_run(schedule)
        assert result is not None
        next_dt = datetime.fromisoformat(result)
        expected = datetime.now().astimezone() + timedelta(minutes=60)
        assert abs((next_dt - expected).total_seconds()) < 5

    def test_interval_with_last_run(self):
        schedule = {"kind": "interval", "minutes": 60}
        last_run = (datetime.now().astimezone() - timedelta(minutes=30)).isoformat()
        result = compute_next_run(schedule, last_run_at=last_run)
        assert result is not None
        next_dt = datetime.fromisoformat(result)
        # Should be 30 minutes from now (last_run + 60min)
        expected = datetime.now().astimezone() + timedelta(minutes=30)
        assert abs((next_dt - expected).total_seconds()) < 5

    def test_cron_expression(self):
        schedule = {"kind": "cron", "expr": "0 9 * * *"}
        result = compute_next_run(schedule)
        assert result is not None
        next_dt = datetime.fromisoformat(result)
        assert next_dt.hour == 9
        assert next_dt.minute == 0

    def test_oneshot_future(self):
        run_at = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
        schedule = {"kind": "once", "run_at": run_at}
        result = compute_next_run(schedule)
        assert result == run_at

    def test_oneshot_past(self):
        run_at = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
        schedule = {"kind": "once", "run_at": run_at}
        result = compute_next_run(schedule)
        assert result is None  # Past grace window

    def test_oneshot_already_run(self):
        run_at = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
        schedule = {"kind": "once", "run_at": run_at}
        result = compute_next_run(schedule, last_run_at=run_at)
        assert result is None  # Already ran


class TestCRUD:
    def test_create_job(self, cron_dir):
        job = create_job(
            prompt="Test task",
            schedule="every 30m",
            name="Test Job",
        )
        assert job.id
        assert job.name == "Test Job"
        assert job.prompt == "Test task"
        assert job.schedule["kind"] == "interval"
        assert job.enabled is True
        assert job.state == "scheduled"

    def test_get_job(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        retrieved = get_job(job.id)
        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.prompt == "Test"

    def test_get_job_not_found(self, cron_dir):
        assert get_job("nonexistent") is None

    def test_list_jobs(self, cron_dir):
        create_job(prompt="Job 1", schedule="every 1h")
        create_job(prompt="Job 2", schedule="every 2h")
        jobs = list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_exclude_disabled(self, cron_dir):
        job = create_job(prompt="Job 1", schedule="every 1h")
        pause_job(job.id)
        jobs = list_jobs(include_disabled=False)
        assert len(jobs) == 0
        jobs_all = list_jobs(include_disabled=True)
        assert len(jobs_all) == 1

    def test_update_job(self, cron_dir):
        job = create_job(prompt="Original", schedule="every 1h")
        updated = update_job(job.id, {"prompt": "Updated"})
        assert updated is not None
        assert updated.prompt == "Updated"

    def test_update_job_schedule(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        updated = update_job(job.id, {"schedule": "every 2h"})
        assert updated is not None
        assert updated.schedule["minutes"] == 120

    def test_remove_job(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        assert remove_job(job.id) is True
        assert get_job(job.id) is None
        assert remove_job(job.id) is False

    def test_pause_resume(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        paused = pause_job(job.id)
        assert paused.enabled is False
        assert paused.state == "paused"

        resumed = resume_job(job.id)
        assert resumed.enabled is True
        assert resumed.state == "scheduled"
        assert resumed.next_run_at is not None

    def test_trigger_job(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        triggered = trigger_job(job.id)
        assert triggered is not None
        # next_run_at should be now (or very close)
        next_run = datetime.fromisoformat(triggered.next_run_at)
        now = datetime.now().astimezone()
        assert abs((next_run - now).total_seconds()) < 5


class TestMarkJobRun:
    def test_mark_success(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        mark_job_run(job.id, success=True)
        updated = get_job(job.id)
        assert updated.last_status == "ok"
        assert updated.last_run_at is not None
        assert updated.last_error is None

    def test_mark_failure(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        mark_job_run(job.id, success=False, error="test error")
        updated = get_job(job.id)
        assert updated.last_status == "error"
        assert updated.last_error == "test error"

    def test_mark_oneshot_removes_job(self, cron_dir):
        job = create_job(prompt="Test", schedule="30m", repeat=1)
        mark_job_run(job.id, success=True)
        assert get_job(job.id) is None

    def test_mark_increments_completed(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h", repeat=3)
        mark_job_run(job.id, success=True)
        updated = get_job(job.id)
        assert updated.repeat["completed"] == 1

        mark_job_run(job.id, success=True)
        updated = get_job(job.id)
        assert updated.repeat["completed"] == 2

        # Third run should remove the job
        mark_job_run(job.id, success=True)
        assert get_job(job.id) is None


class TestGetDueJobs:
    def test_no_due_jobs(self, cron_dir):
        create_job(prompt="Future job", schedule="2h")  # 2 hours from now
        due = get_due_jobs()
        assert len(due) == 0

    def test_due_interval_job(self, cron_dir):
        job = create_job(prompt="Due job", schedule="every 1h")
        # Manually set next_run_at to just past (within grace window)
        jobs = load_jobs()
        jobs[0]["next_run_at"] = (datetime.now().astimezone() - timedelta(seconds=60)).isoformat()
        save_jobs(jobs)

        due = get_due_jobs()
        assert len(due) == 1
        assert due[0].id == job.id

    def test_skips_disabled_jobs(self, cron_dir):
        job = create_job(prompt="Paused", schedule="every 1h")
        pause_job(job.id)
        # Even if due, disabled jobs are skipped
        jobs = load_jobs()
        jobs[0]["next_run_at"] = (datetime.now().astimezone() - timedelta(seconds=60)).isoformat()
        save_jobs(jobs)

        due = get_due_jobs()
        assert len(due) == 0

    def test_skips_running_jobs(self, cron_dir):
        job = create_job(prompt="Running", schedule="every 1h")
        update_job(job.id, {"state": "running"})
        jobs = load_jobs()
        jobs[0]["next_run_at"] = (datetime.now().astimezone() - timedelta(seconds=60)).isoformat()
        save_jobs(jobs)

        due = get_due_jobs()
        assert len(due) == 0


class TestSaveJobOutput:
    def test_save_output(self, cron_dir):
        job = create_job(prompt="Test", schedule="every 1h")
        output = "# Test Output\n\nSome content here."
        path = save_job_output(job.id, output)

        assert path.exists()
        assert path.read_text(encoding="utf-8") == output
        assert path.parent.name == job.id
