"""Child helper to call Gemini safely in a subprocess.

Reads a JSON object from stdin with keys: {"prompt": str, "api_key": str}
Writes a JSON result to stdout: {"success": bool, "text": str, "error": str}

This isolates the SDK (gRPC/google-api-core) so the parent can enforce a hard timeout.
"""
from __future__ import annotations
import sys
import json
import os
from pathlib import Path

# Ensure project root and Db dir are on sys.path so `from Db...` imports work
ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "Db"
for p in (str(ROOT), str(DB_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS

try:
    import google.generativeai as genai
except Exception as e:
    print(json.dumps({"success": False, "error": f"missing genai: {e}"}))
    sys.exit(2)


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        prompt = payload.get("prompt")
        api_key = payload.get("api_key")
        # Debug prints to stderr so stdout remains valid JSON for the parent
        try:
            print("CHILD API:", bool(api_key), file=sys.stderr)
            print("CHILD PROMPT:", bool(prompt), file=sys.stderr)
        except Exception:
            pass
        if not api_key or not prompt:
            print(json.dumps({"success": False, "error": "missing prompt or api_key"}))
            return

        genai.configure(api_key=api_key)
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)

        # allow per-request timeout provided by the parent payload; fall back
        # to LLM_CALL_TIMEOUT_SECONDS from config if not provided.
        timeout_seconds = payload.get("timeout_seconds")
        try:
            timeout_seconds = int(timeout_seconds) if timeout_seconds else int(LLM_CALL_TIMEOUT_SECONDS)
        except Exception:
            timeout_seconds = int(LLM_CALL_TIMEOUT_SECONDS)

        # Call SDK and explicitly disable GAPIC retries and set a per-call timeout.
        # Passing request_options with retry=None prevents google-api-core from
        # applying its default retry wrapper. Timeout here is in seconds.
        resp = model.generate_content(
            prompt,
            request_options={"retry": None, "timeout": timeout_seconds},
        )
        try:
            text = resp.text
        except Exception:
            text = str(resp)

        print(json.dumps({"success": True, "text": text}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


if __name__ == "__main__":
    main()
