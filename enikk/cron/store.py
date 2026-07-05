"""Cron job storage and schedule parsing.

Jobs stored at {enikk_home}/cron/jobs.json.
Output saved to {enikk_home}/cron/output/{job_id}/{timestamp}.md.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from croniter import croniter

from ..config import enikk_home

logger = logging.getLogger(__name__)

# Directories
CRON_DIR = enikk_home() / "cron"
JOBS_FILE = CRON_DIR / "jobs.json"
OUTPUT_DIR = CRON_DIR / "output"
ONESHOT_GRACE_SECONDS = 120


@dataclass
class CronJob:
    """A scheduled cron job."""
    id: str
    name: str
    prompt: str
    schedule: dict                          # {kind, minutes/expr/run_at}
    schedule_display: str
    repeat: dict                            # {times: int|None, completed: int}
    enabled: bool
    state: str                              # scheduled | running | paused | error | completed
    deliver: str                            # im | local | im:<chat_id>
    created_at: str
    next_run_at: str | None
    last_run_at: str | None
    last_status: str | None
    last_error: str | None
    max_run_time: int | None = None         # per-job timeout in seconds, None = use global default

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CronJob:
        return cls(**{k: v for k, v in data.items() if k in {f.name for f in cls.__dataclass_fields__.values()}})


# ── Schedule Parsing ────────────────────────────────────────────────────

def parse_duration(s: str) -> int:
    """Parse duration string into minutes.

    Examples: "30m" -> 30, "2h" -> 120, "1d" -> 1440
    """
    s = s.strip().lower()
    match = re.match(r'^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$', s)
    if not match:
        raise ValueError(f"Invalid duration: '{s}'. Use format like '30m', '2h', or '1d'")
    value = int(match.group(1))
    unit = match.group(2)[0]
    multipliers = {'m': 1, 'h': 60, 'd': 1440}
    return value * multipliers[unit]


def parse_schedule(schedule: str) -> dict:
    """Parse schedule string into structured format.

    Returns dict with:
        - kind: "once" | "interval" | "cron"
        - For "once": "run_at" (ISO timestamp)
        - For "interval": "minutes" (int)
        - For "cron": "expr" (cron expression)

    Examples:
        "30m"              -> once in 30 minutes
        "every 30m"        -> recurring every 30 minutes
        "0 9 * * *"        -> cron expression
        "2026-07-15T14:00" -> once at timestamp
    """
    schedule = schedule.strip()
    original = schedule
    schedule_lower = schedule.lower()

    # "every X" -> recurring interval
    if schedule_lower.startswith("every "):
        duration_str = schedule[6:].strip()
        minutes = parse_duration(duration_str)
        return {"kind": "interval", "minutes": minutes, "display": f"every {minutes}m"}

    # Cron expression (5 space-separated fields)
    parts = schedule.split()
    if len(parts) >= 5 and all(re.match(r'^[\d\*\-,/]+$', p) for p in parts[:5]):
        try:
            croniter(schedule)
        except Exception as e:
            raise ValueError(f"Invalid cron expression '{schedule}': {e}")
        return {"kind": "cron", "expr": schedule, "display": schedule}

    # ISO timestamp
    if 'T' in schedule or re.match(r'^\d{4}-\d{2}-\d{2}', schedule):
        try:
            dt = datetime.fromisoformat(schedule.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return {
                "kind": "once",
                "run_at": dt.isoformat(),
                "display": f"once at {dt.strftime('%Y-%m-%d %H:%M')}",
            }
        except ValueError as e:
            raise ValueError(f"Invalid timestamp '{schedule}': {e}")

    # Duration -> one-shot from now
    try:
        minutes = parse_duration(schedule)
        run_at = datetime.now().astimezone() + timedelta(minutes=minutes)
        return {
            "kind": "once",
            "run_at": run_at.isoformat(),
            "display": f"once in {original}",
        }
    except ValueError:
        pass

    raise ValueError(
        f"Invalid schedule '{original}'. Use:\n"
        f"  - Duration: '30m', '2h', '1d' (one-shot)\n"
        f"  - Interval: 'every 30m', 'every 2h' (recurring)\n"
        f"  - Cron: '0 9 * * *' (cron expression)\n"
        f"  - Timestamp: '2026-07-15T14:00:00' (one-shot at time)"
    )


def _ensure_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime."""
    if dt.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        return dt.replace(tzinfo=local_tz)
    return dt


def _recoverable_oneshot_run_at(
    schedule: dict,
    now: datetime,
    *,
    last_run_at: str | None = None,
) -> str | None:
    """Return a one-shot run time if still eligible (within grace window)."""
    if schedule.get("kind") != "once":
        return None
    if last_run_at:
        return None
    run_at = schedule.get("run_at")
    if not run_at:
        return None
    run_at_dt = _ensure_aware(datetime.fromisoformat(run_at))
    if run_at_dt >= now - timedelta(seconds=ONESHOT_GRACE_SECONDS):
        return run_at
    return None


def compute_next_run(schedule: dict, last_run_at: str | None = None) -> str | None:
    """Compute the next run time for a schedule. Returns ISO timestamp or None."""
    now = datetime.now().astimezone()

    if schedule["kind"] == "once":
        return _recoverable_oneshot_run_at(schedule, now, last_run_at=last_run_at)

    elif schedule["kind"] == "interval":
        minutes = schedule["minutes"]
        if last_run_at:
            last = _ensure_aware(datetime.fromisoformat(last_run_at))
            next_run = last + timedelta(minutes=minutes)
        else:
            next_run = now + timedelta(minutes=minutes)
        return next_run.isoformat()

    elif schedule["kind"] == "cron":
        base_time = now
        if last_run_at:
            base_time = _ensure_aware(datetime.fromisoformat(last_run_at))
        cron = croniter(schedule["expr"], base_time)
        next_run = cron.get_next(datetime)
        return next_run.isoformat()

    return None


# ── Storage ─────────────────────────────────────────────────────────────

def ensure_dirs():
    """Ensure cron directories exist."""
    CRON_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_replace(src: str | Path, dst: str | Path) -> None:
    """Atomically replace dst with src (Windows-compatible)."""
    src, dst = Path(src), Path(dst)
    if os.name == "nt":
        # Windows: rename via os.replace is atomic on same volume
        os.replace(str(src), str(dst))
    else:
        os.replace(str(src), str(dst))


def load_jobs() -> list[dict]:
    """Load all jobs from storage."""
    ensure_dirs()
    if not JOBS_FILE.exists():
        return []
    try:
        with open(JOBS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to load jobs.json: %s", e)
        raise RuntimeError(f"Cron database error: {e}") from e

    if isinstance(data, dict):
        return data.get("jobs", [])
    if isinstance(data, list):
        return data
    raise RuntimeError(f"Cron database corrupted: unexpected format {type(data).__name__}")


def save_jobs(jobs: list[dict]) -> None:
    """Save all jobs to storage (atomic write)."""
    ensure_dirs()
    fd, tmp_path = tempfile.mkstemp(dir=str(CRON_DIR), suffix='.tmp', prefix='.jobs_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({
                "jobs": jobs,
                "updated_at": datetime.now().astimezone().isoformat(),
            }, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        _atomic_replace(tmp_path, JOBS_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ── CRUD Operations ─────────────────────────────────────────────────────

def create_job(
    prompt: str,
    schedule: str,
    *,
    name: str | None = None,
    deliver: str = "im",
    repeat: int | None = None,
    max_run_time: int | None = None,
) -> CronJob:
    """Create a new cron job. Returns the created job."""
    parsed_schedule = parse_schedule(schedule)

    # Auto-set repeat=1 for one-shot if not specified
    if parsed_schedule["kind"] == "once" and repeat is None:
        repeat = 1
    if repeat is not None and repeat <= 0:
        repeat = None

    job_id = uuid.uuid4().hex[:12]
    now = datetime.now().astimezone().isoformat()
    label = name or prompt[:50].strip() or "cron job"

    job = CronJob(
        id=job_id,
        name=label,
        prompt=prompt,
        schedule={k: v for k, v in parsed_schedule.items() if k != "display"},
        schedule_display=parsed_schedule.get("display", schedule),
        repeat={"times": repeat, "completed": 0},
        enabled=True,
        state="scheduled",
        deliver=deliver,
        created_at=now,
        next_run_at=compute_next_run(parsed_schedule),
        last_run_at=None,
        last_status=None,
        last_error=None,
        max_run_time=max_run_time,
    )

    jobs = load_jobs()
    jobs.append(job.to_dict())
    save_jobs(jobs)
    logger.info("Created cron job %s: %s (%s)", job_id, label, job.schedule_display)
    return job


def get_job(job_id: str) -> CronJob | None:
    """Get a job by ID."""
    jobs = load_jobs()
    for j in jobs:
        if j["id"] == job_id:
            return CronJob.from_dict(j)
    return None


def list_jobs(include_disabled: bool = False) -> list[CronJob]:
    """List all jobs, optionally including disabled ones."""
    jobs = [CronJob.from_dict(j) for j in load_jobs()]
    if not include_disabled:
        jobs = [j for j in jobs if j.enabled]
    return jobs


def update_job(job_id: str, updates: dict[str, Any]) -> CronJob | None:
    """Update a job by ID. Returns updated job or None if not found."""
    jobs = load_jobs()
    for i, job in enumerate(jobs):
        if job["id"] != job_id:
            continue

        updated = {**job, **updates}

        # Re-parse schedule if changed
        if "schedule" in updates and isinstance(updates["schedule"], str):
            parsed = parse_schedule(updates["schedule"])
            updated["schedule"] = {k: v for k, v in parsed.items() if k != "display"}
            updated["schedule_display"] = parsed.get("display", updates["schedule"])
            if updated.get("state") != "paused":
                updated["next_run_at"] = compute_next_run(parsed)

        jobs[i] = updated
        save_jobs(jobs)
        logger.info("Updated cron job %s", job_id)
        return CronJob.from_dict(jobs[i])
    return None


def remove_job(job_id: str) -> bool:
    """Remove a job by ID. Returns True if removed."""
    jobs = load_jobs()
    original_len = len(jobs)
    jobs = [j for j in jobs if j["id"] != job_id]
    if len(jobs) < original_len:
        save_jobs(jobs)
        # Clean up output directory
        job_output_dir = OUTPUT_DIR / job_id
        if job_output_dir.exists():
            shutil.rmtree(job_output_dir)
        logger.info("Removed cron job %s", job_id)
        return True
    return False


def pause_job(job_id: str) -> CronJob | None:
    """Pause a job."""
    return update_job(job_id, {
        "enabled": False,
        "state": "paused",
    })


def resume_job(job_id: str) -> CronJob | None:
    """Resume a paused job."""
    job = get_job(job_id)
    if not job:
        return None
    next_run = compute_next_run(job.schedule)
    return update_job(job_id, {
        "enabled": True,
        "state": "scheduled",
        "next_run_at": next_run,
    })


def trigger_job(job_id: str) -> CronJob | None:
    """Schedule a job to run on the next tick."""
    return update_job(job_id, {
        "enabled": True,
        "state": "scheduled",
        "next_run_at": datetime.now().astimezone().isoformat(),
    })


def mark_job_run(job_id: str, success: bool, error: str | None = None) -> None:
    """Mark a job as having been run. Updates last_run_at, state, increments completed."""
    jobs = load_jobs()
    for i, job in enumerate(jobs):
        if job["id"] != job_id:
            continue

        now = datetime.now().astimezone().isoformat()
        job["last_run_at"] = now
        job["last_status"] = "ok" if success else "error"
        job["last_error"] = error if not success else None

        # Increment completed count
        if job.get("repeat"):
            job["repeat"]["completed"] = job["repeat"].get("completed", 0) + 1
            times = job["repeat"].get("times")
            completed = job["repeat"]["completed"]
            if times is not None and times > 0 and completed >= times:
                jobs.pop(i)
                save_jobs(jobs)
                logger.info("Job %s completed all %d runs, removed", job_id, times)
                return

        # Compute next run
        job["next_run_at"] = compute_next_run(job["schedule"], now)
        if job["next_run_at"] is None:
            job["enabled"] = False
            job["state"] = "completed"
        elif job.get("state") != "paused":
            job["state"] = "scheduled"

        jobs[i] = job
        save_jobs(jobs)
        logger.info("Marked job %s as %s", job_id, job["last_status"])
        return

    logger.warning("mark_job_run: job_id %s not found", job_id)


# ── Due Job Resolution ──────────────────────────────────────────────────

def _compute_grace_seconds(schedule: dict) -> int:
    """Compute catch-up grace window: half the period, clamped [120s, 2h]."""
    MIN_GRACE = 120
    MAX_GRACE = 7200

    kind = schedule.get("kind")
    if kind == "interval":
        period_seconds = schedule.get("minutes", 1) * 60
        grace = period_seconds // 2
        return max(MIN_GRACE, min(grace, MAX_GRACE))

    if kind == "cron":
        try:
            now = datetime.now().astimezone()
            cron = croniter(schedule["expr"], now)
            first = cron.get_next(datetime)
            second = cron.get_next(datetime)
            period_seconds = int((second - first).total_seconds())
            grace = period_seconds // 2
            return max(MIN_GRACE, min(grace, MAX_GRACE))
        except Exception:
            pass

    return MIN_GRACE


def get_due_jobs() -> list[CronJob]:
    """Get all jobs that are due to run now.

    Stale recurring jobs (missed by more than grace window) are fast-forwarded
    to the next future occurrence instead of firing immediately.
    """
    now = datetime.now().astimezone()
    raw_jobs = load_jobs()
    due = []
    needs_save = False

    for job in raw_jobs:
        if not job.get("enabled", True):
            continue
        if job.get("state") == "running":
            continue

        next_run = job.get("next_run_at")
        if not next_run:
            # Try to recover
            schedule = job.get("schedule", {})
            kind = schedule.get("kind")
            recovered = None
            if kind == "once":
                recovered = _recoverable_oneshot_run_at(schedule, now, last_run_at=job.get("last_run_at"))
            elif kind in {"cron", "interval"}:
                recovered = compute_next_run(schedule, now.isoformat())
            if not recovered:
                continue
            job["next_run_at"] = recovered
            next_run = recovered
            needs_save = True

        next_run_dt = _ensure_aware(datetime.fromisoformat(next_run))
        if next_run_dt > now:
            continue  # Not due yet

        schedule = job.get("schedule", {})
        kind = schedule.get("kind")

        # Check if stale (missed by more than grace window)
        grace = _compute_grace_seconds(schedule)
        if kind in {"cron", "interval"} and (now - next_run_dt).total_seconds() > grace:
            new_next = compute_next_run(schedule, now.isoformat())
            if new_next:
                logger.info(
                    "Job '%s' missed its window (%s, grace=%ds). Fast-forwarding to %s",
                    job.get("name", job["id"]), next_run, grace, new_next,
                )
                job["next_run_at"] = new_next
                needs_save = True
                continue

        due.append(CronJob.from_dict(job))

    if needs_save:
        save_jobs(raw_jobs)

    return due


# ── Output Storage ───────────────────────────────────────────────────────

def save_job_output(job_id: str, output: str) -> Path:
    """Save job output to file. Returns the output file path."""
    ensure_dirs()
    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = job_output_dir / f"{timestamp}.md"

    fd, tmp_path = tempfile.mkstemp(dir=str(job_output_dir), suffix='.tmp', prefix='.output_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(output)
            f.flush()
            os.fsync(f.fileno())
        _atomic_replace(tmp_path, output_file)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return output_file
