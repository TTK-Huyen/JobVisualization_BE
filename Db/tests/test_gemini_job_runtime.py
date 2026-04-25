from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gemini_job_runtime import ApiKeyScheduler, GeminiJobRunner


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


@pytest.fixture()
def fake_clock() -> FakeClock:
    return FakeClock(current=datetime(2026, 4, 18, 9, 0, 0))


def make_scheduler(keys, fake_clock):
    return ApiKeyScheduler(
        keys,
        max_requests_per_day=20,
        max_requests_per_minute=4,
        now_provider=fake_clock.now,
    )


def test_success_on_first_try(fake_clock):
    scheduler = make_scheduler(["key-1"], fake_clock)
    calls = []

    def call_llm(prompt, api_key):
        calls.append((prompt, api_key))
        return {"answer": "ok"}

    runner = GeminiJobRunner(scheduler, call_llm, fake_clock.sleep, logger=logging.getLogger("test"))
    result = runner.run_job("job-1", "cleaned text")

    assert result == {
        "job_id": "job-1",
        "status": "success",
        "attempts": 1,
        "used_key": "key-1",
        "output": {"answer": "ok"},
    }
    assert calls == [("cleaned text", "key-1")]


def test_fail_twice_then_success(fake_clock):
    scheduler = make_scheduler(["key-1"], fake_clock)
    attempts = {"count": 0}

    def call_llm(prompt, api_key):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError(f"temporary error {attempts['count']}")
        return "done"

    runner = GeminiJobRunner(scheduler, call_llm, fake_clock.sleep, logger=logging.getLogger("test"))
    result = runner.run_job("job-2", "cleaned text")

    assert result["status"] == "success"
    assert result["attempts"] == 3
    assert result["used_key"] == "key-1"
    assert result["output"] == "done"
    assert fake_clock.now() == datetime(2026, 4, 18, 9, 2, 0)


def test_fail_all_retries(fake_clock):
    scheduler = make_scheduler(["key-1"], fake_clock)
    calls = []

    def call_llm(prompt, api_key):
        calls.append(api_key)
        raise RuntimeError("permanent error")

    runner = GeminiJobRunner(scheduler, call_llm, fake_clock.sleep, logger=logging.getLogger("test"))
    result = runner.run_job("job-3", "cleaned text")

    assert result == {
        "job_id": "job-3",
        "status": "failed",
        "attempts": 5,
        "used_key": "key-1",
        "output": None,
    }
    assert calls == ["key-1"] * 5
    assert fake_clock.now() == datetime(2026, 4, 18, 9, 4, 0)


def test_no_available_key_returns_failed(fake_clock):
    scheduler = make_scheduler([], fake_clock)

    def call_llm(prompt, api_key):  # pragma: no cover - should never be called
        raise AssertionError("call_llm must not run when no key is available")

    runner = GeminiJobRunner(scheduler, call_llm, fake_clock.sleep, logger=logging.getLogger("test"))
    result = runner.run_job("job-4", "cleaned text")

    assert result == {
        "job_id": "job-4",
        "status": "failed",
        "attempts": 0,
        "used_key": None,
        "output": None,
    }
