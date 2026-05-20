#!/usr/bin/env python3
"""
Run LLM extraction on all folders from extract_needed_folders.txt
Fixed version: uses no output capture to avoid encoding issues
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
import time

BASE_DIR = Path(__file__).parent.resolve()
PYTHON_EXE = str((BASE_DIR / ".venv" / "Scripts" / "python.exe").resolve())

if not Path(PYTHON_EXE).exists():
    PYTHON_EXE = sys.executable
    print(f"⚠️  .venv not found, using system Python: {PYTHON_EXE}")
else:
    print(f"✅ Using .venv Python: {PYTHON_EXE}")

# Find extract script
EXTRACT_SCRIPT = None
candidate_paths = [
    BASE_DIR / "Db" / "pipeline" / "extract" / "process_pending_llm.py",
    BASE_DIR / "Db" / "extract" / "process_pending_llm.py",
]

for candidate in candidate_paths:
    if candidate.exists():
        EXTRACT_SCRIPT = candidate
        break

if not EXTRACT_SCRIPT:
    print("❌ Error: Could not find process_pending_llm.py")
    sys.exit(1)

print(f"✅ Found extract script: {EXTRACT_SCRIPT}\n")

# Load extract_needed_folders.txt
EXTRACT_LIST_FILE = BASE_DIR / "extract_needed_folders.txt"
if not EXTRACT_LIST_FILE.exists():
    print(f"❌ Error: {EXTRACT_LIST_FILE} not found")
    sys.exit(1)

with open(EXTRACT_LIST_FILE, 'r') as f:
    crawl_paths = [line.strip() for line in f if line.strip()]

print(f"📋 Loaded {len(crawl_paths)} folders to process\n")
print(f"{'='*80}")

success_count = 0
skip_count = 0
error_count = 0
failed_folders = []
start_time = datetime.now()

for idx, crawl_path in enumerate(crawl_paths, 1):
    # Convert backslash to forward slash for consistency
    crawl_path = crawl_path.replace('\\', '/')
    crawl_folder = BASE_DIR / crawl_path
    
    if not crawl_folder.exists():
        skip_count += 1
        continue
    
    clean_dir = crawl_folder / "clean"
    pending_file = clean_dir / "pending_llm.json"
    extracted_file = clean_dir / "extracted.json"
    
    # Skip if pending_llm doesn't exist
    if not pending_file.exists():
        skip_count += 1
        continue
    
    # Check if pending_llm is empty
    try:
        with open(pending_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not data or (isinstance(data, list) and len(data) == 0):
            skip_count += 1
            continue
    except:
        skip_count += 1
        continue
    
    # Check if already extracted
    if extracted_file.exists():
        try:
            size = extracted_file.stat().st_size
            if size > 100:  # Has some data
                skip_count += 1
                continue
        except:
            pass
    
    # Run extraction
    elapsed = (datetime.now() - start_time).total_seconds() / 60
    print(f"[{idx:3d}/{len(crawl_paths)}] [{elapsed:6.1f}m] {crawl_folder.name}: ", end='', flush=True)
    
    output_path = extracted_file
    fallback_path = clean_dir / "extract_fallback.json"
    
    env = os.environ.copy()
    existing_py = env.get('PYTHONPATH', '')
    prepend_paths = os.pathsep.join([str(BASE_DIR / "Db"), str(BASE_DIR)])
    env['PYTHONPATH'] = prepend_paths + (os.pathsep + existing_py if existing_py else '')
    
    try:
        cmd = [
            PYTHON_EXE,
            str(EXTRACT_SCRIPT.resolve()),
            "--input-path", str(pending_file.resolve()),
            "--output-path", str(output_path.resolve()),
            "--fallback-path", str(fallback_path.resolve())
        ]
        
        # Run without capturing output - uses /dev/null equivalent
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR / "Db"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3600  # 1 hour per folder
        )
        
        if result.returncode == 0 and output_path.exists():
            print("✅")
            success_count += 1
        else:
            print(f"❌ (exit: {result.returncode})")
            error_count += 1
            failed_folders.append((crawl_folder.name, f"Exit code: {result.returncode}"))
    
    except subprocess.TimeoutExpired:
        print("⏱️ ")
        error_count += 1
        failed_folders.append((crawl_folder.name, "Timeout (1h exceeded)"))
    
    except Exception as e:
        print(f"❌ ({str(e)[:30]})")
        error_count += 1
        failed_folders.append((crawl_folder.name, str(e)[:50]))

elapsed_time = (datetime.now() - start_time).total_seconds() / 60
print(f"{'='*80}")
print(f"✅ Complete! Total time: {elapsed_time:.1f} minutes")
print(f"{'='*80}")
print(f"  Successful: {success_count}")
print(f"  Skipped:   {skip_count}")
print(f"  Errors:    {error_count}")
print(f"  Total:     {len(crawl_paths)}")
print(f"{'='*80}\n")

# Save summary
summary = {
    'timestamp': datetime.now().isoformat(),
    'total_folders': len(crawl_paths),
    'successful': success_count,
    'skipped': skip_count,
    'errors': error_count,
    'elapsed_minutes': elapsed_time,
    'failed_folders': [{'name': name, 'reason': reason} for name, reason in failed_folders]
}

summary_file = BASE_DIR / "extract_batch_summary.json"
with open(summary_file, 'w') as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print(f"✅ Summary saved to: {summary_file}")

if error_count == 0:
    print(f"✅ ALL EXTRACTIONS SUCCESSFUL!")
    sys.exit(0)
else:
    print(f"\n⚠️  {error_count} folders had errors (see summary file)")
    sys.exit(1)
