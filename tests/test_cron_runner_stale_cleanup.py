"""Test cron runner stale job cleanup on startup."""
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest

from enikk.cron.runner import CronRunner
from enikk.cron.store import create_job, load_jobs, save_jobs, get_job


@pytest.fixture
def mock_config():
    """Create a mock config."""
    config = MagicMock()
    config.cron.tick_interval = 60
    config.cron.max_run_time = 600
    return config


@pytest.fixture
def mock_eternity():
    """Create a mock Eternity."""
    return MagicMock()


@pytest.fixture
def temp_cron_dir(tmp_path):
    """Create a temporary cron directory."""
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir()
    return cron_dir


class TestCronRunnerStaleJobCleanup:
    """Test that CronRunner cleans up stale 'running' jobs on startup."""

    def test_cleanup_stale_running_jobs(self, mock_config, mock_eternity, temp_cron_dir):
        """Stale 'running' jobs should be reset to 'scheduled' on startup."""
        # Patch the cron directory
        with patch('enikk.cron.store.CRON_DIR', temp_cron_dir), \
             patch('enikk.cron.store.JOBS_FILE', temp_cron_dir / 'jobs.json'):
            
            # Create a job and manually set it to 'running' state
            job = create_job(
                prompt="Test task",
                schedule="every 1h",
                name="Test Job"
            )
            
            # Manually set to running state (simulating a crash)
            jobs = load_jobs()
            for j in jobs:
                if j['id'] == job.id:
                    j['state'] = 'running'
            save_jobs(jobs)
            
            # Verify it's in running state
            job_before = get_job(job.id)
            assert job_before.state == 'running'
            
            # Create runner and call _cleanup_stale_running_jobs
            runner = CronRunner(mock_config, mock_eternity)
            runner._cleanup_stale_running_jobs()
            
            # Verify job is now scheduled
            job_after = get_job(job.id)
            assert job_after.state == 'scheduled'
            assert job_after.next_run_at is not None

    def test_cleanup_multiple_stale_jobs(self, mock_config, mock_eternity, temp_cron_dir):
        """Multiple stale 'running' jobs should all be cleaned up."""
        with patch('enikk.cron.store.CRON_DIR', temp_cron_dir), \
             patch('enikk.cron.store.JOBS_FILE', temp_cron_dir / 'jobs.json'):
            
            # Create multiple jobs
            job1 = create_job(prompt="Task 1", schedule="every 1h", name="Job 1")
            job2 = create_job(prompt="Task 2", schedule="every 2h", name="Job 2")
            job3 = create_job(prompt="Task 3", schedule="every 3h", name="Job 3")
            
            # Set all to running state
            jobs = load_jobs()
            for j in jobs:
                j['state'] = 'running'
            save_jobs(jobs)
            
            # Cleanup
            runner = CronRunner(mock_config, mock_eternity)
            runner._cleanup_stale_running_jobs()
            
            # Verify all are scheduled
            for job_id in [job1.id, job2.id, job3.id]:
                job = get_job(job_id)
                assert job.state == 'scheduled'

    def test_cleanup_preserves_scheduled_jobs(self, mock_config, mock_eternity, temp_cron_dir):
        """Already scheduled jobs should not be affected by cleanup."""
        with patch('enikk.cron.store.CRON_DIR', temp_cron_dir), \
             patch('enikk.cron.store.JOBS_FILE', temp_cron_dir / 'jobs.json'):
            
            # Create jobs in different states
            job1 = create_job(prompt="Task 1", schedule="every 1h", name="Scheduled Job")
            job2 = create_job(prompt="Task 2", schedule="every 2h", name="Running Job")
            
            # Set one to running
            jobs = load_jobs()
            for j in jobs:
                if j['id'] == job2.id:
                    j['state'] = 'running'
            save_jobs(jobs)
            
            # Get original next_run_at for scheduled job
            job1_before = get_job(job1.id)
            original_next_run = job1_before.next_run_at
            
            # Cleanup
            runner = CronRunner(mock_config, mock_eternity)
            runner._cleanup_stale_running_jobs()
            
            # Verify scheduled job unchanged
            job1_after = get_job(job1.id)
            assert job1_after.state == 'scheduled'
            assert job1_after.next_run_at == original_next_run
            
            # Verify running job was cleaned
            job2_after = get_job(job2.id)
            assert job2_after.state == 'scheduled'

    def test_cleanup_preserves_paused_jobs(self, mock_config, mock_eternity, temp_cron_dir):
        """Paused jobs should not be affected by cleanup."""
        with patch('enikk.cron.store.CRON_DIR', temp_cron_dir), \
             patch('enikk.cron.store.JOBS_FILE', temp_cron_dir / 'jobs.json'):
            
            # Create jobs
            job1 = create_job(prompt="Task 1", schedule="every 1h", name="Paused Job")
            job2 = create_job(prompt="Task 2", schedule="every 2h", name="Running Job")
            
            # Set states
            jobs = load_jobs()
            for j in jobs:
                if j['id'] == job1.id:
                    j['state'] = 'paused'
                elif j['id'] == job2.id:
                    j['state'] = 'running'
            save_jobs(jobs)
            
            # Cleanup
            runner = CronRunner(mock_config, mock_eternity)
            runner._cleanup_stale_running_jobs()
            
            # Verify paused job unchanged
            job1_after = get_job(job1.id)
            assert job1_after.state == 'paused'
            
            # Verify running job was cleaned
            job2_after = get_job(job2.id)
            assert job2_after.state == 'scheduled'

    def test_start_calls_cleanup(self, mock_config, mock_eternity, temp_cron_dir):
        """start() should call _cleanup_stale_running_jobs."""
        with patch('enikk.cron.store.CRON_DIR', temp_cron_dir), \
             patch('enikk.cron.store.JOBS_FILE', temp_cron_dir / 'jobs.json'):
            
            # Create a stale running job
            job = create_job(prompt="Task", schedule="every 1h", name="Stale Job")
            jobs = load_jobs()
            for j in jobs:
                if j['id'] == job.id:
                    j['state'] = 'running'
            save_jobs(jobs)
            
            # Create runner and start (but don't actually run the loop)
            runner = CronRunner(mock_config, mock_eternity)
            
            # Mock the thread to prevent actual execution
            with patch.object(runner, '_run_loop'):
                runner.start()
                
                # Verify cleanup happened
                job_after = get_job(job.id)
                assert job_after.state == 'scheduled'
                
                # Stop the runner
                runner.stop()

    def test_cleanup_recomputes_next_run(self, mock_config, mock_eternity, temp_cron_dir):
        """Cleanup should recompute next_run_at for cleaned jobs."""
        with patch('enikk.cron.store.CRON_DIR', temp_cron_dir), \
             patch('enikk.cron.store.JOBS_FILE', temp_cron_dir / 'jobs.json'):
            
            # Create a job
            job = create_job(prompt="Task", schedule="every 1h", name="Test Job")
            
            # Set to running with old next_run_at
            jobs = load_jobs()
            for j in jobs:
                if j['id'] == job.id:
                    j['state'] = 'running'
                    j['next_run_at'] = (datetime.now() - timedelta(hours=2)).isoformat()
            save_jobs(jobs)
            
            # Cleanup
            runner = CronRunner(mock_config, mock_eternity)
            runner._cleanup_stale_running_jobs()
            
            # Verify next_run_at was recomputed to future
            job_after = get_job(job.id)
            next_run = datetime.fromisoformat(job_after.next_run_at)
            now = datetime.now().astimezone()
            
            # Should be in the future (within next hour)
            assert next_run > now
            assert next_run < now + timedelta(hours=1, minutes=1)
