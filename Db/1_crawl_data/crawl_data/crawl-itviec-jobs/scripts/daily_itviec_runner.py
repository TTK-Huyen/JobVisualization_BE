#!/usr/bin/env python3
"""Daily rotating ITviec scraper runner for Task Scheduler"""

import os
import sys
import json
from datetime import datetime, date

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Import scraper functions
sys.path.insert(0, os.path.dirname(__file__))
from scrape_itviec import scrape_data, export_to_json


def load_config(config_path: str):
    if not os.path.exists(config_path):
        return {
            "mode": "rotate",
            "location": "Ho Chi Minh",
            "keywords": ["software engineer", "java", "python", "backend", "frontend"]
        }
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_keywords(cfg: dict):
    """Pick keyword(s) based on config mode. Returns list of keywords."""
    kws = cfg.get("keywords", [])
    if not kws:
        return ["software engineer"]
    
    mode = cfg.get("mode", "rotate").lower()
    keywords_per_day = cfg.get("keywords_per_day", 1)
    
    if mode == "random":
        import random
        return random.sample(kws, min(keywords_per_day, len(kws)))
    
    # rotate: pick by day-of-year
    doy = date.today().timetuple().tm_yday
    selected = []
    for i in range(keywords_per_day):
        idx = (doy - 1 + i) % len(kws)
        selected.append(kws[idx])
    return selected


def main():
    base_dir = os.path.dirname(__file__)
    # Prefer shared config at crawl_data root
    cfg_path = os.path.normpath(os.path.join(base_dir, "../..", "keywords_daily.json"))
    cfg = load_config(cfg_path)

    location = os.environ.get("ITVIEC_LOCATION", cfg.get("location", "Ho Chi Minh"))
    
    # Optional max jobs (for testing) via env var
    max_jobs_env = os.environ.get("ITVIEC_MAX_JOBS")
    max_jobs = int(max_jobs_env) if max_jobs_env and max_jobs_env.isdigit() else None

    # Output directory: use OUTPUT_FOLDER from env (set by orchestrator), fallback to data/raw/crawl_YYYYMMDD
    output_dir = os.environ.get("OUTPUT_FOLDER")
    print(f"[DEBUG] OUTPUT_FOLDER env: {output_dir}")
    
    if not output_dir:
        from datetime import date as date_class
        today = date_class.today().strftime("%Y%m%d")
        
        # Try to find data/raw folder
        current = os.path.abspath(base_dir)
        data_raw_dir = None
        for _ in range(10):  # Prevent infinite loop
            data_raw_path = os.path.join(current, "data", "raw")
            if os.path.exists(current) and os.path.exists(os.path.join(current, "data")):
                data_raw_dir = data_raw_path
                print(f"[DEBUG] Found data/raw at: {data_raw_dir}")
                break
            current = os.path.dirname(current)
        
        if data_raw_dir:
            output_dir = os.path.join(data_raw_dir, f"crawl_{today}")
        else:
            # Fallback if data folder not found
            print("[WARN] data/raw folder not found, using output folder")
            output_dir = os.path.join(base_dir, "../../output")
    
    # Ensure output directory exists
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"[DEBUG] Created/verified output_dir: {output_dir}")
    except Exception as e:
        print(f"[ERROR] Failed to create output_dir: {e}")
        raise
    
    # Get keywords for today
    keywords = os.environ.get("ITVIEC_KEYWORDS")
    if keywords:
        keywords_list = keywords.split(",")
    else:
        keywords_list = pick_keywords(cfg)
    
    print("=" * 80)
    print(f"Daily run - keywords: {keywords_list} | location: '{location}'")
    print("=" * 80)
    print(f"[CONFIG] output_dir target: {output_dir}")
    print("=" * 80)
    
    # Run for each keyword
    for keyword in keywords_list:
        keyword = keyword.strip()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Replace spaces in keyword for filename
        keyword_safe = keyword.lower().replace(" ", "_")
        out_prefix = os.path.join(output_dir, f"itviec_{keyword_safe}_{location.lower().replace(' ', '_')}_{timestamp}")
        
        print(f"\n[{keyword}] Scraping...")
        print(f"[PLANNED PATH] {out_prefix}.json")
        jobs_data = scrape_data(keyword, location, max_jobs=max_jobs)
        if not jobs_data:
            print(f"[WARN] No jobs found for '{keyword}'.")
            continue

        export_to_json(jobs_data, out_prefix)
        print(f"✓ JSON saved to: {out_prefix}.json ({len(jobs_data)} jobs)")


if __name__ == "__main__":
    main()
