#!/usr/bin/env python3
"""
SKILL EXTRACTION via LLM - Simple auto-rotate & RPM limiting
- Integrated skill translation (VN → ENG) into extraction step
- Returns skill_name_eng directly without separate translator calls
- NO tracker files
- Auto-rotate on 429 (quota exhausted)
- RPM limit: max 3 requests/minute (20s interval)
- Debug output shows current API key
"""

import json
import os
import sys
import time
import logging
import http.client
import threading
import re
import yaml
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gemini_request_options import build_request_options
from Db.job_extraction_rules import (
    build_job_extraction_generation_config_kwargs,
    load_job_extraction_prompt,
    normalize_job_extraction_output,
)

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Load .env from Db folder (parent of 2_clean_data)
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)


def enable_http_debug_logging():
    """Enable low-level HTTP debug logs for Gemini SDK calls."""
    debug_enabled = os.getenv("GEMINI_HTTP_DEBUG", "true").lower() in ("true", "1", "yes")
    if not debug_enabled:
        return

    http.client.HTTPConnection.debuglevel = 1

    # Log SDK / HTTP library noise to the console so subprocess wrappers can see it.
    logging.basicConfig(level=logging.DEBUG)
    for logger_name in ("google", "google.generativeai", "google.api_core", "urllib3"):
        logging.getLogger(logger_name).setLevel(logging.DEBUG)

    trace_log("[HTTP_DEBUG] Enabled http.client debuglevel=1 and SDK debug logging")


# Global counter for API calls
_api_call_count = 0
_api_call_lock = None
_api_call_log_file = None


class QuotaExhaustedError(Exception):
    """Raised when one API key is exhausted by a 429/quota response."""
    pass

def init_api_counter():
    """Initialize global API call counter with thread lock"""
    global _api_call_lock, _api_call_log_file
    import threading
    _api_call_lock = threading.Lock()
    # Create log file for API calls
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    _api_call_log_file = log_dir / "api_calls.log"
    with open(_api_call_log_file, 'w') as f:
        f.write("=== API CALLS LOG ===\n\n")

def trace_log(msg):
    """Log trace messages to file (works in subprocess)"""
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    trace_file = log_dir / "trace.log"
    with open(trace_file, 'a') as f:
        f.write(f"{msg}\n")


def format_request_times(request_times):
    if not request_times:
        return "[]"
    return "[" + ", ".join(f"{timestamp:.3f}" for timestamp in request_times) + "]"


enable_http_debug_logging()

def increment_api_counter(key_name):
    """Safely increment API call counter"""
    import traceback
    import sys
    global _api_call_count, _api_call_log_file
    if _api_call_lock:
        with _api_call_lock:
            _api_call_count += 1
            caller = traceback.extract_stack()[-2]
            msg = f"[API #{_api_call_count}] {key_name} | {caller.name}() @ line {caller.lineno}"
            print(f"      {msg}", flush=True)
            # Log to file
            if _api_call_log_file:
                with open(_api_call_log_file, 'a') as f:
                    f.write(f"{msg}\n")
            return _api_call_count
    else:
        _api_call_count += 1
        caller = traceback.extract_stack()[-2]
        msg = f"[API #{_api_call_count}] {key_name} | {caller.name}() @ line {caller.lineno}"
        print(f"      {msg}", flush=True)
        # Log to file
        if _api_call_log_file:
            with open(_api_call_log_file, 'a') as f:
                f.write(f"{msg}\n")
        return _api_call_count

def log_extraction_error(job_id, error_reason, api_key=None):
    """Log failed extraction to error file"""
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    error_file = log_dir / "extraction_errors.jsonl"
    
    error_entry = {
        "job_id": str(job_id),
        "error": error_reason,
        "api_key": api_key,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(error_file, 'a') as f:
        f.write(json.dumps(error_entry, ensure_ascii=False) + "\n")

def get_api_call_count():
    """Get current API call counter (thread-safe)"""
    global _api_call_count
    if _api_call_lock:
        with _api_call_lock:
            return _api_call_count
    else:
        return _api_call_count

def reset_api_call_count():
    """Reset API call counter (for testing)"""
    global _api_call_count
    if _api_call_lock:
        with _api_call_lock:
            _api_call_count = 0
    else:
        _api_call_count = 0

def load_all_api_keys():
    """Load all API keys from the environment in numeric order.

    Returns tuple: (list of keys, list of key numbers)
    E.g. if GEMINI_API_KEY_23 and GEMINI_API_KEY_31 exist, returns
    ([key23_value, key31_value], [23, 31]).
    """
    test_key = os.getenv('TEST_SINGLE_KEY')
    if test_key:
        key = os.getenv(f'GEMINI_API_KEY_{test_key}')
        if key:
            return [key], [int(test_key)]

    key_entries = []
    for env_name, env_value in os.environ.items():
        match = re.fullmatch(r'GEMINI_API_KEY_(\d+)', env_name)
        if not match or not env_value:
            continue
        key_entries.append((int(match.group(1)), env_value))

    key_entries.sort(key=lambda item: item[0])

    if key_entries:
        key_numbers = [item[0] for item in key_entries]
        keys = [item[1] for item in key_entries]
        return keys, key_numbers

    fallback = os.getenv('GEMINI_API_KEY')
    return [fallback] if fallback else [], [0]

def get_api_key_by_index(key_index: int):
    """Get specific API key by index (0-based). Used for fixed key-to-thread mapping."""
    keys, _ = load_all_api_keys()
    if key_index < len(keys):
        return keys[key_index]
    return None

def get_key_name_by_index(key_index: int):
    """Get KEY_N name for a given index (e.g., index 0 → 'GEMINI_API_KEY_1')"""
    _, key_numbers = load_all_api_keys()
    if key_index < len(key_numbers):
        return f"GEMINI_API_KEY_{key_numbers[key_index]}"
    return "UNKNOWN_KEY"

def load_extraction_prompt():
    """Load extraction prompt from clean_config.yaml"""
    try:
        config_path = Path(__file__).parent / "clean_config.yaml"
        prompt = load_job_extraction_prompt(config_path)
        print(f"[CONFIG] Loaded extraction prompt from clean_config.yaml ({len(prompt)} chars)")
        return prompt
    except Exception as e:
        print(f"[CONFIG] Failed to load prompt from config: {e}")

    print("[FALLBACK] Using empty prompt - ensure requirements_text is provided!")
    return ""


class SkillExtractor:
    """Extract skills using a fixed or auto-rotating API key.
    
    - fixed_key_idx: If set, ONLY use this key (no auto-rotate). Thread 1→Key index 0, Thread 2→Key index 1, etc.
    - If None: Auto-rotate through all keys when quota exhausted
    
    CLASS-LEVEL CACHE: Models are cached per API key to reuse across instances
    """
    
    SKILL_EXTRACTION_PROMPT = load_extraction_prompt()
    _model_cache = {}  # Cache: {api_key: GenerativeModel instance}
    _global_exhausted_keys = set()
    _global_exhausted_lock = threading.Lock()
    
    def __init__(self, fixed_key_idx=None):
        trace_log(f"[INIT] NEW SkillExtractor(fixed_key_idx={fixed_key_idx}) CREATED")
        
        self.api_keys, self.key_numbers = load_all_api_keys()
        if not self.api_keys:
            raise ValueError("No API keys found in .env")
        
        # Fixed key mapping: Thread assigns specific key index (0-based)
        if fixed_key_idx is not None:
            # FIXED MODE: This thread uses ONLY key at this index
            if fixed_key_idx >= len(self.api_keys):
                # Fallback if more threads than keys
                self.current_key_idx = fixed_key_idx % len(self.api_keys)
            else:
                self.current_key_idx = fixed_key_idx
            self.use_fixed_key = True
        else:
            # AUTO MODE: Auto-rotate (backward compat)
            try:
                key_num = int(os.getenv('CURRENT_API_KEY_NUM', '5'))  # Default to KEY_5
                self.current_key_idx = (key_num - 1) % len(self.api_keys)
            except:
                self.current_key_idx = 4  # Default to KEY_5 (index 4)
            self.use_fixed_key = False
        
        # MUST initialize exhausted_keys BEFORE calling _switch_to_key
        self.exhausted_keys = set()  # Track which keys have returned 429
        
        trace_log(f"[INIT] About to call _switch_to_key({self.current_key_idx})")
        self._switch_to_key(self.current_key_idx)
        trace_log(f"[INIT] _switch_to_key done, extractors ready")
        
        self.extraction_cache = {}
        
        # Show which key this extractor is using
        key_name = get_key_name_by_index(self.current_key_idx)
        key_preview = self.api_keys[self.current_key_idx][:10] + "..." if self.api_keys[self.current_key_idx] else "UNKNOWN"
        print(f"      🔑 [THREAD] Using {key_name} ({key_preview})")
        
        # RPM: read from config, default 4 requests/minute
        self.rpm_limit = int(os.getenv('GEMINI_RPM', '4'))
        self.request_times = []  # Track timestamp of requests in last 60s
        self.request_lock = threading.Lock()
        self.thread_label = threading.current_thread().name

    @classmethod
    def _mark_key_globally_exhausted(cls, key_idx):
        with cls._global_exhausted_lock:
            cls._global_exhausted_keys.add(key_idx)

    @classmethod
    def _get_global_exhausted_keys(cls):
        with cls._global_exhausted_lock:
            return set(cls._global_exhausted_keys)

    def _find_next_available_key(self, start_idx):
        """Find next key that is not exhausted locally or globally."""
        exhausted_keys = self._get_global_exhausted_keys().union(self.exhausted_keys)
        total_keys = len(self.api_keys)

        for offset in range(total_keys):
            key_idx = (start_idx + offset) % total_keys
            if key_idx not in exhausted_keys:
                return key_idx

        return None
    
    def _switch_to_key(self, key_idx):
        """Switch to specific API key (cached to avoid repeated genai calls)."""
        self.current_key_idx = key_idx
        key_name = get_key_name_by_index(key_idx)
        api_key = self.api_keys[key_idx]
        
        # Check cache first
        if api_key in SkillExtractor._model_cache:
            trace_log(f"[SWITCH] _switch_to_key({key_idx}) - CACHE HIT for {key_name}")
            self.model = SkillExtractor._model_cache[api_key]
            return
        
        # Not in cache - init new model (only once per key)
        trace_log(f"[SWITCH] _switch_to_key({key_idx}) - CACHE MISS, calling genai.configure")
        genai.configure(api_key=api_key)
        trace_log(f"[SWITCH] genai.configure() completed for {key_name}")
        
        trace_log(f"[SWITCH] About to create GenerativeModel for {key_name}")
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        trace_log(f"[SWITCH] GenerativeModel() created successfully for {key_name}")
        
        # Cache for future use
        SkillExtractor._model_cache[api_key] = self.model
        trace_log(f"[SWITCH] Model cached for {key_name}")
    
    def extract_skills(self, requirements_text, job_id=None):
        """Extract skills (single attempt, no retry).
        
        Args:
            requirements_text: Job description text
            job_id: Job ID for error logging (optional)
            
        Returns:
            {
                'is_it_job': bool,
                'extracted_skills': list,
                'error': str (if failed),
                'message': str (if failed)
            }
        """
        last_error = None

        while True:
            try:
                result = self._extract_skills_attempt(requirements_text)

                # Success - return result
                if result.get('extracted_skills'):
                    return result

                # Empty but no exception
                return {
                    'is_it_job': False,
                    'extracted_skills': [],
                    'error': 'NO_SKILLS',
                    'message': 'API returned empty skills list'
                }

            except QuotaExhaustedError as e:
                last_error = e
                exhausted_key_name = get_key_name_by_index(self.current_key_idx)
                print(f"      ⚠️  [ROTATE] {exhausted_key_name} exhausted, looking for another key...")

                self.exhausted_keys.add(self.current_key_idx)
                self._mark_key_globally_exhausted(self.current_key_idx)

                next_key_idx = self._find_next_available_key(self.current_key_idx + 1)
                if next_key_idx is None:
                    print(f"      ❌ [ROTATE] No API keys left for this run")
                    break

                next_key_name = get_key_name_by_index(next_key_idx)
                print(f"      [ROTATE] Switching from {exhausted_key_name} → {next_key_name} and retrying job once")
                self._switch_to_key(next_key_idx)
                continue

            except Exception as e:
                last_error = e
                print(f"      ❌ [ERROR] {str(e)[:150]}")
                break

        if job_id and last_error:
            log_extraction_error(job_id, str(last_error))

        # Return error in response
        return {
            'is_it_job': False,
            'extracted_skills': [],
            'error': type(last_error).__name__ if last_error else 'UNKNOWN_ERROR',
            'message': str(last_error) if last_error else 'Unknown extraction error'
        }
    
    def _extract_skills_attempt(self, requirements_text, retry_depth=0):
        """Internal extraction logic (single attempt). Called by extract_skills()."""
        # Limit retries to prevent infinite recursion
        if retry_depth > 0:
            # NO RETRIES - fail fast after first error
            print(f"      ❌ [NO_RETRY] API failed on first try, not retrying (retry_depth={retry_depth})")
            return {'is_it_job': False, 'extracted_skills': []}
        
        if not requirements_text or len(requirements_text.strip()) < 10:
            print(f"      ⚠️  [INPUT] Text too short ({len(requirements_text) if requirements_text else 0} chars), returning empty")
            return {'is_it_job': False, 'extracted_skills': []}
        
        print(f"      [INPUT] Text length: {len(requirements_text)} chars")
        
        # Check cache
        text_hash = hash(requirements_text)
        if text_hash in self.extraction_cache:
            print(f"      [CACHE] HIT - Using cached result")
            return self.extraction_cache[text_hash]
        
        print(f"      [CACHE] MISS - Will call API")
        
        current_time = time.time()
        with self.request_lock:
            self.request_times = [t for t in self.request_times if current_time - t < 60]
            key_name = get_key_name_by_index(self.current_key_idx)
            active_count = len(self.request_times)
            print(
                f"      [RPM][{self.thread_label}] key={key_name} "
                f"window={active_count}/{self.rpm_limit} times={format_request_times(self.request_times)}"
            )

            if active_count >= self.rpm_limit:
                oldest_age = current_time - self.request_times[0]
                sleep_time = max(0.0, 60 - oldest_age + 0.1)
                print(f"      [RPM][{self.thread_label}] key={key_name} limit reached; waiting {sleep_time:.1f}s")
                time.sleep(sleep_time)
                current_time = time.time()
                self.request_times = [t for t in self.request_times if current_time - t < 60]
                print(
                    f"      [RPM][{self.thread_label}] key={key_name} after wait "
                    f"window={len(self.request_times)}/{self.rpm_limit} "
                    f"times={format_request_times(self.request_times)}"
                )

            self.request_times.append(current_time)
            print(
                f"      [RPM][{self.thread_label}] key={key_name} reserved slot -> "
                f"{format_request_times(self.request_times)}"
            )
        
        try:
            # Build prompt with actual job requirements data
            prompt = self.SKILL_EXTRACTION_PROMPT.format(requirements_text=requirements_text)
            
            if not prompt or len(prompt.strip()) == 0:
                print(f"      [ERROR] Prompt is empty after formatting!")
                print(f"      [DEBUG] SKILL_EXTRACTION_PROMPT length: {len(self.SKILL_EXTRACTION_PROMPT)}")
                print(f"      [DEBUG] requirements_text length: {len(requirements_text)}")
                return {'is_it_job': False, 'extracted_skills': []}
            
            print(f"      [PROMPT] Built prompt: {len(prompt)} chars")
            key_name = get_key_name_by_index(self.current_key_idx)
            
            # Increment and show global API call counter
            call_num = increment_api_counter(key_name)
            print(f"      [API #{call_num}] Calling Gemini API using {key_name}...")
            
            # ESTIMATE TOKEN USAGE (without actual API call)
            # Approximate: 1 token ≈ 4 characters
            prompt_tokens = len(prompt) // 4
            max_output_tokens = 8000
            estimated_total_tokens = prompt_tokens + max_output_tokens
            
            print(f"      [TOKEN ESTIMATE]")
            print(f"        Prompt: ~{prompt_tokens} tokens ({len(prompt)} chars)")
            print(f"        Max output: {max_output_tokens} tokens")
            print(f"        Total estimate: ~{estimated_total_tokens} tokens")
            print(f"      📝 Calling REAL API...")
            trace_log(f"[EXTRACT] ABOUT TO CALL generate_content() with prompt {len(prompt)} chars")
            
            # REAL API CALL (enabled for production testing)
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    **build_job_extraction_generation_config_kwargs()
                ),
                request_options=build_request_options()
            )
            trace_log(f"[EXTRACT] generate_content() returned with {len(response.text)} chars")
            
            response_text = response.text.strip()
            print(f"      [API] Real response received: {len(response_text)} chars")

            try:
                result = normalize_job_extraction_output(response_text, job_text=requirements_text)
                extracted_skills = result.get('extracted_skills', [])
                has_eng_translation = any('skill_name_eng' in s for s in extracted_skills if isinstance(s, dict))
                translation_status = "✓ with translations" if has_eng_translation else "⚠️ no translations"

                print(f"      [JSON] ✓ Parsed successfully. Skills: {len(extracted_skills)} {translation_status}")
                key_name = get_key_name_by_index(self.current_key_idx)
                print(f"      ✅ [SUCCESS] {key_name} is WORKING - returned valid skills")
                self.extraction_cache[text_hash] = result
                return result
            except Exception as exc:
                error_msg = f"JSON parse/normalize error: {str(exc)[:100]}"
                print(f"      [JSON] ❌ {error_msg}")
                with self.request_lock:
                    if current_time in self.request_times:
                        self.request_times.remove(current_time)
                raise Exception(error_msg)
        
        except Exception as e:
            error_str = str(e).lower()
            print(f"      [ERROR] Exception type: {type(e).__name__}")
            print(f"      [ERROR] Message: {str(e)[:150]}")
            
            # Auto-rotate on quota error (429 = daily quota exhausted)
            if '429' in error_str or 'quota' in error_str:
                key_name = get_key_name_by_index(self.current_key_idx)
                print(f"      ⚠️  [QUOTA/429] {key_name} daily limit exceeded (RPD=20)")
                self.exhausted_keys.add(self.current_key_idx)
                self._mark_key_globally_exhausted(self.current_key_idx)
                exhausted_names = [get_key_name_by_index(k) for k in sorted(self.exhausted_keys)]
                print(f"      [EXHAUSTED] {len(self.exhausted_keys)}/{len(self.api_keys)} keys exhausted: {exhausted_names}")
                
                # Raise a quota-specific error so the caller can rotate to the next key.
                # Remove timestamp since API failed
                with self.request_lock:
                    if current_time in self.request_times:
                        self.request_times.remove(current_time)
                raise QuotaExhaustedError(f"Quota exhausted on {key_name}")
            
            print(f"      ❌ [FAIL] API call failed: {str(e)[:100]}")
            # Remove timestamp since API failed
            with self.request_lock:
                if current_time in self.request_times:
                    self.request_times.remove(current_time)
            raise


    def clean_html_with_llm(self, dirty_text, max_retries=2):
        """Clean HTML/noise from text using LLM (optional STEP 1B)."""
        trace_log(f"[STEP1B] !!! ENTERED clean_html_with_llm() !!!")
        
        if not dirty_text or len(dirty_text) < 10:
            return None
        
        # Rate-limit: Check RPM
        now = time.time()
        rpm_limit = int(os.getenv('GEMINI_RPM', '4'))

        with self.request_lock:
            self.request_times = [t for t in self.request_times if now - t < 60]
            print(
                f"      [RPM][{self.thread_label}] STEP1B key={get_key_name_by_index(self.current_key_idx)} "
                f"window={len(self.request_times)}/{rpm_limit} times={format_request_times(self.request_times)}"
            )

            if len(self.request_times) >= rpm_limit:
                sleep_time = 60 - (now - self.request_times[0]) + 0.1
                if sleep_time > 0:
                    print(f"      ⏳ [RPM][{self.thread_label}] STEP1B sleeping {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                    now = time.time()
                    self.request_times = [t for t in self.request_times if now - t < 60]

            self.request_times.append(now)
            print(
                f"      [RPM][{self.thread_label}] STEP1B reserved slot -> {format_request_times(self.request_times)}"
            )
        
        try:
            # Configure API
            trace_log(f"[STEP1B] About to call genai.configure()")
            genai.configure(api_key=self.api_keys[self.current_key_idx])
            trace_log(f"[STEP1B] genai.configure() done")
            
            trace_log(f"[STEP1B] About to create GenerativeModel")
            model = genai.GenerativeModel(os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'))
            trace_log(f"[STEP1B] GenerativeModel created")
            
            prompt = f"""Clean the following text. Remove HTML tags, CSS, JavaScript, and noise.
Keep only the main content (job description, requirements, etc).

Text (max 3000 chars):
{dirty_text[:3000]}

Output only the cleaned text, nothing else."""
            
            trace_log(f"[STEP1B] ABOUT TO CALL generate_content() with prompt {len(prompt)} chars")
            response = model.generate_content(prompt, safety_settings=[], request_options=build_request_options())
            trace_log(f"[STEP1B] generate_content() returned with {len(response.text)} chars")
            
            # Track API call count (STEP 1B: LLM clean)
            api_call_num = increment_api_counter(f"KEY_{self.current_key_idx}")
            trace_log(f"[STEP1B] API CALL INCREMENTED to #{api_call_num}")
            
            cleaned = response.text.strip() if response.text else None
            if cleaned and len(cleaned) > 5:
                return cleaned
            
            return None
            
        except Exception as e:
            error_str = str(e).lower()
            trace_log(f"[STEP1B] Exception caught: {type(e).__name__}: {str(e)[:100]}")
            
            # Auto-rotate on quota error
            if '429' in error_str or 'quota' in error_str:
                self.exhausted_keys.add(self.current_key_idx)
                if len(self.exhausted_keys) < len(self.api_keys):
                    next_idx = (self.current_key_idx + 1) % len(self.api_keys)
                    attempts = 0
                    while next_idx in self.exhausted_keys and attempts < len(self.api_keys):
                        next_idx = (next_idx + 1) % len(self.api_keys)
                        attempts += 1
                    self._switch_to_key(next_idx)
                    self.request_times = []
                    
                    if max_retries > 0:
                        print(f"      🔄 [ROTATE] Retrying clean_html with new key...")
                        return self.clean_html_with_llm(dirty_text, max_retries - 1)
            
            with self.request_lock:
                if now in self.request_times:
                    self.request_times.remove(now)
            return None

# Test
if __name__ == '__main__':
    print("[TEST] Skill extraction\n")
    extractor = SkillExtractor()
    
    test_text = "Cần lập trình viên Python với kinh nghiệm Django, Redis, PostgreSQL"
    result = extractor.extract_skills(test_text)
    print(f"Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
