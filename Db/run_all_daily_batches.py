#!/usr/bin/env python3
"""Run ETL pipeline sequentially in batches of 4 keywords to process all 132 keywords daily."""

import os
import sys
import time
import subprocess
import argparse
from datetime import datetime

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
python_exe = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
pipeline_script = os.path.join(BASE_DIR, "run_etl_pipeline.py")

# Configurations
TOTAL_KEYWORDS = 132
BATCH_SIZE = 4
TOTAL_RUNS = (TOTAL_KEYWORDS + BATCH_SIZE - 1) // BATCH_SIZE  # 33 runs
PAUSE_MINUTES = 5  # Rest time in minutes between batches
PAUSE_SECONDS = PAUSE_MINUTES * 60

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ETL pipeline sequentially in batches of 4 keywords to process all 132 keywords daily."
    )
    parser.add_argument(
        "--reset-keywords",
        action="store_true",
        help="Reset keyword rotation back to the beginning (index 0) on the first run of the day."
    )
    return parser.parse_args()

def main():
    args = parse_args()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting daily crawl batches...")
    print(f"Total runs: {TOTAL_RUNS}, batch size: {BATCH_SIZE} keywords, pause: {PAUSE_MINUTES} minutes")
    print(f"Reset keywords on start: {args.reset_keywords}")
    print(f"Working Directory: {BASE_DIR}")
    print(f"Python Venv Executable: {python_exe}")
    print(f"Pipeline Script: {pipeline_script}")
    
    for run in range(1, TOTAL_RUNS + 1):
        print("\n" + "=" * 80)
        print(f"RUN {run} OF {TOTAL_RUNS} - Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
        # Build the command
        cmd = [python_exe, pipeline_script]
        
        # Omit `--step all` to run the full pipeline, and only reset keywords on the very first run
        if run == 1 and args.reset_keywords:
            cmd.append("--reset-keywords")
            
        try:
            # Run in-process with environment intact
            result = subprocess.run(cmd, cwd=BASE_DIR)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Run {run} completed with exit code: {result.returncode}")
        except Exception as e:
            print(f"[ERROR] Run {run} failed with exception: {e}")
            
        if run < TOTAL_RUNS:
            print(f"Waiting for {PAUSE_MINUTES} minutes to avoid rate limit/blocking before next batch...")
            time.sleep(PAUSE_SECONDS)

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] All {TOTAL_RUNS} batches completed successfully!")

if __name__ == "__main__":
    main()
