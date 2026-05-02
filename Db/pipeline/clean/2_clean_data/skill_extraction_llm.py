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
import hashlib
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from gemini_request_options import build_request_options
from Db.llm.job_extraction_rules import (
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

# Prompt cache version: bump this when prompt/static instructions change
STEP2_PROMPT_CACHE_VERSION = "step2_extract_v1"

# Local mapping of cache_key -> provider_cached_id
PROMPT_CACHE_FILE = Path(__file__).parent / "cache" / "prompt_cache.json"
PROMPT_CACHE_FILE.parent.mkdir(exist_ok=True)

def _load_local_prompt_cache():
    try:
        if PROMPT_CACHE_FILE.exists():
            with open(PROMPT_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}

def _save_local_prompt_cache(d: dict):
    try:
        with open(PROMPT_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _compute_prompt_cache_key(model_name: str, static_prompt: str) -> str:
    payload = f"{model_name}:{STEP2_PROMPT_CACHE_VERSION}:{static_prompt}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

def _ensure_provider_cached_prompt(static_prompt: str, model_name: str):
    """Best-effort: create or reuse provider-side cached prompt content.

    Returns provider_cached_id or None. Does not raise on failure.
    """
    try:
        cache_key = _compute_prompt_cache_key(model_name, static_prompt)
        local = _load_local_prompt_cache()
        if cache_key in local:
            print(f"      [PROMPT CACHE] Local cache hit for key={cache_key[:8]}...", flush=True)
            return local.get(cache_key)

        # Attempt provider-specific cached content creation (Gemini SDK best-effort)
        provider_id = None
        # Try common SDK surface names in a safe try/except block
        try:
            # Preferred modern interface: genai.CachedContent.create(...)
            if hasattr(genai, 'CachedContent') and hasattr(genai.CachedContent, 'create'):
                resp = genai.CachedContent.create(model=model_name, content=static_prompt)
                # resp may contain a `name` or `id` property
                provider_id = getattr(resp, 'name', None) or getattr(resp, 'id', None)
        except Exception:
            provider_id = None

        try:
            # Alternate: genai.create_cached_content
            if provider_id is None and hasattr(genai, 'create_cached_content'):
                resp = genai.create_cached_content(model=model_name, content=static_prompt)
                provider_id = getattr(resp, 'name', None) or getattr(resp, 'id', None)
        except Exception:
            provider_id = None

        # If provider_id found, persist local map
        if provider_id:
            local[cache_key] = provider_id
            _save_local_prompt_cache(local)
            print(f"      [PROMPT CACHE] Created provider cached prompt id={str(provider_id)[:12]} for key={cache_key[:8]}...", flush=True)
            return provider_id

        # No provider caching available — save a placeholder to avoid repeated attempts
        local[cache_key] = None
        _save_local_prompt_cache(local)
        print("      [PROMPT CACHE] Provider caching not available; falling back to inline prompt", flush=True)
        return None
    except Exception as e:
        print(f"      [PROMPT CACHE] Failed to ensure cached prompt: {e}", flush=True)
        return None

def increment_api_counter(key_name):
    """Safely increment API call counter"""
    import traceback
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
        
        def _extract_requirements_section(text: str):
            """Extract the requirements section from cleaned job text.

            Returns the sliced section string or None if not found.
            Matches common Vietnamese and English headings and stops at known end headings.
            """
            if not text:
                return None
            txt = text
            # Normalize newlines
            txt_norm = txt.replace('\r', '\n')

            # Start headings (Vietnamese & English)
            starts = [
                r'(^|\n)\s*yêu\s*cầu[^\n]*',
                r'(^|\n)\s*yêu\s*cầu\s*ứng\s*viên[^\n]*',
                r'(^|\n)\s*kỹ\s*năng\s*bắt\s*bư?ộc[^\n]*',
                r'(^|\n)\s*kỹ\s*năng\s*ưu\s*tiên[^\n]*',
                r'(^|\n)\s*requirements[^\n]*',
                r'(^|\n)\s*qualifications[^\n]*',
            ]

            # Stop headings
            stops = [
                r'(^|\n)\s*phúc\s*lợi[^\n]*',
                r'(^|\n)\s*mô\s*tả[^\n]*',
                r'(^|\n)\s*thông\s*tin\s*công\s*ty[^\n]*',
                r'(^|\n)\s*benefits[^\n]*',
                r'(^|\n)\s*description[^\n]*',
            ]

            # Find earliest start match
            start_pos = None
            for pat in starts:
                m = re.search(pat, txt_norm, flags=re.IGNORECASE)
                if m:
                    pos = m.start()
                    if start_pos is None or pos < start_pos:
                        start_pos = pos

            if start_pos is None:
                return None

            # From start_pos, find nearest stop header after it
            tail = txt_norm[start_pos:]
            stop_pos = None
            for pat in stops:
                m = re.search(pat, tail, flags=re.IGNORECASE)
                if m:
                    pos = m.start()
                    if stop_pos is None or pos < stop_pos:
                        stop_pos = pos

            if stop_pos is not None:
                section = tail[:stop_pos]
            else:
                section = tail

            # Trim stray heading lines and return
            section = section.strip()
            # Heuristic: if section is too short, treat as not found
            if len(re.sub(r'\s+', '', section)) < 30:
                return None
            return section

        try:
            # Build prompt with actual job requirements data
            # Extract only the requirements section for the prompt
            req_section = _extract_requirements_section(requirements_text)
            if req_section is None:
                print(f"      ⚠️  [SECTION] Requirements section not found; aborting extraction")
                return {'is_it_job': False, 'extracted_skills': [], 'error': 'NO_REQUIREMENTS_SECTION', 'message': 'requirements section not found', 'raw_requirements_text': None}

            prompt = self.SKILL_EXTRACTION_PROMPT.format(requirements_text=req_section)
            
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
            # Best-effort: ensure provider-side cached prompt exists (may be no-op)
            try:
                model_name = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
                provider_cached_id = _ensure_provider_cached_prompt(self.SKILL_EXTRACTION_PROMPT, model_name)
                # Log cache key/version
                cache_key = _compute_prompt_cache_key(model_name, self.SKILL_EXTRACTION_PROMPT)
                print(f"      [PROMPT CACHE] cache_key={cache_key[:12]} version={STEP2_PROMPT_CACHE_VERSION}", flush=True)
            except Exception:
                provider_cached_id = None

            # Build request options and attach cached content id if provider supports it
            request_opts = build_request_options() or {}
            # Ensure SDK-level retries are disabled and RPC timeout set
            try:
                if isinstance(request_opts, dict):
                    request_opts.setdefault('retry', None)
                    # Use env-configured RPC timeout
                    from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS
                    request_opts.setdefault('timeout', int(LLM_CALL_TIMEOUT_SECONDS))
                else:
                    try:
                        setattr(request_opts, 'retry', None)
                        from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS
                        setattr(request_opts, 'timeout', int(LLM_CALL_TIMEOUT_SECONDS))
                    except Exception:
                        pass
            except Exception:
                # defensive: if build_request_options misbehaves, ignore
                request_opts = request_opts or {}
            try:
                if provider_cached_id:
                    if isinstance(request_opts, dict):
                        request_opts['cached_content_id'] = provider_cached_id
                    else:
                        try:
                            setattr(request_opts, 'cached_content_id', provider_cached_id)
                        except Exception:
                            pass
            except Exception:
                pass

            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    **build_job_extraction_generation_config_kwargs()
                ),
                request_options=request_opts
            )
            trace_log(f"[EXTRACT] generate_content() returned with {len(response.text)} chars")
            
            response_text = response.text.strip()
            print(f"      [API] Real response received: {len(response_text)} chars")

            try:
                result = normalize_job_extraction_output(response_text, job_text=req_section)
                extracted_skills = result.get('extracted_skills', [])

                # Post-process extracted_skills: mark `is_direct_skill` only when the
                # skill appears explicitly in the provided job text (requirements_text).
                # Soft/inferred/contextual skills (e.g., English) should be marked
                # `is_direct_skill=false` with reduced confidence (50-80).
                try:
                    job_text = (requirements_text or "").lower()
                    # small set of soft-skill indicators to always mark as non-direct
                    soft_skill_terms = {
                        'english', 'communication', 'teamwork', 'leadership', 'english proficiency',
                        'giao tiếp', 'tiếng anh', 'kỹ năng giao tiếp', 'soft skill', 'interpersonal'
                    }

                    def _skill_name_of(item):
                        if isinstance(item, dict):
                            return (item.get('skill_name_eng') or item.get('skill_name') or '').strip()
                        if isinstance(item, str):
                            return item.strip()
                        return ''

                    def _found_in_text(skill_name):
                        if not skill_name:
                            return False
                        # word-boundary search, lowercased
                        try:
                            pat = r'\\b' + re.escape(skill_name.lower()) + r'\\b'
                            return re.search(pat, job_text, flags=re.IGNORECASE) is not None
                        except Exception:
                            return skill_name.lower() in job_text

                    # Iterate and adjust
                    for idx, item in enumerate(extracted_skills):
                        name = _skill_name_of(item)
                        name_l = name.lower()
                        found = _found_in_text(name)

                        # Determine existing confidence if any
                        orig_conf = None
                        if isinstance(item, dict):
                            try:
                                orig_conf = int(item.get('confidence'))
                            except Exception:
                                orig_conf = None

                        # Soft-skill override
                        if any(term in name_l for term in soft_skill_terms):
                            is_direct = False
                            new_conf = orig_conf if orig_conf is not None else 60
                            # clamp into 50-80
                            new_conf = max(50, min(80, int(new_conf)))
                        else:
                            if found:
                                is_direct = True
                                new_conf = orig_conf if orig_conf is not None else 100
                                new_conf = max(60, min(100, int(new_conf)))
                            else:
                                # inferred/not present in text: mark non-direct and reduce confidence
                                is_direct = False
                                base = orig_conf if orig_conf is not None else 60
                                # scale down towards the 50-80 range
                                new_conf = max(50, min(80, int(base)))

                        # Apply changes back into item (dict or replace with dict)
                        new_item = None
                        if isinstance(item, dict):
                            item['is_direct_skill'] = bool(is_direct)
                            item['confidence'] = int(new_conf)
                            new_item = item
                        else:
                            new_item = {
                                'skill_name': name,
                                'is_direct_skill': bool(is_direct),
                                'confidence': int(new_conf),
                            }
                        extracted_skills[idx] = new_item

                    # Put back into result
                    result['extracted_skills'] = extracted_skills
                except Exception as e:
                    print(f"      [POST-PROCESS] Skill post-processing failed: {e}")
                # Adjust experience_level confidence: if the level is mapped/inferred
                # (e.g., from "> 2 years") and not explicitly stated ("Senior", "Lead" etc.)
                # reduce very-high confidences (>=90) to a safer inferred value (~75).
                try:
                    job_section = result.get('job', {}) or {}
                    exp_obj = job_section.get('experience_level') or {}
                    if exp_obj and isinstance(exp_obj, dict):
                        exp_val = (exp_obj.get('value') or '').lower()
                        try:
                            exp_conf = int(exp_obj.get('confidence') or 0)
                        except Exception:
                            exp_conf = 0

                        # quick map of explicit keywords to check in job_text
                        explicit_map = {
                            'internship': ['intern', 'thực tập'],
                            'entry_level': ['entry', 'fresher', 'mới tốt nghiệp', 'sinh viên tốt nghiệp'],
                            'mid_senior': ['mid', 'mid-level', 'mid level', 'experienced', 'experienced level'],
                            'director': ['director'],
                            'executive': ['executive'],
                            'unknown': []
                        }

                        def _exp_explicit_in_text(val_token, text):
                            kws = explicit_map.get(val_token, [])
                            for kw in kws:
                                if kw and kw in text:
                                    return True
                            # also check token words like 'senior', 'lead', 'junior'
                            if val_token == 'mid_senior':
                                return bool(re.search(r'\\b(mid|mid-level|junior|senior|lead|sr|jr)\\b', job_text, flags=re.IGNORECASE))
                            if val_token == 'entry_level':
                                return bool(re.search(r'\\b(entry|fresher|junior|jr)\\b', job_text, flags=re.IGNORECASE))
                            if val_token == 'internship':
                                return bool(re.search(r'\\b(intern|thực tập)\\b', job_text, flags=re.IGNORECASE))
                            return False

                        if exp_val and exp_conf >= 90:
                            if not _exp_explicit_in_text(exp_val, job_text):
                                # inferred mapping — lower confidence into 70-85
                                new_conf = 75
                                result['job']['experience_level']['confidence'] = new_conf
                except Exception as e:
                    print(f"      [POST-PROCESS] Experience confidence adjust failed: {e}")
                has_eng_translation = any('skill_name_eng' in s for s in extracted_skills if isinstance(s, dict))
                translation_status = "✓ with translations" if has_eng_translation else "⚠️ no translations"
                # Ensure soft skills and all explicit competencies are included and rendered atomically in English
                try:
                    # Collect existing raw names (prefer skill_name then skill_name_eng)
                    raw_items = []
                    for item in extracted_skills:
                        if isinstance(item, dict):
                            name = (item.get('skill_name') or item.get('skill_name_eng') or '').strip()
                            raw_items.append({'orig': name, 'is_direct': bool(item.get('is_direct_skill', True)), 'conf': int(item.get('confidence', 100) or 100)})
                        elif isinstance(item, str):
                            raw_items.append({'orig': item.strip(), 'is_direct': True, 'conf': 100})

                    # Heuristic lines to scan for additional competencies (keep original wording)
                    lines = [ln.strip() for ln in re.split(r"\r?\n", requirements_text) if ln.strip()]
                    soft_indicators = [
                        'kỹ năng', 'kỹ năng mềm', 'giao tiếp', 'tiếng anh', 'team', 'làm việc nhóm',
                        'khả năng', 'tư duy', 'học hỏi', 'thích nghi', 'giải quyết', 'khách hàng', 'customer',
                        'phân bổ', 'ưu tiên', 'problem', 'lead', 'leadership'
                    ]

                    # Split lines into candidates by common separators to maximize recall
                    def split_candidates(text):
                        parts = re.split(r"[,;\/\\|\t]\s*", text)
                        out = []
                        for p in parts:
                            # further split on ' và ', ' and '
                            for sub in re.split(r"\b(?:và|and|&|\+)\b", p, flags=re.IGNORECASE):
                                s = sub.strip()
                                if s:
                                    out.append(s)
                        return out

                    for ln in lines:
                        candidate = re.sub(r'^[\-\*•\d\)\.\s]+', '', ln).strip()
                        if not candidate:
                            continue
                        # Always attempt to split comma/and style lists to capture atomic items
                        for cand in split_candidates(candidate):
                            # short phrases more likely to be skills; also include lines with soft indicators
                            low = cand.lower()
                            contains_indicator = any(ind in low for ind in soft_indicators)
                            word_count = len([w for w in re.split(r"\s+", cand) if w])
                            if contains_indicator or word_count <= 12:
                                raw_items.append({'orig': cand, 'is_direct': True, 'conf': 100})

                    # Lightweight mapping for common Vietnamese phrases → English (expanded)
                    BENEFITS_MAP = {
                        'đồng phục': 'Uniform',
                        'đồng phụcs': 'Uniform',
                        'đồng phục.': 'Uniform',
                        'đồng phục (uniforms)': 'Uniform',
                        'chế độ thưởng': 'Bonus',
                        'thưởng': 'Bonus',
                        'chăm sóc sức khỏe': 'Healthcare',
                        'chăm sóc sức khoẻ': 'Healthcare',
                        'bảo hiểm sức khỏe': 'Health insurance',
                        'bảo hiểm': 'Insurance',
                        'đào tạo': 'Training',
                        'công tác phí': 'Travel allowance',
                        'tiền công tác': 'Travel allowance',
                        'nghỉ phép năm': 'Annual leave',
                        'nghỉ phép': 'Annual leave',
                        'paid annual leave': 'Annual leave',
                        'paid leave': 'Annual leave',
                        'phụ cấp ăn trưa': 'Meal allowance',
                        'phụ cấp': 'Allowance',
                        'lương cạnh tranh': 'Competitive salary',
                        'làm việc từ xa': 'Remote work',
                        'remote': 'Remote work',
                        'làm việc linh hoạt': 'Flexible working',
                        'office': 'Office',
                        'bảo hiểm': 'Insurance',
                    }
                    Translator = None
                    try:
                        from skill_translator import SkillTranslator
                        Translator = SkillTranslator()
                    except Exception:
                        Translator = None

                    def looks_english(s: str) -> bool:
                        if not s:
                            return False
                        ascii_ratio = sum(1 for c in s if ord(c) < 128) / len(s)
                        if ascii_ratio > 0.85:
                            return True
                        if any(ch in s for ch in ('.', '+', '#', '/')):
                            return True
                        if len(s) <= 6 and s.isupper():
                            return True
                        return False

                    translated_list = []
                    for itm in raw_items:
                        orig = (itm.get('orig') or '').strip()
                        if not orig:
                            continue
                        low = orig.lower()
                        eng_names = None
                        # mapping exact match first
                        if low in TRANSLATION_MAP:
                            eng_names = TRANSLATION_MAP[low]
                        else:
                            # split multi-word Vietnamese phrases heuristically
                            if low in KNOWN_TOOLS or any(tool in low for tool in KNOWN_TOOLS):
                                eng_names = [orig]
                            elif looks_english(orig):
                                eng_names = [orig]
                            else:
                                if Translator:
                                    try:
                                        tr = Translator.translate_skill(orig)
                                        eng_names = [tr if tr else orig]
                                    except Exception:
                                        eng_names = [orig]
                                else:
                                    # fallback: keep original (non-canonical translation)
                                    eng_names = [orig]

                        # Atomic split: break compound English renderings into atomic concepts when applicable
                        for en in eng_names:
                            en = en.strip()
                            # If the mapped name contains multiple concepts separated by commas or slashes, split
                            pieces = re.split(r"[,;/\\|]\s*", en)
                            final_pieces = []
                            for p in pieces:
                                # split on ' and ' / ' & '
                                for sub in re.split(r"\b(?:and|&|\+)\b", p, flags=re.IGNORECASE):
                                    sub = sub.strip()
                                    if not sub:
                                        continue
                                    # If phrase like 'English communication', split into 'English' + 'Communication'
                                    words = sub.split()
                                    if len(words) == 2 and words[0].lower() in ('english', 'tiếng', 'anh'):
                                        final_pieces.append(words[0])
                                        final_pieces.append(words[1].capitalize())
                                    else:
                                        final_pieces.append(sub)

                            for fp in final_pieces:
                                translated_list.append({'skill_name': fp.strip(), 'confidence': int(itm.get('conf', 100)), 'is_direct_skill': bool(itm.get('is_direct', True))})

                    # Apply confidence rules and deduplicate by lowercase English skill_name
                    dedup = []
                    seen = set()
                    for item in translated_list:
                        name = (item.get('skill_name') or '').strip()
                        key = name.lower()
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        # enforce schema defaults
                        item.setdefault('confidence', 100)
                        item.setdefault('is_direct_skill', True)

                        orig_conf = int(item['confidence'] or 100)
                        direct = bool(item['is_direct_skill'])
                        # Confidence tuning per rules
                        if direct:
                            # explicit and clear -> 90-100
                            if orig_conf >= 90:
                                conf = max(90, min(orig_conf, 100))
                            else:
                                conf = 90
                        else:
                            # inferred: 70-85 if reasonably supported, else 50-70
                            if orig_conf >= 85:
                                conf = 80
                            elif orig_conf >= 70:
                                conf = 75
                            elif orig_conf >= 50:
                                conf = max(50, min(orig_conf, 70))
                            else:
                                conf = 50

                        item['confidence'] = conf
                        dedup.append(item)

                    result['extracted_skills'] = dedup
                    extracted_skills = dedup
                except Exception as e:
                    print(f"      [POST-PROCESS] Soft-skill inclusion/translation failed: {e}")

                # --- Additional normalization and recall for specific soft skills & wording ---
                try:
                    # Ensure atomic, standardized wording for specific English phrases
                    normalize_map = {
                        'ui responsive': 'Responsive UI',
                        'responsive ui': 'Responsive UI',
                        'customer-centric': 'Customer-centric mindset',
                        'customer centric': 'Customer-centric mindset',
                        'customer-centric mindset': 'Customer-centric mindset',
                        'english communication': 'English',
                        'communication': 'Communication'
                    }

                    # Add explicit soft skills if their Vietnamese tokens appear anywhere in the requirements_text
                    explicit_soft_map = {
                        'có khả năng ưu tiên và phân bổ công việc hợp lý': ['Task prioritization'],
                        'ưu tiên và phân bổ công việc': ['Task prioritization'],
                        'khả năng ưu tiên': ['Task prioritization'],
                        'khả năng thích nghi nhanh': ['Adaptability'],
                        'khả năng thích nghi nhanh với sự thay đổi': ['Adaptability'],
                        'thích nghi nhanh': ['Adaptability'],
                        'tinh thần học hỏi liên tục': ['Continuous learning'],
                        'tinh thần học tập và phát triển': ['Continuous learning'],
                        'học hỏi liên tục': ['Continuous learning'],
                        'phát triển bản thân': ['Continuous learning']
                    }

                    # Build a lookup of existing skill names to avoid duplicates
                    existing = { (s.get('skill_name') or '').strip().lower(): s for s in (result.get('extracted_skills') or []) }

                    # Normalize skill names in place
                    for s in result.get('extracted_skills', []):
                        name = (s.get('skill_name') or '').strip()
                        key = name.lower()
                        if key in normalize_map:
                            s['skill_name'] = normalize_map[key]
                            existing[normalize_map[key].lower()] = s

                    # Search requirements_text for explicit Vietnamese soft-skill tokens and add translations if missing
                    rt = (requirements_text or '').lower()
                    for token, eng_list in explicit_soft_map.items():
                        if token in rt:
                            for eng in eng_list:
                                ek = eng.lower()
                                if ek not in existing:
                                    new_item = {'skill_name': eng, 'confidence': 100, 'is_direct_skill': True}
                                    result.setdefault('extracted_skills', []).append(new_item)
                                    existing[ek] = new_item

                    # Re-deduplicate preserving order
                    final = []
                    seen = set()
                    for s in result.get('extracted_skills', []):
                        nm = (s.get('skill_name') or '').strip()
                        k = nm.lower()
                        if not k or k in seen:
                            continue
                        seen.add(k)
                        final.append(s)
                    result['extracted_skills'] = final
                except Exception as e:
                    print(f"      [POST-PROCESS] Skill normalization/recall failed: {e}")

                # --- Benefits translation: convert benefits to standardized English strings ---
                try:
                    raw_bens = result.get('benefits') or []
                    if isinstance(raw_bens, str):
                        raw_bens = [raw_bens]

                    # mapping Vietnamese/common phrases -> standardized English benefit terms
                    BENEFITS_MAP = {
                        'đồng phục': 'Uniform',
                        'chế độ thưởng': 'Bonus',
                        'thưởng': 'Bonus',
                        'chăm sóc sức khỏe': 'Healthcare',
                        'bảo hiểm sức khỏe': 'Health insurance',
                        'đào tạo': 'Training',
                        'công tác phí': 'Travel allowance',
                        'tiền công tác': 'Travel allowance',
                        'nghỉ phép năm': 'Annual leave',
                        'nghỉ phép': 'Annual leave',
                        'phụ cấp ăn trưa': 'Meal allowance',
                        'phụ cấp': 'Allowance',
                        'lương cạnh tranh': 'Competitive salary',
                        'làm việc từ xa': 'Remote work',
                        'remote': 'Remote work',
                        'làm việc linh hoạt': 'Flexible working',
                        'office': 'Office',
                        'bảo hiểm': 'Insurance',
                    }

                    # Ensure Translator available if present
                    Translator = None
                    try:
                        from skill_translator import SkillTranslator
                        Translator = SkillTranslator()
                    except Exception:
                        Translator = None

                    benefits_out = []
                    seen = set()
                    for b in raw_bens:
                        if not b:
                            continue
                        s = str(b).strip()
                        low = s.lower()
                        eng = None
                        # exact map
                        if low in BENEFITS_MAP:
                            eng = BENEFITS_MAP[low]
                        else:
                            # if already English-like, use as-is (short phrase)
                            def looks_english_b(sv: str) -> bool:
                                if not sv:
                                    return False
                                ascii_ratio = sum(1 for c in sv if ord(c) < 128) / len(sv)
                                return ascii_ratio > 0.8
                            if looks_english_b(s):
                                eng = s
                            else:
                                if Translator:
                                    try:
                                        tr = Translator.translate_benefit(s)
                                        eng = tr if tr else s
                                    except Exception:
                                        eng = s
                                else:
                                    eng = s

                        eng = eng.strip()
                        key = eng.lower()
                        if key and key not in seen:
                            benefits_out.append(eng)
                            seen.add(key)

                    result['benefits'] = benefits_out
                except Exception as e:
                    print(f"      [POST-PROCESS] Benefits translation failed: {e}")

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
            # Build request options and ensure no SDK retry + timeout
            _step1b_req_opts = build_request_options()
            try:
                if isinstance(_step1b_req_opts, dict):
                    _step1b_req_opts.setdefault('retry', None)
                    from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS
                    _step1b_req_opts.setdefault('timeout', int(LLM_CALL_TIMEOUT_SECONDS))
                else:
                    try:
                        setattr(_step1b_req_opts, 'retry', None)
                        from Db.llm.llm_config import LLM_CALL_TIMEOUT_SECONDS
                        setattr(_step1b_req_opts, 'timeout', int(LLM_CALL_TIMEOUT_SECONDS))
                    except Exception:
                        pass
            except Exception:
                _step1b_req_opts = _step1b_req_opts or {}
            response = model.generate_content(prompt, safety_settings=[], request_options=_step1b_req_opts)
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
