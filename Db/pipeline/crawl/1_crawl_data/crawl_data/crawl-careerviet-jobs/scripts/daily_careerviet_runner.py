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

env_file = None
# Find Db root by searching for run_etl_pipeline.py or parents named 'db' (case-insensitive)
for parent in Path(__file__).resolve().parents:
    if (parent / "run_etl_pipeline.py").exists() or parent.name.lower() == "db":
        env_file = parent / ".env"
        break

if not env_file or not env_file.exists():
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.exists():
            env_file = candidate
            break

if env_file and env_file.exists():
    # Preserve variables passed from the pipeline; only fill missing values from .env.
    load_dotenv(env_file, override=False)
else:
    # Fallback to original hardcoded path if not found
    env_file = Path(__file__).parent.parent.parent.parent.parent / ".env"
    load_dotenv(env_file, override=False)

# Load config from .env (or defaults)
TIER1_JOBS_PER_KEYWORD = int(os.getenv("JOBS_PER_KEYWORD", "3"))
TIER2_JOBS_PER_KEYWORD = int(os.getenv("JOBS_PER_KEYWORD", "3"))
TIER3_JOBS_PER_KEYWORD = int(os.getenv("JOBS_PER_KEYWORD", "3"))

TIER1_KEYWORDS_TO_SELECT = int(os.getenv("TIER1_NUM_KEYWORDS", "1"))
TIER2_KEYWORDS_TO_SELECT = int(os.getenv("TIER2_NUM_KEYWORDS", "0"))
TIER3_KEYWORDS_TO_SELECT = int(os.getenv("TIER3_NUM_KEYWORDS", "0"))

BASE = "https://careerviet.vn/viec-lam/{slug}-kc1-vi.html"


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip().replace(" ", "-")
    s = "".join(ch for ch in s if ch.isalnum() or ch == "-")
    return s


def load_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)



def pick_keywords(cfg: dict):
    """Pick keywords: group_rotation or fallback to old rotation behavior"""
    mode = cfg.get("mode", "rotate").lower()
    doy = date.today().timetuple().tm_yday
    
    if mode == "group_rotation":
        groups = cfg.get("groups", {})
        group_names = sorted(list(groups.keys()))
        if group_names:
            # Chọn 1 nhóm dựa trên ngày trong năm
            picked_group_name = group_names[(doy - 1) % len(group_names)]
            group_cfg = groups.get(picked_group_name, {})
            selected = []
            if isinstance(group_cfg, dict):
                for lang_key in ("en", "vi", "roles"):
                    lang_keywords = group_cfg.get(lang_key, [])
                    if isinstance(lang_keywords, list):
                        selected.extend(lang_keywords)
            selected = list(dict.fromkeys(selected))  # Deduplicate
            print(f"[KEYWORDS] Day {doy} group picked: '{picked_group_name}' with {len(selected)} keywords.")
            return selected
        return []
    
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
    max_pages = int(os.getenv("CRAWL_MAX_PAGES", "3"))
    print("\n" + "=" * 85)
    print(f"🔧 {source} CRAWLER CONFIG - {len(keywords_list)} keywords (max {max_pages} pages per keyword)")
    print("=" * 85)
    
    print(f"\nKeywords:")
    for kw in keywords_list:
        print(f"   • {kw}")
    
    print("\n" + "=" * 85)


def main():
    base_dir = os.path.dirname(__file__)
    cfg_path = os.path.normpath(os.path.join(base_dir, "../..", "keywords_daily.json"))
    cfg = load_config(cfg_path)

    crawl_mode = os.environ.get("PIPELINE_CRAWL_MODE", "auto").strip().lower()

    crawl_mode = os.environ.get("PIPELINE_CRAWL_MODE", "auto").strip().lower()

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
        clean_query = " ".join(keyword.replace("/", " ").split())
        slug = slugify(clean_query)
        list_url = BASE.format(slug=slug)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_prefix = os.path.join(output_dir, f"careerviet_{slug}_{timestamp}")

        max_pages_limit = int(os.getenv("CRAWL_MAX_PAGES", "3"))
        max_jobs_env = os.getenv("CAREERVIET_MAX_JOBS") or os.getenv("JOBS_PER_KEYWORD")
        max_jobs = int(max_jobs_env) if max_jobs_env and max_jobs_env.isdigit() else None
        
        limit_text = "unlimited jobs" if max_jobs is None else f"max_jobs={max_jobs}"
        print(f"\n[{keyword}] Scraping - {list_url} ({limit_text}, max_pages={max_pages_limit})")
        print(f"[PLANNED PATH] {out_prefix}.json")
        raw_jobs = crawl_list_url_to_raw_jobs(list_url, start_page=1, end_page=max_pages_limit, search_keyword=keyword, max_jobs=max_jobs)
        
        if not raw_jobs:
            print(f"[WARN] No jobs found for '{keyword}'.")
            continue
        export_to_json(raw_jobs, out_prefix)
        print(f"✓ JSON saved: {out_prefix}.json ({len(raw_jobs)} jobs)")


if __name__ == "__main__":
    main()
