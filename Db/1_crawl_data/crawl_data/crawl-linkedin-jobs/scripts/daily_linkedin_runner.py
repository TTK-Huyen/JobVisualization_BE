#!/usr/bin/env python3
"""Daily rotating LinkedIn scraper runner"""

import os
import sys
import json
from datetime import datetime, date
from pathlib import Path

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))
from scrape_linkedin import scrape_data, export_to_json

# Load .env
from dotenv import load_dotenv

env_file = Path(__file__).parent.parent.parent.parent.parent / ".env"
load_dotenv(env_file)

# Load config from .env (or defaults)
TIER1_JOBS_PER_KEYWORD = int(os.getenv("JOBS_PER_KEYWORD", "3"))
TIER2_JOBS_PER_KEYWORD = int(os.getenv("JOBS_PER_KEYWORD", "3"))
TIER3_JOBS_PER_KEYWORD = int(os.getenv("JOBS_PER_KEYWORD", "3"))

TIER1_KEYWORDS_TO_SELECT = int(os.getenv("TIER1_NUM_KEYWORDS", "1"))
TIER2_KEYWORDS_TO_SELECT = int(os.getenv("TIER2_NUM_KEYWORDS", "0"))
TIER3_KEYWORDS_TO_SELECT = int(os.getenv("TIER3_NUM_KEYWORDS", "0"))


def load_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_keywords(cfg: dict):
    """Pick keywords based on TIER*_KEYWORDS_TO_SELECT from .env config"""
    mode = cfg.get("mode", "rotate").lower()
    doy = date.today().timetuple().tm_yday
    
    if mode == "group_rotation":
        tier_1 = cfg.get("tier_1", [])
        tier_2 = cfg.get("tier_2", [])
        tier_3 = cfg.get("tier_3", [])
        t2_clusters = cfg.get("tier_2_clusters", {})
        
        selected = []
        
        # Pick from tier_1 (use TIER1_KEYWORDS_TO_SELECT, not hardcoded 8)
        if tier_1 and TIER1_KEYWORDS_TO_SELECT > 0:
            start_idx = (doy - 1) % len(tier_1)
            count = min(TIER1_KEYWORDS_TO_SELECT, len(tier_1))
            for i in range(count):
                idx = (start_idx + i) % len(tier_1)
                selected.append(tier_1[idx])
        
        # Pick from tier_2 (use TIER2_KEYWORDS_TO_SELECT, not hardcoded 2)
        if tier_2 and TIER2_KEYWORDS_TO_SELECT > 0 and t2_clusters:
            # Map each tier_2 keyword to its cluster
            keyword_to_cluster = {}
            for cluster_name, keywords in t2_clusters.items():
                for kw in keywords:
                    if kw in tier_2:
                        keyword_to_cluster[kw] = cluster_name
            
            # Get unique clusters available
            available_clusters = list(set(keyword_to_cluster.values()))
            
            if len(available_clusters) >= TIER2_KEYWORDS_TO_SELECT:
                # Pick N different clusters
                for i in range(TIER2_KEYWORDS_TO_SELECT):
                    c_idx = (doy - 1 + i) % len(available_clusters)
                    cluster = available_clusters[c_idx]
                    c_keywords = [kw for kw in tier_2 if keyword_to_cluster.get(kw) == cluster]
                    if c_keywords:
                        selected.append(c_keywords[(doy - 1 + i) % len(c_keywords)])
        
        # Pick from tier_3 (use TIER3_KEYWORDS_TO_SELECT, not hardcoded 1)
        if tier_3 and TIER3_KEYWORDS_TO_SELECT > 0 and (doy % 3 == 0):
            count = min(TIER3_KEYWORDS_TO_SELECT, len(tier_3))
            for i in range(count):
                idx = (doy - 1 + i) % len(tier_3)
                selected.append(tier_3[idx])
        
        return selected
    
    # Fallback to old behavior
    kws = cfg.get("keywords", [])
    if not kws:
        return ["software engineer"]
    
    keywords_per_day = cfg.get("keywords_per_day", 1)
    
    if mode == "random":
        import random
        return random.sample(kws, min(keywords_per_day, len(kws)))
    
    selected = []
    for i in range(keywords_per_day):
        idx = (doy - 1 + i) % len(kws)
        selected.append(kws[idx])
    return selected


def get_tier_max_jobs(keyword: str, cfg: dict) -> int:
    """Determine max jobs for keyword based on tier"""
    tier_1 = cfg.get("tier_1", [])
    tier_2 = cfg.get("tier_2", [])
    
    if keyword in tier_1:
        return TIER1_JOBS_PER_KEYWORD
    elif keyword in tier_2:
        return TIER2_JOBS_PER_KEYWORD
    else:  # tier_3
        return TIER3_JOBS_PER_KEYWORD


def print_crawl_config(keywords_list: list, cfg: dict, source: str = "LinkedIn"):
    """Display crawler configuration before starting"""
    tier_1 = cfg.get("tier_1", [])
    tier_2 = cfg.get("tier_2", [])
    tier_3 = cfg.get("tier_3", [])
    
    tier1_kws = [k for k in keywords_list if k in tier_1]
    tier2_kws = [k for k in keywords_list if k in tier_2]
    tier3_kws = [k for k in keywords_list if k in tier_3]
    
    total_jobs = (
        len(tier1_kws) * TIER1_JOBS_PER_KEYWORD +
        len(tier2_kws) * TIER2_JOBS_PER_KEYWORD +
        len(tier3_kws) * TIER3_JOBS_PER_KEYWORD
    )
    
    print("\n" + "=" * 85)
    print(f"🔧 {source} CRAWLER CONFIG - {len(keywords_list)} keywords, ~{total_jobs} expected jobs")
    print("=" * 85)
    
    if tier1_kws:
        print(f"\n🔴 TIER 1 ({len(tier1_kws)} keywords × {TIER1_JOBS_PER_KEYWORD}/kw = {len(tier1_kws) * TIER1_JOBS_PER_KEYWORD} jobs):")
        for kw in tier1_kws:
            print(f"   • {kw}")
    
    if tier2_kws:
        print(f"\n🟡 TIER 2 ({len(tier2_kws)} keywords × {TIER2_JOBS_PER_KEYWORD}/kw = {len(tier2_kws) * TIER2_JOBS_PER_KEYWORD} jobs):")
        for kw in tier2_kws:
            print(f"   • {kw}")
    
    if tier3_kws:
        print(f"\n🟢 TIER 3 ({len(tier3_kws)} keywords × {TIER3_JOBS_PER_KEYWORD}/kw = {len(tier3_kws) * TIER3_JOBS_PER_KEYWORD} jobs):")
        for kw in tier3_kws:
            print(f"   • {kw}")
    
    print("\n" + "=" * 85)


def main():
    import sys
    
    # Force immediate stdout flush for real-time logging
    sys.stdout.flush()
    
    print(f"\n{'='*85}")
    print(f"[RUNNER START] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*85}\n")
    sys.stdout.flush()
    
    base_dir = os.path.dirname(__file__)
    cfg_path = os.path.normpath(os.path.join(base_dir, "../..", "keywords_daily.json"))
    cfg = load_config(cfg_path)

    location = os.environ.get("LINKEDIN_LOCATION", cfg.get("location", "Vietnam"))
    
    # Get keywords for today
    keywords_str = os.environ.get("LINKEDIN_KEYWORDS")
    if keywords_str:
        keywords_list = keywords_str.split(",")
    else:
        keywords_list = pick_keywords(cfg)

    print(f"[INFO] Keywords to scrape: {keywords_list}\n")
    sys.stdout.flush()

    # Output directory: use OUTPUT_FOLDER from env (set by orchestrator), fallback to data/raw/crawl_YYYYMMDD
    output_dir = os.environ.get("OUTPUT_FOLDER")
    print(f"[DEBUG] OUTPUT_FOLDER env: {output_dir}")
    
    if not output_dir:
        from datetime import date as date_class
        today_with_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        
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
            output_dir = os.path.join(data_raw_dir, f"crawl_{today_with_time}")
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

    # Display configuration
    print_crawl_config(keywords_list, cfg, source="LinkedIn")
    print(f"[CONFIG] Location: '{location}'")
    print(f"[CONFIG] Output dir: {output_dir}")
    print("=" * 85)
    sys.stdout.flush()
    
    # Run for each keyword
    runner_start = datetime.now()
    for kw_idx, keyword in enumerate(keywords_list, 1):
        keyword = keyword.strip()
        kw_start = datetime.now()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Replace spaces in keyword for filename
        keyword_safe = keyword.lower().replace(" ", "_")
        out_prefix = os.path.join(output_dir, f"linkedin_{keyword_safe}_{location.lower().replace(' ', '_')}_{timestamp}")

        # Determine max_jobs based on tier
        tier_max_jobs = get_tier_max_jobs(keyword, cfg)
        
        print(f"\n{'─'*85}")
        print(f"[KW {kw_idx}/{len(keywords_list)}] START: '{keyword}'")
        print(f"[PLANNED PATH] {out_prefix}.json")
        print(f"[EXPECTED JOBS] {tier_max_jobs}")
        print(f"{'─'*85}")
        sys.stdout.flush()
        
        try:
            print(f"[{keyword}] 🔄 Scraping...")
            sys.stdout.flush()
            
            scrape_start = datetime.now()
            jobs = scrape_data(keyword, location, search_keyword=keyword, max_jobs=tier_max_jobs)
            scrape_elapsed = (datetime.now() - scrape_start).total_seconds()
            
            print(f"[{keyword}] ✓ Scrape done: {len(jobs)} jobs in {scrape_elapsed:.1f}s")
            sys.stdout.flush()
            
            if not jobs:
                print(f"[WARN] ⚠️  No jobs found for '{keyword}'. Skipping export.")
                sys.stdout.flush()
                continue
            
            print(f"[{keyword}] 💾 Exporting to JSON...")
            sys.stdout.flush()
            
            export_start = datetime.now()
            export_to_json(jobs, out_prefix)
            export_elapsed = (datetime.now() - export_start).total_seconds()
            
            kw_elapsed = (datetime.now() - kw_start).total_seconds()
            print(f"[{keyword}] ✓ DONE: {len(jobs)} jobs | scrape={scrape_elapsed:.1f}s, export={export_elapsed:.1f}s, total={kw_elapsed:.1f}s")
            print(f"✓ File: {out_prefix}.json\n")
            sys.stdout.flush()
            
        except Exception as e:
            kw_elapsed = (datetime.now() - kw_start).total_seconds()
            print(f"[{keyword}] ❌ ERROR after {kw_elapsed:.1f}s: {str(e)}\n")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            continue
    
    runner_elapsed = (datetime.now() - runner_start).total_seconds()
    print(f"\n{'='*85}")
    print(f"[RUNNER DONE] Total time: {runner_elapsed:.1f}s")
    print(f"{'='*85}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
