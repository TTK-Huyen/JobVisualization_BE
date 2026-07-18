"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                        CLEAN PROCESS - MAIN MODULE                            ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ PURPOSE: 3-step pipeline orchestrator                                         ║
║   STEP 1: Clean HTML/CSS/JS from job descriptions                           ║
║   STEP 2: Extract sections (requirements, benefits, etc.)                    ║
║   STEP 3: Normalize technical skills with canonical skills map             ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import json
import argparse
import os
import re
import unicodedata
from pathlib import Path
import yaml
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

DB_ROOT = Path(__file__).parent.parent
if str(DB_ROOT) not in sys.path:
    sys.path.insert(0, str(DB_ROOT))

# Workspace root (one level above Db/) — fallback folder will live here alongside `clean` and `raw`
WORKSPACE_ROOT = DB_ROOT.parent


def _find_crawl_run_dir(path_like):
    """Return the crawl run directory under `Db/data/` that contains `path_like`, if any."""
    try:
        p = Path(path_like).resolve()
    except Exception:
        p = Path(path_like)

    data_root = DB_ROOT / 'data'
    for ancestor in [p] + list(p.parents):
        if ancestor.name.startswith('crawl_') and data_root in ancestor.parents:
            return ancestor
    return None

# Load .env for config override — search upward from this file's directory
# so the single /app/Db/.env used in production is found regardless of depth.
_script_dir = Path(__file__).resolve().parent
_env_file_found = None
for _candidate in [
    _script_dir / ".env",
    _script_dir.parent / ".env",
    _script_dir.parent.parent / ".env",
    _script_dir.parent.parent.parent / ".env",
    _script_dir.parent.parent.parent.parent / ".env",
]:
    if _candidate.exists():
        _env_file_found = _candidate
        break

env_file = _env_file_found or (_script_dir.parent / ".env")
if _env_file_found:
    load_dotenv(_env_file_found)
    print(f"[*] Loaded .env from {_env_file_found}")
else:
    print(f"[!] .env not found (searched up to {_script_dir.parent.parent.parent.parent}), using defaults")

print(f"[*] Importing cache_manager...", flush=True)
from cache_manager import initialize_all_caches, save_all_caches, save_pending_failed_jobs, get_job_fingerprint
print(f"[*] Importing utilities...", flush=True)
from clean_job_text import clean_description_html
from utilities import extract_job_sections, log_error
print(f"[*] All imports completed!", flush=True)


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                       INITIALIZE CACHES                                     ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

print("[*] Initializing caches...")
CACHES = initialize_all_caches()


REQUIREMENTS_START_MARKERS = [
    "yêu cầu công việc",
    "yêu cầu ứng viên",
    "yêu cầu",
    "your skills and experience",
    "your skills & experience",
    "skills & experience",
    "qualifications",
    "preferred qualifications",
    "minimum qualifications",
    "who you are",
    "your qualifications and skills",
    "what we are looking for",
    "must-have",
    "nice-to-have",
    "role responsibilities",
    "your opportunity",
    "core responsibilities",
    "what does it take to succeed?",
    "requirements",
    "requirements:",
]

REQUIREMENTS_END_MARKERS = [
    "quyền lợi",
    "phúc lợi",
    "benefits",
    "why you'll love working here",
    "giới thiệu công ty",
    "thông tin công ty",
    "company overview",
    "việc làm đang tuyển",
    "địa điểm làm việc",
    "thông tin khác",
    "application process",
    "who we are",
    "about the company",
    "about the function",
    "what we offer",
    "apply today",
    "equal opportunity employer",
]

NOISE_MARKERS = [
    "chi tiết",
    "tổng quan công ty",
    "việc làm đang tuyển",
    "xem thêm",
    "thu gọn",
    "địa điểm",
    "thông tin công ty",
    "company overview",
    "job opening",
    "apply now",
    "follow",
    "followers",
    "seniority level",
    "employment type",
    "job function",
    "industries",
    "about the company",
    "company",
    "style=",
    "text-decoration",
    "background-color",
    "border:",
    "color:",
    "display:",
]

STEP1_PREFIX_NOISE_PATTERNS = [
    r"^company$",
    r"^about the company$",
    r"^seniority level$",
    r"^employment type$",
    r"^job function$",
    r"^industries$",
    r"^location$",
    r"^posted(?:\s*[:\-–—].*)?$",
    r"^followers?$",
    r"^apply now$",
    r"^save this job$",
    r"^top 3 reasons to join us$",
    r"^báo xấu$",
    r"^gửi tôi việc làm tương tự$",
    r"^xem thêm$",
    r"^thu gọn$",
]

STEP1_LINKEDIN_HTML_NOISE_PATTERNS = [
    r"<section[^>]*class=\"[^\"]*linkedin-job-header[^\"]*\"[^>]*>.*?</section>",
    r"<section[^>]*class=\"[^\"]*linkedin-about-company[^\"]*\"[^>]*>.*?</section>",
]

CSS_NOISE_PATTERNS = [
    r"\ba\s*\{[^{}]{0,400}?\}",
    r"\btr\s+th,\s*tr\s+td\s*\{[^{}]{0,400}?\}",
    r"\btr\s+th\s*\{[^{}]{0,400}?\}",
]


def _normalize_for_search(text):
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = text.replace("\r", "\n")
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def _strip_accents(text):
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _normalize_for_fingerprint(text):
    if not text:
        return ""
    text = _strip_accents(_normalize_for_search(text)).lower()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _remove_noise_blocks(text):
    if not text:
        return ""

    cleaned = text
    for pattern in CSS_NOISE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE | re.DOTALL)

    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()

def _is_nearly_empty_text(text):
    if not text:
        return True

    normalized = _normalize_for_fingerprint(text)
    if not normalized:
        return True

    return len(normalized) < 12



# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                     STEP 1: CLEAN HTML                                      ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def _resolve_run_root(output_file):
    output_path = Path(output_file)
    if output_path.parent.name in ("logs", "clean", "fallback") and output_path.parent.parent:
        return output_path.parent.parent
    return output_path.parent


def step_1_clean_html(input_file, output_file="clean/pending_llm.json", limit=None):
    """Clean HTML/CSS/JavaScript from job descriptions."""
    print(f"\n{'='*80}")
    print("STEP 1: CLEAN HTML FROM TEXT")
    print(f"{'='*80}")
    
    # Check if use LLM cleaning
    use_llm = os.getenv("CLEAN_USE_LLM", "false").lower() in ("true", "1", "yes")
    print(f"[*] Mode: {'LLM + Regex' if use_llm else 'Regex only'}")
    
    try:
        # Load input JSON safely; if unreadable, move to fallback and continue
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        try:
            jobs = json.loads(raw_text)
        except json.JSONDecodeError as e:
            from datetime import datetime
            # Prefer crawl run folder under Db/data (e.g., Db/data/crawl_.../fallback)
            crawl_dir = _find_crawl_run_dir(input_file)
            if crawl_dir:
                fallback_dir = crawl_dir / 'fallback'
            else:
                fallback_dir = DB_ROOT / 'data' / 'fallback'
            fallback_dir.mkdir(parents=True, exist_ok=True)
            # Use fixed fallback filename per step (crawl run folder provides isolation)
            fallback_name = "clean_fallback.json"
            fallback_path = fallback_dir / fallback_name
            with open(fallback_path, 'w', encoding='utf-8') as bf:
                bf.write(raw_text)
            log_error(f"STEP 1: unreadable JSON moved to fallback: {fallback_path} ({str(e)})")
            # Return empty list so pipeline can continue without halting
            return []
        
        if not isinstance(jobs, list):
            jobs = [jobs]
        
        print(f"[*] Loaded {len(jobs)} jobs")

        # ── SANDBOX / LIMIT MODE ────────────────────────────────────────────────
        if limit is not None and limit > 0:
            jobs = jobs[:limit]
            print(f"[⚙️ ] --limit {limit}: Chỉ xử lý {len(jobs)} jobs đầu tiên (Sandbox mode)")

        # Initialize LLM cleaner if enabled
        llm_cleaner = None
        if use_llm:
            print("[*] Initializing LLM cleaner...")
            from skill_extraction_llm import SkillExtractor
            llm_cleaner = SkillExtractor()
        
        cleaned_jobs = []
        non_empty_clean_count = 0
        failed_jobs = []
        from datetime import datetime
        for job in jobs:
            cleaned_job = dict(job)
            # Prioritize requirements_text from scraper, fallback to description_html
            raw_text = cleaned_job.get('requirements_text') or cleaned_job.get('description_html') or ''
            cleaned_text = clean_description_html(str(raw_text))

            # Validation checks before including into cleaned_jobs
            reasons = []

            title = (job.get('title') or job.get('job_title') or '').strip()
            url = (job.get('job_url') or job.get('url') or job.get('job_source_id') or job.get('job_url_raw') or '').strip()

            # 1) Not empty
            if not cleaned_text or not cleaned_text.strip():
                reasons.append('empty_after_clean')

            # 2) Minimum length (chars or words)
            words = [w for w in re.split(r"\s+", cleaned_text.strip()) if w]
            if len(cleaned_text) < 100 and len(words) < 20:
                reasons.append('too_short')

            # 3) Not garbage (alnum ratio)
            total_chars = max(1, len(cleaned_text))
            alnum_count = sum(1 for c in cleaned_text if c.isalnum())
            alnum_ratio = alnum_count / total_chars
            if alnum_ratio < 0.25:
                reasons.append('low_alnum_ratio')

            # 4) Not only special characters / whitespace
            visible_chars = re.sub(r"[\W_]+", "", cleaned_text)
            if not visible_chars:
                reasons.append('only_special_chars')

            # 5) Required metadata
            if not title or not url:
                reasons.append('missing_title_or_url')

            # Decide pass/fail
            if reasons:
                # Prepare fallback entry (keep title, job_url, requirements_text and reason)
                crawl_dir = _find_crawl_run_dir(input_file)
                if crawl_dir:
                    fallback_dir = crawl_dir / 'fallback'
                else:
                    fallback_dir = DB_ROOT / 'data' / 'fallback'
                fallback_dir.mkdir(parents=True, exist_ok=True)

                fallback_entry = {
                    'title': title,
                    'job_url': url,
                    'requirements_text': cleaned_text,
                    '_fallback_reasons': reasons,
                    '_original_job': {k: job.get(k) for k in ('job_source_id','source_name') if job.get(k)},
                    'timestamp': datetime.now().isoformat()
                }

                # Append to in-memory failed list; will be written after loop
                failed_jobs.append((fallback_dir, fallback_entry))
                # Do not include in cleaned_jobs
            else:
                cleaned_job['requirements_text'] = cleaned_text
                cleaned_jobs.append(cleaned_job)

                if cleaned_text:
                    non_empty_clean_count += 1

                if len(cleaned_jobs) == 1:
                    print(f"\n[*] First job cleaning:")
                    print(f"   Raw size: {len(str(raw_text)):,} chars")
                    print(f"   Cleaned size: {len(cleaned_text):,} chars")
                    if raw_text:
                        print(f"   Reduction: {(1 - len(cleaned_text)/len(str(raw_text)))*100:.1f}%")
        
        # Save cleaned output
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(cleaned_jobs, f, ensure_ascii=False, indent=2)

        # Save failed jobs into crawl fallback file (grouped by crawl run)
        if failed_jobs:
            # Group by fallback_dir
            grouped = {}
            for fallback_dir, entry in failed_jobs:
                grouped.setdefault(str(fallback_dir), []).append(entry)

            for dirpath, entries in grouped.items():
                fp = Path(dirpath) / 'clean_fallback.json'
                existing = []
                if fp.exists():
                    try:
                        with open(fp, 'r', encoding='utf-8') as ef:
                            existing = json.load(ef) or []
                    except Exception:
                        existing = []
                existing.extend(entries)
                with open(fp, 'w', encoding='utf-8') as ef:
                    json.dump(existing, ef, ensure_ascii=False, indent=2)
            print(f"\n[!] {sum(len(v) for v in grouped.values())} jobs moved to fallback (see clean_fallback.json)")

        print(f"\n[+] STEP 1 Complete!")
        print(f"   Output: {output_file}")
        print(f"   Jobs: {len(cleaned_jobs)}")
        print(f"   Cleaned text present: {non_empty_clean_count}")

        # ── SANDBOX REPORT ──────────────────────────────────────────────────────
        if limit is not None and limit > 0 and cleaned_jobs:
            print("\n" + "=" * 80)
            print("  📋  SANDBOX REPORT — NGHIỆM THU 5 JOBS MẪU")
            print("=" * 80)
            header = f"{'#':<3} {'Raw Chars':>11} {'Clean Chars':>11} {'Giảm %':>7}  {'URL / Title'}"
            print(header)
            print("-" * 80)
            for i, cj in enumerate(cleaned_jobs, 1):
                orig_job = jobs[i-1]
                raw_txt = orig_job.get('requirements_text') or orig_job.get('description_html') or ''
                clean_txt = cj.get('requirements_text') or ''
                raw_len  = len(raw_txt)
                clean_len = len(clean_txt)
                ratio = (1 - clean_len / raw_len) * 100 if raw_len > 0 else 0.0
                label = (cj.get('job_url') or cj.get('title') or 'N/A')[:60]
                print(f"{i:<3} {raw_len:>11,} {clean_len:>11,} {ratio:>6.1f}%  {label}")
            print("-" * 80)
            total_raw  = sum(len(orig_job.get('requirements_text') or orig_job.get('description_html') or '') for orig_job in jobs[:len(cleaned_jobs)])
            total_clean = sum(len(cj.get('requirements_text') or '') for cj in cleaned_jobs)
            avg_ratio = (1 - total_clean / total_raw) * 100 if total_raw > 0 else 0.0
            print(f"{'AVG':<3} {total_raw//len(cleaned_jobs):>11,} {total_clean//len(cleaned_jobs):>11,} {avg_ratio:>6.1f}%  (trung bình)")
            print("=" * 80)

        return cleaned_jobs

    except Exception as e:
        log_error(f"STEP 1 failed: {str(e)}")
        raise



def run_full_pipeline(input_file, output_file="clean/normalized.json"):
    """Execute all 3 steps."""
    try:
        print("\n" + "█"*80)
        print("█" + " "*78 + "█")
        print("█" + "  FULL PIPELINE: 3-STEP JOB CLEANING & NORMALIZATION".center(78) + "█")
        print("█" + " "*78 + "█")
        print("█"*80)
        
        # STEP 1
        output_1 = "clean/pending_llm.json"
        step_1_clean_html(input_file, output_1)
        
        # STEP 2
        output_2 = "clean/extracted.json"
        step_2_extract_sections(output_1, output_2)
        
        # STEP 3 - with fallback if API quota exceeded
        skip_step3 = os.getenv('SKIP_NORMALIZE', '').lower() == 'true'
        if not skip_step3:
            try:
                step_3_normalize_skills(output_2, output_file)
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "quota" in error_msg.lower() or "daily limit" in error_msg.lower():
                    print(f"\n⚠️  STEP 3 FALLBACK: API quota exceeded, using STEP 2 output directly")
                    print(f"    Error: {error_msg[:100]}")
                    import shutil
                    from datetime import datetime
                    try:
                        with open(output_2, 'r', encoding='utf-8') as sf:
                            payload = json.load(sf)
                    except Exception:
                        # if we can't read JSON, fallback to raw copy
                        shutil.copy(output_2, output_file)
                    else:
                        fallback_obj = {
                            "_is_fallback": True,
                            "fallback_reason": "API quota or rate limit detected",
                            "error_message": error_msg[:100],
                            "source_step": 2,
                            "source_file": str(output_2),
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "data": payload,
                        }
                        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
                        with open(output_file, 'w', encoding='utf-8') as of:
                            json.dump(fallback_obj, of, ensure_ascii=False, indent=2)
                else:
                    raise
        else:
            print(f"\n[SKIP] STEP 3 NORMALIZE skipped (SKIP_NORMALIZE=true)")
            import shutil
            from datetime import datetime
            try:
                with open(output_2, 'r', encoding='utf-8') as sf:
                    payload = json.load(sf)
            except Exception:
                shutil.copy(output_2, output_file)
                print(f"    Copied {output_2} → {output_file} (raw copy)")
            else:
                fallback_obj = {
                    "_is_fallback": True,
                    "fallback_reason": "SKIP_NORMALIZE=true",
                    "source_step": 2,
                    "source_file": str(output_2),
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "data": payload,
                }
                Path(output_file).parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, 'w', encoding='utf-8') as of:
                    json.dump(fallback_obj, of, ensure_ascii=False, indent=2)
                print(f"    Wrote fallback with metadata {output_file}")
        
        print("\n" + "█"*80)
        print("█" + "[+] PIPELINE COMPLETE!".center(78) + "█")
        print("█" + f"Final output: {output_file}".center(78) + "█")
        print("█"*80)
        
        # Save caches
        save_all_caches(CACHES)
        
        # Print total API calls for parent process to capture
        try:
            from skill_extraction_llm import get_api_call_count
        except Exception:
            get_api_call_count = None

        if get_api_call_count:
            total_api_calls = get_api_call_count()
            if total_api_calls > 0:
                print(f"\n[📊] TOTAL API CALLS IN SUBPROCESS: {total_api_calls}")
        
    except Exception as e:
        log_error(f"Pipeline failed: {str(e)}")
        raise


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                         CLI ARGUMENTS                                       ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Job cleaning 3-step pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python clean_process.py input/test_single_job.json
  python clean_process.py input/test_single_job.json --step 1
  python clean_process.py input/test_single_job.json --step 2
  python clean_process.py input/test_single_job.json --step 3
  python clean_process.py input/test_single_job.json --output custom_output.json
  python clean_process.py --input input/test.json --output output.json
        """
    )
    
    parser.add_argument('input_file', nargs='?', help='Input JSON file (positional or use --input)')
    parser.add_argument('--input', dest='input_flagged', help='Input JSON file (alternative to positional)')
    parser.add_argument('--step', type=int, choices=[1, 2, 3],
                       help='Run specific step (1=clean, 2=extract, 3=normalize)')
    parser.add_argument('--output', help='Output file path')
    parser.add_argument('--debug', type=int, help='Debug job at index')
    parser.add_argument('--limit', type=int, default=None, metavar='N',
                       help='Chỉ xử lý N jobs đầu tiên từ input batch (Sandbox mode)')
    parser.add_argument('--sandbox', action='store_true',
                       help='Shorthand: --limit 5, chạy thử nghiệm nhanh 5 jobs đầu')
    
    args = parser.parse_args()
    
    # Support both positional and flag-based input
    input_file = args.input_flagged or args.input_file
    if not input_file:
        print("❌ Error: Input file required (positional or --input flag)")
        parser.print_help()
        sys.exit(1)
    
    # Validate input file
    if not Path(input_file).exists():
        print(f"❌ Error: Input file not found: {input_file}")
        sys.exit(1)
    
    # Resolve limit (--sandbox is shorthand for --limit 5)
    effective_limit = None
    if args.sandbox:
        effective_limit = 5
    elif args.limit is not None:
        effective_limit = args.limit

    if effective_limit is not None:
        mode_label = f"SANDBOX (limit={effective_limit})"
        default_output = f"clean/sandbox_pending_llm.json"
    else:
        mode_label = "FULL"
        default_output = "clean/pending_llm.json"

    # Execute
    if args.step == 1 or effective_limit is not None:
        # Sandbox always runs step 1 only
        output_file = args.output or (default_output if effective_limit else "clean/pending_llm.json")
        print(f"[*] Mode: {mode_label}")
        step_1_clean_html(input_file, output_file, limit=effective_limit)

    elif args.step == 2:
        output_file = args.output or "clean/extracted.json"
        step_2_extract_sections(input_file, output_file)

    elif args.step == 3:
        output_file = args.output or "clean/normalized.json"
        step_3_normalize_skills(input_file, output_file)

    else:
        output_file = args.output or "clean/normalized.json"
        run_full_pipeline(input_file, output_file)
