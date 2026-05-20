#!/usr/bin/env python3
"""
Test extraction on a single small folder
"""

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
PYTHON_EXE = str((BASE_DIR / ".venv" / "Scripts" / "python.exe").resolve())

if not Path(PYTHON_EXE).exists():
    PYTHON_EXE = sys.executable

# Test folder: smallest pending_llm.json
TEST_FOLDER = BASE_DIR / "Db" / "data" / "crawl_20260506_114403"
EXTRACT_SCRIPT = BASE_DIR / "Db" / "pipeline" / "extract" / "process_pending_llm.py"

pending_file = TEST_FOLDER / "clean" / "pending_llm.json"
output_file = TEST_FOLDER / "clean" / "extracted.json"
fallback_file = TEST_FOLDER / "clean" / "extract_fallback.json"

print("="*80)
print(f"🧪 TEST EXTRACTION - Single Folder")
print("="*80)
print(f"Folder: {TEST_FOLDER.name}")
print(f"Pending file: {pending_file}")
print(f"Output file: {output_file}")
print(f"Extract script: {EXTRACT_SCRIPT}")
print("="*80)
print()

if not EXTRACT_SCRIPT.exists():
    print(f"❌ Extract script not found: {EXTRACT_SCRIPT}")
    sys.exit(1)

if not pending_file.exists():
    print(f"❌ Pending file not found: {pending_file}")
    sys.exit(1)

# Read input file size and job count
import json
with open(pending_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

job_count = len(data) if isinstance(data, list) else 0
file_size = pending_file.stat().st_size

print(f"📊 Input File:")
print(f"  - Size: {file_size} bytes ({file_size/1024:.1f} KB)")
print(f"  - Jobs: {job_count}")
print()

# Run extraction
print(f"🔄 Running extraction...")
print()

cmd = [
    PYTHON_EXE,
    str(EXTRACT_SCRIPT.resolve()),
    "--input-path", str(pending_file.resolve()),
    "--output-path", str(output_file.resolve()),
    "--fallback-path", str(fallback_file.resolve())
]

try:
    result = subprocess.run(
        cmd,
        cwd=str(BASE_DIR / "Db"),
        timeout=600
    )
    
    print()
    print("="*80)
    
    if result.returncode == 0:
        print("✅ EXTRACTION SUCCESSFUL!")
        
        # Check output file
        if output_file.exists():
            output_size = output_file.stat().st_size
            with open(output_file, 'r', encoding='utf-8') as f:
                output_data = json.load(f)
            output_count = len(output_data) if isinstance(output_data, list) else 0
            
            print(f"📊 Output File:")
            print(f"  - Size: {output_size} bytes ({output_size/1024:.1f} KB)")
            print(f"  - Jobs extracted: {output_count}")
        
        if fallback_file.exists():
            fallback_size = fallback_file.stat().st_size
            print(f"📊 Fallback File:")
            print(f"  - Size: {fallback_size} bytes ({fallback_size/1024:.1f} KB)")
        
        print("="*80)
        print("✅ Test PASSED - Code is working correctly!")
        print("="*80)
    else:
        print(f"❌ EXTRACTION FAILED (exit code: {result.returncode})")
        print("="*80)
        sys.exit(1)

except subprocess.TimeoutExpired:
    print()
    print("="*80)
    print(f"⏱️  TIMEOUT after 10 minutes")
    print("="*80)
    sys.exit(1)

except Exception as e:
    print()
    print("="*80)
    print(f"❌ ERROR: {e}")
    print("="*80)
    sys.exit(1)
