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

# Load .env for config override
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"[*] Loaded .env from {env_file}")
else:
    print(f"[!] .env not found at {env_file}, using defaults")

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
            raw_text = cleaned_job.get('description_html') or ''
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

            # 3) No significant HTML left
            if re.search(r"<[^>]{1,50}>", cleaned_text):
                reasons.append('html_leftover')

            # 4) Not garbage (alnum ratio)
            total_chars = max(1, len(cleaned_text))
            alnum_count = sum(1 for c in cleaned_text if c.isalnum())
            alnum_ratio = alnum_count / total_chars
            if alnum_ratio < 0.5:
                reasons.append('low_alnum_ratio')

            # 5) Not only special characters / whitespace
            visible_chars = re.sub(r"[\W_]+", "", cleaned_text)
            if not visible_chars:
                reasons.append('only_special_chars')

            # 6) Recruitment signal keywords (EN + VI)
            signals = [
                'requirement','requirements','responsibilities','skills','experience','benefits','job description',
                'yêu cầu','trách nhiệm','kinh nghiệm','quyền lợi','mô tả công việc','yêu cầu công việc'
            ]
            txt_lower = (cleaned_text or '').lower()
            if not any(s in txt_lower for s in signals):
                reasons.append('no_recruitment_signal')

            # 7) Required metadata
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
            header = f"{'#':<3} {'HTML Chars':>11} {'Clean Chars':>11} {'Giảm %':>7}  {'URL / Title'}"
            print(header)
            print("-" * 80)
            for i, cj in enumerate(cleaned_jobs, 1):
                raw_html = cj.get('description_html') or ''
                clean_txt = cj.get('requirements_text') or ''
                html_len  = len(raw_html)
                clean_len = len(clean_txt)
                ratio = (1 - clean_len / html_len) * 100 if html_len > 0 else 0.0
                label = (cj.get('job_url') or cj.get('title') or 'N/A')[:60]
                print(f"{i:<3} {html_len:>11,} {clean_len:>11,} {ratio:>6.1f}%  {label}")
            print("-" * 80)
            total_html  = sum(len(cj.get('description_html') or '') for cj in cleaned_jobs)
            total_clean = sum(len(cj.get('requirements_text') or '') for cj in cleaned_jobs)
            avg_ratio = (1 - total_clean / total_html) * 100 if total_html > 0 else 0.0
            print(f"{'AVG':<3} {total_html//len(cleaned_jobs):>11,} {total_clean//len(cleaned_jobs):>11,} {avg_ratio:>6.1f}%  (trung bình)")
            print("=" * 80)

        return cleaned_jobs

    except Exception as e:
        log_error(f"STEP 1 failed: {str(e)}")
        raise


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                   STEP 2: EXTRACT SECTIONS                                  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def step_2_extract_sections(input_file, output_file="clean/extracted.json"):
    """Extract sections from cleaned text + extract skills via LLM (SEQUENTIAL)."""
    print(f"\n{'='*80}")
    print("STEP 2: EXTRACT JOB SECTIONS & SKILLS (SEQUENTIAL)")
    print(f"{'='*80}")
    
    try:
        # Load config - Priority: .env > clean_config.yaml
        batch_size = int(os.getenv("ETL_CLEAN_BATCH_SIZE", "0"))
        
        if batch_size == 0:
            # Fallback to clean_config.yaml
            config_path = Path(__file__).parent / "clean_config.yaml"
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            batch_size = config.get('batch_size', 60)
            print(f"[*] batch_size from clean_config.yaml: {batch_size}")
        else:
            print(f"[*] batch_size from .env (ETL_CLEAN_BATCH_SIZE): {batch_size}")
        
        # Load input JSON safely; if unreadable, move to fallback and continue
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_text = f.read()
        try:
            jobs = json.loads(raw_text)
        except json.JSONDecodeError as e:
            pass
            # Prefer crawl run folder under Db/data (e.g., Db/data/crawl_.../fallback)
            crawl_dir = _find_crawl_run_dir(input_file)
            if crawl_dir:
                fallback_dir = crawl_dir / 'fallback'
            else:
                fallback_dir = DB_ROOT / 'data' / 'fallback'
            fallback_dir.mkdir(parents=True, exist_ok=True)
            # Use fixed fallback filename per step (crawl run folder provides isolation)
            fallback_name = "extract_fallback.json"
            fallback_path = fallback_dir / fallback_name
            with open(fallback_path, 'w', encoding='utf-8') as bf:
                bf.write(raw_text)
            log_error(f"STEP 2: unreadable JSON moved to fallback: {fallback_path} ({str(e)})")
            # Return empty list so pipeline can continue without halting
            return []
        
        if not isinstance(jobs, list):
            jobs = [jobs]
        
        print(f"[*] Loaded {len(jobs)} jobs")
        print(f"[*] STEP 2 input file: {input_file}")
        print(f"[*] STEP 2 output file: {output_file}")
        print(f"[*] STEP 2 raw job count: {len(jobs)}")
        
        use_llm = os.getenv("CLEAN_USE_LLM", "false").lower() in ("true", "1", "yes")
        if use_llm:
            # Smart thread allocation: Use actual available keys from SkillExtractor
            print("[*] Importing SkillExtractor...", flush=True)
            from skill_extraction_llm import SkillExtractor, init_api_counter

            print("[*] Initializing API call counter...", flush=True)
            init_api_counter()

            from skill_extraction_llm import load_all_api_keys
            available_keys, key_numbers = load_all_api_keys()
            num_available_keys = len(available_keys)

            # Show which keys are loaded
            if key_numbers and key_numbers[0] != 0:  # Skip if fallback (0)
                key_summary = ", ".join([f"GEMINI_API_KEY_{k}" for k in key_numbers])
                print(f"[*] Loaded {num_available_keys} API keys: {key_summary}")
            else:
                print(f"[*] Available API keys: {num_available_keys}")

            print(f"[*] Using sequential extraction only (jobs={len(jobs)}, keys={num_available_keys})")
            sequential_extractor = SkillExtractor()
        else:
            num_available_keys = 0
            sequential_extractor = None
            print(f"[*] Using regex-only mode (jobs={len(jobs)})")
        
        extracted_jobs = []
        
        # Process jobs in batches
        total_batches = (len(jobs) + batch_size - 1) // batch_size
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(jobs))
            batch_jobs = jobs[start_idx:end_idx]
            
            print(f"\n[BATCH {batch_num+1}/{total_batches}] Processing {len(batch_jobs)} jobs ({start_idx+1}-{end_idx})...")
            print(f"   [BATCH {batch_num+1}] job titles: {[(job.get('title') or '')[:40] for job in batch_jobs]}")
            
            # Step A: Prepare jobs for extraction without pre-splitting sections
            print(f"   ├─ SUB-STEP 1: Preparing jobs (no pre-splitting)...")
            for job in batch_jobs:
                # Do not pre-split requirements_text anymore; keep full cleaned text
                pass
            
            # Step B: Extract skills SEQUENTIALLY or skip LLM entirely in regex-only mode
            if use_llm:
                print(f"   ├─ SUB-STEP 2: Extracting skills SEQUENTIALLY ({len(batch_jobs)} jobs)...")
            else:
                print(f"   ├─ SUB-STEP 2: Regex-only mode, skipping Gemini extraction ({len(batch_jobs)} jobs)...")
            
            # Prepare batch: choose extraction input according to priority
            # Priority (first non-empty):
            # 1) job.skills_desc.value (or job.skills_desc)
            # 2) raw.requirements_text
            # 3) requirements_text
            # 4) fallback: full cleaned text (description / description_html)
            batch_for_extraction = []
            for job in batch_jobs:
                # Create a shallow copy for extraction (avoid modifying original)
                job_copy = job.copy()

                def _pick_skill_input(j):
                    # 1) nested job.skills_desc
                    job_block = j.get('job') or {}
                    skills_desc = job_block.get('skills_desc') or j.get('skills_desc')
                    if isinstance(skills_desc, dict):
                        val = skills_desc.get('value')
                        if val and str(val).strip():
                            return str(val), 'job.skills_desc.value'
                    if isinstance(skills_desc, str) and skills_desc.strip():
                        return skills_desc, 'job.skills_desc'

                    # 2) raw.requirements_text
                    raw_req = (j.get('raw') or {}).get('requirements_text')
                    if raw_req and str(raw_req).strip():
                        return str(raw_req), 'raw.requirements_text'

                    # 3) requirements_text
                    req = j.get('requirements_text')
                    if req and str(req).strip():
                        return str(req), 'requirements_text'

                    # 4) fallback to cleaned full text
                    fallback = j.get('description') or j.get('description_html') or j.get('requirements_text') or ''
                    return str(fallback), 'fallback.cleaned_full_text'

                chosen_text, chosen_src = _pick_skill_input(job)
                job_copy['requirements_text'] = chosen_text
                # Annotate source used so we can report/debug later
                job_copy['_skill_input_source'] = chosen_src
                batch_for_extraction.append(job_copy)

            print(f"   ├─ DEBUG: batch_for_extraction size = {len(batch_for_extraction)}")
            for idx, job in enumerate(batch_for_extraction, 1):
                req_len = len(job.get('requirements_text', '') or '')
                print(f"   │  [JOB {idx}] title='{(job.get('title') or '')[:40]}', req_len={req_len}")

            if use_llm and sequential_extractor:
                # Run sequential extraction with a single extractor
                skills_results = []
                for idx, job in enumerate(batch_for_extraction, 1):
                    req_text = job.get('requirements_text', '')
                    title = job.get('title') or ''
                    print(f"   │  [SEQ {idx}/{len(batch_for_extraction)}] title='{title[:40]}' req_len={len(req_text)}")
                    result = sequential_extractor.extract_skills(req_text, job_id=job.get('fingerprint'))
                    skills_results.append(result)

                print(f"   └─ ✓ Sequential extraction complete")
            else:
                skills_results = [
                    {
                        'is_it_job': False,
                        'extracted_skills': [],
                        'benefits': [],
                    }
                    for _ in batch_for_extraction
                ]
                print(f"   └─ ✓ Regex-only output prepared (no LLM calls)")

            # Validate LLM outputs before merge (pre-merge validation)
            try:
                import importlib
                val_mod = importlib.import_module('Db.2_clean_data.extract_validation_rules')
                validate_record = getattr(val_mod, 'validate_record')
            except Exception:
                validate_record = None

            validated_results = []
            for orig_job, skills in zip(batch_for_extraction, skills_results):
                if validate_record and isinstance(skills, dict):
                    try:
                        validated, validation = validate_record(skills, orig_job)
                        # ensure validation present
                        validated['validation'] = validation if isinstance(validation, dict) else validated.get('validation', {})
                        validated_results.append(validated)
                    except Exception as e:
                        print(f"      [VALIDATION] validation failure: {e}")
                        # fallback to original skills result
                        validated_results.append(skills)
                else:
                    validated_results.append(skills)

            # Collect failed jobs so they can be retried on the next run
            failed_jobs = []
            for job, skills in zip(batch_for_extraction, validated_results):
                if isinstance(skills, dict) and skills.get('error'):
                    failed_job = job.copy()
                    failed_job['_error'] = skills.get('error')
                    failed_job['_message'] = skills.get('message', '')
                    failed_job['_fingerprint'] = job.get('fingerprint') or get_job_fingerprint(job)
                    failed_jobs.append(failed_job)

            if failed_jobs:
                print(f"   ⚠️  Saving {len(failed_jobs)} failed jobs for next run")
                save_pending_failed_jobs(failed_jobs)

            # Replace original skills_results with validated_results for merging
            skills_results = validated_results
            
            # Step C: Merge results
            print(f"   └─ SUB-STEP 3: Merging results...")
            for job, skills in zip(batch_jobs, skills_results):

                if isinstance(skills, dict):
                    # Merge null fields from extraction
                    if skills.get('title') and not job.get('title'):
                        job['title'] = skills['title']
                    if skills.get('location') and not job.get('location_raw'):
                        job['location_raw'] = skills['location']
                    if skills.get('employment_type') and not job.get('employment_type'):
                        job['employment_type'] = skills['employment_type']
                    if skills.get('experience_raw') and not job.get('experience_raw'):
                        job['experience_raw'] = skills['experience_raw']
                    if skills.get('company_size_raw') and not job.get('company_size_raw'):
                        job['company_size_raw'] = skills['company_size_raw']
                    if skills.get('company_industry') and not job.get('company_industry'):
                        job['company_industry'] = skills['company_industry']
                    
                    # Add extracted skills
                    job['extracted_skills'] = skills.get('extracted_skills', [])
                    job['benefits'] = skills.get('benefits', [])
                    job['is_it_job'] = skills.get('is_it_job', False)
                    # Fingerprint: Only create AFTER successful LLM extraction
                    # Follow rule: use LLM-returned requirements_text if present, else fallback to original
                                # Ensure `job.search_group` is always set from the original input search_keyword
                # (nested `job` object is added here for compatibility with other extractors)
                if job.get('search_keyword'):
                    job.setdefault('job', {})
                    job['job']['search_group'] = {"value": job.get('search_keyword'), "confidence": 100}

                # Use section extraction to produce a cleaned, bullet-preserving `description`
                # and a human-readable `skills_desc` (requirements section). Prefer the
                # explicit requirements/job_description sections from the cleaned text.
                try:
                    cleaned_text = job.get('requirements_text') or job.get('description_html') or ''
                    sections = extract_job_sections(cleaned_text)
                    jd = (sections.get('job_description') or '').strip()
                    reqs = (sections.get('requirements') or '').strip()
                    # Set description to the job_description section if it's non-empty and
                    # looks richer than any existing short description.
                    if jd:
                        # prefer multi-line / bullet content
                        if not job.get('description') or len(re.sub(r"\s+", " ", str(job.get('description')))) < 120:
                            job['description'] = jd
                    # Set skills_desc to the cleaned requirements section (preserve bullets)
                    if reqs:
                        job['skills_desc'] = reqs
                except Exception:
                    # Do not fail the whole batch if section extraction has an issue
                    pass
                else:
                    job['extracted_skills'] = skills if isinstance(skills, list) else []
                    job['benefits'] = []
                    job['is_it_job'] = len(job.get('extracted_skills', [])) > 0
                
                extracted_jobs.append(job)
        
        # Save output
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(extracted_jobs, f, ensure_ascii=False, indent=2)
        
        print(f"\n[+] STEP 2 Complete!")
        print(f"   Output: {output_file} (debug)")
        print(f"   Jobs: {len(extracted_jobs)}")
        print(f"   Skills extracted: {sum(len(j.get('extracted_skills', [])) for j in extracted_jobs)}")
        
        return extracted_jobs
        
    except Exception as e:
        log_error(f"STEP 2 failed: {str(e)}")
        raise


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                   STEP 3: NORMALIZE SKILLS                                  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def step_3_normalize_skills(input_file, output_file="clean/normalized.json"):
    """Normalize technical skills + benefits using embedding matcher (cached FAISS)."""
    # Delegate normalization to the controller in 2_1_normalized_data
    # The package directory begins with a digit (2_1_normalized_data) which is not a
    # valid Python identifier for direct imports. Load the module by file path so
    # this function works regardless of the directory name.
    run_normalize = None
    try:
        # Prefer filesystem import by locating the controller file
        controller_path = DB_ROOT / '2_1_normalized_data' / 'normalize_controller.py'
        if controller_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location('normalize_controller_local', str(controller_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            run_normalize = getattr(mod, 'run_normalize')
        else:
            # Controller file not found at expected path; will raise below.
            run_normalize = None
    except Exception:
        run_normalize = None

    if run_normalize is None:
        raise ImportError(f"normalize_controller.py not found at {controller_path!s}; cannot run normalization")

    # Determine fallback folder: prefer crawl run folder under Db/data
    crawl_dir = _find_crawl_run_dir(input_file)
    if crawl_dir:
        fallback_dir = crawl_dir / 'fallback'
    else:
        fallback_dir = DB_ROOT / 'data' / 'fallback'
    fallback_dir.mkdir(parents=True, exist_ok=True)
    fallback_file = fallback_dir / "normalize_fallback.json"

    return run_normalize(input_file, output_file, str(fallback_file))


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                    FULL PIPELINE                                            ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

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
