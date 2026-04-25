"""
SCRIPT 12: APPLY LLM RANKINGS TO KEYWORD GROUPS
For each search_keyword group, apply Google Gemini to rank 13 skill categories
"""

import json
import os
import re
import sys
import warnings
import time
from pathlib import Path
from collections import Counter

# Suppress Gemini deprecation warning
warnings.filterwarnings('ignore', category=FutureWarning)

# Try to import Gemini (new or old package)
try:
    import google.genai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    try:
        import google.generativeai as genai
        GEMINI_AVAILABLE = True
    except ImportError:
        GEMINI_AVAILABLE = False
        print("[!] Warning: google-genai or google-generativeai not installed.")
        print("    Install with: pip install google-genai")
        print("    (or: pip install google-generativeai for deprecated version)")

# Get output directory from environment or use current directory
OUTPUT_DIR = os.getenv('PIPELINE_OUTPUT_DIR')
if OUTPUT_DIR:
    OUTPUT_DIR = Path(OUTPUT_DIR)
else:
    OUTPUT_DIR = Path(__file__).parent

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Cache file for LLM rankings (persistent across runs)
CACHE_FILE = OUTPUT_DIR / "category_rankings_by_keyword.json"
CACHE_ENABLED = True  # Set to False to disable caching

# Rate limit configuration
REQUESTS_PER_MINUTE = int(os.getenv('REQUESTS_PER_MINUTE', '60'))
REQUESTS_PER_DAY = int(os.getenv('REQUESTS_PER_DAY', '1500'))  # Gemini free tier limit
DELAY_BETWEEN_REQUESTS = 60.0 / max(REQUESTS_PER_MINUTE, 1)  # seconds
MIN_DELAY_BETWEEN_REQUESTS = 1.0  # Minimum delay (in case of high RPM)

# Request counter tracking (for RPD limit)
REQUEST_LOG_FILE = OUTPUT_DIR / "api_request_log.json"
REQUEST_COUNTER = {
    "today_date": None,
    "requests_today": 0,
    "last_request_time": 0,
    "requests_this_minute": 0,
}

# API key rotation system
GEMINI_API_KEYS = [
    os.getenv('GEMINI_API_KEY_1') or os.getenv('GEMINI_API_KEY'),
    os.getenv('GEMINI_API_KEY_2'),
    os.getenv('GEMINI_API_KEY_3'),
]
# Filter out None values
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

# Current key index
CURRENT_KEY_INDEX = 0
QUOTA_ERRORS = []  # Track which keys hit quota limit

SKILL_CATEGORIES = [
    "Backend_Frameworks",
    "Cloud_DevOps_Tools",
    "Data_AI_Stack",
    "Databases_Storage",
    "Frontend_Frameworks",
    "Languages",
    "Methodologies",
    "Mobile_Frameworks",
    "Security_Tools",
    "Testing_Frameworks",
]

# Fallback heuristics (if Gemini fails)
FALLBACK_RANKINGS = {
    "Backend": [
        "Languages",
        "Backend_Frameworks",
        "Databases_Storage",
        "Cloud_DevOps_Tools",
        "Testing_Frameworks",
        "Methodologies",
        "Security_Tools",
        "Data_AI_Stack",
        "Mobile_Frameworks",
        "Frontend_Frameworks",
    ],
    "Frontend": [
        "Frontend_Frameworks",
        "Languages",
        "Testing_Frameworks",
        "Cloud_DevOps_Tools",
        "Methodologies",
        "Mobile_Frameworks",
        "Backend_Frameworks",
        "Security_Tools",
        "Data_AI_Stack",
        "Databases_Storage",
    ],
    "QA": [
        "Testing_Frameworks",
        "Languages",
        "Backend_Frameworks",
        "Frontend_Frameworks",
        "Cloud_DevOps_Tools",
        "Methodologies",
        "Security_Tools",
        "Databases_Storage",
        "Data_AI_Stack",
        "Mobile_Frameworks",
    ],
    "Data": [
        "Data_AI_Stack",
        "Databases_Storage",
        "Languages",
        "Cloud_DevOps_Tools",
        "Backend_Frameworks",
        "Methodologies",
        "Testing_Frameworks",
        "Security_Tools",
        "Frontend_Frameworks",
        "Mobile_Frameworks",
    ],
    "DevOps": [
        "Cloud_DevOps_Tools",
        "Languages",
        "Backend_Frameworks",
        "Testing_Frameworks",
        "Methodologies",
        "Security_Tools",
        "Databases_Storage",
        "Mobile_Frameworks",
        "Frontend_Frameworks",
        "Data_AI_Stack",
    ],
    "Security": [
        "Security_Tools",
        "Languages",
        "Cloud_DevOps_Tools",
        "Backend_Frameworks",
        "Frontend_Frameworks",
        "Methodologies",
        "Testing_Frameworks",
        "Databases_Storage",
        "Data_AI_Stack",
        "Mobile_Frameworks",
    ],
}


def create_group_summary(keyword: str, jobs: list) -> str:
    """Create a summary of a job group for LLM analysis."""
    
    # Count skill frequencies
    skill_counts = Counter()
    category_counts = Counter()
    
    for job in jobs:
        skills = job.get('skills_with_category', [])
        for skill in skills:
            skill_name = skill.get('name', '').lower()
            category = skill.get('category')
            if skill_name:
                skill_counts[skill_name] += 1
            if category:
                category_counts[category] += 1
    
    # Get top skills per category
    top_skills_by_category = {}
    for job in jobs:
        skills = job.get('skills_with_category', [])
        for skill in skills:
            category = skill.get('category')
            skill_name = skill.get('name', '')
            if category and skill_name:
                if category not in top_skills_by_category:
                    top_skills_by_category[category] = Counter()
                top_skills_by_category[category][skill_name] += 1
    
    # Build summary text
    summary = f"GROUP ANALYSIS: {keyword} Position ({len(jobs)} jobs)\n\nTop Skills:"
    
    for category in SKILL_CATEGORIES:
        if category in top_skills_by_category:
            top_5_skills = top_skills_by_category[category].most_common(5)
            if top_5_skills:
                skills_str = ", ".join([f"{skill}({count})" for skill, count in top_5_skills])
                summary += f"\n  * {category}: {skills_str}"
    
    return summary


def load_request_counter():
    """Load request counter from file."""
    global REQUEST_COUNTER
    
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    
    if REQUEST_LOG_FILE.exists():
        try:
            with open(REQUEST_LOG_FILE, 'r') as f:
                data = json.load(f)
            
            # Reset if it's a new day
            if data.get('today_date') != today:
                REQUEST_COUNTER = {
                    "today_date": today,
                    "requests_today": 0,
                    "last_request_time": 0,
                    "requests_this_minute": 0,
                }
            else:
                REQUEST_COUNTER = data
        except Exception as e:
            print(f"[!] Error loading request counter: {e}")
    else:
        REQUEST_COUNTER['today_date'] = today
    
    return REQUEST_COUNTER


def save_request_counter():
    """Save request counter to file."""
    try:
        with open(REQUEST_LOG_FILE, 'w') as f:
            json.dump(REQUEST_COUNTER, f, indent=2)
    except Exception as e:
        print(f"[!] Error saving request counter: {e}")


def check_rate_limit():
    """Check if we can make another API call without exceeding limits."""
    global REQUEST_COUNTER
    
    from datetime import datetime
    import time as time_module
    
    current_time = time_module.time()
    
    # Check RPD limit
    if REQUEST_COUNTER['requests_today'] >= REQUESTS_PER_DAY:
        return False, f"Daily limit reached ({REQUEST_COUNTER['requests_today']}/{REQUESTS_PER_DAY})"
    
    # Check RPM limit
    time_since_last = current_time - REQUEST_COUNTER['last_request_time']
    
    return True, f"OK ({REQUEST_COUNTER['requests_today']}/{REQUESTS_PER_DAY} today)"


def calculate_smart_delay():
    """Calculate delay before next request based on rate limits."""
    import time as time_module
    
    current_time = time_module.time()
    time_since_last = current_time - REQUEST_COUNTER['last_request_time']
    
    # Calculate required delay for RPM limit
    delay_for_rpm = max(0, DELAY_BETWEEN_REQUESTS - time_since_last)
    
    # Apply delay
    if delay_for_rpm > 0:
        return delay_for_rpm
    
    return MIN_DELAY_BETWEEN_REQUESTS


def record_api_call():
    """Record an API call in the counter."""
    global REQUEST_COUNTER
    import time as time_module
    
    REQUEST_COUNTER['requests_today'] += 1
    REQUEST_COUNTER['last_request_time'] = time_module.time()
    save_request_counter()


def get_next_api_key():

    """Get next available API key, rotating if needed."""
    global CURRENT_KEY_INDEX, QUOTA_ERRORS
    
    if not GEMINI_API_KEYS:
        return None
    
    # Try current key first
    if CURRENT_KEY_INDEX < len(GEMINI_API_KEYS):
        key = GEMINI_API_KEYS[CURRENT_KEY_INDEX]
        if key not in QUOTA_ERRORS:
            return key
    
    # Find next available key
    for idx, key in enumerate(GEMINI_API_KEYS):
        if key and key not in QUOTA_ERRORS:
            CURRENT_KEY_INDEX = idx
            return key
    
    # All keys exhausted
    return None


def rotate_to_next_key():
    """Move to next API key when current one hits quota."""
    global CURRENT_KEY_INDEX, QUOTA_ERRORS
    
    if CURRENT_KEY_INDEX < len(GEMINI_API_KEYS):
        key = GEMINI_API_KEYS[CURRENT_KEY_INDEX]
        QUOTA_ERRORS.append(key)
        print(f"  [!] Key {CURRENT_KEY_INDEX + 1} hit quota limit, rotating...")
    
    CURRENT_KEY_INDEX += 1
    next_key = get_next_api_key()
    
    if next_key:
        print(f"  [*] Now using key {CURRENT_KEY_INDEX + 1}")
        return True
    else:
        print(f"  [!] All API keys exhausted!")
        return False


def call_llm_for_group(keyword: str, jobs: list) -> tuple:
    """
    Call Google Gemini API to rank skill categories for a job group.
    Respects rate limits (RPM & RPD).
    Supports key rotation on quota limit (429 errors).
    Falls back to hardcoded heuristics if all keys exhausted.
    Returns (llm_output, api_called) where api_called=True if Gemini API was used.
    """
    
    # Check rate limits FIRST
    can_call, reason = check_rate_limit()
    if not can_call:
        print(f"  [!] Rate limit: {reason}")
        print(f"  [*] Using fallback for {keyword}")
        
        # Use fallback
        if keyword in FALLBACK_RANKINGS:
            ranking_list = FALLBACK_RANKINGS[keyword]
        else:
            ranking_list = sorted(SKILL_CATEGORIES)
        
        llm_output = "\n".join([f"{idx+1}. {cat}" for idx, cat in enumerate(ranking_list)])
        return llm_output, False
    
    # Use fallback by default (if API not available)
    if keyword in FALLBACK_RANKINGS:
        ranking_list = FALLBACK_RANKINGS[keyword]
    else:
        ranking_list = sorted(SKILL_CATEGORIES)
    
    # Try Gemini API if available
    if not GEMINI_AVAILABLE:
        print(f"  [*] Using fallback for {keyword} (Gemini not available)")
        llm_output = "\n".join([f"{idx+1}. {cat}" for idx, cat in enumerate(ranking_list)])
        return llm_output, False
    
    api_key = get_next_api_key()
    if not api_key:
        print(f"  [*] Using fallback for {keyword} (No GEMINI_API_KEY)")
        llm_output = "\n".join([f"{idx+1}. {cat}" for idx, cat in enumerate(ranking_list)])
        return llm_output, False
    
    # Calculate and apply delay BEFORE making request
    delay = calculate_smart_delay()
    if delay > 0:
        print(f"  [*] Waiting {delay:.2f}s (rate limit: {REQUESTS_PER_MINUTE} req/min)...")
        time.sleep(delay)
    
    try:
        genai.configure(api_key=api_key)
        # Use model from environment or fallback to latest
        model_name = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
        try:
            model = genai.GenerativeModel(model_name)
        except:
            try:
                model = genai.GenerativeModel('gemini-2.0-flash')
            except:
                model = genai.GenerativeModel('gemini-1.5-pro')
        
        # Create summary of skills
        group_summary = create_group_summary(keyword, jobs)
        
        # Prepare prompt for Gemini
        prompt = f"""You are a job market expert. Analyze this job group and rank these 10 skill categories by importance.

{group_summary}

Available categories to rank:
{', '.join(SKILL_CATEGORIES)}

Task: Rank these 10 categories from most to least important for "{keyword}" roles.
Return ONLY a numbered list (1-10), one category per line, in this format:
1. Category_Name
2. Category_Name
...

Do NOT include any other text."""

        # Call Gemini API
        request_options = None
        if genai.__name__ == "google.generativeai":
            from gemini_request_options import build_request_options

            request_options = build_request_options()

        request_kwargs = {
            "generation_config": genai.types.GenerationConfig(
                temperature=0.3,
                top_p=0.9,
                top_k=40,
                max_output_tokens=200,
            ),
        }
        if request_options is not None:
            request_kwargs["request_options"] = request_options

        response = model.generate_content(prompt, **request_kwargs)
        
        llm_output = response.text.strip()
        
        # Record successful API call
        record_api_call()
        
        print(f"  [✓] {keyword} (API call #{REQUEST_COUNTER['requests_today']}/{REQUESTS_PER_DAY})")
        return llm_output, True  # ← API was called
        
    except Exception as e:
        error_str = str(e)
        
        # Check if it's a quota error (429)
        if "429" in error_str or "quota" in error_str.lower():
            # Rotate to next key
            if rotate_to_next_key():
                # Retry with new key
                return call_llm_for_group(keyword, jobs)
            else:
                # All keys exhausted
                print(f"  [!] All keys exhausted for {keyword}")
                print(f"  [*] Using fallback for {keyword}")
                llm_output = "\n".join([f"{idx+1}. {cat}" for idx, cat in enumerate(ranking_list)])
                return llm_output, False
        else:
            # Other error
            print(f"  [!] Gemini error for {keyword}: {error_str[:50]}")
            print(f"  [*] Using fallback for {keyword}")
            llm_output = "\n".join([f"{idx+1}. {cat}" for idx, cat in enumerate(ranking_list)])
            return llm_output, False


def parse_llm_ranking(llm_output: str) -> dict:
    """Parse LLM output to extract rankings."""
    
    rankings = {}
    lines = llm_output.strip().split('\n')
    
    for line in lines:
        match = re.match(r'^\s*(\d+)\.\s*([A-Za-z_]+)', line)
        if match:
            rank = int(match.group(1))
            category = match.group(2)
            if category in SKILL_CATEGORIES:
                rankings[category] = rank
    
    # Fill missing categories
    for category in SKILL_CATEGORIES:
        if category not in rankings:
            rankings[category] = 14
    
    return rankings


def load_ranking_cache():
    """Load cached rankings from previous runs."""
    if not CACHE_ENABLED or not CACHE_FILE.exists():
        return {}
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"📦 Loaded cache with {len(cache)} keywords")
        return cache
    except Exception as e:
        print(f"[!] Error loading cache: {e}")
        return {}


def save_ranking_cache(rankings):
    """Save rankings to cache file."""
    if not CACHE_ENABLED:
        return
    
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(rankings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] Error saving cache: {e}")


def apply_llm_to_groups():
    """Apply LLM to each keyword group (with caching & rate limiting)."""
    
    # Load request counter at start
    print("📊 Rate Limiting:")
    load_request_counter()
    print(f"  • RPM Limit: {REQUESTS_PER_MINUTE} requests/minute")
    print(f"  • RPD Limit: {REQUESTS_PER_DAY} requests/day")
    print(f"  • Requests today: {REQUEST_COUNTER['requests_today']}")
    
    # Load grouped jobs (using test data)
    print("\nLoading jobs_grouped_by_keyword.json...")
    grouped_file = OUTPUT_DIR / "jobs_grouped_by_keyword.json"
    
    if not grouped_file.exists():
        print(f"ERROR: {grouped_file} not found!")
        print("Please run Script 11 first: python 11_generate_training_data.py")
        return
    
    with open(grouped_file, 'r', encoding='utf-8') as f:
        all_groups = json.load(f)
    
    print(f"Loaded {len(all_groups)} job groups")
    
    # Load ranking cache from previous runs
    print("\n📦 Cache system:")
    cached_results = load_ranking_cache()
    
    # Find which keywords need new rankings
    keywords_to_process = [kw for kw in all_groups.keys() if kw not in cached_results]
    keywords_cached = [kw for kw in all_groups.keys() if kw in cached_results]
    
    print(f"  ✓ Cached: {len(keywords_cached)} keywords")
    print(f"  ✗ New: {len(keywords_to_process)} keywords")
    
    # Apply LLM to each NEW group (skip cached ones)
    print("\n🔄 Applying LLM rankings...")
    print(f"  Delay per request: {DELAY_BETWEEN_REQUESTS:.2f}s")
    
    new_results = {}
    api_calls = 0
    
    for keyword, jobs in all_groups.items():
        # Skip if already cached
        if keyword in cached_results:
            print(f"  ⟳ {keyword} (cached)")
            continue
        
        # Call LLM with rate limiting
        llm_output, api_called = call_llm_for_group(keyword, jobs)
        
        # Count API calls
        if api_called:
            api_calls += 1
        
        # Parse rankings
        rankings = parse_llm_ranking(llm_output)
        
        # Store result
        new_results[keyword] = {
            "total_jobs": len(jobs),
            "rankings": rankings
        }
    
    # Merge cached + new results
    results = {**cached_results, **new_results}
    
    # Save combined results
    output_file = OUTPUT_DIR / "category_rankings_by_keyword.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    # Save cache
    save_ranking_cache(results)
    
    print(f"\n📊 Summary:")
    print(f"  • Cached keywords reused: {len(keywords_cached)}")
    print(f"  • New keywords processed: {len(keywords_to_process)}")
    print(f"  • API calls made: {api_calls}/{REQUESTS_PER_DAY} (daily limit)")
    print(f"  • Total results: {len(results)}")
    print(f"  • Daily requests so far: {REQUEST_COUNTER['requests_today']}/{REQUESTS_PER_DAY}")
    print(f"\nSUCCESS: Applied LLM rankings to {len(results)} groups")
    print(f"Output file: {output_file}")
    print(f"File size: {output_file.stat().st_size / 1024:.1f} KB")
    
    # Show sample results
    print("\n" + "="*80)
    print("SAMPLE RESULTS (First 3 keywords)")
    print("="*80)
    
    for keyword, result in list(results.items())[:3]:
        print(f"\nKeyword: {keyword}")
        print(f"Total jobs: {result['total_jobs']}")
        print(f"Rankings (top 7):")
        for cat, rank in sorted(result['rankings'].items(), key=lambda x: x[1])[:7]:
            print(f"  {rank}. {cat}")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    apply_llm_to_groups()
