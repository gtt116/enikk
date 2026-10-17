"""Session statistics — token usage, timing, and context occupancy per session.

Inspired by deepseek-harness's ``dsh-session-stats`` / ``dsh-token-meter``
projections: every figure is derived from observable agent events (API call
boundaries, stream deltas, tool dispatch), accumulated in a per-session
tracker, and persisted as one JSON document per session under
``<enikk home>/session_stats/``. The stats file is a cache in the DSH sense:
deleting it only loses the aggregate, never the conversation itself.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

STATS_SCHEMA_VERSION = 1
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass
class SessionStats:
    """Whole-session counters and wall times (all milliseconds are ints)."""

    api_calls: int = 0
    tool_calls: int = 0
    llm_ms: int = 0
    tool_ms: int = 0
    ttft_ms: int = 0
    ttft_steps: int = 0
    decode_ms: int = 0
    decode_tokens: int = 0
    uncached_input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


def usage_buckets(usage: Mapping[str, Any]) -> dict[str, int]:
    """Extract the four disjoint billing buckets from a hermes usage dict.

    Hermes normalizes provider usage before calling
    ``context_compressor.update_from_response``: ``input_tokens`` is the
    uncached input (the provider aggregate minus cache traffic), while
    ``prompt_tokens`` keeps the raw provider total. The fallback subtracts
    the known cache buckets from the aggregate when the canonical field is
    missing, mirroring DSH's "billed input = sum of three buckets" rule.
    """
    def _count(key: str) -> int:
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        count = int(value)
        return count if count > 0 else 0

    uncached = _count("input_tokens")
    cache_read = _count("cache_read_tokens")
    cache_write = _count("cache_write_tokens")
    output = _count("output_tokens") or _count("completion_tokens")
    reasoning = _count("reasoning_tokens")
    if uncached <= 0:
        aggregate = _count("prompt_tokens")
        if aggregate > 0:
            uncached = max(0, aggregate - cache_read - cache_write)
    return {
        "uncached_input_tokens": uncached,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "output_tokens": output,
        "reasoning_tokens": reasoning,
    }


def cache_hit_percent(stats: Mapping[str, Any]) -> float | None:
    """Prompt-side cache-hit share; None when nothing was billed."""
    billed = (
        stats.get("uncached_input_tokens", 0)
        + stats.get("cache_read_tokens", 0)
        + stats.get("cache_write_tokens", 0)
    )
    read = stats.get("cache_read_tokens", 0)
    if billed <= 0:
        return None
    return round(100.0 * read / billed, 1)


def tokens_per_second(stats: Mapping[str, Any]) -> float | None:
    """Aggregate decode speed over decode-timed API calls."""
    decode_ms = stats.get("decode_ms", 0)
    decode_tokens = stats.get("decode_tokens", 0)
    if decode_ms <= 0 or decode_tokens <= 0:
        return None
    return decode_tokens / (decode_ms / 1000.0)


class SessionStatsStore:
    """Durable per-session stats documents, one JSON file per session."""

    def __init__(self, root: Path):
        self._root = root / "session_stats"

    def path(self, session_id: str) -> Path:
        if not _SAFE_SESSION_ID.match(session_id):
            raise ValueError(f"unsafe session id: {session_id!r}")
        return self._root / f"{session_id}.json"

    def load(self, session_id: str) -> SessionStats:
        """Load stats, returning zeroed stats when absent or unreadable."""
        return self.load_if_exists(session_id) or SessionStats()

    def load_if_exists(self, session_id: str) -> SessionStats | None:
        try:
            file = self.path(session_id)
        except ValueError:
            # User-supplied ids reach this read path via the REST endpoint;
            # an unsafe id simply has no stats document (HTTP 404), never a 500.
            return None
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            logger.warning("Unreadable session stats file %s; starting fresh", file)
            return None
        if not isinstance(raw, dict) or raw.get("version") != STATS_SCHEMA_VERSION:
            logger.debug("Incompatible session stats file %s; starting fresh", file)
            return None
        stats = SessionStats()
        for key in asdict(stats):
            value = raw.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if value > 0:
                setattr(stats, key, int(value))
        return stats

    def load_snapshot_if_exists(self, session_id: str) -> dict[str, int] | None:
        """Load stats as a plain snapshot dict, or None when absent."""
        stats = self.load_if_exists(session_id)
        return None if stats is None else asdict(stats)

    def save(self, stats: SessionStats, session_id: str) -> None:
        """Atomically replace the session's stats document."""
        file = self.path(session_id)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            payload = {"version": STATS_SCHEMA_VERSION, "session_id": session_id, **asdict(stats)}
            tmp = file.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, file)
        except OSError:
            logger.warning("Failed to persist session stats for %s", session_id, exc_info=True)

    def delete(self, session_id: str) -> None:
        try:
            self.path(session_id).unlink(missing_ok=True)
        except (OSError, ValueError):
            logger.debug("Failed to delete stats for %s", session_id, exc_info=True)


class SessionStatsTracker:
    """Accumulate one live session's stats from agent callbacks.

    Boundaries mirror DSH's fold: an API call opens at the step callback,
    the first non-empty stream token closes TTFT, the usage report closes
    the call, and tool time pairs ``tool_call`` → ``tool_result`` by id.
    """

    def __init__(
        self,
        session_id: str,
        store: SessionStatsStore | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.session_id = session_id
        self._store = store
        self._clock = clock
        self._lock = threading.Lock()
        self.stats = SessionStats()
        self._call_start: float | None = None
        self._first_token: float | None = None
        self._pending_tools: dict[str, float] = {}
        self._persisting = True

    @classmethod
    def load(cls, store: SessionStatsStore, session_id: str) -> SessionStatsTracker:
        tracker = cls(session_id, store)
        tracker.stats = store.load(session_id)
        return tracker

    def on_step(self) -> None:
        """One API call is about to start (agent step callback)."""
        with self._lock:
            self._call_start = self._clock()
            self._first_token = None

    def on_token(self) -> None:
        """First streamed token of the current API call (delta or reasoning)."""
        with self._lock:
            if self._call_start is None or self._first_token is not None:
                return
            now = self._clock()
            self._first_token = now
            self.stats.ttft_ms += max(0, round((now - self._call_start) * 1000))
            self.stats.ttft_steps += 1

    def on_usage(self, usage: Mapping[str, Any]) -> dict[str, Any]:
        """One API call reported usage; close its timing and persist."""
        with self._lock:
            now = self._clock()
            if self._call_start is not None:
                self.stats.llm_ms += max(0, round((now - self._call_start) * 1000))
                if self._first_token is not None:
                    self.stats.decode_ms += max(0, round((now - self._first_token) * 1000))
                    self.stats.decode_tokens += usage_buckets(usage)["output_tokens"]
                self._call_start = None
                self._first_token = None
            for key, value in usage_buckets(usage).items():
                setattr(self.stats, key, getattr(self.stats, key) + value)
            self.stats.api_calls += 1
            snapshot = self.snapshot_locked()
        self._persist()
        return snapshot

    def on_tool_start(self, call_id: str) -> None:
        with self._lock:
            self._pending_tools[call_id] = self._clock()

    def on_tool_complete(self, call_id: str) -> dict[str, Any] | None:
        with self._lock:
            started = self._pending_tools.pop(call_id, None)
            if started is None:
                return None
            self.stats.tool_ms += max(0, round((self._clock() - started) * 1000))
            self.stats.tool_calls += 1
            return self.snapshot_locked()

    def close(self) -> dict[str, Any]:
        """Drop unresolved tool pairs (cancelled/failed calls) and persist."""
        with self._lock:
            self._pending_tools.clear()
            snapshot = self.snapshot_locked()
        self._persist()
        return snapshot

    def stop_persisting(self) -> None:
        """Disable durable writes after the session was deleted mid-run.

        The agent thread keeps updating the in-memory counters, but neither
        a later usage report nor ``close()`` may recreate the deleted stats
        document. Blocks until any in-flight write has finished so the
        deletion that follows cannot race a concurrent save.
        """
        with self._lock:
            self._persisting = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.snapshot_locked()

    def snapshot_locked(self) -> dict[str, Any]:
        return asdict(self.stats)

    def _persist(self) -> None:
        if self._store is None:
            return
        # The whole check-copy-write sequence stays under the lock so
        # ``stop_persisting()`` cannot interleave: either this write lands
        # before the flag flips (and the subsequent delete removes it), or
        # every later write is suppressed.
        with self._lock:
            if not self._persisting:
                return
            stats = SessionStats(**asdict(self.stats))
            self._store.save(stats, self.session_id)
