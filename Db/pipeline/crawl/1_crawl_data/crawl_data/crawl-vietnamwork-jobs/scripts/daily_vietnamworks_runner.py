#!/usr/bin/env python3
"""VietnamWorks runner - bootstrap crawl first, then daily incremental crawl."""

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

BASE = "https://www.vietnamworks.com/viec-lam?q={keyword}"
BOOTSTRAP_STATE_FILE = Path(__file__).resolve().parent / "vietnamworks_bootstrap_state.json"


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


def load_bootstrap_state() -> bool:
    """Return True if the first full VietnamWorks crawl has already completed."""
    try:
        if not BOOTSTRAP_STATE_FILE.exists():
            return False
        with open(BOOTSTRAP_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("bootstrap_completed", False))
    except Exception:
        return False


def save_bootstrap_state(output_dir: str, keyword_count: int):
    """Persist that the initial full crawl finished successfully."""
    payload = {
        "bootstrap_completed": True,
        "completed_at": datetime.now().isoformat(),
        "keyword_count": keyword_count,
        "output_dir": output_dir,
    }
    with open(BOOTSTRAP_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[STATE] Bootstrap state saved: {BOOTSTRAP_STATE_FILE}")


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

    # rotate
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
    value = os.environ.get("VNWORKS_KEYWORDS") or os.environ.get("VN_WORKS_KEYWORDS")
    if value:
        kws = [x.strip() for x in value.split(",") if x.strip()]
        if kws:
            return kws, "VNWORKS_KEYWORDS"

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


def print_crawl_config(keywords_list: list, cfg: dict, source: str = "VietnamWorks"):
    """Display crawler configuration before starting"""
    max_pages = int(os.getenv("CRAWL_MAX_PAGES", "3"))
    mode = os.getenv("VNWORKS_CRAWL_MODE", "auto").strip().lower()
    print("\n" + "=" * 85)
    print(f"🔧 {source} CRAWLER CONFIG - {len(keywords_list)} keywords (max {max_pages} pages per keyword)")
    print("=" * 85)
    print(f"\nMode: {mode}")

    print(f"\nKeywords:")
    for kw in keywords_list:
        print(f"   • {kw}")

    print("\n" + "=" * 85)


def main():
    # ============ CONFIGURATION - Chỉnh tham số ở đây ============
    NUM_KEYWORDS = None   # None = use all picked keywords (production mode), 1 = test with 1 keyword
    crawl_mode = os.getenv("VNWORKS_CRAWL_MODE", os.getenv("PIPELINE_CRAWL_MODE", "auto")).strip().lower()
    END_PAGE = 1 if crawl_mode == "test" else int(os.getenv("CRAWL_MAX_PAGES", "3"))  # Số page crawl. 1 = test mode, 5 = production
    # ============================================================

    # Crawl mode is controlled by the pipeline or environment:
    # - bootstrap/full: crawl everything (LinkedIn is capped separately in the pipeline)
    # - daily: crawl 25 jobs per keyword
    # - test: crawl 5 jobs per keyword and only the first page

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

    force_full_crawl = os.getenv("VNWORKS_FORCE_FULL_CRAWL", "").strip().lower() in ("1", "true", "yes")
    bootstrap_already_done = load_bootstrap_state()

    if crawl_mode in ("full", "bootstrap", "initial"):
        is_bootstrap_run = True
    elif crawl_mode in ("daily", "test"):
        is_bootstrap_run = False
    else:
        is_bootstrap_run = force_full_crawl or not bootstrap_already_done

    if is_bootstrap_run:
        print("[MODE] Bootstrap run: crawling all jobs available per keyword")
    elif crawl_mode == "test":
        print("[MODE] Test run: limiting to 5 jobs per keyword and 1 page")
    else:
        print("[MODE] Daily run: limiting to 20 jobs per keyword")

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
    total_crawled = 0
    total_valid = 0
    total_fallback = 0

    for keyword in keywords_list:
        clean_query = " ".join(keyword.replace("/", " ").split())
        list_url = BASE.format(keyword=clean_query.replace(" ", "+"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keyword_safe = clean_query.lower().replace(" ", "_")
        out_prefix = os.path.join(output_dir, f"vietnamworks_{keyword_safe}_{timestamp}")

        print(f"\n[{keyword}] Crawling multiple pages...")
        print(f"List URL: {list_url}")

        try:
            if is_bootstrap_run:
                max_jobs_for_keyword = 0
            else:
                max_jobs_env = os.getenv("VNWORKS_DAILY_MAX_JOBS") or os.getenv("VNWORKS_TEST_MAX_JOBS") or os.getenv("JOBS_PER_KEYWORD")
                max_jobs_for_keyword = int(max_jobs_env) if max_jobs_env and max_jobs_env.isdigit() else None

            max_jobs_text = "unlimited" if max_jobs_for_keyword == 0 else str(max_jobs_for_keyword)
            print(f"[{keyword}] Max jobs for this keyword: {max_jobs_text}")

            raw_jobs = crawl_list_url_to_raw_jobs(
                list_url_page1=list_url,
                start_page=1,
                end_page=END_PAGE,
                prefer_next=True,
                fetch_company=False,
                max_jobs=max_jobs_for_keyword,
                search_keyword=keyword,
            )

            if not raw_jobs:
                print(f"[WARN] No jobs found for '{keyword}'.")
                continue

            # Validation & Fallback logic
            import re
            valid_jobs = []
            fallback_jobs_keyword = []

            for job in raw_jobs:
                req_text = job.requirements_text or ""
                # Strip HTML tags to check text content
                clean_req = re.sub(r'<[^>]*>', '', req_text).strip()
                if clean_req.endswith('...') or clean_req.endswith('…'):
                    reason = "requirements_text is truncated (ends with ellipsis)"
                    job_dict = job.to_dict()
                    job_dict["fallback_reason"] = reason
                    fallback_jobs_keyword.append(job_dict)
                else:
                    valid_jobs.append(job)

            total_crawled += len(raw_jobs)
            total_valid += len(valid_jobs)
            total_fallback += len(fallback_jobs_keyword)

            # Print console stats for the current keyword
            if fallback_jobs_keyword:
                print(f"[FALLBACK STATS] Keyword: '{keyword}'")
                print(f"   • Total jobs crawled: {len(raw_jobs)}")
                print(f"   • Valid jobs: {len(valid_jobs)}")
                print(f"   • Fallback jobs: {len(fallback_jobs_keyword)}")
                print(f"   • Reason: requirements_text is truncated (ends with ellipsis)")

                # Save to raw_fallback.json
                fallback_dir = os.path.join(output_dir, "fallback")
                os.makedirs(fallback_dir, exist_ok=True)
                fallback_file = os.path.join(fallback_dir, "raw_fallback.json")

                existing_fallback = []
                if os.path.exists(fallback_file):
                    try:
                        with open(fallback_file, "r", encoding="utf-8") as f:
                            existing_fallback = json.load(f)
                    except Exception:
                        existing_fallback = []

                existing_fallback.extend(fallback_jobs_keyword)
                with open(fallback_file, "w", encoding="utf-8") as f:
                    json.dump(existing_fallback, f, ensure_ascii=False, indent=2)
                print(f"✓ Fallback JSON saved: {fallback_file} ({len(fallback_jobs_keyword)} jobs appended)")

            # Update raw_jobs to only contain valid jobs
            raw_jobs = valid_jobs

            out_json = f"{out_prefix}.json"
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump([j.to_dict() for j in raw_jobs], f, ensure_ascii=False, indent=2)

            print(f"✓ JSON saved: {out_json} ({len(raw_jobs)} jobs)")
        except Exception as err:
            had_error = True
            log_error(output_dir=output_dir, keyword=keyword, list_url=list_url, err=err)
            continue

    # Print final crawl stats summary
    print("\n" + "=" * 85)
    print("📊 CRAWL RUN SUMMARY")
    print("=" * 85)
    print(f"Total jobs crawled: {total_crawled}")
    print(f"Valid jobs saved:   {total_valid}")
    print(f"Fallback jobs:      {total_fallback}")
    if total_fallback > 0:
        fallback_file = os.path.join(output_dir, "fallback", "raw_fallback.json")
        print(f"Fallback filepath:  {fallback_file}")
    print("=" * 85 + "\n")

    if had_error:
        print("[ERROR] Run finished with errors. Check vietnamworks_errors.log in output directory.")
        raise SystemExit(1)

    if is_bootstrap_run:
        save_bootstrap_state(output_dir=output_dir, keyword_count=len(keywords_list))


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"[FATAL] Unhandled error: {type(err).__name__}: {err}")
        print(traceback.format_exc())
        raise
