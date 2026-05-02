from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the Db folder by default
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


# Public configuration variables with sensible defaults
LLM_CALL_TIMEOUT_SECONDS = _int_env("LLM_CALL_TIMEOUT_SECONDS", 30)
LLM_PARENT_TIMEOUT_SECONDS = LLM_CALL_TIMEOUT_SECONDS + 5
LLM_RETRY_DELAY_1 = _int_env("LLM_RETRY_DELAY_1", 5)
LLM_RETRY_DELAY_2 = _int_env("LLM_RETRY_DELAY_2", 15)
LLM_MAX_RETRY_PER_JOB = _int_env("LLM_MAX_RETRY_PER_JOB", 3)

# New quota/scheduler related defaults
LLM_WORKERS = _int_env("LLM_WORKERS", 1)
LLM_RPM_PER_KEY = _int_env("LLM_RPM_PER_KEY", 10)
LLM_BACKOFF_BASE_SECONDS = _int_env("LLM_BACKOFF_BASE_SECONDS", 30)
LLM_BACKOFF_MAX_SECONDS = _int_env("LLM_BACKOFF_MAX_SECONDS", 300)
LLM_DISABLE_KEY_MINUTES = _int_env("LLM_DISABLE_KEY_MINUTES", 15)
LLM_GLOBAL_503_504_LIMIT = _int_env("LLM_GLOBAL_503_504_LIMIT", 30)

# Batch worker pool / throughput tuning
LLM_WORKERS = _int_env("LLM_WORKERS", 1)
LLM_MAX_KEYS_PER_JOB = _int_env("LLM_MAX_KEYS_PER_JOB", 2)
LLM_MAX_ATTEMPTS_PER_JOB_PER_RUN = _int_env("LLM_MAX_ATTEMPTS_PER_JOB_PER_RUN", 3)
LLM_MAX_WAIT_FOR_KEY_SECONDS = _int_env("LLM_MAX_WAIT_FOR_KEY_SECONDS", 30)
LLM_THROUGHPUT_FIRST = os.getenv("LLM_THROUGHPUT_FIRST", "true").lower() in ("1", "true", "yes")

# Paths
LLM_RETRY_QUEUE_PATH = os.getenv("LLM_RETRY_QUEUE_PATH", str(BASE_DIR / "2_clean_data" / "cache" / "pending_failed_jobs.json"))
LLM_DEAD_LETTER_PATH = os.getenv("LLM_DEAD_LETTER_PATH", str(BASE_DIR / "2_clean_data" / "cache" / "llm_dead_letter_jobs.json"))
LLM_ERROR_LOG_PATH = os.getenv("LLM_ERROR_LOG_PATH", str(BASE_DIR / "logs" / "extraction_errors.jsonl"))


__all__ = [
    "LLM_CALL_TIMEOUT_SECONDS",
    "LLM_PARENT_TIMEOUT_SECONDS",
    "LLM_RETRY_DELAY_1",
    "LLM_RETRY_DELAY_2",
    "LLM_MAX_RETRY_PER_JOB",
    "LLM_WORKERS",
    "LLM_RPM_PER_KEY",
    "LLM_BACKOFF_BASE_SECONDS",
    "LLM_BACKOFF_MAX_SECONDS",
    "LLM_DISABLE_KEY_MINUTES",
    "LLM_GLOBAL_503_504_LIMIT",
    "LLM_WORKERS",
    "LLM_MAX_KEYS_PER_JOB",
    "LLM_MAX_ATTEMPTS_PER_JOB_PER_RUN",
    "LLM_MAX_WAIT_FOR_KEY_SECONDS",
    "LLM_THROUGHPUT_FIRST",
    "LLM_RETRY_QUEUE_PATH",
    "LLM_DEAD_LETTER_PATH",
    "LLM_ERROR_LOG_PATH",
]
