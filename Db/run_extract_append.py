#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
VENV_PY = (BASE_DIR.parent / '.venv' / 'Scripts' / 'python.exe')
PYTHON_EXE = str(VENV_PY) if VENV_PY.exists() else sys.executable


def load_json_list(p: Path):
    if not p.exists():
        return []
    text = p.read_text(encoding='utf-8-sig').strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except Exception:
        # try JSON lines
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
        return items
    if isinstance(obj, list):
        return obj
    # if dict with top-level list field
    for key in ('jobs', 'items', 'data', 'results'):
        if isinstance(obj.get(key), list):
            return obj.get(key)
    return [obj]


def atomic_write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.parent / (p.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        os.replace(str(tmp), str(p))
    except Exception:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    if len(sys.argv) < 2:
        print("Usage: run_extract_append.py <pending_input.json>")
        return 2

    input_path = Path(sys.argv[1])
    if not input_path.is_absolute():
        input_path = BASE_DIR / input_path
    if not input_path.exists():
        print(f"Input not found: {input_path}")
        return 2

    out_path = input_path.parent / 'extracted.json'
    temp_out = out_path.parent / (out_path.name + '.new')

    old_jobs = load_json_list(out_path)
    print(f"Existing extracted: {len(old_jobs)} items")

    # Build command to run the extractor
    extractor = BASE_DIR / 'pipeline' / 'extract' / 'process_pending_llm.py'
    if not extractor.exists():
        extractor = BASE_DIR.parent / 'pipeline' / 'extract' / 'process_pending_llm.py'
    if not extractor.exists():
        extractor = BASE_DIR.parent / 'process_pending_llm.py'
    if not extractor.exists():
        print(f"Extractor not found: attempted {extractor}")
        return 3

    timeout = int(os.getenv('ETL_LLM_TIMEOUT', os.getenv('ETL_LLM_TIMEOUT', '1800')))
    cmd = [PYTHON_EXE, str(extractor), '--input-path', str(input_path.resolve()), '--output-path', str(temp_out.resolve())]
    print("Running extractor:", ' '.join(cmd))

    try:
        rc = subprocess.run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"Extractor timed out after {timeout}s")
        rc = None

    # Determine where extractor wrote
    new_jobs = []
    if temp_out.exists():
        new_jobs = load_json_list(temp_out)
    elif out_path.exists():
        # extractor may have written directly
        new_jobs = load_json_list(out_path)

    print(f"New extracted: {len(new_jobs)} items")

    if not new_jobs:
        print("No new items to append. Exiting.")
        return 0

    merged = old_jobs + new_jobs
    atomic_write(out_path, merged)
    print(f"Wrote merged extracted file: {out_path} ({len(merged)} total items)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
