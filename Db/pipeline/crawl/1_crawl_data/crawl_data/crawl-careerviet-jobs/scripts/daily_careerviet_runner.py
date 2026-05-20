#!/usr/bin/env python3
"""Daily rotating CareerViet scraper runner (RawJobData JSON)"""

import os
import sys
import json
import unicodedata
from datetime import datetime, date

# Configure UTF-8 encoding for console output (Windows compatibility)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))
from scrape_careerviet import crawl_list_url_to_raw_jobs

# Load .env
from pathlib import Path
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

BASE = "https://careerviet.vn/viec-lam/{slug}-k-vi.html"


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip().replace(" ", "-")
    s = "".join(ch for ch in s if ch.isalnum() or ch == "-")
    return s


def load_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)



def pick_keywords(cfg: dict):
    """Pick keywords: 8 from tier_1 + 2 from tier_2 (different clusters) + 1 from tier_3 (every 3 days)"""
    mode = cfg.get("mode", "rotate").lower()
    doy = date.today().timetuple().tm_yday
    
    if mode == "group_rotation":
        tier_1 = cfg.get("tier_1", [])
        tier_2 = cfg.get("tier_2", [])
        tier_3 = cfg.get("tier_3", [])
        t2_clusters = cfg.get("tier_2_clusters", {})
        t3_clusters = cfg.get("tier_3_clusters", {})
        
        selected = []
        
        # Pick N from tier_1 (rotate starting position by day)
        if tier_1:
            start_idx = (doy - 1) % len(tier_1)
            count = min(TIER1_KEYWORDS_TO_SELECT, len(tier_1))
            for i in range(count):
                idx = (start_idx + i) % len(tier_1)
                selected.append(tier_1[idx])
        
        # Pick N from tier_2, ensuring different clusters
        if tier_2 and t2_clusters and TIER2_KEYWORDS_TO_SELECT > 0:
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
                selected_clusters = []
                for i in range(TIER2_KEYWORDS_TO_SELECT):
                    c_idx = (doy - 1 + i) % len(available_clusters)
                    selected_clusters.append(available_clusters[c_idx])
                
                for c in selected_clusters:
                    # Pick 1 keyword from each cluster
                    c_keywords = [kw for kw in tier_2 if keyword_to_cluster.get(kw) == c]
                    if c_keywords:
                        idx_offset = (doy - 1) + selected_clusters.index(c)
                        selected.append(c_keywords[idx_offset % len(c_keywords)])
        
        # Pick 1 from tier_3 (every 3 days)
        if tier_3 and (doy % 3 == 0) and TIER3_KEYWORDS_TO_SELECT > 0:
            idx_t3 = (doy - 1) % len(tier_3)
            selected.append(tier_3[idx_t3])
        
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


def load_keywords_from_env():
    for key in ("SELECTED_KEYWORDS_JSON", "CRAWL_KEYWORDS_JSON", "DAILY_KEYWORDS_JSON"):
        value = os.getenv(key)
        if value:
            try:
                kws = json.loads(value)
                if isinstance(kws, list) and kws:
                    return [str(x).strip() for x in kws if str(x).strip()], key
            except Exception:
                pass

    for key in ("SELECTED_KEYWORDS", "CRAWL_KEYWORDS", "KEYWORDS"):
        value = os.getenv(key)
        if value:
            kws = [x.strip() for x in value.split(",") if x.strip()]
            if kws:
                return kws, key

    for key in ("SELECTED_KEYWORDS_FILE", "CRAWL_KEYWORDS_FILE"):
        path = os.getenv(key)
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                kws = data.get("keywords", []) if isinstance(data, dict) else data
                if isinstance(kws, list) and kws:
                    return [str(x).strip() for x in kws if str(x).strip()], key
            except Exception:
                pass

    # Runner-specific env fallback
    value = os.environ.get("CAREERVIET_KEYWORDS")
    if value:
        kws = [x.strip() for x in value.split(",") if x.strip()]
        if kws:
            return kws, "CAREERVIET_KEYWORDS"

    return [], None


def export_to_json(raw_jobs, out_prefix: str):
    output_file = f"{out_prefix}.json"
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump([j.to_dict() for j in raw_jobs], f, ensure_ascii=False, indent=2)
    print(f"✓ JSON saved: {output_file}")


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


def print_crawl_config(keywords_list: list, cfg: dict, source: str = "CareerViet"):
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
    base_dir = os.path.dirname(__file__)
    cfg_path = os.path.normpath(os.path.join(base_dir, "../..", "keywords_daily.json"))
    cfg = load_config(cfg_path)

    env_keywords, kw_source = load_keywords_from_env()
    if env_keywords:
        keywords_list = env_keywords
        print(f"[KEYWORDS] Loaded {len(keywords_list)} keywords from {kw_source}")
        for i, kw in enumerate(keywords_list, 1):
            print(f"[KEYWORDS] {i:02d}. {kw}")
    else:
        keywords_list = pick_keywords(cfg)

    # Output directory: use OUTPUT_FOLDER from env (set by orchestrator), fallback to data/raw/crawl_YYYYMMDD
    output_dir = os.environ.get("OUTPUT_FOLDER")
    print(f"[DEBUG] OUTPUT_FOLDER env: {output_dir}")
    
    if not output_dir:
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
    print_crawl_config(keywords_list, cfg, source="CareerViet")
    print(f"[CONFIG] Output dir: {output_dir}")
    print("=" * 85)
    
    # Run for each keyword
    for keyword in keywords_list:
        keyword = keyword.strip()
        slug = slugify(keyword)
        list_url = BASE.format(slug=slug)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_prefix = os.path.join(output_dir, f"careerviet_{slug}_{timestamp}")

        # Determine max_jobs based on tier
        tier_max_jobs = get_tier_max_jobs(keyword, cfg)
        
        print(f"\n[{keyword}] Scraping - {list_url} (tier_max_jobs={tier_max_jobs})")
        print(f"[PLANNED PATH] {out_prefix}.json")
        raw_jobs = crawl_list_url_to_raw_jobs(list_url, start_page=1, end_page=1, search_keyword=keyword, max_jobs=tier_max_jobs)
        
        if not raw_jobs:
            print(f"[WARN] No jobs found for '{keyword}'.")
            continue
        export_to_json(raw_jobs, out_prefix)
        print(f"✓ JSON saved: {out_prefix}.json ({len(raw_jobs)} jobs)")


if __name__ == "__main__":
    main()
