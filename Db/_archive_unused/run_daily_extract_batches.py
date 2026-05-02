"""run_daily_extract_batches.py
Run each micro-batch produced by create_daily_batches.py in sequence.
- Sleeps 15 minutes between batches
- Uses production env overrides (low concurrency, conservative backoff)
- For each batch writes a per-batch summary
- At the end writes daily_extract_summary.json

Usage:
  python run_daily_extract_batches.py --batches data/.../clean/batches

Notes:
- Does NOT change process_pending_llm.py behavior; it calls it as a subprocess
- Failed jobs are recorded by process_pending_llm.py into pending_failed_jobs.json
"""
from __future__ import annotations
import subprocess, time, json, pathlib, argparse, os
from datetime import datetime

BASE = pathlib.Path(__file__).resolve().parent
DEFAULT_BATCH_DIR = BASE / 'data' / 'crawl_20260430_154707' / 'clean' / 'batches'
RETRY_QUEUE = BASE / '2_clean_data' / 'cache' / 'pending_failed_jobs.json'
OUTPUT_DIR = BASE / 'data' / 'crawl_20260430_154707' / 'clean' / 'batches_outputs'
FALLBACK_DIR = BASE / 'data' / 'crawl_20260430_154707' / 'fallback' / 'batches_fallback'
SUMMARY_DIR = BASE / 'data' / 'crawl_20260430_154707' / 'clean'
PROCESS_SCRIPT = BASE / 'process_pending_llm.py'

# Production settings (as requested)
PROD_ENV = {
    'LLM_WORKERS': '1',
    'LLM_MAX_KEYS_PER_JOB': '1',
    'LLM_MAX_WAIT_FOR_KEY_SECONDS': '30',
    'LLM_BACKOFF_BASE_SECONDS': '300',
    'LLM_BACKOFF_MAX_SECONDS': '1800',
    'LLM_CALL_TIMEOUT_SECONDS': '45',
    'LLM_PARENT_TIMEOUT_SECONDS': '60',
}

SLEEP_BETWEEN_BATCHES = 15 * 60  # 15 minutes


def load_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding='utf-8') or '[]')
    except Exception:
        return []


def write_json(p: pathlib.Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def run_batch(batch_path: pathlib.Path, batch_id: str):
    # prepare output paths for this batch
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f'{batch_id}_extracted.json'
    fallback_path = FALLBACK_DIR / f'{batch_id}_fallback.json'

    cmd = [str(BASE / '.venv' / 'Scripts' / 'python.exe') if (BASE / '.venv' / 'Scripts' / 'python.exe').exists() else str(os.sys.executable), str(PROCESS_SCRIPT), '--input-path', str(batch_path), '--output-path', str(out_path), '--fallback-path', str(fallback_path), '--config-path', str(BASE / '2_clean_data' / 'clean_config.yaml')]

    env = os.environ.copy()
    env.update(PROD_ENV)

    start = time.monotonic()
    proc = subprocess.Popen(cmd, env=env, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    end = time.monotonic()
    runtime = end - start

    # metrics
    extracted = load_json(out_path)
    extracted_count = len(extracted or [])
    fallback = load_json(fallback_path)
    fallback_count = len(fallback or [])

    # compute delta in retry queue (new entries added by this batch)
    retry_after = load_json(RETRY_QUEUE)
    retry_count_total = len(retry_after)

    # best-effort count of 429 vs 5xx from entries added in this run
    count_429 = 0
    count_5xx = 0
    # we cannot easily know which entries were present before this batch without storing previous snapshot.
    # Caller will compute delta by passing previous_retry_len.

    # attempt to parse last_error fields
    for r in retry_after:
        le = r.get('last_error')
        if not le:
            continue
        s = str(le)
        if '429' in s:
            count_429 += 1
        if any(x in s for x in ('5xx', '503', '504', 'timeout')):
            count_5xx += 1

    summary = {
        'batch_id': batch_id,
        'input_count': len(load_json(batch_path) or []),
        'extracted_count': extracted_count,
        'retry_count_total': retry_count_total,
        'fallback_count': fallback_count,
        'count_429_total_so_far': count_429,
        'count_5xx_total_so_far': count_5xx,
        'runtime_seconds': int(runtime),
        'return_code': proc.returncode,
    }

    return summary, out, err


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--batches', '-b', help='batches dir', default=str(DEFAULT_BATCH_DIR))
    p.add_argument('--sleep', type=int, help='sleep seconds between batches', default=SLEEP_BETWEEN_BATCHES)
    p.add_argument('--max-batches', type=int, help='limit number of batches to run', default=None)
    args = p.parse_args()

    batch_dir = pathlib.Path(args.batches)
    if not batch_dir.exists():
        print('Batches dir not found:', batch_dir)
        return

    batch_files = sorted([p for p in batch_dir.iterdir() if p.is_file() and p.suffix.lower() == '.json'])
    if args.max_batches:
        batch_files = batch_files[:args.max_batches]

    # ensure retry queue exists
    RETRY_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    if not RETRY_QUEUE.exists():
        RETRY_QUEUE.write_text('[]', encoding='utf-8')

    daily_summary = {
        'date': datetime.utcnow().isoformat(),
        'batches': [],
    }

    # snapshot retry queue before runs to compute per-batch delta
    prev_retry_len = len(load_json(RETRY_QUEUE))
    total_extracted = 0
    total_retry = 0
    total_fallback = 0
    total_429 = 0
    total_5xx = 0
    total_jobs = 0

    for idx, bf in enumerate(batch_files, start=1):
        batch_id = bf.stem
        print('\n=== Running batch', batch_id, '===')
        summary, out, err = run_batch(bf, batch_id)

        # compute per-batch retry delta and counts
        retry_now = load_json(RETRY_QUEUE)
        retry_len_now = len(retry_now)
        new_retries = retry_len_now - prev_retry_len
        if new_retries < 0:
            new_retries = 0
        # count 429/5xx among newly added entries
        new_entries = retry_now[-new_retries:] if new_retries > 0 else []
        count_429 = sum(1 for r in new_entries if r.get('last_error') and '429' in str(r.get('last_error')))
        count_5xx = sum(1 for r in new_entries if r.get('last_error') and any(x in str(r.get('last_error')) for x in ('5xx','503','504','timeout')))

        per_batch = {
            'batch_id': batch_id,
            'input_count': summary['input_count'],
            'extracted_count': summary['extracted_count'],
            'retry_added': new_retries,
            'fallback_count': summary['fallback_count'],
            'count_429': count_429,
            'count_5xx': count_5xx,
            'runtime_seconds': summary['runtime_seconds'],
            'return_code': summary['return_code'],
        }
        print('Batch summary:', per_batch)

        daily_summary['batches'].append(per_batch)

        total_extracted += per_batch['extracted_count']
        total_retry += per_batch['retry_added']
        total_fallback += per_batch['fallback_count']
        total_429 += per_batch['count_429']
        total_5xx += per_batch['count_5xx']
        total_jobs += per_batch['input_count']

        prev_retry_len = retry_len_now

        # sleep between batches (unless last)
        if idx < len(batch_files):
            s = args.sleep
            print(f'Sleeping {s} seconds before next batch...')
            time.sleep(s)

    # write daily summary
    final = {
        'date': datetime.utcnow().isoformat(),
        'total_jobs': total_jobs,
        'total_extracted': total_extracted,
        'total_retry': total_retry,
        'total_fallback': total_fallback,
        'total_429': total_429,
        'total_5xx': total_5xx,
        'batches': daily_summary['batches'],
    }

    outp = SUMMARY_DIR / 'daily_extract_summary.json'
    write_json(outp, final)
    print('\nWrote summary to', outp)
    print('FINAL:', final)

if __name__ == '__main__':
    main()
