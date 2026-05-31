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
from scrape_linkedin import scrape_data, export_to_json, build_driver, get_next_proxy

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
    # Keep env vars passed from the pipeline (test/daily/bootstrap) and only fill missing values from .env.
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


def load_config(config_path: str):
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_keywords(cfg: dict):
    """Pick keywords based on TIER*_KEYWORDS_TO_SELECT from .env config or group_rotation"""
    mode = cfg.get("mode", "rotate").lower()
    doy = date.today().timetuple().tm_yday

    if mode == "group_rotation":
        groups = cfg.get("groups", {})
        group_names = sorted(list(groups.keys()))
        if group_names:
            # Chọn 1 nhóm dựa trên ngày trong năm
            picked_group_name = group_names[(doy - 1) % len(group_names)]
            selected = groups[picked_group_name].get("roles", [])
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
    value = os.environ.get("LINKEDIN_KEYWORDS")
    if value:
        kws = [x.strip() for x in value.split(",") if x.strip()]
        if kws:
            return kws, "LINKEDIN_KEYWORDS"

    return [], None


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
    max_pages = int(os.getenv("CRAWL_MAX_PAGES", "3"))
    print("\n" + "=" * 85)
    print(f"🔧 {source} CRAWLER CONFIG - {len(keywords_list)} keywords (max {max_pages} pages per keyword)")
    print("=" * 85)

    print(f"\nKeywords:")
    for kw in keywords_list:
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

    crawl_mode = os.getenv("PIPELINE_CRAWL_MODE", "auto").strip().lower()

    # Make the runner self-contained when it is executed directly.
    # Bootstrap must not use the recent-date filter, while daily/test keep it.
    if crawl_mode == "bootstrap":
        os.environ["JOB_DATE_MODE"] = "off"
        os.environ.pop("DAYS_BACK", None)
        os.environ.pop("REALTIME_DAYS", None)
        os.environ["LINKEDIN_SEARCH_TPR"] = "off"
        os.environ["LINKEDIN_MAX_JOBS_LIMIT"] = os.environ.get("LINKEDIN_MAX_JOBS_LIMIT", "150")
    elif crawl_mode in ("daily", "test"):
        os.environ["JOB_DATE_MODE"] = "on"
        os.environ.setdefault("DAYS_BACK", "3")
        os.environ.setdefault("REALTIME_DAYS", "3")
        os.environ.setdefault("LINKEDIN_SEARCH_TPR", "r259200")

    location = os.environ.get("LINKEDIN_LOCATION", cfg.get("location", "Vietnam"))

    # Get keywords for today
    env_keywords, kw_source = load_keywords_from_env()
    if env_keywords:
        keywords_list = env_keywords
        print(f"[KEYWORDS] Loaded {len(keywords_list)} keywords from {kw_source}")
        for i, kw in enumerate(keywords_list, 1):
            print(f"[KEYWORDS] {i:02d}. {kw}")
    else:
        keywords_list = pick_keywords(cfg)

    print(f"[INFO] Keywords to scrape: {keywords_list}\n")
    sys.stdout.flush()

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
    print_crawl_config(keywords_list, cfg, source="LinkedIn")
    print(f"[CONFIG] Location: '{location}'")
    print(f"[CONFIG] Output dir: {output_dir}")
    print("=" * 85)
    sys.stdout.flush()

    shared_driver = None
    shared_proxy = None
    detail_scrape_enabled = os.environ.get("LINKEDIN_DETAIL_SCRAPE", "true").lower() in ("true", "1", "yes")
    max_jobs_env = os.environ.get("LINKEDIN_MAX_JOBS") or os.environ.get("JOBS_PER_KEYWORD")
    max_jobs = int(max_jobs_env) if max_jobs_env and max_jobs_env.isdigit() else None

    if detail_scrape_enabled:
        try:
            shared_proxy = get_next_proxy()
            if shared_proxy:
                print(f"[INFO] Creating one shared LinkedIn driver for the whole run...")
            else:
                print(f"[INFO] Creating one shared LinkedIn driver with direct connection...")
            sys.stdout.flush()
            shared_driver = build_driver(shared_proxy)
        except Exception as e:
            print(f"[WARN] Shared LinkedIn driver init failed, falling back to per-keyword driver: {e}")
            shared_driver = None

    # Run for each keyword
    runner_start = datetime.now()
    try:
        for kw_idx, keyword in enumerate(keywords_list, 1):
            keyword = keyword.strip()
            kw_start = datetime.now()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Replace spaces in keyword for filename
            keyword_safe = keyword.lower().replace(" ", "_")
            out_prefix = os.path.join(output_dir, f"linkedin_{keyword_safe}_{location.lower().replace(' ', '_')}_{timestamp}")

            print(f"\n{'─'*85}")
            print(f"[KW {kw_idx}/{len(keywords_list)}] START: '{keyword}'")
            print(f"[PLANNED PATH] {out_prefix}.json")
            print(f"{'─'*85}")
            sys.stdout.flush()

            try:
                print(f"[{keyword}] 🔄 Scraping...")
                sys.stdout.flush()

                scrape_start = datetime.now()
                jobs = scrape_data(keyword, location, search_keyword=keyword, max_jobs=max_jobs, driver=shared_driver, close_driver=False)
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
    finally:
        if shared_driver:
            try:
                tunnel = getattr(shared_driver, '_proxy_tunnel', None)
                shared_driver.quit()
                if tunnel:
                    tunnel.stop()
                print("[INFO] Closed shared LinkedIn driver.")
            except Exception:
                pass

    runner_elapsed = (datetime.now() - runner_start).total_seconds()
    print(f"\n{'='*85}")
    print(f"[RUNNER DONE] Total time: {runner_elapsed:.1f}s")
    print(f"{'='*85}\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
