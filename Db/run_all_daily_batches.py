#!/usr/bin/env python3
"""Run ETL pipeline sequentially in batches of 4 keywords to process all 132 keywords daily."""

import os
import sys
import time
import subprocess
import argparse
from datetime import datetime
from dotenv import load_dotenv

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
# Resolve the Python interpreter cross-platform. On Windows the venv lives in
# .venv/Scripts/python.exe, on POSIX in .venv/bin/python. In Docker there is no
# .venv (it is excluded via .dockerignore), so fall back to the running
# interpreter (sys.executable), which is the container's python3.
if os.name == "nt":
    _venv_python = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
else:
    _venv_python = os.path.join(BASE_DIR, ".venv", "bin", "python")
python_exe = _venv_python if os.path.exists(_venv_python) else sys.executable
pipeline_script = os.path.join(BASE_DIR, "run_etl_pipeline.py")

# Configurations
def get_total_keywords():
    try:
        config_path = os.getenv("KEYWORDS_DAILY_PATH")
        if not config_path or not os.path.exists(config_path):
            config_path = os.path.join(BASE_DIR, "input", "keywords_daily.json")
        if not os.path.exists(config_path):
            config_path = os.path.join(BASE_DIR, "keywords_daily.json")
        if not os.path.exists(config_path):
            return 132
            
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            
        keywords = []
        for tier_key in ("tier_1", "tier_2", "tier_3"):
            tier_keywords = cfg.get(tier_key, [])
            if isinstance(tier_keywords, list):
                keywords.extend(tier_keywords)
                
        groups = cfg.get("groups", {})
        if isinstance(groups, dict):
            for group_cfg in groups.values():
                if not isinstance(group_cfg, dict):
                    continue
                for lang_key in ("en", "vi", "roles"):
                    lang_keywords = group_cfg.get(lang_key, [])
                    if isinstance(lang_keywords, list):
                        keywords.extend(lang_keywords)
                        
                clusters = group_cfg.get("clusters", {})
                if isinstance(clusters, dict):
                    for cluster_roles in clusters.values():
                        if isinstance(cluster_roles, list):
                            keywords.extend(cluster_roles)
                            
        seen = set()
        deduped = []
        for kw in keywords:
            kw_clean = str(kw).strip()
            if not kw_clean:
                continue
            kw_lower = kw_clean.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                deduped.append(kw_clean)
                
        return len(deduped)
    except Exception as e:
        print(f"[WARN] Error reading keyword count: {e}. Using fallback 132.")
        return 132

import json
TOTAL_KEYWORDS = get_total_keywords()
BATCH_SIZE = 4
TOTAL_RUNS = (TOTAL_KEYWORDS + BATCH_SIZE - 1) // BATCH_SIZE
PAUSE_MINUTES = int(os.getenv("PAUSE_MINUTES", "5"))  # Rest time in minutes between batches
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
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Limit the number of runs/batches to execute."
    )
    return parser.parse_args()

def main():
    args = parse_args()
    runs_to_execute = TOTAL_RUNS
    if args.max_runs is not None:
        runs_to_execute = min(TOTAL_RUNS, args.max_runs)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting daily crawl batches...")
    print(f"Total runs to execute: {runs_to_execute} (out of {TOTAL_RUNS} total runs), batch size: {BATCH_SIZE} keywords, pause: {PAUSE_MINUTES} minutes")
    print(f"Reset keywords on start: {args.reset_keywords}")
    print(f"Working Directory: {BASE_DIR}")
    print(f"Python Venv Executable: {python_exe}")
    print(f"Pipeline Script: {pipeline_script}")
    
    for run in range(1, runs_to_execute + 1):
        print("\n" + "=" * 80)
        print(f"RUN {run} OF {runs_to_execute} - Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
            
        if run < runs_to_execute:
            print(f"Waiting for {PAUSE_MINUTES} minutes to avoid rate limit/blocking before next batch...")
            time.sleep(PAUSE_SECONDS)

    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] All {runs_to_execute} batches completed successfully!")

if __name__ == "__main__":
    main()
