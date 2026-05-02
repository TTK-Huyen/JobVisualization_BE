"""create_daily_batches.py
Split a pending LLM JSON file into micro-batches (default size 5).

Usage:
  python create_daily_batches.py --input data/.../pending_llm.json --outdir data/.../clean/batches --size 5

Creates files: pending_llm_batch_001.json, ... each with up to `size` jobs.
"""
from __future__ import annotations
import json, pathlib, argparse

BASE = pathlib.Path(__file__).resolve().parent

def chunked(it, size):
    for i in range(0, len(it), size):
        yield it[i:i+size]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', '-i', help='pending input json', default=str(BASE / 'data' / 'crawl_20260430_154707' / 'clean' / 'pending_llm.json'))
    p.add_argument('--outdir', '-o', help='batches output dir', default=str(BASE / 'data' / 'crawl_20260430_154707' / 'clean' / 'batches'))
    p.add_argument('--size', '-s', type=int, default=5, help='max jobs per batch')
    args = p.parse_args()

    inp = pathlib.Path(args.input)
    outdir = pathlib.Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    try:
        jobs = json.loads(inp.read_text(encoding='utf-8') or '[]')
    except Exception as e:
        print('Failed to read input:', e)
        return

    chunks = list(chunked(jobs, args.size))
    width = max(3, len(str(len(chunks))))
    for idx, chunk in enumerate(chunks, start=1):
        fname = f'pending_llm_batch_{idx:0{width}d}.json'
        target = outdir / fname
        target.write_text(json.dumps(chunk, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Wrote', target)

    print('Created', len(chunks), 'batches in', outdir)

if __name__ == '__main__':
    main()
