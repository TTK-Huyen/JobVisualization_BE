"""run_multi_pass.py
Simple wrapper to run process_pending_llm.py up to N times, sleeping between runs
so deferred jobs in `2_clean_data/cache/pending_failed_jobs.json` are retried.

Behavior:
- First run uses the initial pending input (pending_llm_10.json)
- Subsequent runs use `2_clean_data/cache/pending_failed_jobs.json` as input
- Stop early if retry queue becomes empty
- Sleep 30-60s between runs when there are still deferred jobs
- Report total extracted_count and remaining retry queue at end
"""
from __future__ import annotations
import subprocess, sys, os, json, time, random, pathlib

BASE = pathlib.Path(__file__).resolve().parent
PY = (BASE / '.venv' / 'Scripts' / 'python.exe')
if not PY.exists():
    PY = pathlib.Path(sys.executable)

PROCESS_SCRIPT = BASE / 'process_pending_llm.py'
INITIAL_INPUT = BASE / 'data' / 'crawl_20260430_154707' / 'clean' / 'pending_llm_10.json'
RETRY_QUEUE = BASE / '2_clean_data' / 'cache' / 'pending_failed_jobs.json'
OUTPUT_PATH = BASE / 'data' / 'crawl_20260430_154707' / 'clean' / 'extracted_10.json'
FALLBACK_PATH = BASE / 'data' / 'crawl_20260430_154707' / 'fallback' / 'extract_fallback_10.json'
CONFIG = BASE / '2_clean_data' / 'clean_config.yaml'

MAX_PASSES = 3
SLEEP_MIN = 30
SLEEP_MAX = 60

def load_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding='utf-8') or '[]')
    except Exception:
        return []


def run_once(input_path: pathlib.Path):
    cmd = [str(PY), str(PROCESS_SCRIPT), '--input-path', str(input_path), '--output-path', str(OUTPUT_PATH), '--fallback-path', str(FALLBACK_PATH), '--config-path', str(CONFIG)]
    env = os.environ.copy()
    # keep existing env defaults; caller can override if desired
    env.setdefault('LLM_MAX_WAIT_FOR_KEY_SECONDS', os.getenv('LLM_MAX_WAIT_FOR_KEY_SECONDS', '30'))
    env.setdefault('LLM_WORKERS', os.getenv('LLM_WORKERS', '1'))
    print('\n=== Running:', ' '.join(cmd))
    proc = subprocess.Popen(cmd, env=env, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    print('RC=', proc.returncode)
    if out:
        print('--- STDOUT ---')
        print(out)
    if err:
        print('--- STDERR ---')
        print(err)
    return proc.returncode


def main():
    total_extracted = 0
    prev_extracted_count = 0

    # ensure retry file exists
    RETRY_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    if not RETRY_QUEUE.exists():
        RETRY_QUEUE.write_text('[]', encoding='utf-8')

    for i in range(MAX_PASSES):
        input_path = INITIAL_INPUT if i == 0 else RETRY_QUEUE
        print(f"\n--- PASS {i+1}/{MAX_PASSES} (input={input_path}) ---")
        rc = run_once(input_path)
        # read extracted output and compute delta
        extracted = load_json(OUTPUT_PATH)
        curr_ex = len(extracted or [])
        delta = max(0, curr_ex - prev_extracted_count)
        total_extracted += delta
        prev_extracted_count = curr_ex
        # read retry queue
        retry = load_json(RETRY_QUEUE)
        remaining = len(retry or [])
        print(f"Pass {i+1} result: extracted_this_pass={delta}, remaining_retry_queue={remaining}")
        if remaining == 0:
            print('Retry queue empty — stopping early.')
            break
        if i < MAX_PASSES - 1:
            s = random.randint(SLEEP_MIN, SLEEP_MAX)
            print(f"Sleeping {s}s before next pass...")
            time.sleep(s)

    # final summary
    retry = load_json(RETRY_QUEUE)
    final_remaining = len(retry or [])
    print('\n=== FINAL SUMMARY ===')
    print('total_extracted_count=', total_extracted)
    print('final_retry_queue_count=', final_remaining)

if __name__ == '__main__':
    main()
