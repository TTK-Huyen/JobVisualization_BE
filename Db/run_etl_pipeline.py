#!/usr/bin/env python3
"""
ETL PIPELINE ORCHESTRATOR
Điều hướng 3 bước chính: Crawl -> Clean -> Import
Gọi các script chính trong từng folder
Kiến trúc Hybrid:
  - Crawlers → 1_crawl_data/crawl_data/output/ (tạm thời)
  - Clean → data/crawl_YYYYMMDD/clean/ (lưu trữ)
  - Import → đọc từ data/crawl_YYYYMMDD/clean/
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

# ============================================================================
# CONFIGURATION
# ============================================================================
BASE_DIR = Path(__file__).parent

# Use .venv Python executable if available
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
if VENV_PYTHON.exists():
    PYTHON_EXE = str(VENV_PYTHON)
    print(f"✓ Using .venv Python: {PYTHON_EXE}")
else:
    PYTHON_EXE = sys.executable
    print(f"⚠ .venv not found, using system Python: {PYTHON_EXE}")

# Import config
try:
    from etl_config import JOB_LIMITS, CRAWLER_TIMEOUT, CLEAN_TIMEOUT, IMPORT_TIMEOUT
except ImportError:
    JOB_LIMITS = {"itviec": 1, "linkedin": 1, "careerviet": 1, "vietnamworks": 1}
    CRAWLER_TIMEOUT = CLEAN_TIMEOUT = IMPORT_TIMEOUT = 600

# Date-based folder for archival
RUN_DATE = datetime.now().strftime("%Y%m%d")
DATA_FOLDER = BASE_DIR / "data" / f"crawl_{RUN_DATE}"
RAW_FOLDER = DATA_FOLDER / "raw"
CLEAN_FOLDER = DATA_FOLDER / "clean"

# ============================================================================
# HELPER
# ============================================================================
def log(msg):
    """Simple logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def run_step(name, script_path, args=None, timeout=600, cwd=None, env=None, is_batch=False):
    """Execute a script (Python or Batch) as a step"""
    log(f"{name}...")
    
    if not script_path.exists():
        log(f"{script_path} không tồn tại")
        return False
    
    # For .bat files on Windows, use cmd /c
    if is_batch or str(script_path).endswith('.bat'):
        cmd = ['cmd', '/c', str(script_path)]
    else:
        cmd = [PYTHON_EXE, str(script_path)]
    
    if args:
        cmd.extend(args)
    
    # Merge environment variables
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd or script_path.parent),
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=timeout,
            env=run_env
        )
        
        # Print output
        if result.stdout:
            print(result.stdout)
        if result.stderr and result.returncode != 0:
            print(result.stderr)
        
        if result.returncode == 0:
            log(f"{name} thành công\n")
            return True
        else:
            log(f"{name} thất bại\n")
            return False
    except subprocess.TimeoutExpired:
        log(f"{name} timeout\n")
        return False
    except Exception as e:
        log(f"{name} lỗi: {e}\n")
        return False

# ============================================================================
# MAIN
# ============================================================================
def main():
    log("=" * 80)
    log("ETL PIPELINE START")
    log(f"Run Date: {RUN_DATE}")
    log(f"Archive: {DATA_FOLDER}")
    log("=" * 80 + "\n")
    
    # Read step control flags from environment variables
    step_crawl = os.environ.get("STEP_CRAWL", "true").lower() in ("true", "1", "yes")
    step_merge = os.environ.get("STEP_MERGE", "true").lower() in ("true", "1", "yes")
    step_clean = os.environ.get("STEP_CLEAN", "true").lower() in ("true", "1", "yes")
    step_import = os.environ.get("STEP_IMPORT", "true").lower() in ("true", "1", "yes")
    
    log(f"Steps: CRAWL={step_crawl}, MERGE={step_merge}, CLEAN={step_clean}, IMPORT={step_import}\n")
    
    start = datetime.now()
    
    # Create archive folders
    RAW_FOLDER.mkdir(parents=True, exist_ok=True)
    CLEAN_FOLDER.mkdir(parents=True, exist_ok=True)
    
    crawl_ok = True
    clean_ok = True
    import_ok = True
    
    # -------- STEP 1: CRAWL --------
    if step_crawl:
        log("STEP 1: CRAWL DATA")
        
        # Prepare environment variables for crawlers
        crawl_env = os.environ.copy()  # Inherit current env
        crawl_env.update({
            "OUTPUT_FOLDER": str(RAW_FOLDER),
            "RAW_DATA_FOLDER": str(RAW_FOLDER),
            # Pass job limits to crawlers - use correct env var names
            "ITVIEC_MAX_JOBS": str(JOB_LIMITS.get("itviec", 50)),
            "LINKEDIN_MAX_JOBS": str(JOB_LIMITS.get("linkedin", 100)),
            "CAREERVIET_MAX_JOBS": str(JOB_LIMITS.get("careerviet", 50)),
            "VNWORKS_MAX_JOBS": str(JOB_LIMITS.get("vietnamworks", 50))
        })
        
        log(f"Job Limits: iTviec={JOB_LIMITS.get('itviec', 50)}, LinkedIn={JOB_LIMITS.get('linkedin', 100)}, CareerViet={JOB_LIMITS.get('careerviet', 50)}, VietnamWorks={JOB_LIMITS.get('vietnamworks', 50)}")
        
        # Call daily runners directly (not via .bat) to preserve environment variables
        crawlers = [
            ("ITviec", "crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py"),
            ("LinkedIn", "crawl_data/crawl-linkedin-jobs/scripts/daily_linkedin_runner.py"),
            ("CareerViet", "crawl_data/crawl-careerviet-jobs/scripts/daily_careerviet_runner.py"),
            ("VietnamWorks", "crawl_data/crawl-vietnamwork-jobs/scripts/daily_vietnamworks_runner.py"),
        ]
        
        crawl_dir = BASE_DIR / "1_crawl_data"
        
        for crawler_name, crawler_path in crawlers:
            crawler_script = crawl_dir / crawler_path
            if crawler_script.exists():
                log(f"Running {crawler_name} crawler...")
                if not run_step(f"{crawler_name} Crawler", crawler_script, timeout=CRAWLER_TIMEOUT, cwd=crawl_dir, env=crawl_env):
                    log(f"⚠️  {crawler_name} crawler failed or returned no jobs")
            else:
                log(f"⚠️  {crawler_name} crawler not found: {crawler_script}")
        
        # Merge outputs
        if step_merge:
            merge_script = crawl_dir / "merge_daily_outputs.py"
            if merge_script.exists():
                log("Merging crawler outputs...")
                crawl_ok = run_step("Merge Outputs", merge_script, timeout=CRAWLER_TIMEOUT, cwd=crawl_dir, env=crawl_env)
            else:
                log("⚠️  Merge script not found")
                crawl_ok = False
            
            # [NEW] Normalize schema after merge
            if crawl_ok:
                log("Normalizing crawler schemas...")
                normalize_script = crawl_dir / "normalize_schema.py"
                if normalize_script.exists():
                    merged_file = crawl_dir / "crawl_data" / "output" / "jobs_combined.json"
                    crawl_ok = run_step("Normalize Schema", normalize_script, timeout=CRAWLER_TIMEOUT, cwd=BASE_DIR, env=crawl_env)
                else:
                    log("⚠️  Normalize script not found")
                    crawl_ok = False
        else:
            log("Skipping MERGE (STEP_MERGE=false)")
        
        if not crawl_ok:
            log("Crawl failed")
    else:
        log("Skipping CRAWL (STEP_CRAWL=false)\n")
    
    # -------- STEP 2: CLEAN --------
    if step_clean:
        log("STEP 2: CLEAN DATA")
        clean_script = BASE_DIR / "2_clean_data" / "clean_process.py"
        
        # Use normalized input if it exists, otherwise use raw combined output from data/raw
        normalized_file = RAW_FOLDER / "jobs_normalized.json"
        combined_file = RAW_FOLDER / "jobs_combined.json"
        
        if normalized_file.exists():
            input_for_clean = str(normalized_file)
            log(f"Using normalized input: {normalized_file.name}")
        elif combined_file.exists():
            input_for_clean = str(combined_file)
            log(f"Using raw combined input: {combined_file.name}")
        else:
            log("❌ No input file found for cleaning")
            clean_ok = False
            input_for_clean = ""
        
        if input_for_clean:
            # Pass input/output paths to clean process
            clean_args = [
                "--input", input_for_clean,
                "--output", str(CLEAN_FOLDER / f"clean_data_final_{RUN_DATE}.json")
            ]
            
            clean_ok = run_step("CLEAN", clean_script, args=clean_args, timeout=CLEAN_TIMEOUT, cwd=BASE_DIR / "2_clean_data")
            
            if not clean_ok:
                log("Clean failed")
    else:
        log("Skipping CLEAN (STEP_CLEAN=false)\n")
    
    # -------- STEP 3: IMPORT --------
    if step_import:
        log("STEP 3: IMPORT TO DATABASE")
        import_script = BASE_DIR / "3_mapping_data_db" / "import_to_db.py"
        
        # Pass cleaned data path to import script
        import_args = [
            "--input", str(CLEAN_FOLDER / f"clean_data_final_{RUN_DATE}.json")
        ]
        
        import_ok = run_step("IMPORT", import_script, args=import_args, timeout=IMPORT_TIMEOUT, cwd=BASE_DIR / "3_mapping_data_db")
        
        if not import_ok:
            log("Import failed")
    else:
        log("Skipping IMPORT (STEP_IMPORT=false)\n")
    
    # -------- SUMMARY --------
    log("=" * 80)
    log("SUMMARY")
    log("=" * 80)
    log(f"Crawl  : {'Done' if crawl_ok else 'Skipped/Failed'}")
    log(f"Clean  : {'Done' if clean_ok else 'Skipped/Failed'}")
    log(f"Import : {'Done' if import_ok else 'Skipped/Failed'}")
    
    duration = datetime.now() - start
    log(f"Duration: {duration}")
    log("=" * 80)
    
    return crawl_ok and clean_ok and import_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
