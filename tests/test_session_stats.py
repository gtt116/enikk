"""Unit tests for enikk.session_stats — DSH-style session statistics."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enikk.session_stats import (
    SessionStats,
    SessionStatsStore,
    SessionStatsTracker,
    cache_hit_percent,
    tokens_per_second,
    usage_buckets,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ── usage_buckets ──────────────────────────────────────────────────────

class TestUsageBuckets:
    def test_canonical_fields_win(self):
        usage = {
            "input_tokens": 800,
            "cache_read_tokens": 150,
            "cache_write_tokens": 50,
            "output_tokens": 200,
            "reasoning_tokens": 40,
            "prompt_tokens": 1000,
        }
        assert usage_buckets(usage) == {
            "uncached_input_tokens": 800,
            "cache_read_tokens": 150,
            "cache_write_tokens": 50,
            "output_tokens": 200,
            "reasoning_tokens": 40,
        }

    def test_prompt_total_fallback_subtracts_cache(self):
        usage = {"prompt_tokens": 1000, "cache_read_tokens": 300, "completion_tokens": 10}
        buckets = usage_buckets(usage)
        assert buckets["uncached_input_tokens"] == 700
        assert buckets["output_tokens"] == 10

    def test_invalid_values_read_as_zero(self):
        buckets = usage_buckets({"input_tokens": "x", "output_tokens": None, "cache_read_tokens": -5})
        assert buckets == {
            "uncached_input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        }


# ── derived figures ───────────────────────────────────────────────────

class TestDerived:
    def test_cache_hit_percent(self):
        stats = {"uncached_input_tokens": 100, "cache_read_tokens": 300, "cache_write_tokens": 100}
        assert cache_hit_percent(stats) == 60.0
        assert cache_hit_percent({"uncached_input_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}) is None

    def test_tokens_per_second(self):
        assert tokens_per_second({"decode_ms": 2000, "decode_tokens": 100}) == 50.0
        assert tokens_per_second({"decode_ms": 0, "decode_tokens": 100}) is None


# ── tracker fold ──────────────────────────────────────────────────────

class TestTracker:
    def test_one_call_full_boundary(self):
        clock = FakeClock()
        tracker = SessionStatsTracker("s1", clock=clock)
        tracker.on_step()          # t=0
        clock.advance(0.8)         # TTFT 800ms
        tracker.on_token()
        clock.advance(1.2)         # decode 1200ms
        snapshot = tracker.on_usage({"input_tokens": 900, "cache_read_tokens": 100, "output_tokens": 60})
        assert snapshot["ttft_ms"] == 800
        assert snapshot["llm_ms"] == 2000
        assert snapshot["decode_ms"] == 1200
        assert snapshot["decode_tokens"] == 60
        assert snapshot["uncached_input_tokens"] == 900
        assert snapshot["cache_read_tokens"] == 100
        assert snapshot["api_calls"] == 1

    def test_two_calls_accumulate(self):
        clock = FakeClock()
        tracker = SessionStatsTracker("s1", clock=clock)
        tracker.on_step()
        clock.advance(0.5)
        tracker.on_token()
        clock.advance(0.5)
        tracker.on_usage({"input_tokens": 10, "output_tokens": 10})
        tracker.on_step()
        clock.advance(0.25)
        tracker.on_token()
        clock.advance(0.75)
        tracker.on_usage({"input_tokens": 20, "output_tokens": 30})
        s = tracker.snapshot()
        assert s["api_calls"] == 2
        assert s["llm_ms"] == 2000
        assert s["ttft_ms"] == 750
        assert s["ttft_steps"] == 2
        assert s["decode_ms"] == 1250
        assert s["decode_tokens"] == 40
        assert s["output_tokens"] == 40

    def test_usage_without_step_still_counts_tokens(self):
        tracker = SessionStatsTracker("s1", clock=FakeClock())
        snapshot = tracker.on_usage({"input_tokens": 5, "output_tokens": 7})
        assert snapshot["api_calls"] == 1
        assert snapshot["llm_ms"] == 0
        assert snapshot["output_tokens"] == 7

    def test_token_without_call_is_ignored(self):
        tracker = SessionStatsTracker("s1", clock=FakeClock())
        tracker.on_token()
        assert tracker.snapshot()["ttft_steps"] == 0

    def test_tool_pairing_and_unmatched_drop(self):
        clock = FakeClock()
        tracker = SessionStatsTracker("s1", clock=clock)
        tracker.on_tool_start("a")
        clock.advance(1.5)
        assert tracker.on_tool_complete("a")["tool_ms"] == 1500
        tracker.on_tool_start("b")
        clock.advance(0.5)
        assert tracker.on_tool_complete("nope") is None
        final = tracker.close()
        assert final["tool_calls"] == 1
        assert final["tool_ms"] == 1500  # "b" dropped without a result

    def test_stop_persisting_blocks_future_writes(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        tracker = SessionStatsTracker("s1", store, clock=FakeClock())
        tracker.on_usage({"input_tokens": 10, "output_tokens": 10})
        assert store.path("s1").exists()

        tracker.stop_persisting()
        store.delete("s1")  # what eternity.delete_session does next
        tracker.on_usage({"input_tokens": 5, "output_tokens": 5})
        tracker.close()
        assert not store.path("s1").exists()
        # In-memory counters still advance for the running thread.
        assert tracker.snapshot()["output_tokens"] == 15

    def test_repeated_usage_without_new_step_does_not_retime(self):
        clock = FakeClock()
        tracker = SessionStatsTracker("s1", clock=clock)
        tracker.on_step()
        clock.advance(1.0)
        tracker.on_usage({"output_tokens": 5})
        clock.advance(5.0)
        tracker.on_usage({"output_tokens": 5})
        s = tracker.snapshot()
        assert s["api_calls"] == 2
        assert s["llm_ms"] == 1000  # second report had no open call boundary


# ── persistence ───────────────────────────────────────────────────────

class TestStore:
    def test_round_trip(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        tracker = SessionStatsTracker("abc123", store, clock=FakeClock())
        tracker.on_usage({"input_tokens": 3, "output_tokens": 4})
        loaded = SessionStatsTracker.load(store, "abc123")
        assert loaded.snapshot() == tracker.snapshot()

    def test_missing_file_returns_none_then_zeros(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        assert store.load_if_exists("nope") is None
        assert store.load("nope") == SessionStats()

    def test_corrupt_file_ignored(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        store.path("bad").parent.mkdir(parents=True)
        store.path("bad").write_text("{not json", encoding="utf-8")
        assert store.load_if_exists("bad") is None

    def test_wrong_version_ignored(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        store.path("old").parent.mkdir(parents=True)
        store.path("old").write_text(json.dumps({"version": 99, "llm_ms": 5}), encoding="utf-8")
        assert store.load_if_exists("old") is None

    def test_delete(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        store.save(SessionStats(llm_ms=1), "s")
        store.delete("s")
        assert not store.path("s").exists()
        store.delete("s")  # idempotent

    def test_unsafe_session_id_rejected(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        with pytest.raises(ValueError):
            store.path("../evil")

    def test_unsafe_session_id_reads_as_missing(self, tmp_path: Path):
        # The REST endpoint forwards user-supplied ids here; an unsafe id
        # must read as "no stats" (404), never raise into a 500.
        store = SessionStatsStore(tmp_path)
        assert store.load_if_exists("foo bar") is None
        assert store.load_snapshot_if_exists("foo bar") is None
        assert store.load("foo bar") == SessionStats()

    def test_continue_session_accumulates(self, tmp_path: Path):
        store = SessionStatsStore(tmp_path)
        first = SessionStatsTracker("cont", store, clock=FakeClock())
        first.on_usage({"input_tokens": 10, "output_tokens": 10})
        second = SessionStatsTracker.load(store, "cont")
        second.on_usage({"input_tokens": 5, "output_tokens": 5})
        assert second.snapshot()["uncached_input_tokens"] == 15
        assert second.snapshot()["output_tokens"] == 15
