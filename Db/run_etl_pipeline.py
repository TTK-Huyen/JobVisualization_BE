#!/usr/bin/env python3
"""
ETL PIPELINE ORCHESTRATOR
Điều hướng 3 bước chính: Crawl -> Clean -> Import
Gọi các script chính trong từng folder
Kiến trúc Hybrid:
  - Crawlers → 1_crawl_data/crawl_data/output/ (tạm thời)
  - Clean → data/crawl_YYYYMMDD/clean/ (lưu trữ)
  - Import → đọc từ data/crawl_YYYYMMDD/clean/

Usage:
  python run_etl_pipeline.py                           # Auto detect latest crawl
  python run_etl_pipeline.py --input path/to/file.json # Use custom input file
  python run_etl_pipeline.py --crawl-only              # Only run crawl step
  python run_etl_pipeline.py --clean-only              # Only run clean step
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, date
from dotenv import load_dotenv

# Fix encoding for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# ============================================================================
# LOAD ENV CONFIGURATION
# ============================================================================
# Use an absolute BASE_DIR to ensure any derived folders (DATA_FOLDER, RAW_FOLDER)
# are absolute paths. This prevents relative paths being interpreted relative to
# the crawler working directory and producing duplicated prefixes like "Db/Db/...".
BASE_DIR = Path(__file__).parent.resolve()
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)
print(f"✓ Loaded .env from: {ENV_FILE}")

# Support optional pipeline/ layout while keeping backward compatibility.
# If user moves pipeline subfolders into `pipeline/`, prefer those paths;
# otherwise fall back to existing top-level folders.
PIPELINE_ROOT = BASE_DIR / "pipeline"


def resolve_pipeline_path(*parts: str) -> Path:
        """Return the pipeline-prefixed path if it exists, otherwise fallback to BASE_DIR path.

        Examples:
            resolve_pipeline_path('clean', '2_clean_data') -> pipeline/clean/2_clean_data if exists
            resolve_pipeline_path('3_import', 'import.py') -> pipeline/3_import/import.py if exists
        """
        candidate = PIPELINE_ROOT.joinpath(*parts)
        if candidate.exists():
                return candidate
        return BASE_DIR.joinpath(*parts)


# ============================================================================
# CONFIGURATION
# ============================================================================

# Use .venv Python executable if available; resolve to absolute path so
# subprocess calls use an absolute interpreter path regardless of cwd.
VENV_PYTHON = (BASE_DIR / ".venv" / "Scripts" / "python.exe").resolve()
if VENV_PYTHON.exists():
    PYTHON_EXE = str(VENV_PYTHON)
    print(f"✓ Using .venv Python: {PYTHON_EXE}")
else:
    PYTHON_EXE = sys.executable
    print(f"⚠ .venv not found, using system Python: {PYTHON_EXE}")

# Import config
try:
    from input import (
        JOB_LIMITS,
        JOBS_PER_KEYWORD,
        KEYWORD_SELECTION_CONFIG,
        PIPELINE_STEPS,
        CRAWLER_TIMEOUTS,
        print_config,
        print_api_status,
    )
    print("\n" + "="*80)
    print("✅ Config loaded from input package")
    print("="*80)
    print_config()
    print_api_status()
    print("="*80 + "\n")
except ImportError as e:
    print(f"❌ Error importing from input package: {e}")
    print("Fallback to default values")
    JOB_LIMITS = {"itviec": 1, "linkedin": 1, "careerviet": 1, "vietnamworks": 1}
    JOBS_PER_KEYWORD = 3
    KEYWORD_SELECTION_CONFIG = {}
    PIPELINE_STEPS = {"crawl": True, "clean": True, "import": True}
    CRAWLER_TIMEOUTS = {"itviec": 600, "linkedin": 300, "careerviet": 600, "vietnamworks": 600}

# Timeouts (fixed)
CRAWLER_TIMEOUT = 1200  # 20 phút
CLEAN_TIMEOUT = 600     # 10 phút
IMPORT_TIMEOUT = 900    # 15 phút

# ============================================================================
# ETL PIPELINE CONFIG - Load from .env
# ============================================================================
ETL_CONFIG = {
    "input_file": os.getenv("ETL_INPUT_FILE", ""),  # Custom input file (empty = auto-detect)
    "batch_size": int(os.getenv("ETL_CLEAN_BATCH_SIZE", "60")),  # Batch size for CLEAN step
    "max_threads": int(os.getenv("ETL_MAX_THREADS", "30")),  # Max parallel threads for LLM extraction
    "confidence_threshold": float(os.getenv("ETL_CONFIDENCE_THRESHOLD", "0.7")),  # Min confidence for skills/benefits
}

KEYWORD_CONFIG = {
    "daily_num_keywords": int(os.getenv("DAILY_NUM_KEYWORDS", "10")),
    "selection_method": os.getenv("KEYWORD_SELECTION_METHOD", "sequential").strip().lower(),
    "rotation_state_path": os.getenv(
        "KEYWORD_ROTATION_STATE_PATH",
        "2_clean_data/cache/keyword_rotation_state.json",
    ),
    "keywords_file": os.getenv(
        "KEYWORDS_DAILY_PATH",
        "input/keywords_daily.json",
    ),
}

print(f"\n🔥 ETL CONFIG (from .env):")
print(f"  → Input file: {ETL_CONFIG['input_file'] or 'AUTO-DETECT'}")
print(f"  → Batch size: {ETL_CONFIG['batch_size']}")
print(f"  → Max threads: {ETL_CONFIG['max_threads']}")
print(f"  → Confidence threshold: {ETL_CONFIG['confidence_threshold']}")
print(f"  → Daily keywords: {KEYWORD_CONFIG['daily_num_keywords']}")
print(f"  → Keyword method: {KEYWORD_CONFIG['selection_method']}")
print(f"  → Keyword state: {KEYWORD_CONFIG['rotation_state_path']}")
print()

# Date-time-based folder for archival (avoid overwrite)
RUN_DATE = datetime.now().strftime("%Y%m%d_%H%M%S")
DATA_FOLDER = BASE_DIR / "data" / f"crawl_{RUN_DATE}"
RAW_FOLDER = DATA_FOLDER / "raw"
CLEAN_FOLDER = DATA_FOLDER / "clean"
FALLBACK_FOLDER = DATA_FOLDER / "fallback"
LOGS_FOLDER = DATA_FOLDER / "logs"

# ============================================================================
# HELPER
# ============================================================================
def log(msg):
    """Simple logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")

def run_step(name, script_path, args=None, timeout=600, cwd=None, env=None, is_batch=False):
    """Execute a script (Python or Batch) as a step"""
    log(f"{name}...")
    
    if not script_path.exists():
        log(f"{script_path} không tồn tại")
        return False
    
    # For .bat files on Windows, use cmd /c
    if is_batch or str(script_path).endswith('.bat'):
        cmd = ['cmd', '/c', str(script_path)]
    else:
        # Use absolute script path to avoid cwd-relative duplication when
        # spawning the Python interpreter in a different working directory.
        script_abspath = str(Path(script_path).resolve())
        cmd = [PYTHON_EXE, script_abspath]
    
    if args:
        cmd.extend(args)
    
    # Merge environment variables
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    
    try:
        # Stream output in realtime instead of buffering (no capture_output)
        result = subprocess.run(
            cmd,
            cwd=str(cwd or script_path.parent),
            text=True,
            encoding='utf-8',
            timeout=timeout,
            env=run_env
        )
        
        if result.returncode == 0:
            log(f"{name} thành công\n")
            return True
        else:
            log(f"{name} thất bại\n")
            return False
    except subprocess.TimeoutExpired:
        log(f"{name} timeout\n")
        return False
    except Exception as e:
        log(f"{name} lỗi: {e}\n")
        return False


def _safe_delete(path: Path) -> bool:
    """Delete a file if it exists. Returns True on success or when already absent."""
    try:
        if path.exists() and path.is_file():
            path.unlink()
            log(f"[CLEANUP] Deleted {path}")
        return True
    except Exception as exc:
        log(f"[CLEANUP] Could not delete {path}: {exc}")
        return False


def cleanup_retention_artifacts():
    """Keep only long-lived artifacts after a successful full pipeline run."""
    cleanup_ok = True

    # Clean folder: keep only the final import-ready file.
    if CLEAN_FOLDER.exists():
        for item in sorted(CLEAN_FOLDER.rglob("*"), reverse=True):
            if item.is_file() and item.name != "import_ready.json":
                cleanup_ok = _safe_delete(item) and cleanup_ok
            elif item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    pass

    # Keep logs/ intact for debugging and history.
    # No deletion is performed inside LOGS_FOLDER.

    # Historical temp files that may appear at the crawl archive root.
    root_cleanup_patterns = [
        DATA_FOLDER / "output_1_cleaned.json",
        DATA_FOLDER / "output_2_sections.json",
    ]
    for item in root_cleanup_patterns:
        cleanup_ok = _safe_delete(item) and cleanup_ok

    for item in sorted(DATA_FOLDER.rglob("batch_*.json"), reverse=True):
        if LOGS_FOLDER in item.parents:
            continue
        cleanup_ok = _safe_delete(item) and cleanup_ok

    for item in sorted(DATA_FOLDER.rglob("retry_r*.json"), reverse=True):
        if LOGS_FOLDER in item.parents:
            continue
        cleanup_ok = _safe_delete(item) and cleanup_ok

    return cleanup_ok



def _resolve_project_path(path_value: str) -> Path:
    """Resolve a path from .env relative to BASE_DIR unless it is already absolute."""
    path = Path(path_value)
    return path if path.is_absolute() else (BASE_DIR / path)


def _dedupe_keep_order(items):
    """Remove duplicate keywords while preserving the original order."""
    seen = set()
    result = []
    for item in items:
        keyword = str(item).strip()
        if not keyword:
            continue
        key = keyword.lower()
        if key not in seen:
            seen.add(key)
            result.append(keyword)
    return result


def _flatten_keywords_daily(config: dict) -> list:
    """
    Support both old tier format and new group_rotation format.

    Accepted formats:
      - {"tier_1": [...], "tier_2": [...], "tier_3": [...]}
      - {"mode": "group_rotation", "groups": {"group": {"roles": [...], "clusters": {...}}}}
    """
    keywords = []

    for tier_key in ("tier_1", "tier_2", "tier_3"):
        tier_keywords = config.get(tier_key, [])
        if isinstance(tier_keywords, list):
            keywords.extend(tier_keywords)

    groups = config.get("groups", {})
    if isinstance(groups, dict):
        for group_cfg in groups.values():
            if not isinstance(group_cfg, dict):
                continue

            roles = group_cfg.get("roles", [])
            if isinstance(roles, list):
                keywords.extend(roles)

            clusters = group_cfg.get("clusters", {})
            if isinstance(clusters, dict):
                for cluster_roles in clusters.values():
                    if isinstance(cluster_roles, list):
                        keywords.extend(cluster_roles)

    return _dedupe_keep_order(keywords)


def select_daily_keywords() -> list:
    """
    Select DAILY_NUM_KEYWORDS sequentially and persist rotation state.

    Same calendar date reuses the same selected keywords, so rerunning the
    pipeline on the same day does not accidentally advance the rotation.
    """
    num_keywords = max(1, KEYWORD_CONFIG["daily_num_keywords"])
    method = KEYWORD_CONFIG["selection_method"]
    keywords_file = _resolve_project_path(KEYWORD_CONFIG["keywords_file"])
    state_path = _resolve_project_path(KEYWORD_CONFIG["rotation_state_path"])
    today = date.today().isoformat()

    if not keywords_file.exists():
        # Check common fallback locations in order of preference
        fallback_candidates = [
            BASE_DIR / "input" / "keywords_daily.json",
            BASE_DIR / "keywords_daily.json",
        ]
        found = None
        for cand in fallback_candidates:
            if cand.exists():
                found = cand
                break
        if found:
            keywords_file = found
        else:
            log(f"⚠️ Keyword file not found: {keywords_file}")
            return []

    with open(keywords_file, encoding="utf-8") as f:
        keyword_cfg = json.load(f)

    all_keywords = _flatten_keywords_daily(keyword_cfg)
    if not all_keywords:
        log(f"⚠️ No keywords found in: {keywords_file}")
        return []

    state = {}
    if state_path.exists():
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
        except Exception as exc:
            log(f"⚠️ Cannot read keyword rotation state, starting from 0: {exc}")
            state = {}

    if (
        state.get("last_run_date") == today
        and isinstance(state.get("selected_keywords"), list)
        and state.get("all_keywords_count") == len(all_keywords)
        and state.get("daily_num_keywords") == num_keywords
    ):
        selected = state["selected_keywords"][:num_keywords]
        log(f"🔁 Reusing today's keyword batch from state: {state_path}")
        return selected

    if method != "sequential":
        log(f"⚠️ Unsupported KEYWORD_SELECTION_METHOD={method}; fallback to sequential")

    start_index = int(state.get("next_index", 0) or 0) % len(all_keywords)
    selected = [
        all_keywords[(start_index + offset) % len(all_keywords)]
        for offset in range(min(num_keywords, len(all_keywords)))
    ]
    next_index = (start_index + len(selected)) % len(all_keywords)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    new_state = {
        "last_run_date": today,
        "method": "sequential",
        "daily_num_keywords": num_keywords,
        "all_keywords_count": len(all_keywords),
        "start_index": start_index,
        "next_index": next_index,
        "selected_keywords": selected,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "keywords_file": str(keywords_file),
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(new_state, f, ensure_ascii=False, indent=2)

    return selected


def write_selected_keywords_file(selected_keywords: list) -> Path:
    """Write selected keywords for audit/debug and for crawlers that accept a file path."""
    selected_file = RAW_FOLDER / "selected_keywords.json"
    selected_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_date": RUN_DATE,
        "selected_date": date.today().isoformat(),
        "selection_method": "sequential",
        "jobs_per_keyword": JOBS_PER_KEYWORD,
        "num_keywords": len(selected_keywords),
        "keywords": selected_keywords,
    }
    with open(selected_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return selected_file



def estimate_and_display_runtime():
    """Calculate and display estimated runtime for today's pipeline"""
    try:
        total_keywords = KEYWORD_CONFIG["daily_num_keywords"]
        total_jobs = total_keywords * JOBS_PER_KEYWORD

        # Estimate times
        crawl_time = 46  # seconds (from performance analysis)
        merge_time = 6   # seconds
        clean_time = 5 + (total_jobs * 0.55)  # ~0.55s per job

        log("\n" + "=" * 85)
        log("⏱️  ESTIMATED RUNTIME FOR TODAY'S CRAWL+CLEAN")
        log("=" * 85)
        log(f"\n📊 CONFIG:")
        log(f"   Keywords: {total_keywords} ({KEYWORD_CONFIG['selection_method']})")
        log(f"   Jobs per keyword: {JOBS_PER_KEYWORD}")
        log(f"   Total jobs: ~{total_jobs}")

        log(f"\n⏱️  TIMELINE:")
        log(f"   🔍 CRAWL (parallel):     ~{int(crawl_time)}s")
        log(f"   📦 MERGE (sequential):   ~{int(merge_time)}s")
        log(f"   🧹 CLEAN (sequential):   ~{int(clean_time):.0f}s")
        log(f"   ────────────────────────────────")
        log(f"   TOTAL EXECUTION:        ~{int(crawl_time + merge_time + clean_time)}s ({(crawl_time + merge_time + clean_time)/60:.1f}m)")
        log(f"\n" + "=" * 85 + "\n")

    except Exception:
        pass  # Silently fail if estimation can't be done


# ============================================================================
# MAIN
# ============================================================================
def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="ETL Pipeline: Crawl → Clean → Import",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_etl_pipeline.py                                  # Auto detect latest crawl
  python run_etl_pipeline.py --input path/to/jobs.json       # Use custom input file for clean step
  python run_etl_pipeline.py --crawl-only                     # Only run crawl + merge
  python run_etl_pipeline.py --clean-only --input jobs.json   # Only run clean step with custom input
        """
    )
    parser.add_argument(
        "--input", 
        type=str,
        default=ETL_CONFIG["input_file"] if ETL_CONFIG["input_file"] else None,
        help=f"Custom input file for CLEAN step (default: auto-detect, or use ETL_INPUT_FILE from .env)"
    )
    parser.add_argument(
        "--extracted",
        type=str,
        default=None,
        help="Path to an already-extracted LLM output (extracted.json). If provided, skip LLM extract step.",
    )
    parser.add_argument(
        "--normalized",
        type=str,
        default=None,
        help="Path to an already-normalized file (normalized.json produced by normalize_embeddings). If provided, skip normalization step.",
    )
    parser.add_argument(
        "--crawl-only", 
        action="store_true", 
        help="Only run CRAWL step (skip CLEAN and IMPORT)"
    )
    parser.add_argument(
        "--clean-only", 
        action="store_true", 
        help="Only run CLEAN step (requires --input or auto-detection)"
    )
    parser.add_argument(
        "--import-only", 
        action="store_true", 
        help="Only run IMPORT step"
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Run full pipeline but skip IMPORT step",
    )
    
    args = parser.parse_args()
    
    # Override PIPELINE_STEPS based on command line flags
    global PIPELINE_STEPS
    if args.crawl_only:
        PIPELINE_STEPS = {"crawl": True, "clean": False, "import": False}
    elif args.clean_only:
        PIPELINE_STEPS = {"crawl": False, "clean": True, "import": False}
    elif args.import_only:
        PIPELINE_STEPS = {"crawl": False, "clean": False, "import": True}
    # allow skipping import explicitly while keeping default crawl+clean
    if args.skip_import:
        # respect other flags: if user asked only crawl/clean/import, keep those
        if not (args.crawl_only or args.clean_only or args.import_only):
            PIPELINE_STEPS = {"crawl": True, "clean": True, "import": False}
    
    log("=" * 80)
    log("ETL PIPELINE START")
    log(f"Run Date: {RUN_DATE}")
    log(f"Archive: {DATA_FOLDER}")
    log("=" * 80 + "\n")
    
    # Display estimated runtime
    estimate_and_display_runtime()
    
    # Read step control flags from PIPELINE_STEPS config (not environment variables)
    step_crawl = PIPELINE_STEPS.get("crawl", True)
    step_clean = PIPELINE_STEPS.get("clean", True)
    step_import = PIPELINE_STEPS.get("import", True)
    
    log(f"Steps: CRAWL (incl. MERGE)={step_crawl}, CLEAN={step_clean}, IMPORT={step_import}\n")
    
    start = datetime.now()
    
    # Create archive folders
    RAW_FOLDER.mkdir(parents=True, exist_ok=True)
    CLEAN_FOLDER.mkdir(parents=True, exist_ok=True)
    FALLBACK_FOLDER.mkdir(parents=True, exist_ok=True)
    LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
    
    crawl_ok = True
    clean_ok = True
    import_ok = True
    
    # -------- STEP 1: CRAWL --------
    if step_crawl:
        log("STEP 1: CRAWL DATA")
        
        # Prepare environment variables for crawlers
        crawl_env = os.environ.copy()  # Inherit current env
        crawl_env.update({
            "RUN_DATE": RUN_DATE,  # Pass RUN_DATE so merge/normalize use same folder
            "OUTPUT_FOLDER": str(RAW_FOLDER),
            "RAW_DATA_FOLDER": str(RAW_FOLDER),
        })

        selected_keywords = select_daily_keywords()
        if selected_keywords:
            selected_keywords_file = write_selected_keywords_file(selected_keywords)
            keywords_json = json.dumps(selected_keywords, ensure_ascii=False)

            # Pass multiple env aliases so existing crawler runners can consume the
            # selected batch without changing their CLI contract.
            crawl_env.update({
                "DAILY_NUM_KEYWORDS": str(len(selected_keywords)),
                "KEYWORD_SELECTION_METHOD": "sequential",
                "JOBS_PER_KEYWORD": str(JOBS_PER_KEYWORD),
                "SELECTED_KEYWORDS": ",".join(selected_keywords),
                "CRAWL_KEYWORDS": ",".join(selected_keywords),
                "KEYWORDS": ",".join(selected_keywords),
                "SELECTED_KEYWORDS_JSON": keywords_json,
                "CRAWL_KEYWORDS_JSON": keywords_json,
                "DAILY_KEYWORDS_JSON": keywords_json,
                "SELECTED_KEYWORDS_FILE": str(selected_keywords_file),
                "CRAWL_KEYWORDS_FILE": str(selected_keywords_file),
            })

            log("🎯 Today's selected keywords:")
            for idx, keyword in enumerate(selected_keywords, start=1):
                log(f"   {idx:02d}. {keyword}")
            log(f"   Saved to: {selected_keywords_file}")
        else:
            log("⚠️ No selected keywords were generated; crawlers will use their own defaults.")
        
        # Deprecated: Job limits are now defined in input package (config_jobs.py) via .env
        # log(f"Job Limits: iTviec={JOB_LIMITS.get('itviec', 50)}, LinkedIn={JOB_LIMITS.get('linkedin', 100)}, CareerViet={JOB_LIMITS.get('careerviet', 50)}, VietnamWorks={JOB_LIMITS.get('vietnamworks', 50)}")
        
        # Call daily runners directly (not via .bat) to preserve environment variables
        crawlers = [
            ("ITviec", "crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py", "itviec"),
            ("LinkedIn", "crawl_data/crawl-linkedin-jobs/scripts/daily_linkedin_runner.py", "linkedin"),
            ("CareerViet", "crawl_data/crawl-careerviet-jobs/scripts/daily_careerviet_runner.py", "careerviet"),
            ("VietnamWorks", "crawl_data/crawl-vietnamwork-jobs/scripts/daily_vietnamworks_runner.py", "vietnamworks"),
        ]

        # Prefer pipeline/crawl/1_crawl_data when present, else fallback to top-level 1_crawl_data
        crawl_dir = resolve_pipeline_path("crawl", "1_crawl_data")
        
        for crawler_name, crawler_path, limit_key in crawlers:
            # Skip crawlers with 0 job limit
            if JOB_LIMITS.get(limit_key, 1) == 0:
                log(f"Skipping {crawler_name} crawler (job_limit=0)")
                continue
            
            crawler_script = crawl_dir / crawler_path
            if crawler_script.exists():
                log(f"Running {crawler_name} crawler...")
                # Use per-crawler timeout
                crawler_timeout = CRAWLER_TIMEOUTS.get(limit_key, 600)
                if not run_step(f"{crawler_name} Crawler", crawler_script, timeout=crawler_timeout, cwd=crawl_dir, env=crawl_env):
                    log(f"⚠️  {crawler_name} crawler skipped (timeout or error)")
            else:
                log(f"⚠️  {crawler_name} crawler not found: {crawler_script}")
        
        # ---- MERGE (automatically after crawl) ----
        log("Merging crawler outputs...")
        merge_script = crawl_dir / "merge_daily_outputs.py"
        if merge_script.exists():
            crawl_ok = run_step("Merge Outputs", merge_script, timeout=CRAWLER_TIMEOUT, cwd=crawl_dir, env=crawl_env)
        else:
            log("⚠️  Merge script not found")
            crawl_ok = False
        
        if not crawl_ok:
            log("Crawl failed")
    else:
        log("Skipping CRAWL (STEP_CRAWL=false)\n")
    
    # -------- STEP 2: CLEAN -> PENDING -> EXTRACT -> NORMALIZE -> TRANSFORM --------
    if step_clean:
        log("STEP 2: CLEAN DATA (debug clean -> pending_llm -> extracted -> normalized -> import_ready)")

        raw_combined = None
        if args.input:
            custom_input = Path(args.input)
            if custom_input.exists():
                raw_combined = custom_input
                log(f"Using custom input for clean flow: {custom_input.name}")
            else:
                log(f"❌ Custom input file not found: {args.input}")
                clean_ok = False

        if raw_combined is None and clean_ok:
            raw_combined = RAW_FOLDER / "jobs_combined.json"

        # If the default raw_combined doesn't exist, try pipeline or repo candidates.
        if not raw_combined or not raw_combined.exists():
            pipeline_candidate = resolve_pipeline_path("crawl", "data", f"crawl_{RUN_DATE}", "raw", "jobs_combined.json")
            repo_candidate = BASE_DIR / "data" / f"crawl_{RUN_DATE}" / "raw" / "jobs_combined.json"
            if pipeline_candidate.exists():
                raw_combined = pipeline_candidate
            elif repo_candidate.exists():
                raw_combined = repo_candidate

        # After attempting fallbacks, ensure we have a valid input before running clean flow
        if not raw_combined or not raw_combined.exists():
            log("❌ No raw combined input found for cleaning")
            clean_ok = False
        else:
            pending_file = CLEAN_FOLDER / "pending_llm.json"
            # allow user-provided extracted/normalized files via CLI
            extracted_file = Path(args.extracted) if args.extracted else (CLEAN_FOLDER / "extracted.json")
            normalized_file = Path(args.normalized) if args.normalized else (CLEAN_FOLDER / "normalized.json")

            extract_fallback_file = FALLBACK_FOLDER / "extract_fallback.json"
   

            # Resolve scripts to pipeline layout if files were moved into pipeline/
            clean_dir = resolve_pipeline_path("clean", "2_clean_data")
            clean_script = clean_dir / "clean_process.py"
            # Prefer pipeline/extract/process_pending_llm.py, fallback to pipeline/process_pending_llm.py or top-level
            extract_script = resolve_pipeline_path("extract", "process_pending_llm.py")
            if not extract_script.exists():
                extract_script = resolve_pipeline_path("process_pending_llm.py")
            # transform_for_import.py lives in 2_1_normalized_data; prefer pipeline layout
            transform_script = resolve_pipeline_path("normalize", "2_1_normalized_data", "transform_for_import.py")
            if not transform_script.exists():
                transform_script = BASE_DIR / "2_1_normalized_data" / "transform_for_import.py"

            if clean_script.exists():
                clean_ok = run_step(
                    "CLEAN STEP 1",
                    clean_script,
                    args=[str(raw_combined), "--step", "1", "--output", str(pending_file)],
                    timeout=CLEAN_TIMEOUT,
                    cwd=clean_dir,
                )
            else:
                log(f"⚠️  Clean script not found: {clean_script}")
                clean_ok = False

            # Run LLM extract only if an extracted file was not provided
            if args.extracted:
                log(f"Skipping LLM EXTRACT because extracted file provided: {extracted_file}")
            elif clean_ok and extract_script.exists():
                # Run extract from project root so top-level package imports (e.g., `from Db...`) resolve.
                extract_env = os.environ.copy()
                existing_py = extract_env.get("PYTHONPATH", "")
                # Ensure both project `Db/` (BASE_DIR) and its parent are on PYTHONPATH
                prepend_paths = os.pathsep.join([str(BASE_DIR), str(BASE_DIR.parent)])
                extract_env["PYTHONPATH"] = prepend_paths + (os.pathsep + existing_py if existing_py else "")

                # Run extract from parent of BASE_DIR so `import Db...` resolves correctly
                extract_cwd = BASE_DIR.parent
                clean_ok = run_step(
                    "LLM EXTRACT",
                    extract_script,
                    args=["--input-path", str(pending_file), "--output-path", str(extracted_file), "--fallback-path", str(extract_fallback_file)],
                    timeout=CLEAN_TIMEOUT,
                    cwd=extract_cwd,
                    env=extract_env,
                )
            elif clean_ok:
                log(f"⚠️  Extract script not found: {extract_script}")
                clean_ok = False

            # Use the new normalize runner inside 2_1_normalized_data
            normalize_entry = resolve_pipeline_path("normalize", "2_1_normalized_data", "normalize_embeddings.py")
            # Run normalization only if normalized file not provided
            if args.normalized:
                log(f"Skipping NORMALIZE because normalized file provided: {normalized_file}")
            elif clean_ok and normalize_entry.exists():
                # call run_normalize with run-date and default level=2 (full)
                # Use directory of normalize_entry if available in pipeline layout
                normalize_cwd = normalize_entry.parent if normalize_entry.exists() else resolve_pipeline_path("2_1_normalized_data")
                clean_ok = run_step(
                    "NORMALIZE",
                    normalize_entry,
                    args=[
                        "--input", str(extracted_file),
                        "--output", str(normalized_file),
                    ],
                    timeout=CLEAN_TIMEOUT,
                    cwd=normalize_cwd,
                )
            elif clean_ok:
                log(f"⚠️  Normalize entry not found: {normalize_entry}")
                clean_ok = False
            elif clean_ok:
                clean_ok = False

            
            if clean_ok and not pending_file.exists():
                log(f"❌ Pending queue not found: {pending_file}")
                clean_ok = False
            if clean_ok and not extracted_file.exists():
                log(f"❌ Extracted output not found: {extracted_file}")
                clean_ok = False
            if clean_ok and not normalized_file.exists():
                log(f"❌ Normalized output not found: {normalized_file}")
                clean_ok = False
            

            if clean_ok:
                log(f"[OK] Clean outputs ready:")
                log(f"  pending_llm  -> {pending_file.name}")
                log(f"  extracted    -> {extracted_file.name}")
                log(f"  normalized   -> {normalized_file.name}")
                log(f"  import input -> {normalized_file.name}")
            else:
                log("Clean failed")
    else:
        log("Skipping CLEAN (STEP_CLEAN=false)\n")

    # -------- STEP 3: IMPORT --------
    if step_import:
        log("STEP 3: IMPORT TO DATABASE")
        # Prefer pipeline/import_db then pipeline/import for import step
        import_script = resolve_pipeline_path("import_db", "3_import", "import.py")
        if not import_script.exists():
            import_script = resolve_pipeline_path("import", "3_import", "import.py")
        import_input = CLEAN_FOLDER / "normalized.json"

        if import_input.exists():
            log(f"Using normalized output: {import_input.name}")
            import_args = ["--input", str(import_input)]
            import_ok = run_step(
                "IMPORT",
                import_script,
                args=import_args,
                timeout=IMPORT_TIMEOUT,
                cwd=import_script.parent
            )
            if not import_ok:
                log("Import failed")
        else:
            log("❌ No normalized data found for import")
            import_ok = False
    else:
        log("Skipping IMPORT (STEP_IMPORT=false)\n")
    
    # -------- SUMMARY --------
    cleanup_ok = True
    should_cleanup = step_clean and step_import and crawl_ok and clean_ok and import_ok
    if should_cleanup:
        log("Running retention cleanup for transient artifacts...")
        cleanup_ok = cleanup_retention_artifacts()
        if cleanup_ok:
            log("Retention cleanup complete")
        else:
            log("Retention cleanup completed with warnings")

    log("=" * 80)
    log("SUMMARY")
    log("=" * 80)
    log(f"Crawl  : {'Done' if crawl_ok else 'Skipped/Failed'}")
    log(f"Clean  : {'Done' if clean_ok else 'Skipped/Failed'}")
    log(f"Import : {'Done' if import_ok else 'Skipped/Failed'}")
    log(f"Cleanup: {'Done' if cleanup_ok else ('Skipped' if not should_cleanup else 'Warnings')}")
    log(f"(API calls tracked in CLEAN step summary above)")
    
    duration = datetime.now() - start
    log(f"Duration: {duration}")
    log("=" * 80)
    
    return crawl_ok and clean_ok and import_ok

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
