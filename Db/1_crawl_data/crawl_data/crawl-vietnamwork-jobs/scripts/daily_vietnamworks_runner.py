#!/usr/bin/env python3
"""VietnamWorks runner - crawl multiple keywords and pages with freshness filtering"""

import os
import sys
import json
import traceback
from datetime import datetime, date
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))
from scrape_vietnamwork import crawl_list_url_to_raw_jobs

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

BASE = "https://www.vietnamworks.com/viec-lam?q={keyword}"


def log_error(output_dir: str, keyword: str, list_url: str, err: Exception):
    """Log crawl error to console and file for easier debugging/monitoring."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    err_trace = traceback.format_exc()
    err_data = {
        "timestamp": timestamp,
        "keyword": keyword,
        "list_url": list_url,
        "error_type": type(err).__name__,
        "error_message": str(err),
        "traceback": err_trace,
    }

    print(f"[ERROR] Crawl failed for keyword='{keyword}'")
    print(f"[ERROR] {type(err).__name__}: {err}")
    print("[ERROR] Traceback:")
    print(err_trace)

    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "vietnamworks_errors.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(err_data, ensure_ascii=False) + "\n")

    print(f"[ERROR] Error log saved: {log_path}")


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
    
    # rotate
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


def print_crawl_config(keywords_list: list, cfg: dict, source: str = "VietnamWorks"):
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
    # ============ CONFIGURATION - Chỉnh tham số ở đây ============
    NUM_KEYWORDS = None   # None = use all picked keywords (production mode), 1 = test with 1 keyword
    END_PAGE = 1          # Số page crawl. 1 = test mode, 5 = production
    # ============================================================
    
    # Note: MAX_JOBS is now determined by tier-based logic in get_tier_max_jobs()
    # Hard-coded override below for backward compatibility only
    
    base_dir = os.path.dirname(__file__)
    cfg_path = os.path.normpath(os.path.join(base_dir, "../..", "keywords_daily.json"))
    cfg = load_config(cfg_path)

    keywords_str = os.environ.get("VNWORKS_KEYWORDS")
    if keywords_str:
        keywords_list = [k.strip() for k in keywords_str.split(",") if k.strip()]
    else:
        # Use new group_rotation logic if mode is set
        if cfg.get("mode") == "group_rotation":
            keywords_list = pick_keywords(cfg)
        else:
            # Fallback to old behavior: load all keywords
            all_keywords = cfg.get("keywords", [])
            keywords_list = all_keywords if all_keywords else ["software engineer"]
    
    # Apply NUM_KEYWORDS limit
    if NUM_KEYWORDS is not None and NUM_KEYWORDS > 0:
        keywords_list = keywords_list[:NUM_KEYWORDS]
        print(f"[CONFIG] Limited to {NUM_KEYWORDS} keyword(s)")

    output_dir = os.environ.get("OUTPUT_FOLDER")
    if not output_dir:
        today_with_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(base_dir, "output", f"crawl_{today_with_time}")

    os.makedirs(output_dir, exist_ok=True)

    # Display configuration
    print_crawl_config(keywords_list, cfg, source="VietnamWorks")
    print(f"[CONFIG] Pages per keyword: {END_PAGE}")
    print(f"[CONFIG] Output dir: {output_dir}")
    print("=" * 85)

    had_error = False

    for keyword in keywords_list:
        list_url = BASE.format(keyword=keyword.replace(" ", "+"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keyword_safe = keyword.lower().replace(" ", "_")
        out_prefix = os.path.join(output_dir, f"vietnamworks_{keyword_safe}_{timestamp}")

        print(f"\n[{keyword}] Crawling multiple pages...")
        print(f"List URL: {list_url}")

        try:
            # Determine max_jobs based on tier
            tier_max_jobs = get_tier_max_jobs(keyword, cfg)
            
            raw_jobs = crawl_list_url_to_raw_jobs(
                list_url_page1=list_url,
                start_page=1,
                end_page=END_PAGE,
                prefer_next=True,
                fetch_company=False,
                max_jobs=tier_max_jobs,
                search_keyword=keyword,
            )

            if not raw_jobs:
                print(f"[WARN] No jobs found for '{keyword}'.")
                continue

            out_json = f"{out_prefix}.json"
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump([j.to_dict() for j in raw_jobs], f, ensure_ascii=False, indent=2)

            print(f"✓ JSON saved: {out_json} ({len(raw_jobs)} jobs)")
        except Exception as err:
            had_error = True
            log_error(output_dir=output_dir, keyword=keyword, list_url=list_url, err=err)
            continue

    if had_error:
        print("[ERROR] Run finished with errors. Check vietnamworks_errors.log in output directory.")
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"[FATAL] Unhandled error: {type(err).__name__}: {err}")
        print(traceback.format_exc())
        raise