"""
Enikk Telemetry

Lightweight telemetry module. Async, silent on failure.
User can opt out via telemetry.enabled: false in config.yaml.
"""

import uuid
import json
import logging
import platform
import threading
import time
from urllib import request as urllib_request

from .config import enikk_home

logger = logging.getLogger(__name__)

# Module-level enabled flag — set by __main__.py after loading config
enabled = True

TELEMETRY_URL = "http://telemetry.gaott.top:8000/event"
TELEMETRY_WRITE_TOKEN = "enikk-write-token-2026"


def _get_install_id() -> str:
    """Get or generate a persistent install ID."""
    id_file = enikk_home() / "install_id"
    if id_file.exists():
        return id_file.read_text().strip()

    install_id = str(uuid.uuid4())
    id_file.parent.mkdir(parents=True, exist_ok=True)
    id_file.write_text(install_id)
    return install_id


def send_event(event: str, **kwargs):
    """Async send telemetry event. Silent on failure."""
    if not enabled:
        return

    def _send():
        try:
            data = {
                "install_id": _get_install_id(),
                "event": event,
                "version": kwargs.get("version", "unknown"),
                "os": f"{platform.system()} {platform.release()}",
                "arch": platform.machine(),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            for key in ("features", "uptime_hours",
                        "schedule_type", "platform",
                        "skill_count", "cron_count",
                        "model_provider", "model_name",
                        "success", "tool_call_count", "duration_seconds",
                        "error_type", "error_detail", "tool_name"):
                if key in kwargs and kwargs[key] is not None:
                    data[key] = kwargs[key]

            req = urllib_request.Request(
                TELEMETRY_URL,
                data=json.dumps(data).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {TELEMETRY_WRITE_TOKEN}",
                    "User-Agent": f"Enikk/{kwargs.get('version', 'unknown')}",
                },
                method="POST",
            )
            urllib_request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning("Telemetry send failed: %s — %s", event, e)

    threading.Thread(target=_send, daemon=True).start()


def track_start(version: str, features: list[str] | None = None,
                skill_count: int | None = None, cron_count: int | None = None,
                model_provider: str | None = None, model_name: str | None = None):
    send_event("app_start", version=version, features=features or [],
               skill_count=skill_count, cron_count=cron_count,
               model_provider=model_provider, model_name=model_name)


def track_exit(version: str, uptime_hours: float):
    send_event("app_exit", version=version, uptime_hours=uptime_hours)


def track_session_completed(version: str, success: bool, tool_call_count: int | None = None,
                            duration_seconds: float | None = None):
    send_event("session_completed", version=version, success=success,
               tool_call_count=tool_call_count, duration_seconds=duration_seconds)


def track_agent_error(version: str, error_type: str, error_detail: str | None = None):
    send_event("agent_error", version=version, error_type=error_type,
               error_detail=error_detail)


def track_tool_error(version: str, tool_name: str, error_type: str,
                     error_detail: str | None = None):
    """Report a failed tool call.

    error_type distinguishes the failure class:
      - "exception": handler raised during dispatch (system-level bug,
        e.g. signature mismatch after a hermes upgrade)
      - "tool_error": handler ran and returned an error result
    """
    send_event("tool_error", version=version, tool_name=tool_name,
               error_type=error_type, error_detail=error_detail)


def track_session_started(version: str):
    send_event("session_started", version=version)


def track_memory_modified(version: str):
    send_event("memory_modified", version=version)


def track_desktop_captured(version: str):
    send_event("desktop_captured", version=version)


def track_cron_created(version: str, schedule_type: str):
    send_event("cron_created", version=version, schedule_type=schedule_type)


def track_im_connected(version: str, platform_name: str):
    send_event("im_connected", version=version, platform=platform_name)
