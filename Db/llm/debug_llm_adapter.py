"""Minimal debug adapter for Gemini LLM used by legacy scripts.

Provides `call_llm(prompt: str, api_key: str) -> str` which returns the
raw model text. This is a lightweight shim that configures the SDK with the
provided key and calls `generate_content`. It intentionally avoids heavy
generation config so it's safe as a fallback.
"""
from __future__ import annotations

import os
from typing import Any


def call_llm(prompt: str, api_key: str, timeout_seconds: int | None = None, request_options: dict | None = None) -> Any:
    """Call Gemini with the given prompt and API key.

    Supports an optional `timeout_seconds` which is passed to the child process
    and to the SDK as the per-call timeout. `request_options` is reserved for
    future use.
    """
    if not api_key:
        raise ValueError("api_key is required")

    # Use a subprocess helper to isolate SDK and enforce a hard timeout.
    # NOTE: We do NOT monkeypatch requests.Session here because this function
    # is called from multiple threads simultaneously and global patching is
    # NOT thread-safe. The child subprocess runs in its own process space
    # so it is completely isolated from the parent's session state.
    import subprocess
    import sys
    from pathlib import Path
    import json
    from Db.llm.llm_config import LLM_PARENT_TIMEOUT_SECONDS

    child = Path(__file__).parent / "debug_llm_child.py"
    if not child.exists():
        raise RuntimeError("debug_llm_child.py missing; cannot call LLM safely")

    payload = json.dumps({"prompt": prompt, "api_key": api_key, "timeout_seconds": timeout_seconds})
    try:
        # Run child with a strict timeout (derived from LLM_PARENT_TIMEOUT_SECONDS).
        # Parent timeout is slightly higher to give the child RPC a chance to finish.
        # Parent timeout defaults to env `LLM_PARENT_TIMEOUT_SECONDS` but if a
        # per-request `timeout_seconds` is supplied, use a slightly higher
        # parent timeout to allow the child to clean up.
        parent_timeout = None
        try:
            if timeout_seconds:
                parent_timeout = int(timeout_seconds) + 5
        except Exception:
            parent_timeout = None
        if parent_timeout is None:
            parent_timeout = int(os.getenv("LLM_PARENT_TIMEOUT_SECONDS", str(LLM_PARENT_TIMEOUT_SECONDS)))

        # Ensure child runs with the project root as cwd and PYTHONPATH so
        # `from Db...` imports work regardless of how the parent was invoked.
        PROJECT_ROOT = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        existing_py = env.get("PYTHONPATH", "")
        prepend = str(PROJECT_ROOT)
        if existing_py:
            env["PYTHONPATH"] = prepend + os.pathsep + existing_py
        else:
            env["PYTHONPATH"] = prepend

        proc = subprocess.run(
            [sys.executable, str(child.resolve())],
            input=payload.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=parent_timeout,
            cwd=str(PROJECT_ROOT),
            env=env,
        )

        # Parse child output
        out = proc.stdout.decode("utf-8", errors="ignore").strip()
        if not out:
            err = proc.stderr.decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"LLM child produced no output; stderr={err}")

        try:
            result = json.loads(out)
        except Exception as e:
            raise RuntimeError(f"Invalid JSON from LLM child: {e}; raw={out}")

        if not result.get("success"):
            raise RuntimeError(result.get("error") or "LLM child failure")

        return result.get("text")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"LLM child process timed out after {parent_timeout}s")
