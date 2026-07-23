"""Cron job runner — background thread that executes due jobs via Eternity."""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime

from ..config import Config
from ..eternity import Eternity
from ..im_bridge import IMBridge
from ..mem_track import mem_tag
from .store import get_due_jobs, mark_job_run, save_job_output, update_job

logger = logging.getLogger(__name__)


class CronRunner:
    """Background thread that ticks every interval and executes due cron jobs.

    Each job runs in an isolated Eternity session. Results are delivered to
    the configured IM platform or saved locally.
    """

    def __init__(
        self,
        config: Config,
        eternity: Eternity,
        im_bridge: IMBridge | None = None,
        im_loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.config = config
        self.eternity = eternity
        self.im_bridge = im_bridge
        self.im_loop = im_loop
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._tick_interval = config.cron.tick_interval if config.cron else 60
        self._max_run_time = config.cron.max_run_time if config.cron else 600

    def start(self) -> None:
        """Start the background cron runner thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Cron runner already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="cron-runner",
        )
        self._thread.start()
        logger.info("Cron runner started (interval=%ds, max_run=%ds)", self._tick_interval, self._max_run_time)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the cron runner thread gracefully."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            logger.warning("Cron runner did not stop within timeout")
        self._thread = None
        logger.info("Cron runner stopped")

    def _run_loop(self) -> None:
        """Main loop: tick, sleep, repeat."""
        logger.info("Cron runner loop started")
        while not self._stop_event.is_set():
            try:
                count = self.tick()
                if count:
                    logger.info("Cron tick: executed %d job(s)", count)
            except Exception:
                logger.exception("Cron tick failed")
            self._stop_event.wait(timeout=self._tick_interval)
        logger.info("Cron runner loop exiting")

    def tick(self) -> int:
        """Check for due jobs and execute them. Returns number of jobs executed."""
        due_jobs = get_due_jobs()
        if not due_jobs:
            return 0

        executed = 0
        for job in due_jobs:
            if self._stop_event.is_set():
                break
            try:
                self._execute_job(job)
                executed += 1
            except Exception:
                logger.exception("Job %s (%s) failed unexpectedly", job.id, job.name)
                mark_job_run(job.id, success=False, error="runner exception")
        return executed

    def _execute_job(self, job) -> None:
        """Execute a single cron job end-to-end."""
        job_id = job.id
        job_name = job.name

        logger.info("Executing cron job %s: %s", job_id, job_name)

        # Mark as running
        update_job(job_id, {"state": "running"})

        # Create an isolated session with cron-prefixed ID for identification
        cron_session_id = f"cron_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            session_id = self.eternity.create_session(task=job.prompt, session_id=cron_session_id)
        except RuntimeError as e:
            error_msg = f"Failed to create session: {e}"
            logger.error("Job %s: %s", job_id, error_msg)
            mark_job_run(job_id, success=False, error=error_msg)
            return

        # Set a title to mark this as a cron session
        title = f"⏰ {job_name} · {datetime.now().strftime('%m/%d %H:%M')}"
        try:
            self.eternity._session_db.set_session_title(session_id, title)
        except Exception:
            logger.debug("Failed to set cron session title", exc_info=True)

        # Use per-job timeout if set, otherwise fall back to global default
        timeout = job.max_run_time if job.max_run_time else self._max_run_time

        # Wait for session to complete with timeout
        result = self.eternity.wait_for_session(session_id, timeout=timeout)

        if result is None:
            # Timeout — stop the session
            logger.error("Job %s timed out after %ds, stopping session", job_id, timeout)
            self.eternity.stop_session(session_id)
            self.eternity.evict_session(session_id)
            error_msg = f"Job timed out after {timeout}s"
            self._save_and_deliver(job, success=False, error=error_msg, output="")
            mark_job_run(job_id, success=False, error=error_msg)
            return

        if result.get("error"):
            self.eternity.evict_session(session_id)
            error_msg = result.get("error", "unknown error")
            logger.error("Job %s failed: %s", job_id, error_msg)
            self._save_and_deliver(job, success=False, error=error_msg, output="")
            mark_job_run(job_id, success=False, error=error_msg)
            return

        if result.get("status") == "interrupted":
            self.eternity.evict_session(session_id)
            logger.info("Job %s was interrupted", job_id)
            mark_job_run(job_id, success=False, error="interrupted")
            return

        final_response = result.get("final_response", "")
        if not final_response.strip():
            self.eternity.evict_session(session_id)
            logger.warning("Job %s completed but produced empty response", job_id)
            mark_job_run(job_id, success=False, error="empty response")
            return

        # Build output document
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        output = (
            f"# Cron Job: {job_name}\n\n"
            f"**Job ID:** {job_id}\n"
            f"**Run Time:** {now_str}\n"
            f"**Schedule:** {job.schedule_display}\n\n"
            f"## Prompt\n\n{job.prompt}\n\n"
            f"## Response\n\n{final_response}\n"
        )

        self._save_and_deliver(job, success=True, error=None, output=output, final_response=final_response)
        mark_job_run(job_id, success=True)
        logger.info("Job %s completed successfully", job_id)

        # Release finished cron session from memory (history stays on disk)
        self.eternity.evict_session(session_id)

        mem_tag(f"after cron {job_id}", extra=f"({len(self.eternity._sessions)} sessions)")

    def _save_and_deliver(
        self,
        job,
        *,
        success: bool,
        error: str | None,
        output: str,
        final_response: str = "",
    ) -> None:
        """Save output to file and deliver to IM if configured."""
        # Always save output locally
        try:
            if output:
                path = save_job_output(job.id, output)
                logger.info("Job %s output saved to %s", job.id, path)
        except Exception:
            logger.exception("Failed to save output for job %s", job.id)

        # Deliver to IM if configured
        deliver = job.deliver or "im"
        if deliver == "local":
            return

        if not self.im_bridge:
            logger.warning("Job %s: deliver=%s but IM bridge not configured, saving locally only", job.id, deliver)
            return

        # Build delivery message
        if success:
            content = final_response
        else:
            content = f"⚠️ Cron job '{job.name}' failed:\n{error}"

        if not content.strip():
            return

        # Determine target chat
        chat_id = None
        if deliver.startswith("im:"):
            chat_id = deliver[3:].strip()
        else:
            # Use default IM chat (first configured platform's default)
            chat_id = self._get_default_chat_id()

        if not chat_id:
            logger.warning("Job %s: no chat_id for IM delivery", job.id)
            return

        # Deliver asynchronously
        try:
            self._deliver_to_im(chat_id, content)
        except Exception:
            logger.exception("Job %s: IM delivery failed", job.id)

    def _get_default_chat_id(self) -> str | None:
        """Get the default chat ID from the IM bridge for delivery."""
        if not self.im_bridge:
            return None
        # _chat_sessions maps chat_id -> session_id; we want chat_ids (keys)
        if hasattr(self.im_bridge, '_chat_sessions') and self.im_bridge._chat_sessions:
            return next(iter(self.im_bridge._chat_sessions.keys()), None)
        return None

    def _deliver_to_im(self, chat_id: str, content: str) -> None:
        """Deliver content to IM bridge. Handles async adapter calls from sync thread."""
        if not self.im_bridge or not self.im_bridge._adapter:
            return

        adapter = self.im_bridge._adapter

        # The adapter.send() is async; run it in the IM bridge's event loop
        if self.im_loop and self.im_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                adapter.send(chat_id, content),
                self.im_loop,
            )
            try:
                future.result(timeout=30)
                logger.info("Delivered cron output to IM chat %s", chat_id)
            except Exception as e:
                logger.error("IM delivery failed: %s", e)
        else:
            # No running loop — try asyncio.run
            try:
                asyncio.run(adapter.send(chat_id, content))
                logger.info("Delivered cron output to IM chat %s", chat_id)
            except Exception as e:
                logger.error("IM delivery failed: %s", e)
