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
        python run_etl_pipeline.py --crawl-mode daily        # Daily crawl (default)
        python run_etl_pipeline.py --crawl-mode bootstrap    # Full bootstrap crawl
        python run_etl_pipeline.py --parallel-crawl          # Run daily crawl in parallel
"""

import os
import sys
import json
import argparse
import concurrent.futures
import importlib
import subprocess
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, date, timedelta
from urllib.parse import quote_plus
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
load_dotenv(ENV_FILE, override=False)
print(f"✓ Loaded .env from: {ENV_FILE}")

# Support optional pipeline/ layout while keeping backward compatibility.
# If user moves pipeline subfolders into `pipeline/`, prefer those paths;
# otherwise fall back to existing top-level folders.
PIPELINE_ROOT = BASE_DIR / "pipeline"
CRAWL_DATA_ROOT = PIPELINE_ROOT / "crawl" / "1_crawl_data" / "crawl_data"


def ensure_crawler_import_paths():
    """Make crawler scripts and shared crawl helpers importable in-process."""
    candidate_paths = [
        CRAWL_DATA_ROOT,
        CRAWL_DATA_ROOT / "crawl-itviec-jobs" / "scripts",
        CRAWL_DATA_ROOT / "crawl-vietnamwork-jobs" / "scripts",
        CRAWL_DATA_ROOT / "crawl-careerviet-jobs" / "scripts",
        CRAWL_DATA_ROOT / "crawl-linkedin-jobs" / "scripts",
    ]
    for candidate in candidate_paths:
        candidate_str = str(candidate)
        if candidate.exists() and candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


ensure_crawler_import_paths()


def filter_recent_jobs_safe(raw_jobs):
    """Post-scrape date filtering bypassed per user request (relying on early filter at list crawl phase)"""
    return raw_jobs


def resolve_pipeline_path(*parts: str) -> Path:
        """Return the pipeline-prefixed path if it exists, otherwise fallback to BASE_DIR path.

        Examples:
            resolve_pipeline_path('clean', '2_clean_data') -> pipeline/clean/2_clean_data if exists
            resolve_pipeline_path('3_import', 'import.py') -> pipeline/3_import/import.py if exists
        """
        candidate = PIPELINE_ROOT.joinpath(*parts)
        if candidate.exists():
                return candidate
        alt = BASE_DIR.joinpath(*parts)
        if alt.exists():
            return alt

        return None

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
        CRAWL_MAX_PAGES,
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
    JOBS_PER_KEYWORD = None
    CRAWL_MAX_PAGES = 3
    KEYWORD_SELECTION_CONFIG = {}
    PIPELINE_STEPS = {"crawl": True, "clean": True, "import": True}
    CRAWLER_TIMEOUTS = {"itviec": 600, "linkedin": 300, "careerviet": 600, "vietnamworks": 600}

# Timeouts (fixed)
CRAWLER_TIMEOUT = 1200  # 20 phút
CLEAN_TIMEOUT = 600     # 10 phút
IMPORT_TIMEOUT = 900    # 15 phút

PIPELINE_CRAWL_STATE_FILE = BASE_DIR / "data" / "pipeline_crawl_state.json"

# ============================================================================
# ETL PIPELINE CONFIG - Load from .env
# ============================================================================
ETL_CONFIG = {
    "input_file": os.getenv("ETL_INPUT_FILE", ""),  # Custom input file (empty = auto-detect)
    "batch_size": int(os.getenv("ETL_CLEAN_BATCH_SIZE", "60")),  # Batch size for CLEAN step
    "max_threads": int(os.getenv("ETL_MAX_THREADS", "30")),  # Max parallel threads for LLM extraction
    "confidence_threshold": float(os.getenv("ETL_CONFIDENCE_THRESHOLD", "0.7")),  # Min confidence for skills/benefits
    # Timeout (seconds) for the LLM extract step. Can be overridden with ETL_LLM_TIMEOUT in .env
    "llm_timeout": int(os.getenv("ETL_LLM_TIMEOUT", "1800")),
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

# If a test keywords file exists and the user asked to use test keywords via
# `USE_TEST_KEYWORDS` env var, prefer it. Also prefer it when no explicit
# `KEYWORDS_DAILY_PATH` env var is provided but a `Db/input/test_keywords_daily.json`
# file is present (convenience for local testing).
test_candidate_paths = [
    BASE_DIR / "Db" / "input" / "test_keywords_daily.json",
    BASE_DIR / "input" / "test_keywords_daily.json",
]
use_test_flag = os.getenv("USE_TEST_KEYWORDS", "").strip().lower() in ("1", "true", "yes")
env_kw_path = os.environ.get("KEYWORDS_DAILY_PATH")
for tp in test_candidate_paths:
    if tp.exists():
        if use_test_flag or not env_kw_path:
            KEYWORD_CONFIG["keywords_file"] = str(tp.relative_to(BASE_DIR))
            print(f"Using test keywords file for selection: {KEYWORD_CONFIG['keywords_file']}")
        break

print(f"\n🔥 ETL CONFIG (from .env):")
print(f"  → Input file: {ETL_CONFIG['input_file'] or 'AUTO-DETECT'}")
print(f"  → Batch size: {ETL_CONFIG['batch_size']}")
print(f"  → Max threads: {ETL_CONFIG['max_threads']}")
print(f"  → Confidence threshold: {ETL_CONFIG['confidence_threshold']}")
print(f"  → LLM extract timeout: {ETL_CONFIG['llm_timeout']}s")
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

# Global log file handle - will be set when LOGS_FOLDER is created in main()
_LOG_FILE_HANDLE = None
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr

class TeeStream:
    def __init__(self, original_stream):
        self.original_stream = original_stream

    def write(self, data):
        self.original_stream.write(data)
        self.original_stream.flush()
        if _LOG_FILE_HANDLE is not None:
            try:
                _LOG_FILE_HANDLE.write(data)
                _LOG_FILE_HANDLE.flush()
            except Exception:
                pass

    def flush(self):
        self.original_stream.flush()
        if _LOG_FILE_HANDLE is not None:
            try:
                _LOG_FILE_HANDLE.flush()
            except Exception:
                pass

    def __getattr__(self, attr):
        return getattr(self.original_stream, attr)

# ============================================================================
# HELPER
# ============================================================================
def log(msg):
    """Simple logging — writes to stdout (which TeeStream replicates to the log file)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)


def _open_log_file(logs_folder: Path) -> None:
    """Open (or create) the session log file and store the handle globally."""
    global _LOG_FILE_HANDLE
    try:
        logs_folder.mkdir(parents=True, exist_ok=True)
        log_path = logs_folder / f"pipeline_{RUN_DATE}.log"
        _LOG_FILE_HANDLE = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = TeeStream(_ORIGINAL_STDOUT)
        sys.stderr = TeeStream(_ORIGINAL_STDERR)
        log(f"📄 Log file: {log_path}")
    except Exception as exc:
        print(f"[WARN] Could not open log file: {exc}")


def _close_log_file() -> None:
    """Close the session log file and restore original stdout/stderr streams."""
    global _LOG_FILE_HANDLE
    sys.stdout = _ORIGINAL_STDOUT
    sys.stderr = _ORIGINAL_STDERR
    if _LOG_FILE_HANDLE is not None:
        try:
            _LOG_FILE_HANDLE.close()
        except Exception:
            pass
        _LOG_FILE_HANDLE = None


def validate_crawl_date_filter(raw_combined_path: Path, crawl_env: dict, crawl_mode: str):
    """Check whether crawled jobs respect the configured date filter."""
    # Bỏ hoàn toàn việc lọc/cảnh báo ngày ở bước sau theo yêu cầu người dùng (Phương án 2)
    return

    def parse_job_date(value):
        if value is None:
            return None
        if isinstance(value, date):
            return value

        value_text = str(value).strip()
        if not value_text:
            return None

        try:
            return datetime.fromisoformat(value_text.replace("Z", "+00:00")).date()
        except ValueError:
            pass

        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(value_text, pattern).date()
            except ValueError:
                continue

        return None

    days_back_text = str(crawl_env.get("DAYS_BACK") or "2").strip()
    try:
        days_back = int(days_back_text)
    except ValueError:
        days_back = 2


    cutoff = date.today() - timedelta(days=days_back)
    if not raw_combined_path.exists():
        log(f"⚠️  Date filter check skipped; output file not found: {raw_combined_path}")
        return

    try:
        with raw_combined_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        log(f"⚠️  Date filter check skipped; could not read {raw_combined_path.name}: {exc}")
        return

    if isinstance(payload, dict):
        jobs = [payload]
    elif isinstance(payload, list):
        jobs = payload
    else:
        log(f"⚠️  Date filter check skipped; unexpected JSON shape in {raw_combined_path.name}")
        return

    violations = []
    for job in jobs:
        posted_date = parse_job_date(job.get("posted_date"))
        if posted_date is not None and posted_date < cutoff:
            violations.append((job.get("source_name") or "unknown", job.get("job_url") or job.get("job_source_id") or "n/a", posted_date.isoformat()))

    log(f"Date filter active for {crawl_mode}: realtime >= {cutoff.isoformat()} (last {days_back} day(s))")
    if violations:
        sample = "; ".join(f"{source} | {posted_date} | {job_id}" for source, job_id, posted_date in violations[:5])
        log(f"⚠️  Date filter validation found {len(violations)} out-of-range job(s) in {raw_combined_path.name}: {sample}")
    else:
        log(f"✅ Date filter validation passed for {raw_combined_path.name}")


def resolve_crawl_output_path(run_date: str) -> Path:
    """Return the most likely merged crawl output path for the current run date."""
    pipeline_candidate = resolve_pipeline_path("crawl", "data", f"crawl_{run_date}", "raw", "jobs_combined.json")
    if pipeline_candidate and pipeline_candidate.exists():
        return pipeline_candidate

    repo_candidate = BASE_DIR / "data" / f"crawl_{run_date}" / "raw" / "jobs_combined.json"
    if repo_candidate.exists():
        return repo_candidate

    return RAW_FOLDER / "jobs_combined.json"

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
        run_env["PYTHONUNBUFFERED"] = "1"
        run_env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd or script_path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=run_env
        )
        
        # Stream output in realtime to console and log file
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
        
        returncode = process.wait(timeout=timeout)
        
        if returncode == 0:
            log(f"{name} thành công\n")
            return True
        else:
            log(f"{name} thất bại với mã thoát: {returncode}\n")
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


def load_pipeline_crawl_state() -> dict:
    """Load the pipeline crawl mode state if it exists."""
    try:
        if not PIPELINE_CRAWL_STATE_FILE.exists():
            return {}
        with open(PIPELINE_CRAWL_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log(f"[STATE] Could not load crawl state: {exc}")
        return {}


def save_pipeline_crawl_state(crawl_mode: str):
    """Persist the last successful crawl mode."""
    try:
        PIPELINE_CRAWL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "crawl_mode": crawl_mode,
            "bootstrap_completed": crawl_mode == "bootstrap",
            "updated_at": datetime.now().isoformat(),
        }
        with open(PIPELINE_CRAWL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        log(f"[STATE] Saved crawl state: {PIPELINE_CRAWL_STATE_FILE}")
    except Exception as exc:
        log(f"[STATE] Could not save crawl state: {exc}")


def resolve_crawl_mode(requested_mode: str | None) -> str:
    """Resolve the effective crawl mode from CLI/env/state."""
    mode = (requested_mode or "auto").strip().lower()
    if mode in ("bootstrap", "daily", "test"):
        return mode

    return "daily"


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


def slugify_keyword(keyword: str) -> str:
    """Build a safe slug for CareerViet URLs."""
    keyword = (keyword or "").strip().lower().replace(" ", "-")
    keyword = "".join(ch for ch in keyword if ch.isalnum() or ch == "-")
    return keyword or "software-engineer"


def build_daily_raw_output_path() -> Path:
    return RAW_FOLDER / "jobs_combined.json"


def _serialize_raw_jobs(raw_jobs):
    serialized = []
    for item in raw_jobs or []:
        if hasattr(item, "to_dict"):
            serialized.append(item.to_dict())
        elif isinstance(item, dict):
            serialized.append(item)
        else:
            serialized.append({"value": str(item)})
    return serialized


def _write_raw_jobs_json(raw_jobs, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(_serialize_raw_jobs(raw_jobs), f, ensure_ascii=False, indent=2)
    return output_path


@contextmanager
def _temporary_environment(overrides: dict):
    original_values = {}
    removed_keys = []
    try:
        for key, value in (overrides or {}).items():
            if key in os.environ:
                original_values[key] = os.environ[key]
            else:
                removed_keys.append(key)
            os.environ[key] = str(value)
        yield
    finally:
        for key in removed_keys:
            os.environ.pop(key, None)
        for key, value in original_values.items():
            os.environ[key] = value


def _make_daily_parallel_workers(
    keyword: str,
    location: str,
    domestic_max_jobs: int,
    linkedin_max_jobs: int,
    itviec_max_jobs: int | None = None,
    domestic_max_pages: int = 2,
):
    """Build callables that execute each crawler in-process and return raw records."""
    itviec_module = importlib.import_module("scrape_itviec")
    vietnamworks_module = importlib.import_module("scrape_vietnamwork")
    careerviet_module = importlib.import_module("scrape_careerviet")
    linkedin_module = importlib.import_module("scrape_linkedin")

    itviec_scrape_data = itviec_module.scrape_data
    vietnamworks_crawl = vietnamworks_module.crawl_list_url_to_raw_jobs
    careerviet_crawl = careerviet_module.crawl_list_url_to_raw_jobs
    linkedin_scrape_data = linkedin_module.scrape_data

    # Format query to replace slashes with spaces and strip duplicate whitespace
    search_query = " ".join(keyword.replace("/", " ").split())

    vietnamworks_url = f"https://www.vietnamworks.com/viec-lam?q={quote_plus(search_query)}&sorting=lasted"
    careerviet_url = f"https://careerviet.vn/viec-lam/{slugify_keyword(search_query)}-k-vi.html"

    itviec_limit = domestic_max_jobs if itviec_max_jobs is None else itviec_max_jobs

    return {
        "ITviec": lambda: itviec_scrape_data(search_query, location, max_jobs=itviec_limit, search_keyword=keyword) if itviec_limit > 0 else [],
        "VietnamWorks": lambda: vietnamworks_crawl(
            list_url_page1=vietnamworks_url,
            start_page=1,
            end_page=domestic_max_pages,
            max_jobs=domestic_max_jobs,
            search_keyword=keyword,
        ) if domestic_max_jobs > 0 else [],
        "CareerViet": lambda: careerviet_crawl(
            list_url_page1=careerviet_url,
            start_page=1,
            end_page=domestic_max_pages,
            delay_between_pages=(0.1, 0.2),
            search_keyword=keyword,
            max_jobs=domestic_max_jobs,
        ) if domestic_max_jobs > 0 else [],
        "LinkedIn": lambda: linkedin_scrape_data(
            search_query,
            location,
            search_keyword=keyword,
            max_jobs=linkedin_max_jobs,
        ) if linkedin_max_jobs > 0 else [],
    }


def run_daily_crawl_parallel(
    keyword: str | list[str],
    location: str,
    domestic_max_jobs: int,
    linkedin_max_jobs: int,
    crawl_env: dict,
    crawl_dir: Path | None = None,
    itviec_max_jobs: int | None = None,
    domestic_max_pages: int = 2,
):
    """Run the four crawlers concurrently and return per-source counts plus combined raw jobs."""
    enabled_sources = _parse_enabled_sources()
    results_tracker = {"ITviec": 0, "VietnamWorks": 0, "CareerViet": 0, "LinkedIn": 0}
    source_status = {}
    combined_raw_jobs = []
    # keyword_stats: {keyword -> {source -> count}}
    keyword_stats: dict = {}

    if isinstance(keyword, str):
        keyword_list = [part.strip() for part in keyword.split(",") if part.strip()]
    else:
        keyword_list = [str(part).strip() for part in keyword if str(part).strip()]

    if not keyword_list:
        keyword_list = ["software engineer"]

    log("STEP 1: CRAWL DATA (PARALLEL) - Starting crawl")
    if crawl_dir:
        log(f"[PARALLEL] Crawl scripts path: {crawl_dir}")
    for current_keyword in keyword_list:
        keyword_stats[current_keyword] = {}
        keyword_env = dict(crawl_env)
        keyword_json = json.dumps([current_keyword], ensure_ascii=False)
        keyword_env.update({
            "DAILY_NUM_KEYWORDS": "1",
            "SELECTED_KEYWORDS": current_keyword,
            "CRAWL_KEYWORDS": current_keyword,
            "KEYWORDS": current_keyword,
            "SELECTED_KEYWORDS_JSON": keyword_json,
            "CRAWL_KEYWORDS_JSON": keyword_json,
            "DAILY_KEYWORDS_JSON": keyword_json,
        })

        workers = _make_daily_parallel_workers(
            current_keyword,
            location,
            domestic_max_jobs,
            linkedin_max_jobs,
            itviec_max_jobs=itviec_max_jobs,
            domestic_max_pages=domestic_max_pages,
        )
        if enabled_sources is not None:
            workers = {
                name: worker
                for name, worker in workers.items()
                if name.lower() in enabled_sources
            }

        with _temporary_environment(keyword_env):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                future_map = {executor.submit(worker): source_name for source_name, worker in workers.items()}
                for future in concurrent.futures.as_completed(future_map):
                    source_name = future_map[future]
                    try:
                        raw_jobs = future.result()
                        raw_jobs = raw_jobs or []
                        n = len(raw_jobs)
                        value = results_tracker.get(source_name, 0)
                        if isinstance(value, int):
                            results_tracker[source_name] = value + n
                        else:
                            results_tracker[source_name] = n

                        # Get processed count from stats_collector (thread-safe, global inside process)
                        from central_filters import stats_collector
                        scraped_list = 0
                        detail_scraped = n
                        with stats_collector.lock:
                            kw_map = stats_collector.keyword_stats.get(current_keyword, {})
                            src_map = kw_map.get(source_name, {})
                            scraped_list = src_map.get("scraped_list", 0)
                            detail_scraped = max(n, src_map.get("detail_scraped", 0))

                        keyword_stats[current_keyword][source_name] = {
                            "scraped_list": scraped_list,
                            "detail_scraped": detail_scraped
                        }

                        previous_status = source_status.get(source_name)
                        if previous_status and previous_status != "Thành công":
                            source_status[source_name] = previous_status
                        else:
                            source_status[source_name] = "Thành công"
                        combined_raw_jobs.extend(raw_jobs)
                        log(f"[OK] {source_name}: {n} jobs for '{current_keyword}'")
                    except Exception as exc:
                        existing_status = source_status.get(source_name)
                        if not existing_status or existing_status == "Thành công":
                            source_status[source_name] = f"Lỗi: {type(exc).__name__}: {exc}"
                        value = results_tracker.get(source_name, 0)
                        if isinstance(value, int):
                            results_tracker[source_name] = value
                        else:
                            results_tracker[source_name] = 0

                        from central_filters import stats_collector
                        scraped_list = 0
                        detail_scraped = 0
                        with stats_collector.lock:
                            kw_map = stats_collector.keyword_stats.get(current_keyword, {})
                            src_map = kw_map.get(source_name, {})
                            scraped_list = src_map.get("scraped_list", 0)
                            detail_scraped = src_map.get("detail_scraped", 0)

                        keyword_stats[current_keyword][source_name] = {
                            "scraped_list": scraped_list,
                            "detail_scraped": detail_scraped
                        }
                        log(f"[ERROR] {source_name} ({current_keyword}): {exc}")

    # Load keywords config to translate search_keywords
    keyword_cfg = {}
    keywords_file = _resolve_project_path(KEYWORD_CONFIG["keywords_file"])
    if not keywords_file.exists():
        fallback_candidates = [
            BASE_DIR / "input" / "keywords_daily.json",
            BASE_DIR / "keywords_daily.json",
        ]
        for cand in fallback_candidates:
            if cand.exists():
                keywords_file = cand
                break
    if keywords_file.exists():
        try:
            with open(keywords_file, encoding="utf-8") as f:
                keyword_cfg = json.load(f)
        except Exception:
            pass

    normalize_job_search_keywords(combined_raw_jobs, keyword_cfg)

    combined_raw_jobs = filter_recent_jobs_safe(combined_raw_jobs)
    raw_output_path = _write_raw_jobs_json(combined_raw_jobs, build_daily_raw_output_path())
    log(f"[CRAWL] Combined raw output saved: {raw_output_path}")

    # In báo cáo thống kê crawler & scraper chi tiết
    try:
        from central_filters import stats_collector
        stats_collector.end_time = datetime.now()
        print(stats_collector.get_summary_report())
    except Exception as e:
        log(f"[WARN] Failed to print summary report: {e}")

    crawl_ok = len(combined_raw_jobs) > 0
    return crawl_ok, results_tracker, source_status, raw_output_path, keyword_stats


def format_daily_crawl_summary(
    keyword: str,
    activated_at: datetime,
    crawl_mode: str,
    results_tracker: dict,
    source_status: dict,
    raw_output_path: Path,
    clean_output_path: Path,
    import_stats: dict = None,
    keyword_stats: dict = None,
) -> str:
    """Render a concise daily crawl summary for console output."""
    mode_key = (crawl_mode or "daily").strip().lower()
    keyword_count = len([part for part in str(keyword).split(",") if part.strip()])
    keyword_count = max(1, keyword_count)
    if mode_key == "bootstrap":
        mode_title = "BOOTSTRAP"
        mode_description = f"BOOTSTRAP ({keyword_count} keyword(s), Không giới hạn ngày)"
    elif mode_key == "test":
        mode_title = "TEST"
        mode_description = "TEST (1 keyword / 5 jobs/source)"
    else:
        mode_title = "DAILY"
        mode_description = f"DAILY ({keyword_count} keyword(s), Lọc dữ liệu mới trong 3 ngày)"

    lines = []
    lines.append("=" * 81)
    lines.append(f"📊 TỔNG KẾT PHIÊN THU THẬP DỮ LIỆU {mode_title} (CRAWL SUMMARY)")
    lines.append("=" * 81)
    lines.append(f" - Từ khóa tìm kiếm     : {keyword}")
    lines.append(f" - Thời gian kích hoạt   : {activated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f" - Chế độ cấu hình       : {mode_description}")
    lines.append("-" * 81)
    lines.append(" [Thống kê chi tiết từng nguồn dữ liệu]:")
    for display_name in ("ITviec", "VietnamWorks", "CareerViet", "LinkedIn"):
        value = results_tracker.get(display_name, 0)
        if isinstance(value, str):
            source_line = f" ✓ Nguồn {display_name:<14}: {value}"
        else:
            status_text = source_status.get(display_name, "Thành công")
            
            # Fetch max jobs from stats_collector
            from central_filters import stats_collector
            max_jobs = 0
            with stats_collector.lock:
                max_jobs = stats_collector.stats.get(display_name, {}).get("max_jobs", 0)
            
            # Robust fallback from environment variables
            if not max_jobs:
                if display_name == "ITviec":
                    max_jobs_val = os.getenv("ITVIEC_MAX_JOBS") or os.getenv("DOMESTIC_MAX_JOBS")
                elif display_name == "VietnamWorks":
                    max_jobs_val = os.getenv("VNWORKS_DAILY_MAX_JOBS") or os.getenv("VNWORKS_TEST_MAX_JOBS") or os.getenv("DOMESTIC_MAX_JOBS")
                elif display_name == "CareerViet":
                    max_jobs_val = os.getenv("CAREERVIET_MAX_JOBS") or os.getenv("DOMESTIC_MAX_JOBS")
                elif display_name == "LinkedIn":
                    max_jobs_val = os.getenv("LINKEDIN_MAX_JOBS")
                else:
                    max_jobs_val = None
                
                if max_jobs_val:
                    try:
                        max_jobs = int(max_jobs_val)
                    except Exception:
                        max_jobs = 0

            # Default fallbacks based on mode if still 0
            if not max_jobs:
                if mode_key == "test":
                    max_jobs = 1
                elif mode_key == "bootstrap":
                    max_jobs = 150
                else:  # daily
                    if display_name == "LinkedIn":
                        max_jobs = 150
                    else:
                        max_jobs = 0

            max_jobs_str = "không giới hạn" if max_jobs >= 999999 else str(max_jobs)
            if max_jobs > 0:
                source_line = f" ✓ Nguồn {display_name:<14}: {value} / {max_jobs_str} jobs ({status_text})"
            else:
                source_line = f" ✓ Nguồn {display_name:<14}: {value} jobs ({status_text})"
        lines.append(source_line)
    lines.append("-" * 81)
    total_jobs = 0
    for value in results_tracker.values():
        if isinstance(value, int):
            total_jobs += value
    lines.append(f" 🔥 TỔNG CỘNG RECORD CÀO ĐƯỢC: {total_jobs} jobs")

    # Per-keyword breakdown
    if keyword_stats:
        lines.append("-" * 81)
        lines.append(" [Thống kê theo từ khóa (Duyệt / Cào)]:")
        sources_shown = ["ITviec", "VietnamWorks", "CareerViet", "LinkedIn"]
        header = f"  {'Từ khóa':<35}" + "".join(f" {s:<14}" for s in sources_shown) + "  Tổng"
        lines.append(header)
        lines.append("  " + "-" * 77)
        for kw, src_counts in keyword_stats.items():
            kw_display = (kw[:33] + ".." if len(kw) > 35 else kw)
            row = f"  {kw_display:<35}"
            total_list = 0
            total_detail = 0
            for src in sources_shown:
                val = src_counts.get(src, 0)
                if isinstance(val, dict):
                    sl = val.get("scraped_list", 0)
                    ds = val.get("detail_scraped", 0)
                else:
                    sl = 0
                    ds = val
                total_list += sl
                total_detail += ds
                row += f" {f'{sl} / {ds}':<14}"
            row += f"  {total_list} / {total_detail}"
            lines.append(row)

    lines.append("-" * 81)
    if import_stats:
        lines.append(" [Thống kê xử lý trong database (IMPORT)]:")
        lines.append(f"  • Đã thêm mới (Inserted)  : {import_stats.get('inserted', 0)} jobs")
        lines.append(f"  • Đã cập nhật (Updated)   : {import_stats.get('updated', 0)} jobs")
        lines.append(f"  • Bỏ qua (Skipped)        : {import_stats.get('skipped', 0)} jobs")
        lines.append(f"  • Lỗi (Errors)            : {import_stats.get('errors', 0)} jobs")
        lines.append("-" * 81)
    def _safe_relative_path(p):
        if not p:
            return ""
        try:
            return str(p.relative_to(BASE_DIR))
        except ValueError:
            try:
                return str(p.relative_to(BASE_DIR.parent))
            except ValueError:
                return str(p)

    lines.append(f" 📂 Trạng thái lưu trữ   : Đã xuất file raw tại '{_safe_relative_path(raw_output_path)}'")
    lines.append(f"                             và file sạch tại '{_safe_relative_path(clean_output_path)}'")
    lines.append("=" * 81)
    return "\n".join(lines)




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


def _parse_enabled_sources() -> set[str] | None:
    """Return the set of enabled source names, or None (= run all).

    Priority:
    1. PIPELINE_CRAWL_SOURCES / CRAWL_SOURCES  – explicit comma-separated list
    2. CRAWL_*_JOBS flags in .env              – 0 / "false" / "off" disables that source
    3. If nothing is configured               – return None (run all sources)
    """
    # 1. Explicit allowlist takes priority
    raw = os.getenv("PIPELINE_CRAWL_SOURCES") or os.getenv("CRAWL_SOURCES")
    if raw:
        enabled = {part.strip().lower() for part in raw.split(",") if part.strip()}
        return enabled or None

    # 2. Per-source on/off flags  (CRAWL_ITVIEC_JOBS, CRAWL_LINKEDIN_JOBS, …)
    _DISABLED_VALUES = {"0", "false", "off", "no"}
    crawl_flags = {
        "itviec":       os.getenv("CRAWL_ITVIEC_JOBS"),
        "vietnamworks": os.getenv("CRAWL_VIETNAMWORKS_JOBS"),
        "careerviet":   os.getenv("CRAWL_CAREERVIET_JOBS"),
        "linkedin":     os.getenv("CRAWL_LINKEDIN_JOBS"),
    }

    # If none of the flags are set, run all sources
    if not any(v is not None for v in crawl_flags.values()):
        return None

    # Sources explicitly set to 0/false are disabled; unset or non-zero are enabled
    enabled = {
        src for src, val in crawl_flags.items()
        if val is None or str(val).strip().lower() not in _DISABLED_VALUES
    }
    return enabled if enabled else None


def normalize_job_search_keywords(jobs: list, config: dict):
    """
    Map each job's search_keyword to its English counterpart if searched by a Vietnamese keyword.
    Modifies the jobs in-place. Handles both objects (RawJobData) and dictionaries.
    Also removes the `search_group` field from dictionary jobs.
    """
    groups = config.get("groups", {})
    vi_to_en = {}
    if isinstance(groups, dict):
        for group_cfg in groups.values():
            if not isinstance(group_cfg, dict):
                continue
            en_list = group_cfg.get("en", [])
            vi_list = group_cfg.get("vi", [])
            if not isinstance(en_list, list) or not en_list:
                continue
            if isinstance(vi_list, list):
                for i, vi_kw in enumerate(vi_list):
                    vi_kw_clean = str(vi_kw).strip().lower()
                    corresponding_en = en_list[i] if i < len(en_list) else en_list[0]
                    vi_to_en[vi_kw_clean] = str(corresponding_en).strip()

    for job in jobs:
        if hasattr(job, "search_keyword"):
            kw = getattr(job, "search_keyword")
            if isinstance(kw, str):
                kw_clean = kw.strip().lower()
                if kw_clean in vi_to_en:
                    setattr(job, "search_keyword", vi_to_en[kw_clean])
        elif isinstance(job, dict):
            kw = job.get("search_keyword")
            if isinstance(kw, str):
                kw_clean = kw.strip().lower()
                if kw_clean in vi_to_en:
                    job["search_keyword"] = vi_to_en[kw_clean]
            if "search_group" in job:
                del job["search_group"]


def _flatten_keywords_daily(config: dict) -> list:
    """
    Support both old tier format, old group_rotation format, and new bilingual format.

    Accepted formats:
      - {"tier_1": [...], "tier_2": [...], "tier_3": [...]}
      - {"mode": "group_rotation", "groups": {"group": {"en": [...], "vi": [...], "roles": [...], "clusters": {...}}}}
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

            # Support bilingual config format: "en", "vi", and fallback to "roles"
            for lang_key in ("en", "roles"):
                lang_keywords = group_cfg.get(lang_key, [])
                if isinstance(lang_keywords, list):
                    keywords.extend(lang_keywords)

            clusters = group_cfg.get("clusters", {})
            if isinstance(clusters, dict):
                for cluster_roles in clusters.values():
                    if isinstance(cluster_roles, list):
                        keywords.extend(cluster_roles)

    return _dedupe_keep_order(keywords)


def _flatten_keywords_with_groupnames(config: dict) -> list:
    """
    Return a flat list of keywords from the complex daily keywords config,
    but also include the top-level group names as additional search keywords.

    This preserves the original file format (no file edits) while allowing
    the pipeline to crawl group-level names (e.g. "Web Developer",
    "Computer Support Specialist") in addition to the child roles.
    """
    # Start from the usual flattened roles/clusters
    flattened = _flatten_keywords_daily(config)

    # Collect human-friendly group names from the top-level keys
    groups = config.get("groups", {})
    group_keywords = []
    if isinstance(groups, dict):
        for g in groups.keys():
            # Convert snake_case to Title Case for readability/search
            pretty = str(g).replace("_", " ").strip()
            if pretty:
                group_keywords.append(pretty.title())

    # Prepend group names so they get considered early in rotation, then
    # dedupe while preserving order and case-insensitive uniqueness.
    combined = group_keywords + flattened
    return _dedupe_keep_order(combined)


def select_daily_keywords(reset_rotation: bool = False, num_keywords: int | None = None) -> list:
    """
    Select DAILY_NUM_KEYWORDS sequentially and persist rotation state.

    Same calendar date reuses the same selected keywords, so rerunning the
    pipeline on the same day does not accidentally advance the rotation.
    """
    if num_keywords is None:
        num_keywords = KEYWORD_CONFIG["daily_num_keywords"]
    num_keywords = max(1, int(num_keywords))
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

    # Load keywords file with a tolerant fallback: if ordinary json.load fails
    # (e.g., due to trailing commas or inline comments), attempt a quick
    # sanitization and parse again. This avoids forcing edits to the
    # user's `keywords_daily.json` while keeping the pipeline robust.
    try:
        with open(keywords_file, encoding="utf-8") as f:
            keyword_cfg = json.load(f)
    except Exception as exc:
        log(f"⚠️  Failed to parse keywords file as strict JSON: {keywords_file} -> {exc}")
        try:
            txt = Path(keywords_file).read_text(encoding="utf-8")
            # Remove single-line comments (//...) and C-style comments
            import re
            txt = re.sub(r"//.*?$", "", txt, flags=re.MULTILINE)
            txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.DOTALL)
            # Remove trailing commas before ] or }
            txt = re.sub(r",\s*(\]|})", r"\1", txt)
            keyword_cfg = json.loads(txt)
            log(f"✅ Parsed keywords file after sanitization: {keywords_file}")
        except Exception as exc2:
            log(f"❌ Still cannot parse keywords file: {keywords_file} -> {exc2}")
            return []

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

    rotate_every_run = os.getenv("ROTATE_EVERY_RUN", "true").strip().lower() in ("1", "true", "yes")
    env_reset = os.getenv("RESET_KEYWORD_ROTATION", "false").strip().lower() in ("1", "true", "yes")
    should_reset = reset_rotation or env_reset

    if should_reset:
        log("🔄 Resetting keyword rotation to start from the beginning (index 0).")

    if (
        not should_reset
        and not rotate_every_run
        and state.get("last_run_date") == today
        and isinstance(state.get("selected_keywords"), list)
        and state.get("all_keywords_count") == len(all_keywords)
        and state.get("daily_num_keywords") == num_keywords
    ):
        selected = state["selected_keywords"][:num_keywords]
        log(f"🔁 Reusing today's keyword batch from state: {state_path}")
        return selected

    if method != "sequential":
        log(f"⚠️ Unsupported KEYWORD_SELECTION_METHOD={method}; fallback to sequential")

    if should_reset:
        start_index = 0
    else:
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

        # Estimate times based on CRAWL_MAX_PAGES
        crawl_time = total_keywords * CRAWL_MAX_PAGES * 30  # seconds
        merge_time = 6   # seconds
        clean_time = 15  # seconds

        log("\n" + "=" * 85)
        log("⏱️  ESTIMATED RUNTIME FOR TODAY'S CRAWL+CLEAN")
        log("=" * 85)
        log(f"\n📊 CONFIG:")
        log(f"   Keywords: {total_keywords} ({KEYWORD_CONFIG['selection_method']})")
        log(f"   Max pages per source: {CRAWL_MAX_PAGES}")

        log(f"\n⏱️  TIMELINE:")
        log(f"   🔍 CRAWL:                ~{int(crawl_time)}s")
        log(f"   📦 MERGE:                ~{int(merge_time)}s")
        log(f"   🧹 CLEAN:                ~{int(clean_time)}s")
        log(f"   ────────────────────────────────")
        log(f"   TOTAL EXECUTION:        ~{int(crawl_time + merge_time + clean_time)}s ({(crawl_time + merge_time + clean_time)/60:.1f}m)")
        log(f"\n" + "=" * 85 + "\n")

    except Exception:
        pass  # Silently fail if estimation can't be done


# ============================================================================
# MAIN
# ============================================================================
def main():
    global RUN_DATE, DATA_FOLDER, RAW_FOLDER, CLEAN_FOLDER, FALLBACK_FOLDER, LOGS_FOLDER
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
    python run_etl_pipeline.py --crawl-mode bootstrap          # First full crawl
    python run_etl_pipeline.py --crawl-mode daily              # Daily crawl: domestic full, LinkedIn capped at 500, 3-day lookback
    python run_etl_pipeline.py --crawl-mode test               # Test crawl: 1 keyword, 5 jobs/source, 1 page
    python run_etl_pipeline.py --crawl-mode daily --parallel-crawl  # Daily crawl in parallel
        """
    )
    parser.add_argument(
        "--input", 
        type=str,
        default=ETL_CONFIG["input_file"] if ETL_CONFIG["input_file"] else None,
        help=f"Custom input file for CLEAN step (default: auto-detect, or use ETL_INPUT_FILE from .env)"
    )
    parser.add_argument(
        "--step",
        type=str,
        default=None,
        help="Run a specific pipeline step only: crawl|clean|extract|import",
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
    # Deprecated duplicate flags (kept as comments for traceability):
    # parser.add_argument(
    #     "--crawl-only", 
    #     action="store_true", 
    #     help="Only run CRAWL step (skip CLEAN and IMPORT)"
    # )
    # parser.add_argument(
    #     "--clean-only", 
    #     action="store_true", 
    #     help="Only run CLEAN step (requires --input or auto-detection)"
    # )
    # parser.add_argument(
    #     "--import-only", 
    #     action="store_true", 
    #     help="Only run IMPORT step"
    # )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Run full pipeline but skip IMPORT step",
    )
    parser.add_argument(
        "--reset-keywords",
        action="store_true",
        help="Reset keyword rotation back to the beginning (index 0)",
    )
    parser.add_argument(
        "--crawl-mode",
        type=str,
        default=os.getenv("PIPELINE_CRAWL_MODE", "daily"),
        choices=("daily", "bootstrap", "test"),
        help="Crawl mode: daily (default), bootstrap (full crawl), or test (1 keyword / 5 jobs/source)",
    )
    parser.add_argument(
        "--parallel-crawl",
        action="store_true",
        help="Run crawl phase with ThreadPoolExecutor (parallel is default; sequential is used automatically on failure)",
    )
    parser.add_argument(
        "--debug-out",
        action="store_true",
        help="Output results to the root Debug folder instead of the data folder",
    )
    
    args = parser.parse_args()

    # Load accumulated stats if running daily
    stats_file = BASE_DIR / "data" / "accumulated_stats.json"
    if args.reset_keywords:
        if stats_file.exists():
            try:
                stats_file.unlink()
            except Exception:
                pass
        from central_filters import stats_collector
        stats_collector.reset()
    else:
        from central_filters import stats_collector
        stats_collector.load_from_disk(str(stats_file))

    # Default behavior: always try parallel crawl first.
    # If parallel mode fails, each crawl mode will automatically fallback to sequential.
    args.parallel_crawl = True

    # Deprecated alias handling (kept as comments for traceability):
    # # Backwards-friendly alias: --parallel => --parallel-crawl
    # if getattr(args, "parallel", False):
    #     args.parallel_crawl = True

    # Deprecated translation to duplicate flags (kept as comments for traceability):
    # # If user asked for a specific step via --step, translate to flags where appropriate
    # if args.step:
    #     step_arg = str(args.step).strip().lower()
    #     if step_arg == 'crawl':
    #         args.crawl_only = True
    #     elif step_arg == 'clean':
    #         args.clean_only = True
    #     elif step_arg == 'import':
    #         args.import_only = True
    #     elif step_arg == 'extract':
    #         # We'll handle extract-only mode specially below
    #         pass
    #     else:
    #         log(f"⚠️ Unknown --step value: {args.step}; ignoring")

    step_arg = str(args.step).strip().lower() if args.step else ""
    step_is_crawl = step_arg == 'crawl'
    step_is_clean = step_arg == 'clean'
    step_is_import = step_arg == 'import'
    if args.step and step_arg not in ('crawl', 'clean', 'import', 'extract'):
        log(f"⚠️ Unknown --step value: {args.step}; ignoring")

    # If user requested extract-only, handle it immediately and exit before
    # creating archive folders or selecting keywords.
    if args.step and str(args.step).strip().lower() == 'extract':
        input_path = Path(args.input) if args.input else None
        if not input_path:
            log("❌ --input is required for extract mode")
            return False
        if not input_path.exists():
            log(f"❌ Input file not found: {input_path}")
            return False

        # Count jobs for logging
        try:
            raw = input_path.read_text(encoding='utf-8')
            import json as _json
            payload = _json.loads(raw)
            if isinstance(payload, list):
                total_jobs = len(payload)
            elif isinstance(payload, dict):
                # common wrappers
                for key in ('jobs', 'items', 'data', 'results'):
                    if isinstance(payload.get(key), list):
                        total_jobs = len(payload.get(key))
                        break
                else:
                    total_jobs = 1
            else:
                total_jobs = 0
        except Exception:
            total_jobs = 0

        log("[EXTRACT MODE]")
        log(f"Input: {input_path}")
        log(f"Total jobs: {total_jobs}")

        # Resolve extract script
        extract_script = resolve_pipeline_path('extract', 'process_pending_llm.py')
        if not extract_script or not extract_script.exists():
            extract_script = resolve_pipeline_path('process_pending_llm.py')
        if not extract_script or not extract_script.exists():
            log(f"❌ Extract script not found: {extract_script}")
            return False

        output_path = BASE_DIR / 'data' / 'extracted_jobs.json'
        fallback_path = BASE_DIR / 'data' / 'extract_fallback.json'

        extract_env = os.environ.copy()
        existing_py = extract_env.get('PYTHONPATH', '')
        prepend_paths = os.pathsep.join([str(BASE_DIR), str(BASE_DIR.parent)])
        extract_env['PYTHONPATH'] = prepend_paths + (os.pathsep + existing_py if existing_py else '')
        extract_cwd = BASE_DIR.parent

        ok = run_step(
            "LLM EXTRACT",
            extract_script,
            args=["--input-path", str(input_path.resolve()), "--output-path", str(output_path.resolve()), "--fallback-path", str(fallback_path.resolve())],
            timeout=ETL_CONFIG.get('llm_timeout', CLEAN_TIMEOUT),
            cwd=extract_cwd,
            env=extract_env,
        )

        log("DONE")
        log(f"Output: {output_path}")
        return ok
    # ── NEW: Nếu --input được truyền vào, suy ra crawl folder từ path đó
    # Ví dụ: .../data/crawl_20260506_114403/raw/jobs_combined.json
    # → dùng crawl_20260506_114403 làm RUN_DATE thay vì datetime.now()
    if args.input:
        try:
            input_path = Path(args.input).resolve()
            # Tìm phần "crawl_YYYYMMDD_HHMMSS" hoặc "bootstrap" trong path
            for part in input_path.parts:
                if (part.startswith("crawl_") and len(part) > 10) or part == "bootstrap":
                    inferred_run_date = part.replace("crawl_", "")
                    RUN_DATE = inferred_run_date
                    DATA_FOLDER = BASE_DIR / "data" / part
                    RAW_FOLDER  = DATA_FOLDER / "raw"
                    CLEAN_FOLDER   = DATA_FOLDER / "clean"
                    FALLBACK_FOLDER = DATA_FOLDER / "fallback"
                    LOGS_FOLDER    = DATA_FOLDER / "logs"
                    log(f"[AUTO] Suy ra crawl folder từ --input: {DATA_FOLDER}")
                    break
        except Exception as e:
            log(f"[WARN] Không thể suy ra crawl folder từ --input: {e}")
    # ── END NEW
    
    # Deprecated duplicate-flag branching (kept as comments for traceability):
    # # Override PIPELINE_STEPS based on command line flags
    # global PIPELINE_STEPS
    # if args.crawl_only:
    #     PIPELINE_STEPS = {"crawl": True, "clean": False, "import": False}
    # elif args.clean_only:
    #     PIPELINE_STEPS = {"crawl": False, "clean": True, "import": False}
    # elif args.import_only:
    #     PIPELINE_STEPS = {"crawl": False, "clean": False, "import": True}

    # Override PIPELINE_STEPS based on --step (non-duplicate control path)
    global PIPELINE_STEPS
    if step_is_crawl:
        PIPELINE_STEPS = {"crawl": True, "clean": False, "import": False}
    elif step_is_clean:
        PIPELINE_STEPS = {"crawl": False, "clean": True, "import": False}
    elif step_is_import:
        PIPELINE_STEPS = {"crawl": False, "clean": False, "import": True}
    # allow skipping import explicitly while keeping default crawl+clean
    if args.skip_import:
        # respect explicit --step mode when provided
        if not (step_is_crawl or step_is_clean or step_is_import):
            PIPELINE_STEPS = {"crawl": True, "clean": True, "import": False}

    effective_crawl_mode = resolve_crawl_mode(args.crawl_mode)
    log(f"[MODE] Effective crawl mode: {effective_crawl_mode}")
    
    if effective_crawl_mode == "bootstrap":
        RUN_DATE = "bootstrap"
        DATA_FOLDER = BASE_DIR / "data" / "bootstrap"
        RAW_FOLDER  = DATA_FOLDER / "raw"
        CLEAN_FOLDER   = DATA_FOLDER / "clean"
        FALLBACK_FOLDER = DATA_FOLDER / "fallback"
        LOGS_FOLDER    = DATA_FOLDER / "logs"
        log(f"[AUTO] Redirecting bootstrap output to: {DATA_FOLDER}")
    
    if args.debug_out:
        DATA_FOLDER = BASE_DIR.parent / "Debug"
        RAW_FOLDER  = DATA_FOLDER
        CLEAN_FOLDER   = DATA_FOLDER
        FALLBACK_FOLDER = DATA_FOLDER
        LOGS_FOLDER    = DATA_FOLDER
        log(f"[DEBUG OUT] Redirecting all pipeline outputs to root Debug folder: {DATA_FOLDER}")
    
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
    _open_log_file(LOGS_FOLDER)
    
    crawl_ok = True
    clean_ok = True
    import_ok = True
    crawl_summary_bundle = None
    raw_combined = None
    
    # -------- STEP 1: CRAWL --------
    if step_crawl:
        log("STEP 1: CRAWL DATA")
        
        # Prepare environment variables for crawlers
        crawl_env = os.environ.copy()  # Inherit current env
        crawl_env.update({
            "RUN_DATE": RUN_DATE,  # Pass RUN_DATE so merge/normalize use same folder
            "OUTPUT_FOLDER": str(RAW_FOLDER),
            "RAW_DATA_FOLDER": str(RAW_FOLDER),
            "PIPELINE_CRAWL_MODE": effective_crawl_mode,
        })

        # Keep page count as a safety cap only; job limits drive actual crawl size.
        if effective_crawl_mode == "bootstrap":
            page_safety_cap = "999"
        elif effective_crawl_mode == "test":
            page_safety_cap = "1"
        else:
            page_safety_cap = "100"
        crawl_env["CRAWL_MAX_PAGES"] = page_safety_cap

        if effective_crawl_mode == "bootstrap":
            crawl_env.update({
                "VNWORKS_CRAWL_MODE": "bootstrap",
                "VNWORKS_FORCE_FULL_CRAWL": "1",
                "VNWORKS_DAILY_MAX_JOBS": "0",
                "LINKEDIN_MAX_JOBS": "500",
                "LINKEDIN_MAX_JOBS_LIMIT": "500",
                "LINKEDIN_DETAIL_SCRAPE": "true",
                "LINKEDIN_SEARCH_TPR": "off",
                "ITVIEC_MAX_JOBS": "0",
                "CAREERVIET_MAX_JOBS": "0",
                "PIPELINE_DAILY_MAX_JOBS_PER_SOURCE": "0",
                "JOB_DATE_MODE": os.getenv("JOB_DATE_MODE", "off"),
                "DAYS_BACK": "",
            })
        elif effective_crawl_mode == "test":
            crawl_env.update({
                "VNWORKS_CRAWL_MODE": "test",
                "VNWORKS_TEST_MAX_JOBS": "5",
                "VNWORKS_DAILY_MAX_JOBS": "5",
                "LINKEDIN_MAX_JOBS": "5",
                "LINKEDIN_DETAIL_SCRAPE": "false",
                "ITVIEC_MAX_JOBS": "5",
                "CAREERVIET_MAX_JOBS": "5",
                "ITVIEC_LOCATION": "Vietnam",
                "LINKEDIN_LOCATION": "Vietnam",
                "JOB_DATE_MODE": os.getenv("JOB_DATE_MODE", "realtime"),
                "DAYS_BACK": os.getenv("DAYS_BACK", "3"),
            })
        else:
            daily_domestic_max_jobs = 0
            daily_linkedin_max_jobs = 500
            crawl_env.update({
                "VNWORKS_CRAWL_MODE": "daily",
                "VNWORKS_DAILY_MAX_JOBS": str(daily_domestic_max_jobs),
                "LINKEDIN_MAX_JOBS": str(daily_linkedin_max_jobs),
                "LINKEDIN_MAX_JOBS_LIMIT": "500",
                "LINKEDIN_SEARCH_TPR": "r259200",
                "PIPELINE_DAILY_MAX_JOBS_PER_SOURCE": str(daily_domestic_max_jobs),
                "LINKEDIN_DETAIL_SCRAPE": "false",
                "ITVIEC_MAX_JOBS": str(daily_domestic_max_jobs),
                "CAREERVIET_MAX_JOBS": str(daily_domestic_max_jobs),
                "ITVIEC_LOCATION": "Vietnam",
                "LINKEDIN_LOCATION": "Vietnam",
                "JOB_DATE_MODE": os.getenv("JOB_DATE_MODE", "realtime"),
                "DAYS_BACK": os.getenv("DAYS_BACK", "3"),
            })

        if effective_crawl_mode == "daily":
            selected_keywords = select_daily_keywords(reset_rotation=args.reset_keywords, num_keywords=4)
            if not selected_keywords:
                selected_keywords = ["software engineer", "backend engineer", "data engineer", "qa engineer"]

            keyword = ", ".join(selected_keywords)
            location = "Vietnam"
            
            # Read from environment variables if defined (useful for tests/overrides)
            domestic_max_jobs = int(os.getenv("DOMESTIC_MAX_JOBS", os.getenv("JOBS_PER_KEYWORD", "0")))
            linkedin_max_jobs = int(os.getenv("LINKEDIN_MAX_JOBS", os.getenv("JOBS_PER_KEYWORD", "150")))
            selected_keywords_file = write_selected_keywords_file(selected_keywords)
            keywords_json = json.dumps(selected_keywords, ensure_ascii=False)

            crawl_env.update({
                "DAILY_NUM_KEYWORDS": str(len(selected_keywords)),
                "KEYWORD_SELECTION_METHOD": "sequential",
                "SELECTED_KEYWORDS": keyword,
                "CRAWL_KEYWORDS": keyword,
                "KEYWORDS": keyword,
                "SELECTED_KEYWORDS_JSON": keywords_json,
                "CRAWL_KEYWORDS_JSON": keywords_json,
                "DAILY_KEYWORDS_JSON": keywords_json,
                "SELECTED_KEYWORDS_FILE": str(selected_keywords_file),
                "CRAWL_KEYWORDS_FILE": str(selected_keywords_file),
                "ITVIEC_LOCATION": location,
                "LINKEDIN_LOCATION": location,
                "ITVIEC_MAX_JOBS": str(domestic_max_jobs),
                "CAREERVIET_MAX_JOBS": str(domestic_max_jobs),
                "VNWORKS_DAILY_MAX_JOBS": str(domestic_max_jobs),
                "LINKEDIN_MAX_JOBS": str(linkedin_max_jobs),
                "LINKEDIN_MAX_JOBS_LIMIT": str(linkedin_max_jobs),
                "PIPELINE_DAILY_MAX_JOBS_PER_SOURCE": str(domestic_max_jobs),
                "JOB_DATE_MODE": os.getenv("JOB_DATE_MODE", "realtime"),
                "DAYS_BACK": os.getenv("DAYS_BACK", "3"),
            })

            enabled_sources = _parse_enabled_sources()

            log("🎯 Today's selected keywords:")
            for idx, kw in enumerate(selected_keywords, start=1):
                log(f"   {idx:02d}. {kw}")
            log(f"   Saved to: {selected_keywords_file}")

            run_sequential_fallback = False
            if args.parallel_crawl:
                try:
                    crawl_ok, results_tracker, source_status, raw_combined, keyword_stats = run_daily_crawl_parallel(
                        selected_keywords,
                        location,
                        domestic_max_jobs,
                        linkedin_max_jobs,
                        crawl_env,
                    )
                    crawl_summary_bundle = {
                        "keyword": keyword,
                        "activated_at": start,
                        "crawl_mode": "DAILY",
                        "results_tracker": results_tracker,
                        "source_status": source_status,
                        "raw_output_path": raw_combined,
                        "keyword_stats": keyword_stats,
                    }
                    if not crawl_ok:
                        has_errors = any(
                            str(s).startswith("Lỗi") for s in source_status.values()
                        )
                        if has_errors:
                            log("⚠️ Parallel crawl had source errors. Falling back to sequential crawl...")
                            run_sequential_fallback = True
                        else:
                            log("ℹ️ Parallel crawl completed — 0 jobs found (keyword may have no recent postings).")
                            crawl_ok = True  # crawlers ran OK, just no new jobs
                except Exception as exc:
                    log(f"⚠️ Parallel crawl crashed: {exc}")
                    log("↩️ Falling back to sequential crawl...")
                    crawl_ok = False
                    run_sequential_fallback = True

            if run_sequential_fallback:
                crawlers = [
                    ("ITviec", "crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py", "itviec"),
                    ("LinkedIn", "crawl_data/crawl-linkedin-jobs/scripts/daily_linkedin_runner.py", "linkedin"),
                    ("CareerViet", "crawl_data/crawl-careerviet-jobs/scripts/daily_careerviet_runner.py", "careerviet"),
                    ("VietnamWorks", "crawl_data/crawl-vietnamwork-jobs/scripts/daily_vietnamworks_runner.py", "vietnamworks"),
                ]

                crawl_dir = resolve_pipeline_path("crawl", "1_crawl_data")

                for crawler_name, crawler_path, limit_key in crawlers:
                    if enabled_sources is not None and crawler_name.lower() not in enabled_sources:
                        log(f"Skipping {crawler_name} crawler (filtered by PIPELINE_CRAWL_SOURCES)")
                        continue
                    crawler_script = crawl_dir / crawler_path
                    if crawler_script.exists():
                        log(f"Running {crawler_name} crawler...")
                        crawler_timeout = CRAWLER_TIMEOUTS.get(limit_key, 600)
                        if not run_step(f"{crawler_name} Crawler", crawler_script, timeout=crawler_timeout, cwd=crawl_dir, env=crawl_env):
                            log(f"⚠️  {crawler_name} crawler skipped (timeout or error)")
                    else:
                        log(f"⚠️  {crawler_name} crawler not found: {crawler_script}")

                log("Merging crawler outputs...")
                merge_script = crawl_dir / "merge_daily_outputs.py"
                if merge_script.exists():
                    crawl_ok = run_step("Merge Outputs", merge_script, timeout=CRAWLER_TIMEOUT, cwd=crawl_dir, env=crawl_env)
                else:
                    log("⚠️  Merge script not found")
                    crawl_ok = False

                if crawl_ok:
                    raw_combined = resolve_crawl_output_path(RUN_DATE)
                else:
                    log("Crawl failed")
        elif effective_crawl_mode == "bootstrap":
            selected_keywords = select_daily_keywords(reset_rotation=args.reset_keywords, num_keywords=4)
            if not selected_keywords:
                selected_keywords = ["software engineer", "backend engineer", "data engineer", "qa engineer"]

            keyword = ", ".join(selected_keywords)
            location = "Vietnam"
            bootstrap_max_jobs = 150
            bootstrap_max_pages = 8
            domestic_max_jobs = bootstrap_max_jobs
            linkedin_max_jobs = bootstrap_max_jobs
            selected_keywords_file = write_selected_keywords_file(selected_keywords)
            keywords_json = json.dumps(selected_keywords, ensure_ascii=False)

            crawl_env.update({
                "DAILY_NUM_KEYWORDS": str(len(selected_keywords)),
                "KEYWORD_SELECTION_METHOD": "sequential",
                "SELECTED_KEYWORDS": keyword,
                "CRAWL_KEYWORDS": keyword,
                "KEYWORDS": keyword,
                "SELECTED_KEYWORDS_JSON": keywords_json,
                "CRAWL_KEYWORDS_JSON": keywords_json,
                "DAILY_KEYWORDS_JSON": keywords_json,
                "SELECTED_KEYWORDS_FILE": str(selected_keywords_file),
                "CRAWL_KEYWORDS_FILE": str(selected_keywords_file),
                "ITVIEC_LOCATION": location,
                "LINKEDIN_LOCATION": location,
                "ITVIEC_MAX_JOBS": str(bootstrap_max_jobs),
                "CAREERVIET_MAX_JOBS": str(bootstrap_max_jobs),
                "VNWORKS_DAILY_MAX_JOBS": str(bootstrap_max_jobs),
                "LINKEDIN_MAX_JOBS": str(linkedin_max_jobs),
                "LINKEDIN_MAX_JOBS_LIMIT": str(bootstrap_max_jobs),
                "PIPELINE_DAILY_MAX_JOBS_PER_SOURCE": str(bootstrap_max_jobs),
                "CRAWL_MAX_PAGES": str(bootstrap_max_pages),
                "VNWORKS_CRAWL_MODE": "bootstrap",
                "VNWORKS_FORCE_FULL_CRAWL": "1",
                "LINKEDIN_DETAIL_SCRAPE": "true",
                "JOB_DATE_MODE": os.getenv("JOB_DATE_MODE", "off"),
                "DAYS_BACK": "",
            })

            enabled_sources = _parse_enabled_sources()

            log("🚀 Bootstrap keywords:")
            for idx, kw in enumerate(selected_keywords, start=1):
                log(f"   {idx:02d}. {kw}")
            log(f"   Saved to: {selected_keywords_file}")

            run_sequential_fallback = False
            if args.parallel_crawl:
                try:
                    crawl_ok, results_tracker, source_status, raw_combined, keyword_stats = run_daily_crawl_parallel(
                        selected_keywords,
                        location,
                        domestic_max_jobs,
                        linkedin_max_jobs,
                        crawl_env,
                        domestic_max_pages=bootstrap_max_pages,
                    )
                    crawl_summary_bundle = {
                        "keyword": keyword,
                        "activated_at": start,
                        "crawl_mode": "BOOTSTRAP",
                        "results_tracker": results_tracker,
                        "source_status": source_status,
                        "raw_output_path": raw_combined,
                        "keyword_stats": keyword_stats,
                    }
                    if not crawl_ok:
                        has_errors = any(
                            str(s).startswith("Lỗi") for s in source_status.values()
                        )
                        if has_errors:
                            log("⚠️ Parallel crawl had source errors. Falling back to sequential crawl...")
                            run_sequential_fallback = True
                        else:
                            log("ℹ️ Parallel crawl completed — 0 jobs found (keyword may have no recent postings).")
                            crawl_ok = True  # crawlers ran OK, just no new jobs
                except Exception as exc:
                    log(f"⚠️ Parallel crawl crashed: {exc}")
                    log("↩️ Falling back to sequential crawl...")
                    crawl_ok = False
                    run_sequential_fallback = True

            if run_sequential_fallback:
                crawlers = [
                    ("ITviec", "crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py", "itviec"),
                    ("LinkedIn", "crawl_data/crawl-linkedin-jobs/scripts/daily_linkedin_runner.py", "linkedin"),
                    ("CareerViet", "crawl_data/crawl-careerviet-jobs/scripts/daily_careerviet_runner.py", "careerviet"),
                    ("VietnamWorks", "crawl_data/crawl-vietnamwork-jobs/scripts/daily_vietnamworks_runner.py", "vietnamworks"),
                ]

                crawl_dir = resolve_pipeline_path("crawl", "1_crawl_data")

                for crawler_name, crawler_path, limit_key in crawlers:
                    if enabled_sources is not None and crawler_name.lower() not in enabled_sources:
                        log(f"Skipping {crawler_name} crawler (filtered by PIPELINE_CRAWL_SOURCES)")
                        continue
                    crawler_script = crawl_dir / crawler_path
                    if crawler_script.exists():
                        log(f"Running {crawler_name} crawler...")
                        crawler_timeout = CRAWLER_TIMEOUTS.get(limit_key, 600)
                        if not run_step(f"{crawler_name} Crawler", crawler_script, timeout=crawler_timeout, cwd=crawl_dir, env=crawl_env):
                            log(f"⚠️  {crawler_name} crawler skipped (timeout or error)")
                    else:
                        log(f"⚠️  {crawler_name} crawler not found: {crawler_script}")

                log("Merging crawler outputs...")
                merge_script = crawl_dir / "merge_daily_outputs.py"
                if merge_script.exists():
                    crawl_ok = run_step("Merge Outputs", merge_script, timeout=CRAWLER_TIMEOUT, cwd=crawl_dir, env=crawl_env)
                else:
                    log("⚠️  Merge script not found")
                    crawl_ok = False

                if crawl_ok:
                    raw_combined = resolve_crawl_output_path(RUN_DATE)
                else:
                    log("Crawl failed")
        elif effective_crawl_mode == "test":
            selected_keywords = select_daily_keywords(reset_rotation=args.reset_keywords, num_keywords=1)
            if not selected_keywords:
                selected_keywords = ["software engineer"]

            keyword = ", ".join(selected_keywords)
            location = "Vietnam"
            max_jobs_per_source = 1
            itviec_max_jobs = 1
            selected_keywords_file = write_selected_keywords_file(selected_keywords)
            keywords_json = json.dumps(selected_keywords, ensure_ascii=False)

            crawl_env.update({
                "DAILY_NUM_KEYWORDS": str(len(selected_keywords)),
                "KEYWORD_SELECTION_METHOD": "sequential",
                "SELECTED_KEYWORDS": keyword,
                "CRAWL_KEYWORDS": keyword,
                "KEYWORDS": keyword,
                "SELECTED_KEYWORDS_JSON": keywords_json,
                "CRAWL_KEYWORDS_JSON": keywords_json,
                "DAILY_KEYWORDS_JSON": keywords_json,
                "SELECTED_KEYWORDS_FILE": str(selected_keywords_file),
                "CRAWL_KEYWORDS_FILE": str(selected_keywords_file),
                "ITVIEC_LOCATION": location,
                "LINKEDIN_LOCATION": location,
                "ITVIEC_MAX_JOBS": str(itviec_max_jobs),
                "CAREERVIET_MAX_JOBS": str(max_jobs_per_source),
                "VNWORKS_TEST_MAX_JOBS": str(max_jobs_per_source),
                "VNWORKS_DAILY_MAX_JOBS": str(max_jobs_per_source),
                "LINKEDIN_MAX_JOBS": str(max_jobs_per_source),
                "LINKEDIN_SEARCH_TPR": "r259200",
                "JOB_DATE_MODE": os.getenv("JOB_DATE_MODE", "realtime"),
                "DAYS_BACK": os.getenv("DAYS_BACK", "3"),
            })

            log("🧪 Test keywords:")
            for idx, kw in enumerate(selected_keywords, start=1):
                log(f"   {idx:02d}. {kw}")
            log(f"   Saved to: {selected_keywords_file}")

            run_sequential_fallback = False
            if args.parallel_crawl:
                try:
                    crawl_ok, results_tracker, source_status, raw_combined, keyword_stats = run_daily_crawl_parallel(
                        keyword,
                        location,
                        max_jobs_per_source,
                        max_jobs_per_source,
                        crawl_env,
                        itviec_max_jobs=itviec_max_jobs,
                    )
                    crawl_summary_bundle = {
                        "keyword": keyword,
                        "activated_at": start,
                        "crawl_mode": "TEST",
                        "results_tracker": results_tracker,
                        "source_status": source_status,
                        "raw_output_path": raw_combined,
                        "keyword_stats": keyword_stats,
                    }
                    if not crawl_ok:
                        has_errors = any(
                            str(s).startswith("Lỗi") for s in source_status.values()
                        )
                        if has_errors:
                            log("⚠️ Parallel crawl had source errors. Falling back to sequential crawl...")
                            run_sequential_fallback = True
                        else:
                            log("ℹ️ Parallel crawl completed — 0 jobs found (keyword may have no recent postings).")
                            crawl_ok = True  # crawlers ran OK, just no new jobs
                except Exception as exc:
                    log(f"⚠️ Parallel crawl crashed: {exc}")
                    log("↩️ Falling back to sequential crawl...")
                    crawl_ok = False
                    run_sequential_fallback = True

            if run_sequential_fallback:
                crawlers = [
                    ("ITviec", "crawl_data/crawl-itviec-jobs/scripts/daily_itviec_runner.py", "itviec"),
                    ("LinkedIn", "crawl_data/crawl-linkedin-jobs/scripts/daily_linkedin_runner.py", "linkedin"),
                    ("CareerViet", "crawl_data/crawl-careerviet-jobs/scripts/daily_careerviet_runner.py", "careerviet"),
                    ("VietnamWorks", "crawl_data/crawl-vietnamwork-jobs/scripts/daily_vietnamworks_runner.py", "vietnamworks"),
                ]

                crawl_dir = resolve_pipeline_path("crawl", "1_crawl_data")

                for crawler_name, crawler_path, limit_key in crawlers:
                    crawler_script = crawl_dir / crawler_path
                    if crawler_script.exists():
                        log(f"Running {crawler_name} crawler...")
                        crawler_timeout = CRAWLER_TIMEOUTS.get(limit_key, 600)
                        if not run_step(f"{crawler_name} Crawler", crawler_script, timeout=crawler_timeout, cwd=crawl_dir, env=crawl_env):
                            log(f"⚠️  {crawler_name} crawler skipped (timeout or error)")
                    else:
                        log(f"⚠️  {crawler_name} crawler not found: {crawler_script}")

                log("Merging crawler outputs...")
                merge_script = crawl_dir / "merge_daily_outputs.py"
                if merge_script.exists():
                    crawl_ok = run_step("Merge Outputs", merge_script, timeout=CRAWLER_TIMEOUT, cwd=crawl_dir, env=crawl_env)
                else:
                    log("⚠️  Merge script not found")
                    crawl_ok = False

                if crawl_ok:
                    raw_combined = resolve_crawl_output_path(RUN_DATE)
                else:
                    log("Crawl failed")
        if crawl_ok and raw_combined:
            validate_crawl_date_filter(raw_combined, crawl_env, effective_crawl_mode)
    if not step_crawl:
        log("Skipping CRAWL (STEP_CRAWL=false)\n")
    
    # -------- STEP 2: CLEAN -> PENDING -> EXTRACT -> NORMALIZE -> TRANSFORM --------

    if step_clean:
        log("STEP 2: CLEAN DATA (debug clean -> pending_llm -> extracted -> normalized -> import_ready)")

        crawl_raw_combined = raw_combined
        raw_combined = None
        if args.input:
            # Resolve custom input to an absolute path so subprocesses receive
            # an absolute filename regardless of the working directory used
            # when spawning the child clean/extract/normalize scripts.
            custom_input = Path(args.input).resolve()
            if custom_input.exists():
                raw_combined = custom_input
                log(f"Using custom input for clean flow: {custom_input.name}")
            else:
                log(f"❌ Custom input file not found: {args.input}")
                clean_ok = False

        if raw_combined is None and clean_ok:
            raw_combined = crawl_raw_combined or (RAW_FOLDER / "jobs_combined.json")

        # If the default raw_combined doesn't exist, try pipeline or repo candidates.
        if not raw_combined or not raw_combined.exists():
            pipeline_candidate = resolve_pipeline_path("crawl", "data", f"crawl_{RUN_DATE}", "raw", "jobs_combined.json")
            repo_candidate = BASE_DIR / "data" / f"crawl_{RUN_DATE}" / "raw" / "jobs_combined.json"
            if pipeline_candidate and pipeline_candidate.exists():
                raw_combined = pipeline_candidate
            elif repo_candidate.exists():
                raw_combined = repo_candidate
            else:
                # defensive: resolve_pipeline_path may return None; avoid AttributeError
                raw_combined = None

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
           

            if clean_script.exists():
                # Ensure absolute paths are passed to the child process so
                # path resolution inside the clean script is unambiguous.
                in_path = Path(raw_combined).resolve()
                out_path = pending_file.resolve()
                clean_ok = run_step(
                    "CLEAN STEP 1",
                    clean_script,
                    args=[str(in_path), "--step", "1", "--output", str(out_path)],
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
                    timeout=ETL_CONFIG.get('llm_timeout', CLEAN_TIMEOUT),
                    cwd=extract_cwd,
                    env=extract_env,
                )
            elif clean_ok:
                log(f"⚠️  Extract script not found: {extract_script}")
                clean_ok = False

            # Use the new normalize runner (v2) inside 2_1_normalized_data
            normalize_entry = resolve_pipeline_path("normalize", "2_1_normalized_data", "normalize_pipeline_v2.py")
            # Run normalization only if normalized file not provided
            if args.normalized:
                log(f"Skipping NORMALIZE because normalized file provided: {normalized_file}")
            elif clean_ok and normalize_entry and normalize_entry.exists():
                # call normalize_pipeline_v2 with input/output/fallback args
                # Use directory of normalize_entry if available in pipeline layout
                normalize_cwd = normalize_entry.parent if normalize_entry.exists() else resolve_pipeline_path("2_1_normalized_data")
                normalize_fallback = FALLBACK_FOLDER / "normalize_fallback.json"
                clean_ok = run_step(
                    "NORMALIZE (v2)",
                    normalize_entry,
                    args=[
                        "--input", str(extracted_file),
                        "--output", str(normalized_file),
                        "--fallback", str(normalize_fallback),
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

        if import_script is None or not import_script.exists():
            import_script = resolve_pipeline_path("import", "3_import", "import.py")

        if import_script is None or not import_script.exists():
            log("❌ Import script not found")
            import_ok = False
        else:
            import_input = CLEAN_FOLDER / "normalized.json"

            if import_input.exists():
                log(f"Using normalized output: {import_input.name}")
                import_stats_path = FALLBACK_FOLDER / "import_stats.json"
                import_args = [
                    "--input", str(import_input),
                    "--fallback", str(FALLBACK_FOLDER / "import_fallback.json"),
                    "--stats-output", str(import_stats_path)
                ]

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
    should_cleanup = False
    # should_cleanup = step_clean and step_import and crawl_ok and clean_ok and import_ok
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

    if crawl_summary_bundle:
        # Load import stats from file if available
        _import_stats = None
        try:
            stats_path = FALLBACK_FOLDER / "import_stats.json"
            if stats_path.exists():
                with open(stats_path, encoding="utf-8") as _sf:
                    _import_stats = json.load(_sf)
        except Exception:
            pass

        summary_text = format_daily_crawl_summary(
            keyword=crawl_summary_bundle["keyword"],
            activated_at=crawl_summary_bundle["activated_at"],
            crawl_mode=crawl_summary_bundle["crawl_mode"],
            results_tracker=crawl_summary_bundle["results_tracker"],
            source_status=crawl_summary_bundle["source_status"],
            raw_output_path=crawl_summary_bundle["raw_output_path"],
            clean_output_path=CLEAN_FOLDER / "normalized.json",
            import_stats=_import_stats,
            keyword_stats=crawl_summary_bundle.get("keyword_stats"),
        )
        print()
        print(summary_text)


    log("=" * 80)

    success = crawl_ok and clean_ok and import_ok
    if success and effective_crawl_mode == "bootstrap" and step_crawl and step_clean and step_import:
        save_pipeline_crawl_state("bootstrap")

    # Save accumulated stats
    try:
        stats_file = BASE_DIR / "data" / "accumulated_stats.json"
        from central_filters import stats_collector
        stats_collector.save_to_disk(str(stats_file))
    except Exception as e:
        log(f"[WARN] Failed to save accumulated stats: {e}")

    # Print log path at the end of execution for user convenience
    try:
        log_path = (LOGS_FOLDER / f"pipeline_{RUN_DATE}.log").resolve()
        log(f"📄 Session log saved at: {log_path}")
    except Exception:
        pass

    _close_log_file()
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
