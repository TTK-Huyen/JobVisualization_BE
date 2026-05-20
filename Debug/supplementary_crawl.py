#!/usr/bin/env python3
"""
SUPPLEMENTARY CRAWL SCRIPT
Crawl bổ sung data cho các ngày thiếu trong khoảng 1/4/2026 - 19/5/2026

Ngày thiếu cần crawl:
- 2026-04-01, 2026-04-02 (2 days)
- 2026-04-04, 2026-04-05, 2026-04-06 (3 days)
- 2026-04-12 (1 day)
- 2026-04-20 (1 day)
- 2026-04-22 (1 day)
- 2026-05-02 (1 day)
TỔNG: 9 ngày cần crawl

Usage:
  python supplementary_crawl.py [--dry-run] [--date 2026-04-01]

Flags:
  --dry-run      Chỉ show config, không crawl thực
  --date         Crawl một ngày cụ thể (YYYY-MM-DD format)
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION
# ============================================================================

# Base directories
BASE_DIR = Path(__file__).parent.resolve()
PIPELINE_CRAWL_DIR = BASE_DIR / "Db" / "pipeline" / "crawl" / "1_crawl_data"
FALLBACK_CRAWL_DIR = BASE_DIR / "Db" / "1_crawl_data"  # If pipeline layout not used

# Chọn crawl directory (prefer pipeline, fallback to repo level)
CRAWL_DIR = PIPELINE_CRAWL_DIR if PIPELINE_CRAWL_DIR.exists() else FALLBACK_CRAWL_DIR

# Crawlers path
CRAWLERS = {
    "careerviet": CRAWL_DIR / "crawl_data" / "crawl-careerviet-jobs" / "scripts" / "daily_careerviet_runner.py",
    "itviec": CRAWL_DIR / "crawl_data" / "crawl-itviec-jobs" / "scripts" / "daily_itviec_runner.py",
    "linkedin": CRAWL_DIR / "crawl_data" / "crawl-linkedin-jobs" / "scripts" / "daily_linkedin_runner.py",
    "vietnamwork": CRAWL_DIR / "crawl_data" / "crawl-vietnamwork-jobs" / "scripts" / "daily_vietnamworks_runner.py",
}

# Days to supplement - 9 ngày thiếu
MISSING_DATES = [
    "2026-04-01",
    "2026-04-02",
    "2026-04-04",
    "2026-04-05",
    "2026-04-06",
    "2026-04-12",
    "2026-04-20",
    "2026-04-22",
    "2026-05-02",
]

# Load environment
ENV_FILE = BASE_DIR / "Db" / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# Get Python exe
PYTHON_EXE = (BASE_DIR / "Db" / ".venv" / "Scripts" / "python.exe").resolve()
if not PYTHON_EXE.exists():
    PYTHON_EXE = sys.executable

# ============================================================================
# FUNCTIONS
# ============================================================================

def log(msg, level="INFO"):
    """Simple logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{timestamp}] {level:7s}"
    # Use ASCII-safe characters to avoid Unicode encoding errors on Windows
    msg = msg.replace('✅', '[OK]').replace('❌', '[FAIL]').replace('📊', '[REPORT]')
    print(f"{prefix} | {msg}")

def run_crawler(crawler_path, target_date, dry_run=False):
    """
    Run a single crawler for a target date
    
    Args:
        crawler_path: Path to crawler script
        target_date: Date string (YYYY-MM-DD)
        dry_run: If True, just show what would run
    
    Returns:
        True if success, False otherwise
    """
    
    if not crawler_path.exists():
        log(f"Crawler not found: {crawler_path}", "WARN")
        return False
    
    # Set environment for crawler
    env = os.environ.copy()
    env["TARGET_DATE"] = target_date
    env["RUN_DATE"] = datetime.strptime(target_date, "%Y-%m-%d").strftime("%Y%m%d_%H%M%S")
    
    # Use full job count for production crawl
    env["CAREERVIET_MAX_JOBS"] = "999"
    env["ITVIEC_MAX_JOBS"] = "999"
    env["LINKEDIN_MAX_JOBS"] = "999"
    env["VIETNAMWORKS_MAX_JOBS"] = "999"
    
    cmd = [str(PYTHON_EXE), str(crawler_path)]
    
    if dry_run:
        log(f"[DRY-RUN] Would run: {' '.join(cmd)}", "PLAN")
        log(f"[DRY-RUN] With env: TARGET_DATE={target_date}", "PLAN")
        return True
    
    try:
        log(f"Running: {crawler_path.name} for {target_date}", "EXEC")
        result = subprocess.run(
            cmd,
            cwd=CRAWL_DIR,
            env=env,
            capture_output=False,
            timeout=3000  # 50 min per crawler (LinkedIn needs time for Selenium)
        )
        
        if result.returncode == 0:
            log(f"[OK] {crawler_path.name} completed", "OK")
            return True
        else:
            log(f"[FAIL] {crawler_path.name} failed (exit code {result.returncode})", "ERR")
            return False
    
    except subprocess.TimeoutExpired:
        log(f"[FAIL] {crawler_path.name} timed out", "ERR")
        return False
    except Exception as e:
        log(f"[FAIL] Error running {crawler_path.name}: {e}", "ERR")
        return False

def crawl_single_date(target_date, dry_run=False):
    """Crawl all sources for a single date"""
    
    log(f"{'='*80}", "INFO")
    log(f"CRAWLING: {target_date}", "START")
    log(f"{'='*80}", "INFO")
    
    results = {}
    for source_name, crawler_path in CRAWLERS.items():
        log(f"Crawler: {source_name}", "STEP")
        success = run_crawler(crawler_path, target_date, dry_run)
        results[source_name] = success
    
    return results

def crawl_all_missing_dates(dry_run=False):
    """Crawl all missing dates"""
    
    log(f"Starting supplementary crawl for {len(MISSING_DATES)} days", "INFO")
    
    if dry_run:
        log("⚠️  DRY-RUN MODE - No actual crawling", "WARN")
    
    all_results = {}
    for i, date in enumerate(MISSING_DATES, 1):
        log(f"\n[{i}/{len(MISSING_DATES)}] Processing {date}...", "INFO")
        results = crawl_single_date(date, dry_run)
        all_results[date] = results
    
    return all_results

def print_summary(all_results):
    """Print summary of crawl results"""
    
    print("\n" + "=" * 80)
    print("[REPORT] SUPPLEMENTARY CRAWL SUMMARY")
    print("=" * 80)
    
    total_dates = len(all_results)
    dates_success = sum(1 for r in all_results.values() if all(r.values()))
    
    print(f"\nDates processed: {total_dates}")
    print(f"Dates with all crawlers OK: {dates_success}")
    
    print("\nDetailed results:")
    print("-" * 80)
    print(f"{'Date':<15} | {'CareerViet':<12} | {'ITViec':<12} | {'LinkedIn':<12} | {'VNWorks':<12}")
    print("-" * 80)
    
    for date, sources in sorted(all_results.items()):
        status = []
        for source in ["careerviet", "itviec", "linkedin", "vietnamwork"]:
            s = "[OK]" if sources.get(source) else "[X]"
            status.append(s)
        
        print(f"{date:<15} | {status[0]:<12} | {status[1]:<12} | {status[2]:<12} | {status[3]:<12}")
    
    print("=" * 80)

# ============================================================================
# MAIN
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Crawl supplementary job data for missing dates"
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--date", type=str, help="Crawl single date (YYYY-MM-DD)")
    parser.add_argument("--no-summary", action="store_true", help="Skip summary")
    
    args = parser.parse_args()
    
    # Validate paths
    if not CRAWL_DIR.exists():
        log(f"❌ Crawl directory not found: {CRAWL_DIR}", "ERR")
        sys.exit(1)
    
    log(f"Crawl directory: {CRAWL_DIR}", "INFO")
    log(f"Python executable: {PYTHON_EXE}", "INFO")
    
    # Run crawl
    if args.date:
        # Single date mode
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            log(f"❌ Invalid date format: {args.date}. Use YYYY-MM-DD", "ERR")
            sys.exit(1)
        
        results = {args.date: crawl_single_date(args.date, args.dry_run)}
    else:
        # All missing dates mode
        results = crawl_all_missing_dates(args.dry_run)
    
    # Print summary
    if not args.no_summary:
        print_summary(results)
    
    log("✅ Supplementary crawl completed!", "OK")

if __name__ == "__main__":
    main()
