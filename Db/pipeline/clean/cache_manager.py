"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                         CACHE MANAGEMENT MODULE                               ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║ PURPOSE:                                                                      ║
║   Quản lý 3 layers cache để tránh tính toán lại:                             ║
║   1. Normalized Skill Cache    - Lưu skills đã chuẩn hóa                    ║
║   2. Normalized Jobs Cache      - Lưu jobs đã xử lý (requirements + skills) ║
║   3. Skill Extraction Cache     - Lưu bộ skills đã trích xuất               ║
║                                                                               ║
║ CACHE LAYERS:                                                                 ║
║   Layer 1: Individual skills → {skill_lower: (normalized, category, conf)}  ║
║   Layer 2: Full jobs → {fingerprint: requirements, extracted_skills}        ║
║   Layer 3: Skill sets → {hash(skill_list): normalized_skills}               ║
║                                                                               ║
║ ORGANIZATION:                                                                 ║
║   1. Configuration & Globals     - Cache paths, CACHE_ENABLED flag          ║
║   2. Cache Key Generation        - Tạo keys từ skill/job/list               ║
║   3. Skill Cache (Load/Save)     - Lưu individual skills                    ║
║   4. Jobs Cache (Load/Save)      - Lưu full job documents                   ║
║   5. Extraction Cache (Load/Save)- Lưu skill sets                           ║
║   6. Batch Operations            - Initialize & save all caches             ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

import json
from pathlib import Path
import hashlib


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                     1. CONFIGURATION & GLOBALS                              ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

# Cache directory & file paths
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

NORMALIZED_SKILL_CACHE_FILE = CACHE_DIR / "normalized_skill_cache.json"
NORMALIZED_JOBS_CACHE_FILE = CACHE_DIR / "normalized_jobs_cache.json"
SKILL_EXTRACTION_CACHE_FILE = CACHE_DIR / "skill_extraction_cache.json"
PENDING_FAILED_JOBS_FILE = CACHE_DIR / "pending_failed_jobs.json"

# Enable/disable caching globally
CACHE_ENABLED = True  # Set to False to disable all caching


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                  2. CACHE KEY GENERATION (Generate Keys)                    ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def get_normalized_skill_cache_key(skill_name):
    """Normalize skill name to lowercase cache key."""
    return skill_name.lower().strip()


def get_normalized_jobs_cache_key(fingerprint):
    """Normalize job fingerprint to cache key."""
    return fingerprint.lower().strip()


def get_skill_extraction_cache_key(skills_list):
    """Hash skill list to deterministic MD5 cache key."""
    if not skills_list:
        return ""
    
    # Extract skill names and sort for consistency
    skill_names = sorted([s.get('skill_name', '') for s in skills_list])
    combined = '|'.join(skill_names)
    return hashlib.md5(combined.encode()).hexdigest()


def get_job_fingerprint(job):
    """Build a stable fingerprint for a job record."""
    title = job.get('title', '')
    company = job.get('company_name', '')
    requirements_text = job.get('requirements_text', '')
    combined = f"{title}|{company}|{requirements_text}"
    return hashlib.md5(combined.encode('utf-8')).hexdigest()


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║                3. SKILL CACHE (Load & Save individual skills)              ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def load_normalized_skill_cache():
    """Load normalized skill mappings from disk cache."""
    if not CACHE_ENABLED or not NORMALIZED_SKILL_CACHE_FILE.exists():
        return {}
    
    try:
        with open(NORMALIZED_SKILL_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"✓ Loaded normalized skill cache: {len(cache)} entries")
        return cache
    except Exception as e:
        print(f"⚠️  Could not load normalized skill cache: {e}")
        return {}


def save_normalized_skill_cache(cache):
    """Save normalized skill cache to disk."""
    if not CACHE_ENABLED:
        return
    
    try:
        with open(NORMALIZED_SKILL_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save normalized skill cache: {e}")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║            4. JOBS CACHE (Load & Save normalized job documents)            ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def load_normalized_jobs_cache():
    """Load normalized job documents from disk cache."""
    if not CACHE_ENABLED or not NORMALIZED_JOBS_CACHE_FILE.exists():
        return {}
    
    try:
        with open(NORMALIZED_JOBS_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"✓ Loaded normalized jobs cache: {len(cache)} entries")
        return cache
    except Exception as e:
        print(f"⚠️  Could not load normalized jobs cache: {e}")
        return {}


def save_normalized_jobs_cache(cache):
    """Save normalized job cache to disk."""
    if not CACHE_ENABLED:
        return
    
    try:
        with open(NORMALIZED_JOBS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save normalized jobs cache: {e}")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║         5. EXTRACTION CACHE (Load & Save skill set extractions)            ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def load_skill_extraction_cache():
    """Load extracted skill sets from disk cache."""
    if not CACHE_ENABLED or not SKILL_EXTRACTION_CACHE_FILE.exists():
        return {}
    
    try:
        with open(SKILL_EXTRACTION_CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"✓ Loaded skill extraction cache: {len(cache)} entries")
        return cache
    except Exception as e:
        print(f"⚠️  Could not load skill extraction cache: {e}")
        return {}


def save_skill_extraction_cache(cache):
    """Save skill extraction cache to disk."""
    if not CACHE_ENABLED:
        return
    
    try:
        with open(SKILL_EXTRACTION_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️  Could not save skill extraction cache: {e}")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║              5B. PENDING FAILED JOBS QUEUE (Load & Save)                  ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def load_pending_failed_jobs():
    """Load failed jobs queue from disk."""
    if not CACHE_ENABLED or not PENDING_FAILED_JOBS_FILE.exists():
        return []

    try:
        with open(PENDING_FAILED_JOBS_FILE, 'r', encoding='utf-8') as f:
            jobs = json.load(f)
        if not isinstance(jobs, list):
            jobs = [jobs]
        print(f"✓ Loaded pending failed jobs queue: {len(jobs)} jobs")
        return jobs
    except Exception as e:
        print(f"⚠️  Could not load pending failed jobs queue: {e}")
        return []


def save_pending_failed_jobs(jobs):
    """Save failed jobs queue to disk."""
    if not CACHE_ENABLED:
        return

    try:
        unique_jobs = {}
        for job in jobs or []:
            if not isinstance(job, dict):
                continue
            fingerprint = job.get('_fingerprint') or get_job_fingerprint(job)
            unique_jobs[fingerprint] = job

        with open(PENDING_FAILED_JOBS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(unique_jobs.values()), f, ensure_ascii=False, indent=2)

        print(f"✓ Saved pending failed jobs queue: {len(unique_jobs)} jobs")
    except Exception as e:
        print(f"⚠️  Could not save pending failed jobs queue: {e}")


def clear_pending_failed_jobs():
    """Remove pending failed jobs queue file."""
    try:
        if PENDING_FAILED_JOBS_FILE.exists():
            PENDING_FAILED_JOBS_FILE.unlink()
    except Exception as e:
        print(f"⚠️  Could not clear pending failed jobs queue: {e}")


# ╔═════════════════════════════════════════════════════════════════════════════╗
# ║              6. BATCH OPERATIONS (Load all / Save all)                      ║
# ╚═════════════════════════════════════════════════════════════════════════════╝

def initialize_all_caches():
    """Load all 3 caches into memory at startup."""
    normalized_skill_cache = load_normalized_skill_cache()
    normalized_jobs_cache = load_normalized_jobs_cache()
    skill_extraction_cache = load_skill_extraction_cache()
    
    return {
        'normalized_skill_cache': normalized_skill_cache,
        'normalized_jobs_cache': normalized_jobs_cache,
        'skill_extraction_cache': skill_extraction_cache
    }


def save_all_caches(caches):
    """Save all 3 caches to disk in one operation."""
    save_normalized_skill_cache(caches.get('normalized_skill_cache', {}))
    save_normalized_jobs_cache(caches.get('normalized_jobs_cache', {}))
    save_skill_extraction_cache(caches.get('skill_extraction_cache', {}))
    
    total = sum(len(v) for v in caches.values() if isinstance(v, dict))
    print(f"   💾 Saved all caches: {total} total entries")
