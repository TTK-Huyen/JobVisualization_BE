#!/usr/bin/env python3
"""
Run LLM extraction step on folders listed in extract_needed_folders.txt
Processes pending_llm.json files and generates extracted.json outputs.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

# ============================================================================
# CONFIGURATION
# ============================================================================

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
    BASE_DIR / "pipeline" / "extract" / "process_pending_llm.py",
    BASE_DIR / "extract" / "process_pending_llm.py",
]

for candidate in candidate_paths:
    if candidate.exists():
        EXTRACT_SCRIPT = candidate
        break

if not EXTRACT_SCRIPT:
    print("❌ Error: Could not find process_pending_llm.py")
    print(f"   Searched in: {[str(p) for p in candidate_paths]}")
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

# ============================================================================
# EXTRACTION LOOP
# ============================================================================

success_count = 0
skip_count = 0
error_count = 0
failed_folders = []

for idx, crawl_path in enumerate(crawl_paths, 1):
    # Convert backslash to forward slash for consistency
    crawl_path = crawl_path.replace('\\', '/')
    crawl_folder = BASE_DIR / crawl_path
    
    if not crawl_folder.exists():
        print(f"[{idx}/{len(crawl_paths)}] ⏭️  {crawl_folder.name}: FOLDER NOT FOUND")
        skip_count += 1
        continue
    
    clean_dir = crawl_folder / "clean"
    pending_file = clean_dir / "pending_llm.json"
    extracted_file = clean_dir / "extracted.json"
    
    # Skip if pending_llm doesn't exist or is empty
    if not pending_file.exists():
        print(f"[{idx}/{len(crawl_paths)}] ⏭️  {crawl_folder.name}: NO pending_llm.json")
        skip_count += 1
        continue
    
    try:
        with open(pending_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not data or (isinstance(data, list) and len(data) == 0):
            print(f"[{idx}/{len(crawl_paths)}] ⏭️  {crawl_folder.name}: pending_llm.json is empty")
            skip_count += 1
            continue
    except (json.JSONDecodeError, IOError) as e:
        print(f"[{idx}/{len(crawl_paths)}] ⏭️  {crawl_folder.name}: ERROR reading pending_llm.json - {e}")
        skip_count += 1
        continue
    
    # Run extraction
    print(f"[{idx}/{len(crawl_paths)}] 🔄 {crawl_folder.name}: Processing...", end='', flush=True)
    
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
        
        # Don't capture output - just run the process silently
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR / "Db"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1800  # 30 minutes
        )
        
        if result.returncode == 0:
            # Check if output was created
            if output_path.exists():
                print(" ✅")
                success_count += 1
            else:
                print(" ⚠️  (no output file created)")
                error_count += 1
                failed_folders.append((crawl_folder.name, "No output file created"))
        else:
            print(f" ❌ (exit code: {result.returncode})")
            error_count += 1
            failed_folders.append((crawl_folder.name, f"Exit code: {result.returncode}"))
    
    except subprocess.TimeoutExpired:
        print(f" ⏱️  (timeout)")
        error_count += 1
        failed_folders.append((crawl_folder.name, "Timeout (30 min exceeded)"))
    
    except Exception as e:
        print(f" ❌ ({str(e)[:50]})")
        error_count += 1
        failed_folders.append((crawl_folder.name, str(e)[:100]))

# ============================================================================
# SUMMARY
# ============================================================================

print(f"\n{'='*80}")
print(f"📊 EXTRACTION COMPLETE")
print(f"{'='*80}")
print(f"✅ Successful: {success_count}")
print(f"⏭️  Skipped:   {skip_count}")
print(f"❌ Errors:    {error_count}")
print(f"{'='*80}\n")

if failed_folders:
    print(f"Failed folders ({len(failed_folders)}):")
    for folder_name, reason in failed_folders[:20]:
        print(f"  - {folder_name}: {reason}")
    if len(failed_folders) > 20:
        print(f"  ... and {len(failed_folders) - 20} more")

# Save summary
summary = {
    'timestamp': datetime.now().isoformat(),
    'total_folders': len(crawl_paths),
    'successful': success_count,
    'skipped': skip_count,
    'errors': error_count,
    'failed_folders': [{'name': name, 'reason': reason} for name, reason in failed_folders]
}

summary_file = BASE_DIR / "extract_run_summary.json"
with open(summary_file, 'w') as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print(f"✅ Summary saved to: {summary_file}")
