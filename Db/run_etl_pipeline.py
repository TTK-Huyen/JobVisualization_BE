#!/usr/bin/env python3
"""
ETL PIPELINE ORCHESTRATOR
Điều hướng 3 bước chính: Crawl -> Clean -> Import
Gọi các script chính trong từng folder
Kiến trúc Hybrid:
  - Crawlers → 1_crawl_data/crawl_data/output/ (tạm thời)
  - Clean → data/crawl_YYYYMMDD/clean/ (lưu trữ)
  - Import → đọc từ data/crawl_YYYYMMDD/clean/

Usage:
  python run_etl_pipeline.py                           # Auto detect latest crawl
  python run_etl_pipeline.py --input path/to/file.json # Use custom input file
  python run_etl_pipeline.py --crawl-only              # Only run crawl step
  python run_etl_pipeline.py --clean-only              # Only run clean step
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, date
from dotenv import load_dotenv

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# ============================================================================
# LOAD ENV CONFIGURATION
# ============================================================================
BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)
print(f"✓ Loaded .env from: {ENV_FILE}")

# ============================================================================
# CONFIGURATION
# ============================================================================

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
    from input import (
        JOB_LIMITS,
        JOBS_PER_KEYWORD,
        KEYWORD_SELECTION_CONFIG,
        PIPELINE_STEPS,
        CRAWLER_TIMEOUTS,
        print_config,
        get_api_key,
        print_api_status,
    )
    print("\n" + "="*80)
    print("✅ Config loaded from input package")
    print("="*80)
    print_config()
    print_api_status()
    print("="*80 + "\n")
except ImportError as e:
    print(f"❌ Error importing from input package: {e}")
    print("Fallback to default values")
    JOB_LIMITS = {"itviec": 1, "linkedin": 1, "careerviet": 1, "vietnamworks": 1}
    JOBS_PER_KEYWORD = 3
    KEYWORD_SELECTION_CONFIG = {}
    PIPELINE_STEPS = {"crawl": True, "clean": True, "import": True}
    CRAWLER_TIMEOUTS = {"itviec": 600, "linkedin": 300, "careerviet": 600, "vietnamworks": 600}

# Timeouts (fixed)
CRAWLER_TIMEOUT = 1200  # 20 phút
CLEAN_TIMEOUT = 600     # 10 phút
IMPORT_TIMEOUT = 900    # 15 phút

# ============================================================================
# ETL PIPELINE CONFIG - Load from .env
# ============================================================================
ETL_CONFIG = {
    "input_file": os.getenv("ETL_INPUT_FILE", ""),  # Custom input file (empty = auto-detect)
    "batch_size": int(os.getenv("ETL_CLEAN_BATCH_SIZE", "60")),  # Batch size for CLEAN step
    "max_threads": int(os.getenv("ETL_MAX_THREADS", "30")),  # Max parallel threads for LLM extraction
    "confidence_threshold": float(os.getenv("ETL_CONFIDENCE_THRESHOLD", "0.7")),  # Min confidence for skills/benefits
}

print(f"\n🔥 ETL CONFIG (from .env):")
print(f"  → Input file: {ETL_CONFIG['input_file'] or 'AUTO-DETECT'}")
print(f"  → Batch size: {ETL_CONFIG['batch_size']}")
print(f"  → Max threads: {ETL_CONFIG['max_threads']}")
print(f"  → Confidence threshold: {ETL_CONFIG['confidence_threshold']}")
print()

# Date-time-based folder for archival (avoid overwrite)
RUN_DATE = datetime.now().strftime("%Y%m%d_%H%M%S")
DATA_FOLDER = BASE_DIR / "data" / f"crawl_{RUN_DATE}"
RAW_FOLDER = DATA_FOLDER / "raw"
CLEAN_FOLDER = DATA_FOLDER / "clean"
FALLBACK_FOLDER = DATA_FOLDER / "fallback"
LOGS_FOLDER = DATA_FOLDER / "logs"

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
        # Stream output in realtime instead of buffering (no capture_output)
        result = subprocess.run(
            cmd,
            cwd=str(cwd or script_path.parent),
            text=True,
            encoding='utf-8',
            timeout=timeout,
            env=run_env
        )
        
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


def _safe_delete(path: Path) -> bool:
    """Delete a file if it exists. Returns True on success or when already absent."""
    try:
        if path.exists() and path.is_file():
            path.unlink()
            log(f"[CLEANUP] Deleted {path}")
        return True
    except Exception as exc:
        log(f"[CLEANUP] Could not delete {path}: {exc}")
        return False


def cleanup_retention_artifacts():
    """Keep only long-lived artifacts after a successful full pipeline run."""
    cleanup_ok = True

    # Clean folder: keep only the final import-ready file.
    if CLEAN_FOLDER.exists():
        for item in sorted(CLEAN_FOLDER.rglob("*"), reverse=True):
            if item.is_file() and item.name != "import_ready.json":
                cleanup_ok = _safe_delete(item) and cleanup_ok
            elif item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    pass

    # Keep logs/ intact for debugging and history.
    # No deletion is performed inside LOGS_FOLDER.

    # Historical temp files that may appear at the crawl archive root.
    root_cleanup_patterns = [
        DATA_FOLDER / "output_1_cleaned.json",
        DATA_FOLDER / "output_2_sections.json",
    ]
    for item in root_cleanup_patterns:
        cleanup_ok = _safe_delete(item) and cleanup_ok

    for item in sorted(DATA_FOLDER.rglob("batch_*.json"), reverse=True):
        if LOGS_FOLDER in item.parents:
            continue
        cleanup_ok = _safe_delete(item) and cleanup_ok

    for item in sorted(DATA_FOLDER.rglob("retry_r*.json"), reverse=True):
        if LOGS_FOLDER in item.parents:
            continue
        cleanup_ok = _safe_delete(item) and cleanup_ok

    return cleanup_ok


def estimate_and_display_runtime():
    """Calculate and display estimated runtime for today's pipeline"""
    try:
        # Use actual config from input package instead of hardcoded values
        if KEYWORD_SELECTION_CONFIG:
            # Extract tier counts from loaded config
            tier1_count = KEYWORD_SELECTION_CONFIG.get('tier1', {}).get('num_to_crawl', 0)
            tier2_count = KEYWORD_SELECTION_CONFIG.get('tier2', {}).get('num_to_crawl', 0)
            tier3_count = KEYWORD_SELECTION_CONFIG.get('tier3', {}).get('num_to_crawl', 0)
        else:
            # Fallback: Load today's keywords
            config_path = BASE_DIR / "1_crawl_data/crawl_data/keywords_daily.json"
            if not config_path.exists():
                return
            
            with open(config_path, encoding='utf-8') as f:
                cfg = json.load(f)
            
            # Simplified keyword picking logic
            tier_1 = cfg.get('tier_1', [])
            tier_2 = cfg.get('tier_2', [])
            tier_3 = cfg.get('tier_3', [])
            doy = date.today().timetuple().tm_yday
            
            # Estimate tier selections
            tier1_count = min(8, len(tier_1))
            tier2_count = min(2, len(tier_2)) if len(tier_2) >= 2 else 0
            tier3_count = 1 if tier_3 and (doy % 3 == 0) else 0
        
        total_keywords = tier1_count + tier2_count + tier3_count
        
        # Load jobs per keyword from input config
        tier1_jobs = tier1_count * JOBS_PER_KEYWORD
        tier2_jobs = tier2_count * JOBS_PER_KEYWORD
        tier3_jobs = tier3_count * JOBS_PER_KEYWORD
        total_jobs = tier1_jobs + tier2_jobs + tier3_jobs
        
        # Estimate times
        crawl_time = 46  # seconds (from performance analysis)
        merge_time = 6   # seconds
        clean_time = 5 + (total_jobs * 0.55)  # ~0.55s per job
        
        log("\n" + "=" * 85)
        log("⏱️  ESTIMATED RUNTIME FOR TODAY'S CRAWL+CLEAN")
        log("=" * 85)
        log(f"\n📊 CONFIG:")
        log(f"   Keywords: {total_keywords} ({tier1_count}×tier1 + {tier2_count}×tier2 + {tier3_count}×tier3)")
        log(f"   Total jobs: ~{total_jobs} ({tier1_jobs}+{tier2_jobs}+{tier3_jobs})")
        
        log(f"\n⏱️  TIMELINE:")
        log(f"   🔍 CRAWL (parallel):     ~{int(crawl_time)}s")
        log(f"   📦 MERGE (sequential):   ~{int(merge_time)}s")
        log(f"   🧹 CLEAN (sequential):   ~{int(clean_time):.0f}s")
        log(f"   ────────────────────────────────")
        log(f"   TOTAL EXECUTION:        ~{int(crawl_time + merge_time + clean_time)}s ({(crawl_time + merge_time + clean_time)/60:.1f}m)")
        log(f"\n" + "=" * 85 + "\n")
        
    except Exception as e:
        pass  # Silently fail if estimation can't be done


# ============================================================================
# MAIN
# ============================================================================
def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="ETL Pipeline: Crawl → Clean → Import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_etl_pipeline.py                                  # Auto detect latest crawl
  python run_etl_pipeline.py --input path/to/jobs.json       # Use custom input file for clean step
  python run_etl_pipeline.py --crawl-only                     # Only run crawl + merge
  python run_etl_pipeline.py --clean-only --input jobs.json   # Only run clean step with custom input
        """
    )
    parser.add_argument(
        "--input", 
        type=str,
        default=ETL_CONFIG["input_file"] if ETL_CONFIG["input_file"] else None,
        help=f"Custom input file for CLEAN step (default: auto-detect, or use ETL_INPUT_FILE from .env)"
    )
    parser.add_argument(
        "--crawl-only", 
        action="store_true", 
        help="Only run CRAWL step (skip CLEAN and IMPORT)"
    )
    parser.add_argument(
        "--clean-only", 
        action="store_true", 
        help="Only run CLEAN step (requires --input or auto-detection)"
    )
    parser.add_argument(
        "--import-only", 
        action="store_true", 
        help="Only run IMPORT step"
    )
    
    args = parser.parse_args()
    
    # Override PIPELINE_STEPS based on command line flags
    global PIPELINE_STEPS
    if args.crawl_only:
        PIPELINE_STEPS = {"crawl": True, "clean": False, "import": False}
    elif args.clean_only:
        PIPELINE_STEPS = {"crawl": False, "clean": True, "import": False}
    elif args.import_only:
        PIPELINE_STEPS = {"crawl": False, "clean": False, "import": True}
    
    log("=" * 80)
    log("ETL PIPELINE START")
    log(f"Run Date: {RUN_DATE}")
    log(f"Archive: {DATA_FOLDER}")
    log("=" * 80 + "\n")
    
    # Display estimated runtime
    estimate_and_display_runtime()
    
    # Read step control flags from PIPELINE_STEPS config (not environment variables)
    step_crawl = PIPELINE_STEPS.get("crawl", True)
    step_clean = PIPELINE_STEPS.get("clean", True)
    step_import = PIPELINE_STEPS.get("import", True)
    
    log(f"Steps: CRAWL (incl. MERGE)={step_crawl}, CLEAN={step_clean}, IMPORT={step_import}\n")
    
    start = datetime.now()
    
    # Create archive folders
    RAW_FOLDER.mkdir(parents=True, exist_ok=True)
    CLEAN_FOLDER.mkdir(parents=True, exist_ok=True)
    FALLBACK_FOLDER.mkdir(parents=True, exist_ok=True)
    LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
    
    crawl_ok = True
    clean_ok = True
    import_ok = True
    
    # -------- STEP 1: CRAWL --------
    if step_crawl:
        log("STEP 1: CRAWL DATA")
        
        # Prepare environment variables for crawlers
        crawl_env = os.environ.copy()  # Inherit current env
        crawl_env.update({
            "RUN_DATE": RUN_DATE,  # Pass RUN_DATE so merge/normalize use same folder
            "OUTPUT_FOLDER": str(RAW_FOLDER),
            "RAW_DATA_FOLDER": str(RAW_FOLDER),
        })
        
        # Deprecated: Job limits are now defined in input package (config_jobs.py) via .env
        # log(f"Job Limits: iTviec={JOB_LIMITS.get('itviec', 50)}, LinkedIn={JOB_LIMITS.get('linkedin', 100)}, CareerViet={JOB_LIMITS.get('careerviet', 50)}, VietnamWorks={JOB_LIMITS.get('vietnamworks', 50)}")
        
        # Call daily runners directly (not via .bat) to preserve environment variables
        crawlers = [
            ("ITviec", "crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py", "itviec"),
            ("LinkedIn", "crawl_data/crawl-linkedin-jobs/scripts/daily_linkedin_runner.py", "linkedin"),
            ("CareerViet", "crawl_data/crawl-careerviet-jobs/scripts/daily_careerviet_runner.py", "careerviet"),
            ("VietnamWorks", "crawl_data/crawl-vietnamwork-jobs/scripts/daily_vietnamworks_runner.py", "vietnamworks"),
        ]
        
        crawl_dir = BASE_DIR / "1_crawl_data"
        
        for crawler_name, crawler_path, limit_key in crawlers:
            # Skip crawlers with 0 job limit
            if JOB_LIMITS.get(limit_key, 1) == 0:
                log(f"Skipping {crawler_name} crawler (job_limit=0)")
                continue
            
            crawler_script = crawl_dir / crawler_path
            if crawler_script.exists():
                log(f"Running {crawler_name} crawler...")
                # Use per-crawler timeout
                crawler_timeout = CRAWLER_TIMEOUTS.get(limit_key, 600)
                if not run_step(f"{crawler_name} Crawler", crawler_script, timeout=crawler_timeout, cwd=crawl_dir, env=crawl_env):
                    log(f"⚠️  {crawler_name} crawler skipped (timeout or error)")
            else:
                log(f"⚠️  {crawler_name} crawler not found: {crawler_script}")
        
        # ---- MERGE (automatically after crawl) ----
        log("Merging crawler outputs...")
        merge_script = crawl_dir / "merge_daily_outputs.py"
        if merge_script.exists():
            crawl_ok = run_step("Merge Outputs", merge_script, timeout=CRAWLER_TIMEOUT, cwd=crawl_dir, env=crawl_env)
        else:
            log("⚠️  Merge script not found")
            crawl_ok = False
        
        if not crawl_ok:
            log("Crawl failed")
    else:
        log("Skipping CRAWL (STEP_CRAWL=false)\n")
    
    # -------- STEP 2: CLEAN -> PENDING -> EXTRACT -> NORMALIZE -> TRANSFORM --------
    if step_clean:
        log("STEP 2: CLEAN DATA (debug clean -> pending_llm -> extracted -> normalized -> import_ready)")

        raw_combined = None
        if args.input:
            custom_input = Path(args.input)
            if custom_input.exists():
                raw_combined = custom_input
                log(f"Using custom input for clean flow: {custom_input.name}")
            else:
                log(f"❌ Custom input file not found: {args.input}")
                clean_ok = False

        if raw_combined is None and clean_ok:
            raw_combined = RAW_FOLDER / "jobs_combined.json"

        if not raw_combined or not raw_combined.exists():
            log("❌ No raw combined input found for cleaning")
            clean_ok = False
        else:
            pending_file = CLEAN_FOLDER / "pending_llm.json"
            extracted_file = CLEAN_FOLDER / "extracted.json"
            normalized_file = CLEAN_FOLDER / "normalized.json"
            import_ready_file = CLEAN_FOLDER / "import_ready.json"
            clean_fallback_file = FALLBACK_FOLDER / "clean_fallback.json"
            extract_fallback_file = FALLBACK_FOLDER / "extract_fallback.json"
            normalize_fallback_file = FALLBACK_FOLDER / "normalize_fallback.json"
            import_fallback_file = FALLBACK_FOLDER / "import_fallback.json"

            clean_script = BASE_DIR / "2_clean_data" / "clean_process.py"
            extract_script = BASE_DIR / "process_pending_llm.py"
            transform_script = BASE_DIR / "transform_for_import.py"

            if clean_script.exists():
                clean_ok = run_step(
                    "CLEAN STEP 1",
                    clean_script,
                    args=[str(raw_combined), "--step", "1", "--output", str(pending_file)],
                    timeout=CLEAN_TIMEOUT,
                    cwd=BASE_DIR / "2_clean_data",
                )
            else:
                log(f"⚠️  Clean script not found: {clean_script}")
                clean_ok = False

            if clean_ok and extract_script.exists():
                clean_ok = run_step(
                    "LLM EXTRACT",
                    extract_script,
                    args=["--input-path", str(pending_file), "--output-path", str(extracted_file), "--fallback-path", str(extract_fallback_file)],
                    timeout=CLEAN_TIMEOUT,
                    cwd=BASE_DIR,
                )
            elif clean_ok:
                log(f"⚠️  Extract script not found: {extract_script}")
                clean_ok = False

            # Use the new normalize runner inside 2_1_normalized_data
            normalize_entry = BASE_DIR / "normalize" / "run_normalize.py"
            if clean_ok and normalize_entry.exists():
                # call run_normalize with run-date and default level=2 (full)
                clean_ok = run_step(
                    "NORMALIZE",
                    normalize_entry,
                    args=["--run-date", RUN_DATE.split("_")[0], "--level", "2"],
                    timeout=CLEAN_TIMEOUT,
                    cwd=BASE_DIR,
                )
            elif clean_ok:
                log(f"⚠️  Normalize entry not found: {normalize_entry}")
                clean_ok = False
            elif clean_ok:
                clean_ok = False

            if clean_ok and transform_script.exists():
                clean_ok = run_step(
                    "TRANSFORM FOR IMPORT",
                    transform_script,
                    args=[str(normalized_file), "--output", str(import_ready_file), "--fallback-output", str(import_fallback_file)],
                    timeout=CLEAN_TIMEOUT,
                    cwd=BASE_DIR,
                )
            elif clean_ok:
                log(f"⚠️  Transform script not found: {transform_script}")
                clean_ok = False

            if clean_ok and not pending_file.exists():
                log(f"❌ Pending queue not found: {pending_file}")
                clean_ok = False
            if clean_ok and not extracted_file.exists():
                log(f"❌ Extracted output not found: {extracted_file}")
                clean_ok = False
            if clean_ok and not normalized_file.exists():
                log(f"❌ Normalized output not found: {normalized_file}")
                clean_ok = False
            if clean_ok and not import_ready_file.exists():
                log(f"❌ Import-ready output not found: {import_ready_file}")
                clean_ok = False

            if clean_ok:
                log(f"[OK] Clean outputs ready:")
                log(f"  pending_llm  -> {pending_file.name}")
                log(f"  extracted    -> {extracted_file.name}")
                log(f"  normalized   -> {normalized_file.name}")
                log(f"  import_ready -> {import_ready_file.name}")
            else:
                log("Clean failed")
    else:
        log("Skipping CLEAN (STEP_CLEAN=false)\n")

    # -------- STEP 3: IMPORT --------
    if step_import:
        log("STEP 3: IMPORT TO DATABASE")
        import_script = BASE_DIR / "3_mapping_data_db" / "import_to_db.py"
        import_input = CLEAN_FOLDER / "import_ready.json"

        if import_input.exists():
            log(f"Using import-ready output: {import_input.name}")
            import_args = ["--input", str(import_input)]
            import_ok = run_step("IMPORT", import_script, args=import_args, timeout=IMPORT_TIMEOUT, cwd=BASE_DIR / "3_mapping_data_db")
            if not import_ok:
                log("Import failed")
        else:
            log("❌ No import-ready data found for import")
            import_ok = False
    else:
        log("Skipping IMPORT (STEP_IMPORT=false)\n")
    
    # -------- SUMMARY --------
    cleanup_ok = True
    should_cleanup = step_clean and step_import and crawl_ok and clean_ok and import_ok
    if should_cleanup:
        log("Running retention cleanup for transient artifacts...")
        cleanup_ok = cleanup_retention_artifacts()
        if cleanup_ok:
            log("Retention cleanup complete")
        else:
            log("Retention cleanup completed with warnings")

    log("=" * 80)
    log("SUMMARY")
    log("=" * 80)
    log(f"Crawl  : {'Done' if crawl_ok else 'Skipped/Failed'}")
    log(f"Clean  : {'Done' if clean_ok else 'Skipped/Failed'}")
    log(f"Import : {'Done' if import_ok else 'Skipped/Failed'}")
    log(f"Cleanup: {'Done' if cleanup_ok else ('Skipped' if not should_cleanup else 'Warnings')}")
    log(f"(API calls tracked in CLEAN step summary above)")
    
    duration = datetime.now() - start
    log(f"Duration: {duration}")
    log("=" * 80)
    
    return crawl_ok and clean_ok and import_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
