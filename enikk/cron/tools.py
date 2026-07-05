"""Cron management tools for the AI agent.

Exposes cron CRUD operations as tools the agent can call to schedule,
manage, and inspect recurring tasks. Toolset: "enikk_cron".
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from tools.registry import registry, tool_result

from .store import (
    create_job,
    get_job,
    list_jobs,
    update_job,
    remove_job,
    pause_job,
    resume_job,
    trigger_job,
)

logger = logging.getLogger(__name__)

TOOLSET = "enikk_cron"


def _job_to_dict(job) -> dict:
    """Convert a CronJob to a serializable dict."""
    if job is None:
        return {}
    return job.to_dict()


# ── Tool handlers ───────────────────────────────────────────────────────

def cron_create(
    prompt: str,
    schedule: str,
    name: Optional[str] = None,
    deliver: str = "im",
    repeat: Optional[int] = None,
    max_run_time: Optional[int] = None,
) -> str:
    """Create a new cron job.

    Args:
        prompt: The task to execute when the job runs.
        schedule: Schedule string: "30m" (once), "every 2h" (recurring), "0 9 * * *" (cron expr), or ISO timestamp.
        name: Optional friendly name for the job.
        deliver: Where to send results: "im" (default, send to IM), "local" (save to file only), or "im:<chat_id>".
        repeat: How many times to run. None = forever, 1 = once.
        max_run_time: Per-job timeout in seconds. None = use global default (config.cron.max_run_time).
    """
    try:
        job = create_job(
            prompt=prompt,
            schedule=schedule,
            name=name,
            deliver=deliver,
            repeat=repeat,
            max_run_time=max_run_time,
        )
    except ValueError as e:
        return tool_result({"error": str(e)})
    return tool_result({"status": "created", "job": _job_to_dict(job)})


def cron_list() -> str:
    """List all active cron jobs."""
    jobs = list_jobs(include_disabled=False)
    return tool_result({"jobs": [_job_to_dict(j) for j in jobs], "count": len(jobs)})


def cron_get(job_id: str) -> str:
    """Get details of a specific cron job.

    Args:
        job_id: The job ID to look up.
    """
    job = get_job(job_id)
    if not job:
        return tool_result({"error": f"Job {job_id} not found"})
    return tool_result(_job_to_dict(job))


def cron_update(
    job_id: str,
    prompt: Optional[str] = None,
    schedule: Optional[str] = None,
    name: Optional[str] = None,
    deliver: Optional[str] = None,
    max_run_time: Optional[int] = None,
) -> str:
    """Update an existing cron job. Only provided fields are changed.

    Args:
        job_id: The job ID to update.
        prompt: New task prompt (optional).
        schedule: New schedule string (optional).
        name: New name (optional).
        deliver: New delivery target (optional).
        max_run_time: Per-job timeout in seconds. 0 = clear (use global default).
    """
    updates: dict[str, Any] = {}
    if prompt is not None:
        updates["prompt"] = prompt
    if schedule is not None:
        updates["schedule"] = schedule
    if name is not None:
        updates["name"] = name
    if deliver is not None:
        updates["deliver"] = deliver
    if max_run_time is not None:
        updates["max_run_time"] = max_run_time if max_run_time > 0 else None
    if not updates:
        return tool_result({"error": "No fields to update"})
    try:
        job = update_job(job_id, updates)
    except ValueError as e:
        return tool_result({"error": str(e)})
    if not job:
        return tool_result({"error": f"Job {job_id} not found"})
    return tool_result({"status": "updated", "job": _job_to_dict(job)})


def cron_delete(job_id: str) -> str:
    """Delete a cron job.

    Args:
        job_id: The job ID to delete.
    """
    if remove_job(job_id):
        return tool_result({"status": "deleted", "job_id": job_id})
    return tool_result({"error": f"Job {job_id} not found"})


def cron_pause(job_id: str) -> str:
    """Pause a cron job without deleting it.

    Args:
        job_id: The job ID to pause.
    """
    job = pause_job(job_id)
    if not job:
        return tool_result({"error": f"Job {job_id} not found"})
    return tool_result({"status": "paused", "job": _job_to_dict(job)})


def cron_resume(job_id: str) -> str:
    """Resume a paused cron job.

    Args:
        job_id: The job ID to resume.
    """
    job = resume_job(job_id)
    if not job:
        return tool_result({"error": f"Job {job_id} not found"})
    return tool_result({"status": "resumed", "job": _job_to_dict(job)})


def cron_trigger(job_id: str) -> str:
    """Trigger a cron job to run immediately on the next scheduler tick.

    Args:
        job_id: The job ID to trigger.
    """
    job = trigger_job(job_id)
    if not job:
        return tool_result({"error": f"Job {job_id} not found"})
    return tool_result({"status": "triggered", "job": _job_to_dict(job)})


# ── Schemas ─────────────────────────────────────────────────────────────

_CRON_CREATE_SCHEMA = {
    "name": "cron_create",
    "description": "Create a new scheduled cron job. The job will execute the prompt on the given schedule and deliver results to IM or local storage.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The task to execute when the job runs.",
            },
            "schedule": {
                "type": "string",
                "description": 'Schedule string: "30m" (once in 30 min), "every 2h" (recurring), "0 9 * * *" (cron expr), or ISO timestamp.',
            },
            "name": {
                "type": "string",
                "description": "Optional friendly name for the job.",
            },
            "deliver": {
                "type": "string",
                "description": 'Where to send results: "im" (default), "local", or "im:<chat_id>".',
            },
            "repeat": {
                "type": "integer",
                "description": "How many times to run. Omit for forever, 1 for once.",
            },
            "max_run_time": {
                "type": "integer",
                "description": "Per-job timeout in seconds. Omit to use global default.",
            },
        },
        "required": ["prompt", "schedule"],
    },
}

_CRON_LIST_SCHEMA = {
    "name": "cron_list",
    "description": "List all active cron jobs.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

_CRON_GET_SCHEMA = {
    "name": "cron_get",
    "description": "Get details of a specific cron job by ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to look up."},
        },
        "required": ["job_id"],
    },
}

_CRON_UPDATE_SCHEMA = {
    "name": "cron_update",
    "description": "Update an existing cron job. Only provided fields are changed.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to update."},
            "prompt": {"type": "string", "description": "New task prompt."},
            "schedule": {"type": "string", "description": "New schedule string."},
            "name": {"type": "string", "description": "New name."},
            "deliver": {"type": "string", "description": "New delivery target."},
            "max_run_time": {
                "type": "integer",
                "description": "Per-job timeout in seconds. 0 to clear (use global default).",
            },
        },
        "required": ["job_id"],
    },
}

_CRON_DELETE_SCHEMA = {
    "name": "cron_delete",
    "description": "Delete a cron job permanently.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to delete."},
        },
        "required": ["job_id"],
    },
}

_CRON_PAUSE_SCHEMA = {
    "name": "cron_pause",
    "description": "Pause a cron job without deleting it. It will stop running until resumed.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to pause."},
        },
        "required": ["job_id"],
    },
}

_CRON_RESUME_SCHEMA = {
    "name": "cron_resume",
    "description": "Resume a previously paused cron job.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to resume."},
        },
        "required": ["job_id"],
    },
}

_CRON_TRIGGER_SCHEMA = {
    "name": "cron_trigger",
    "description": "Trigger a cron job to run immediately on the next scheduler tick, regardless of its schedule.",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job ID to trigger."},
        },
        "required": ["job_id"],
    },
}


# ── Registration ────────────────────────────────────────────────────────

def register_cron_tools() -> None:
    """Register all cron management tools with the hermes tool registry."""
    tools = [
        (cron_create, _CRON_CREATE_SCHEMA),
        (cron_list, _CRON_LIST_SCHEMA),
        (cron_get, _CRON_GET_SCHEMA),
        (cron_update, _CRON_UPDATE_SCHEMA),
        (cron_delete, _CRON_DELETE_SCHEMA),
        (cron_pause, _CRON_PAUSE_SCHEMA),
        (cron_resume, _CRON_RESUME_SCHEMA),
        (cron_trigger, _CRON_TRIGGER_SCHEMA),
    ]
    for handler, schema in tools:
        registry.register(
            name=schema["name"],
            toolset=TOOLSET,
            schema=schema,
            handler=lambda args, _fn=handler, **kw: _fn(
                **{k: v for k, v in args.items() if k in _fn.__code__.co_varnames}
            ),
            emoji="⏰",
        )
    logger.info("Registered %d cron tools (toolset=%s)", len(tools), TOOLSET)
