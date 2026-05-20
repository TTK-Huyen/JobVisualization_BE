"""
Kiểm tra tất cả crawl folders, nếu đã có pending_llm.json trong folder clean thì giữ nguyên,
nếu không thì chạy bước clean step 1 (regex), input là jobs_combined.json trong folder raw,
output là pending_llm.json trong folder clean.
"""
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

BASE_DIR = Path(__file__).resolve().parent / "Db"
DATA_DIR = BASE_DIR / "data"
PIPELINE_DIR = BASE_DIR / "pipeline"

# Use .venv Python executable if available
VENV_PYTHON = (BASE_DIR.parent / ".venv" / "Scripts" / "python.exe").resolve()
if VENV_PYTHON.exists():
    PYTHON_EXE = str(VENV_PYTHON)
    print(f"✓ Using .venv Python: {PYTHON_EXE}")
else:
    PYTHON_EXE = sys.executable
    print(f"⚠ .venv not found, using system Python: {PYTHON_EXE}")

def log(msg):
    """Simple logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def resolve_pipeline_path(*parts: str) -> Path:
    """Return the pipeline-prefixed path if it exists, otherwise fallback to BASE_DIR path."""
    candidate = PIPELINE_DIR.joinpath(*parts)
    if candidate.exists():
        return candidate
    alt = BASE_DIR.joinpath(*parts)
    if alt.exists():
        return alt
    return None

def find_clean_script() -> Path:
    """Find clean_process.py in pipeline or top-level 2_clean_data"""
    clean_script = resolve_pipeline_path("clean", "2_clean_data", "clean_process.py")
    if clean_script is None or not clean_script.exists():
        clean_script = resolve_pipeline_path("2_clean_data", "clean_process.py")
    return clean_script

def get_clean_dir() -> Path:
    """Get the 2_clean_data directory"""
    clean_dir = resolve_pipeline_path("clean", "2_clean_data")
    if clean_dir is None or not clean_dir.exists():
        clean_dir = resolve_pipeline_path("2_clean_data")
    return clean_dir

def run_clean_step(raw_file: Path, output_file: Path, clean_script: Path, clean_dir: Path, timeout=600) -> bool:
    """Run clean_process.py step 1"""
    if not clean_script.exists():
        log(f"  ✗ Clean script not found: {clean_script}")
        return False
    
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [PYTHON_EXE, str(clean_script.resolve()), str(raw_file), "--step", "1", "--output", str(output_file)]
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(clean_dir),
            text=True,
            encoding='utf-8',
            timeout=timeout
        )
        
        if result.returncode == 0:
            log(f"  ✓ Clean step 1 completed")
            return True
        else:
            log(f"  ✗ Clean step 1 failed (exit code: {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        log(f"  ✗ Clean step 1 timeout")
        return False
    except Exception as e:
        log(f"  ✗ Clean step 1 error: {e}")
        return False

def main():
    if not DATA_DIR.exists():
        log(f"❌ Data directory not found: {DATA_DIR}")
        return
    
    clean_script = find_clean_script()
    clean_dir = get_clean_dir()
    
    if clean_script is None or not clean_script.exists():
        log(f"❌ Clean script not found")
        return
    
    log(f"Clean script: {clean_script}")
    log(f"Clean directory: {clean_dir}")
    print()
    
    # Get all crawl folders
    crawl_folders = sorted([d for d in DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("crawl_")])
    
    processed = 0
    skipped_has_pending = 0
    skipped_no_combined = 0
    cleaned = 0
    
    for crawl_folder in crawl_folders:
        raw_dir = crawl_folder / "raw"
        clean_dir_instance = crawl_folder / "clean"
        
        combined_file = raw_dir / "jobs_combined.json"
        pending_file = clean_dir_instance / "pending_llm.json"
        
        # Check if pending_llm.json already exists
        if pending_file.exists():
            skipped_has_pending += 1
            continue
        
        # Check if jobs_combined.json exists
        if not combined_file.exists():
            skipped_no_combined += 1
            continue
        
        # Found a candidate for cleaning
        processed += 1
        print(f"[{processed}] {crawl_folder.name}")
        
        if run_clean_step(combined_file, pending_file, clean_script, clean_dir):
            cleaned += 1
            # Verify output was created
            if pending_file.exists():
                file_size = pending_file.stat().st_size
                log(f"  Output: {pending_file.name} ({file_size:,} bytes)")
            else:
                log(f"  ⚠️ Output file not created: {pending_file}")
        else:
            log(f"  ✗ SKIPPED: Clean step 1 failed")
        print()
    
    log("=" * 70)
    log("SUMMARY:")
    log(f"  Total crawl folders: {len(crawl_folders)}")
    log(f"  Skipped (already has pending_llm.json): {skipped_has_pending}")
    log(f"  Skipped (no jobs_combined.json): {skipped_no_combined}")
    log(f"  Candidates checked: {processed}")
    log(f"  Successfully cleaned: {cleaned}")
    log("=" * 70)

if __name__ == '__main__':
    main()
