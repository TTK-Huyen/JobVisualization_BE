#!/usr/bin/env python3
"""Daily rotating VietnamWorks scraper runner (DataFrame JSON)"""

import os
import sys
import json
from datetime import datetime, date

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))
from scrape_vietnamwork import crawl_list_url_to_raw_jobs

BASE = "https://www.vietnamworks.com/viec-lam?q={keyword}"


def load_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_keywords(kws, mode="rotate", keywords_per_day=1):
    """Pick keyword(s) based on mode. Returns list of keywords."""
    if not kws:
        return ["software engineer"]
    
    if mode.lower() == "random":
        import random
        return random.sample(kws, min(keywords_per_day, len(kws)))
    
    doy = date.today().timetuple().tm_yday
    selected = []
    for i in range(keywords_per_day):
        idx = (doy - 1 + i) % len(kws)
        selected.append(kws[idx])
    return selected


def main():
    base_dir = os.path.dirname(__file__)
    cfg_path = os.path.normpath(os.path.join(base_dir, "../..", "keywords_daily.json"))
    cfg = load_config(cfg_path)

    # Get keywords for today
    keywords_str = os.environ.get("VNWORKS_KEYWORDS")
    if keywords_str:
        keywords_list = keywords_str.split(",")
    else:
        keywords_list = pick_keywords(
            cfg.get("keywords", []),
            cfg.get("mode", "rotate"),
            cfg.get("keywords_per_day", 1)
        )

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

    print("=" * 80)
    print(f"VietnamWorks Daily - keywords: {keywords_list}")
    print("=" * 80)
    print(f"[CONFIG] output_dir target: {output_dir}")
    print("=" * 80)
    
    # Run for each keyword
    for keyword in keywords_list:
        keyword = keyword.strip()
        list_url = BASE.format(keyword=keyword.replace(" ", "+"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Replace spaces in keyword for filename
        keyword_safe = keyword.lower().replace(" ", "_")
        out_prefix = os.path.join(output_dir, f"vietnamworks_{keyword_safe}_{timestamp}")

        print(f"\n[{keyword}] Scraping - {list_url}")
        print(f"[PLANNED PATH] {out_prefix}.json")
        raw_jobs = crawl_list_url_to_raw_jobs(list_url, start_page=1, end_page=1, prefer_next=True, fetch_company=False)
        if not raw_jobs:
            print(f"[WARN] No jobs found for '{keyword}'.")
            continue
        
        # Optional: limit number of jobs via env var for testing
        max_jobs_env = os.environ.get("VNWORKS_MAX_JOBS")
        if max_jobs_env and max_jobs_env.isdigit():
            raw_jobs = raw_jobs[:int(max_jobs_env)]
        
        # Save JSON (RawJobData schema)
        out_json = f"{out_prefix}.json"
        import json as _json
        with open(out_json, "w", encoding="utf-8") as f:
            _json.dump([j.to_dict() for j in raw_jobs], f, ensure_ascii=False, indent=2)
        print(f"✓ JSON saved: {out_json} ({len(raw_jobs)} jobs)")


if __name__ == "__main__":
    main()
