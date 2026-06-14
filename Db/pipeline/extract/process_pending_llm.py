from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import time
import hashlib
import traceback
from datetime import datetime, timedelta, date

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
# Ensure workspace parent is available so `import Db.*` can resolve when this
# script runs with different working directories. BASE_DIR.parents[2] points to
# the parent of the `Db` folder (workspace root), which contains the `Db` package.
try:
    workspace_parent = str(BASE_DIR.parents[2])
    if workspace_parent not in sys.path:
        sys.path.insert(0, workspace_parent)
except Exception:
    pass

from Db.llm.retry_queue import load_retry_queue, remove_retry_queue_entries, save_retry_queue

from dotenv import load_dotenv
import importlib.util
from Db.llm.llm_config import (
    LLM_MAX_RETRY_PER_JOB,
    LLM_BACKOFF_BASE_SECONDS,
    LLM_BACKOFF_MAX_SECONDS,
    LLM_MAX_WAIT_FOR_KEY_SECONDS,
)

from Db.llm.debug_llm_adapter import call_llm as call_gemini_llm

from Db.llm.job_extraction_rules import load_job_extraction_prompt
from Db.scripts.split_description import extract_clean_job_description



DEFAULT_INPUT_PATH = BASE_DIR / "data" / "queue" / "batch_1.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "queue"
DEFAULT_CONFIG_PATH = ROOT_DIR / "clean" / "2_clean_data" / "clean_config.yaml"
DEFAULT_FALLBACK_DIR = BASE_DIR / "data" / "queue"

# Top-level fields guaranteed by the crawler and must not be overwritten by LLM
GUARANTEED_TOPLEVEL = [
    "source_name",
    "job_url",
    "job_source_id",
    "description_html",
    "search_keyword",
]

# Very-high confidence threshold for overriding certain guaranteed empty fields (percent)
VERY_HIGH_CONF = 90


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("process_pending_llm")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger

def today_str() -> str:
    return date.today().isoformat()

def get_job_url(job: Dict[str, Any]) -> Optional[str]:
    for key in ['job_url', 'url', 'job_url_raw', 'job_source_id']:
        val = job.get(key)
        if val and isinstance(val, str):
            val_strip = val.strip()
            if val_strip:
                return val_strip
    return None

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process pending jobs through Gemini and write extracted output.")
    parser.add_argument(
        "--input-path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to the pending_llm JSON file.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=None,
        help="Path to the extracted JSON file. If omitted, it is derived from the input file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the extracted JSON file will be written.",
    )
    parser.add_argument(
        "--fallback-path",
        type=Path,
        default=None,
        help="Optional path where failed records will be written. Only created when failures exist.",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to clean_config.yaml that contains prompt_extraction.",
    )
    parser.add_argument(
        "--ignore-retry-queue",
        action="store_true",
        help="Ignore existing retry queue and process only the current pending file.",
    )
    parser.add_argument(
        "--no-inline-retry",
        action="store_true",
        help="Do not retry temporary LLM failures inside the same extract run.",
    )
    return parser.parse_args()


def load_jobs(input_path: Path) -> List[Dict[str, Any]]:
    if not input_path.is_absolute():
        input_path = BASE_DIR / input_path

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    raw_text = input_path.read_text(encoding="utf-8-sig").strip()
    if not raw_text:
        return []

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        jobs: List[Dict[str, Any]] = []
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                jobs.append(item)
        return jobs

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if isinstance(payload, dict):
        for key in ("jobs", "items", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]

    raise ValueError(f"Unsupported input format: {type(payload).__name__}")


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _load_api_keys(prefix: str = "GEMINI_API_KEY_") -> List[str]:
    key_entries: List[Tuple[int, str]] = []
    for env_name, env_value in os.environ.items():
        match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", env_name)
        if not match or not env_value:
            continue
        key_entries.append((int(match.group(1)), env_value))

    key_entries.sort(key=lambda item: item[0])
    return [value for _, value in key_entries]


def _build_prompt(job: Dict[str, Any], config_path: Path) -> str:
    prompt_template = load_job_extraction_prompt(config_path)
    requirements_text = _normalize_text(job.get("requirements_text"))
    # Use a safe single-placeholder replacement because templates may contain
    # JSON examples with braces that would break str.format().
    if requirements_text is None:
        requirements_text = ""
    return prompt_template.replace("{requirements_text}", requirements_text)


def _is_api_error(exc: Exception) -> bool:
    error_text = f"{type(exc).__name__}: {exc}".lower()
    api_markers = (
        "resourceexhausted",
        "quota",
        "429",
        "503",
        "service unavailable",
        "deadlineexceeded",
        "googleapierror",
        "api error",
        "connection",
        "timeout",
        "temporarily unavailable",
    )
    return any(marker in error_text for marker in api_markers)


def _is_parse_error(exc: Exception) -> bool:
    error_text = f"{type(exc).__name__}: {exc}".lower()
    parse_markers = (
        "jsondecodeerror",
        "parse",
        "structured response is not an object",
        "empty gemini response",
        "model output is not a json object",
        "normalize",
    )
    return any(marker in error_text for marker in parse_markers)


def call_llm(job: Dict[str, Any], api_key: str, config_path: Path) -> Dict[str, Any]:
    # Build a sanitized, truncated input for the LLM and log its length.
    logger = logging.getLogger("process_pending_llm")
    cleaned = build_llm_input_text(job)
    
    if not cleaned.strip():
        logger.warning(f"Cleaned job description is empty for job {job.get('job_url', 'unknown')}. Skipping Gemini API call to save tokens.")
        raise ValueError("Cleaned job description/requirements text is empty. Skipping LLM call.")
        
    try:
        logger.info("LLM input length: %d", len(cleaned))
    except Exception:
        pass

    # Create a shallow copy and set the `requirements_text` placeholder
    job_for_prompt = dict(job)
    job_for_prompt['requirements_text'] = cleaned
    prompt = _build_prompt(job_for_prompt, config_path)
    # Runtime verification before calling child adapter
    try:
        print("API KEY EXISTS:", bool(api_key))
        print("PROMPT EXISTS:", bool(prompt))
        logger.info("Calling LLM: api_key_present=%s prompt_present=%s", bool(api_key), bool(prompt))
    except Exception:
        logger.exception("Error while printing API/prompt existence")
    # pass per-request timeout from env to the adapter if supported
    try:
        timeout_seconds = int(os.getenv('LLM_REQUEST_TIMEOUT_SECONDS', os.getenv('LLM_REQUEST_TIMEOUT_SECONDS', '60')))
    except Exception:
        timeout_seconds = None
    try:
        return call_gemini_llm(prompt, api_key, timeout_seconds=timeout_seconds)
    except TypeError:
        # adapter doesn't support timeout arg; fallback
        return call_gemini_llm(prompt, api_key)


def build_llm_input_text(job: Dict[str, Any], max_chars: int = 8000) -> str:
    """Construct a small cleaned text blob from a job record for LLM input.

    - removes script/style/header/footer/nav blocks
    - strips HTML tags
    - normalizes whitespace
    - keeps only title, company, location, description, requirements, benefits
    - truncates to `max_chars` characters
    """
    parts: List[str] = []

    def _safe_get(*keys):
        for k in keys:
            v = job.get(k)
            if v:
                return v
        return None

    title = _safe_get('title')
    if title:
        parts.append(str(title).strip())

    company = _safe_get('company_name')
    if company:
        parts.append(str(company).strip())

    # Location candidates
    location = _safe_get('location_raw', 'location', 'company_address')
    if location:
        parts.append(str(location).strip())

    # Salary candidates
    salary = _safe_get('salary_raw', 'salary')
    if salary:
        parts.append(f"Salary: {str(salary).strip()}")

    # Description: remove noisy tags then strip HTML
    desc_html = _safe_get('description_html', 'description')
    if isinstance(desc_html, str) and desc_html.strip():
        import html
        txt = desc_html
        # remove script/style/header/footer/nav blocks
        txt = re.sub(r'<script[\s\S]*?</script>', ' ', txt, flags=re.I)
        txt = re.sub(r'<style[\s\S]*?</style>', ' ', txt, flags=re.I)
        txt = re.sub(r'<header[\s\S]*?</header>', ' ', txt, flags=re.I)
        txt = re.sub(r'<nav[\s\S]*?</nav>', ' ', txt, flags=re.I)
        txt = re.sub(r'<footer[\s\S]*?</footer>', ' ', txt, flags=re.I)
        
        # Unescape HTML entities (e.g. &lt; -> <, &gt; -> >) before regex tag stripping
        txt = html.unescape(txt)
        
        # Strip remaining tags using a refined regex that excludes template brackets and mathematical operators
        # Standard tag names start with a letter and have word characters or hyphens.
        tag_re = re.compile(r'</?[a-zA-Z][a-zA-Z0-9:-]*(\s+[^>]*)?>')
        txt = tag_re.sub(' ', txt)
        
        txt = re.sub(r'\s+', ' ', txt).strip()
        if txt:
            parts.append(txt)

    # Requirements / cleaned text
    req = _safe_get('requirements_text', 'requirements', 'requirements_raw')
    if isinstance(req, list):
        req = ' '.join(str(x) for x in req)
    if req:
        parts.append(str(req).strip())

    # Benefits
    ben = _safe_get('benefits', 'benefit_list', 'benefits_list')
    if isinstance(ben, list):
        ben_txt = ' '.join(str(x) for x in ben)
        if ben_txt.strip():
            parts.append(ben_txt.strip())
    elif isinstance(ben, str) and ben.strip():
        parts.append(ben.strip())

    # Join and normalize whitespace
    joined = "\n\n".join([re.sub(r"\s+", " ", p).strip() for p in parts if p])
    if not isinstance(joined, str):
        joined = str(joined)
    # Truncate to max_chars
    if len(joined) > max_chars:
        joined = joined[:max_chars]
    return joined


def _parse_iso_date(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return None
    s = str(value).strip()
    if not s:
        return None
    # Try fromisoformat (accepts YYYY-MM-DD and YYYY-MM-DDTHH:MM:SS and offsets)
    try:
        if s.endswith('Z'):
            s2 = s[:-1] + '+00:00'
        else:
            s2 = s
        dt = datetime_fromisoformat_safe(s2)
        if dt:
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
    except Exception:
        pass
    # Try common date-only parse
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except Exception:
            continue
    return None


def datetime_fromisoformat_safe(s: str) -> Optional["datetime"]:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _to_number_or_null(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Remove common separators and non-numeric characters except . and ,
    s_clean = re.sub(r"[^0-9.,-]", "", s)
    # Normalize comma as decimal when appropriate (but prefer dot)
    s_clean = s_clean.replace(',', '')
    try:
        return float(s_clean)
    except Exception:
        return None


def _to_int_or_null(value: Any) -> Optional[int]:
    num = _to_number_or_null(value)
    if num is None:
        return None
    try:
        return int(num)
    except Exception:
        return None


def _load_2cd_module(name: str):
    """Import a module from the `Db.2_clean_data` package path.

    Prefer normal import so relative imports inside the module work.
    """
    import importlib
    for pkg_name in (
        f"Db.pipeline.clean.2_clean_data.{name}",
        f"pipeline.clean.2_clean_data.{name}",
        f"Db.2_clean_data.{name}"
    ):
        try:
            return importlib.import_module(pkg_name)
        except Exception:
            continue

    # fallback: load by path
    module_path = ROOT_DIR / "clean" / "2_clean_data" / f"{name}.py"
    if not module_path.exists():
        # also try old location relative to BASE_DIR
        module_path = BASE_DIR / "2_clean_data" / f"{name}.py"
    if not module_path.exists():
        raise FileNotFoundError(f"Module file not found: {name}")

    spec = importlib.util.spec_from_file_location(name, str(module_path))
    mod = importlib.util.module_from_spec(spec)
    loader = spec.loader
    assert loader is not None
    loader.exec_module(mod)
    return mod



def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """Try to extract the first JSON object from a model output text.

    Steps:
    - Try direct json.loads(text)
    - Strip markdown fences and attempt again
    - Fallback: take substring from first '{' to last '}' and parse
    """
    if not isinstance(text, str):
        text = str(text)
    txt = text.strip()
    # direct parse
    try:
        return json.loads(txt)
    except Exception:
        pass

    # remove triple-backtick fences
    txt2 = re.sub(r"^```(?:json)?\s*", "", txt, flags=re.I)
    txt2 = re.sub(r"\s*```$", "", txt2, flags=re.I)
    try:
        return json.loads(txt2)
    except Exception:
        pass

    # fallback: take between first { and last }
    first = txt2.find("{")
    last = txt2.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = txt2[first : last + 1]
        try:
            return json.loads(candidate)
        except Exception as e:
            raise ValueError(f"Failed to parse JSON candidate: {e}")

    raise ValueError("No JSON object could be extracted from model output")


def parse_salary_locally(salary_raw: str) -> Optional[Dict[str, Any]]:
    """Try to parse the salary raw string locally using Regex rules.
    Bypasses Gemini API calls for standard formats.
    """
    s = str(salary_raw).strip().lower()
    if not s:
        return None
        
    # Determine currency
    currency = "unknown"
    if any(x in s for x in ("vnd", "đ", "₫", "triệu", "tr", "nghìn", "k", "dong", "đồng")):
        currency = "VND"
    elif any(x in s for x in ("usd", "$", "dollar")):
        currency = "USD"
        
    # Determine pay period
    pay_period = "monthly"  # default
    if any(x in s for x in ("năm", "year", "yearly", "annually")):
        pay_period = "yearly"
    elif any(x in s for x in ("giờ", "hour", "hourly")):
        pay_period = "hourly"
    elif any(x in s for x in ("ngày", "day", "daily")):
        pay_period = "daily"
    elif any(x in s for x in ("tuần", "week", "weekly")):
        pay_period = "weekly"
        
    # Clean separators for full digits (e.g. 15.000.000 -> 15000000, 1,500 -> 1500)
    s_clean = s
    if re.search(r'\d{1,3}(?:[.,]\d{3}){1,3}', s):
        s_clean = re.sub(r'(\d+)[.,](\d{3})(?![0-9])', r'\1\2', s_clean)
        s_clean = re.sub(r'(\d+)[.,](\d{3})(?![0-9])', r'\1\2', s_clean)  # double pass
        
    # Normalize remaining commas to dots (e.g. 4,5 -> 4.5)
    s_clean = s_clean.replace(',', '.')

    # Clean up common non-salary numbers to avoid false extraction (e.g. "13th-month", "5 YOE")
    s_clean = re.sub(r'\b13[- ]*(th)?[- ]*month\b', '', s_clean)
    s_clean = re.sub(r'\blương[- ]*tháng[- ]*13\b', '', s_clean)
    s_clean = re.sub(r'\btháng[- ]*13\b', '', s_clean)
    s_clean = re.sub(r'\b\d+\s*\+?\s*(yoe|year|năm|tháng)\s*(kinh nghiệm|exp|experience)?\b', '', s_clean)
    s_clean = re.sub(r'\b\d+\s*([-–—]|đến|tới|to)\s*\d+\s*(tuổi|t|age)\b', '', s_clean)
    s_clean = re.sub(r'\b(từ)?\s*\d+\s*(tuổi|t|age)\b', '', s_clean)
    s_clean = re.sub(r'\b(tuyển|số lượng|headcount|sl)\s*[:\s-]*\d+\b', '', s_clean)
    s_clean = re.sub(r'\b\d+\s*(nhân sự|người|dev|developer|vị trí|slot)\b', '', s_clean)
        
    # Find all numbers and their potential multipliers
    num_matches = list(re.finditer(r'(\d+(?:\.\d+)?)\s*(tr|triệu|k|nghìn|million|m|vnd|usd|\$|₫)?', s_clean))
    
    if num_matches:
        def get_val(num_str, suffix):
            val = float(num_str)
            if not suffix:
                if any(x in s_clean for x in ("triệu", "tr", "million")) and val < 500:
                    val *= 1000000
                elif (re.search(r'\b(nghìn|k)\b', s_clean) or re.search(r'\d+\s*k\b', s_clean)) and val < 10000:
                    val *= 1000
            else:
                if suffix in ("tr", "triệu", "million", "m"):
                    val *= 1000000
                elif suffix in ("k", "nghìn"):
                    val *= 1000
            return int(val)
            
        if len(num_matches) >= 2:
            try:
                vals = [get_val(m.group(1), m.group(2)) for m in num_matches]
                if len(set(vals)) == 1:
                    num_matches = [num_matches[0]]
            except Exception:
                pass
                
        is_range = any(x in s_clean for x in ("-", "–", "—", "đến", "tới", "to"))
        
        if len(num_matches) >= 2 and is_range:
            n1_str, suff1 = num_matches[0].groups()
            n2_str, suff2 = num_matches[1].groups()
            
            if not suff1 and suff2:
                suff1 = suff2
                
            min_s = get_val(n1_str, suff1)
            max_s = get_val(n2_str, suff2)
            
            if min_s < 1000 and currency == "VND":
                min_s *= 1000000
                max_s *= 1000000
                
            med_s = (min_s + max_s) // 2
            return {
                "min_salary": min_s,
                "max_salary": max_s,
                "med_salary": med_s,
                "currency": currency,
                "pay_period": pay_period
            }
        elif len(num_matches) >= 1:
            n_str, suff = num_matches[0].groups()
            val = get_val(n_str, suff)
            
            if val < 1000 and currency == "VND":
                val *= 1000000
                
            if any(x in s_clean for x in ("lên đến", "lên tới", "upto", "up to", "tối đa", "max", "dưới")):
                return {
                    "min_salary": None,
                    "max_salary": val,
                    "med_salary": None,
                    "currency": currency,
                    "pay_period": pay_period
                }
            elif any(x in s_clean for x in ("từ", "from", "tối thiểu", "min", "trên")):
                return {
                    "min_salary": val,
                    "max_salary": None,
                    "med_salary": None,
                    "currency": currency,
                    "pay_period": pay_period
                }
            else:
                return {
                    "min_salary": val,
                    "max_salary": val,
                    "med_salary": val,
                    "currency": currency,
                    "pay_period": pay_period
                }

    negotiable_keywords = ("thỏa thuận", "thoả thuận", "thương lượng", "cạnh tranh", "negotiable", "competitive")
    if any(neg in s for neg in negotiable_keywords):
        return {
            "min_salary": None,
            "max_salary": None,
            "med_salary": None,
            "currency": "unknown",
            "pay_period": "negotiable"
        }
        
    return None


def _validate_and_normalize(extracted: Dict[str, Any], original_job: Dict[str, Any]) -> Dict[str, Any]:
    warnings: List[str] = []
    errors: List[str] = []

    # Ensure top-level containers exist
    job = extracted.get('job') or {}
    company = extracted.get('company') or {}
    salary = extracted.get('salary') or {}
    raw = extracted.get('raw') or {}

    # Failsafe fallback: if salary fields are empty, try local parsing first
    if (salary.get('min_salary') is None and salary.get('max_salary') is None 
            and salary.get('pay_period') not in ('negotiable', 'yearly', 'monthly', 'hourly', 'daily', 'weekly')):
        raw_sal_str = original_job.get('salary_raw') or original_job.get('salary') or extracted.get('salary_raw')
        if raw_sal_str:
            local_extracted = parse_salary_locally(raw_sal_str)
            if local_extracted:
                salary.update({
                    'min_salary': local_extracted.get('min_salary'),
                    'max_salary': local_extracted.get('max_salary'),
                    'med_salary': local_extracted.get('med_salary'),
                    'currency': local_extracted.get('currency'),
                    'pay_period': local_extracted.get('pay_period')
                })

    # 2. Validate work_type enum
    allowed_work = {
        'full_time', 'part_time', 'internship', 'contract', 'temporary', 'freelance', 'other', 'unknown'
    }
    wt = job.get('work_type')
    if wt not in allowed_work:
        warnings.append(f"work_type invalid: {wt}")
        job['work_type'] = 'unknown'

    # 3. Validate currency
    allowed_currency = {'VND', 'USD', 'EUR', 'JPY', 'KRW', 'SGD', 'OTHER', 'unknown'}
    cur = salary.get('currency')
    if cur not in allowed_currency:
        warnings.append(f"salary.currency invalid: {cur}")
        salary['currency'] = 'unknown'

    # 4. Validate pay_period
    allowed_period = {'monthly', 'yearly', 'hourly', 'daily', 'negotiable', 'unknown'}
    pp = salary.get('pay_period')
    if pp not in allowed_period:
        warnings.append(f"salary.pay_period invalid: {pp}")
        salary['pay_period'] = 'unknown'

    # 5. Validate salary numbers
    min_s = _to_number_or_null(salary.get('min_salary'))
    max_s = _to_number_or_null(salary.get('max_salary'))
    med_s = _to_number_or_null(salary.get('med_salary'))
    salary['min_salary'] = None if min_s is None else int(min_s)
    salary['max_salary'] = None if max_s is None else int(max_s)
    salary['med_salary'] = None if med_s is None else int(med_s)

    # 6. Swap salary if max < min
    if salary['min_salary'] is not None and salary['max_salary'] is not None:
        if salary['max_salary'] < salary['min_salary']:
            warnings.append('salary.max_salary < min_salary; swapped')
            salary['min_salary'], salary['max_salary'] = salary['max_salary'], salary['min_salary']

    # 7. Compute med_salary if possible
    if salary.get('med_salary') is None and salary.get('min_salary') is not None and salary.get('max_salary') is not None:
        salary['med_salary'] = int((salary['min_salary'] + salary['max_salary']) // 2)

    # 8. Company size ints
    cmin = _to_int_or_null(company.get('company_size_min'))
    cmax = _to_int_or_null(company.get('company_size_max'))
    company['company_size_min'] = cmin
    company['company_size_max'] = cmax
    if cmin is not None and cmax is not None and cmax < cmin:
        warnings.append('company.company_size_max < min; swapped')
        company['company_size_min'], company['company_size_max'] = company['company_size_max'], company['company_size_min']

    # 10. Validate dates
    listed = _parse_iso_date(job.get('listed_time') or extracted.get('listed_time'))
    expiry = _parse_iso_date(job.get('expiry_time') or extracted.get('expiry_time'))
    job['listed_time'] = listed
    job['expiry_time'] = expiry
    if listed is None and (job.get('listed_time') or extracted.get('listed_time')):
        warnings.append('listed_time unparseable')
    if expiry is None and (job.get('expiry_time') or extracted.get('expiry_time')):
        warnings.append('expiry_time unparseable')

    # 11. If expiry < listed, add warning but keep both
    try:
        if listed and expiry:
            dt_listed = datetime_fromisoformat_safe(listed)
            dt_expiry = datetime_fromisoformat_safe(expiry)
            if dt_listed and dt_expiry and dt_expiry < dt_listed:
                warnings.append('expiry_time < listed_time')
    except Exception:
        pass

    # 12/13. Ensure lists
    if not isinstance(extracted.get('extracted_skills'), list):
        warnings.append('extracted_skills not a list; coerced to empty list')
        extracted['extracted_skills'] = []
    if not isinstance(extracted.get('benefits'), list):
        if isinstance(extracted.get('benefits'), str) and extracted.get('benefits').strip():
            extracted['benefits'] = [extracted['benefits']]
        else:
            extracted['benefits'] = []

    # 1. Preserve original source fields (ensure they remain present)
    for key in ('source_name', 'job_url', 'job_source_id', 'search_keyword', 'scraped_at', 'description_html'):
        if key in original_job and key not in extracted:
            extracted[key] = original_job.get(key)

    # Attach normalized containers back
    extracted['job'] = job
    extracted['company'] = company
    extracted['salary'] = salary
    extracted['raw'] = raw

    # Final validation flags
    validation = extracted.get('validation', {}) or {}
    validation.setdefault('warnings', [])
    validation.setdefault('errors', [])
    validation['warnings'].extend(warnings)
    validation['errors'].extend(errors)
    # is_valid_for_import = True if no errors
    validation['is_valid_for_import'] = len(validation['errors']) == 0
    extracted['validation'] = validation

    return extracted


def process_job(job: Dict[str, Any], api_key: str, config_path: Path, api_key_name: Optional[str] = None) -> Dict[str, Any]:
    base_record = dict(job)
    base_record["status"] = "pending_llm"
    if api_key_name:
        base_record["api_key_used"] = api_key_name

    llm_out = None

    try:
        llm_out = call_llm(job, api_key, config_path)

        # Parse model output to dict (accept text or already-parsed dict)
        if isinstance(llm_out, dict):
            extracted = llm_out
        else:
            extracted = _extract_json_from_text(llm_out)

        if not isinstance(extracted, dict):
            raise ValueError(f"Structured output is not an object: {type(extracted).__name__}")

        # Remove fields that must be generated by code only
        extracted.pop('fingerprint', None)
        extracted.pop('validation', None)

        # Before validation: enforce `job.search_group` to the original input `search_keyword` when present.
        # This always sets the field from the crawler input (confidence=100) so downstream groups
        # reliably reflect the original search keyword used to find the posting.
        if job.get('search_keyword'):
            extracted.setdefault('job', {})
            extracted['job']['search_group'] = {"value": job.get('search_keyword'), "confidence": 100}

        # Validate using extract_validation_rules (load dynamically)
        try:
            val_mod = _load_2cd_module('extract_validation_rules')
            validate_record = getattr(val_mod, 'validate_record')
        except Exception:
            validate_record = None

        if validate_record:
            try:
                extracted, validation = validate_record(extracted)
                # ensure validation object present
                extracted['validation'] = validation if isinstance(validation, dict) else extracted.get('validation', {})
            except Exception as ve:  # validation should not break pipeline
                extracted.setdefault('validation', {'is_valid_for_import': False, 'warnings': [], 'errors': [str(ve)]})

        # Preserve original full requirements_text from input in raw.requirements_text
        # (do not let LLM destroy the original raw text). If present in the input job,
        # store it under extracted['raw']['requirements_text'] and prefer it for flattening.
        if job.get('requirements_text'):
            extracted.setdefault('raw', {})
            # only overwrite raw.requirements_text if missing to preserve any LLM-provided raw
            if not extracted['raw'].get('requirements_text'):
                extracted['raw']['requirements_text'] = job.get('requirements_text')

        # Flatten compatibility fields expected downstream (keep nested copies too)
        title = extracted.get('job', {}).get('title')
        if title:
            extracted['title'] = title

        company_name = extracted.get('company', {}).get('name')
        if company_name:
            extracted['company_name'] = company_name

        requirements_text = extracted.get('raw', {}).get('requirements_text') or extracted.get('job', {}).get('skills_desc')
        if requirements_text:
            extracted['requirements_text'] = requirements_text

        # Ensure `raw.location_raw` represents job location, not company address.
        # Prefer job.location; if missing, use extracted raw.location_raw.
        location_raw = extracted.get('job', {}).get('location') or extracted.get('raw', {}).get('location_raw')
        if location_raw:
            extracted['location_raw'] = location_raw

        # Heuristic: if raw.location_raw looks like a postal/company address (street number, 'phường', 'đường', 'street', etc.)
        # and company.address is empty, move that value into company.address and clear raw.location_raw.
        addr_candidate = extracted.get('raw', {}).get('location_raw')
        company_addr = extracted.get('company', {}).get('address')
        if addr_candidate and not company_addr:
            addr_text = str(addr_candidate)
            addr_indicators = ('đường', 'đ.', 'phố', 'phường', 'số', 'st', 'street', 'road', 'rd', 'avenue', 'av', ',')
            contains_indicator = any(ind.lower() in addr_text.lower() for ind in addr_indicators)
            contains_digit = bool(re.search(r"\d", addr_text))
            if contains_indicator or contains_digit:
                extracted.setdefault('company', {})
                extracted['company']['address'] = {"value": addr_text, "confidence": 100}
                # Prefer job.location for raw.location_raw; if not available, clear to avoid confusion
                if extracted.get('job', {}).get('location'):
                    extracted['raw']['location_raw'] = extracted.get('job', {}).get('location')
                else:
                    extracted['raw'].pop('location_raw', None)

        salary_raw = extracted.get('raw', {}).get('salary_raw')
        if salary_raw:
            extracted['salary_raw'] = salary_raw

        employment_type = extracted.get('raw', {}).get('employment_type_raw')
        if employment_type:
            extracted['employment_type'] = employment_type

        experience_raw = extracted.get('raw', {}).get('experience_raw')
        if experience_raw:
            extracted['experience_raw'] = experience_raw

        listed_time = extracted.get('job', {}).get('listed_time')
        if listed_time:
            extracted['listed_time'] = listed_time

        expiry_time = extracted.get('job', {}).get('expiry_time')
        if expiry_time:
            extracted['expiry_time'] = expiry_time

        # Preserve original source fields from input job if missing in extracted
        # 1) Enforce guaranteed top-level fields: always preserve from input
        for key in GUARANTEED_TOPLEVEL:
            if key in job and job.get(key) is not None:
                extracted[key] = job.get(key)

        # Clean description_html using split_description logic
        source_name = extracted.get("source_name")
        desc_html = extracted.get("description_html")
        if source_name and desc_html:
            extracted["description_html"] = extract_clean_job_description(source_name, desc_html)


        # 2) Special company_name rule: if input has non-empty company_name, preserve it.
        #    If input company_name is missing/empty and LLM produced company.name with very-high
        #    confidence, allow filling top-level company_name from company.name.
        input_cname = job.get('company_name')
        if input_cname and str(input_cname).strip():
            extracted['company_name'] = input_cname
        else:
            # check confidence map produced by validation
            conf_map = extracted.get('confidence') or extracted.get('validation', {}).get('confidence', {})
            try:
                cname_conf = int(conf_map.get('company.name', 0))
            except Exception:
                cname_conf = 0
            if cname_conf >= VERY_HIGH_CONF:
                cname = extracted.get('company', {}).get('name')
                if cname:
                    extracted['company_name'] = cname

        # Title merge rule: title is no longer guaranteed. If LLM provided a title (after
        # validation/unwrapping), prefer it. If LLM did not provide title, preserve input title
        # when available.
        if not extracted.get('title') and job.get('title'):
            extracted['title'] = job.get('title')

        # Apply older inline normalization as fallback (merge results)
        try:
            normalized = _validate_and_normalize(extracted, job)
        except Exception:
            normalized = extracted

        # Merge normalized into final record and return
        base_record.update(normalized)
        base_record["status"] = "success"
        base_record.pop("error", None)
        return base_record
    except Exception as exc:  # noqa: BLE001
        err_text = str(exc) or ""
        # Determine failure reason with some granularity
        if _is_parse_error(exc) or "empty gemini response" in err_text.lower():
            failure_reason = "invalid_json_response"
            base_record["status"] = "invalid_json_response"
        elif _is_api_error(exc):
            failure_reason = "llm_api_fail"
            base_record["status"] = "llm_api_fail"
        else:
            failure_reason = "llm_api_fail"
            base_record["status"] = "llm_api_fail"

        base_record["error"] = err_text
        base_record["failure_reason"] = failure_reason

        # Attach raw model output and traceback to assist debugging
        try:
            base_record['llm_raw'] = llm_out
        except Exception:
            base_record['llm_raw'] = None
        try:
            base_record['traceback'] = traceback.format_exc()
        except Exception:
            base_record['traceback'] = None

        # Do not compute fingerprint for failed records at extract stage.
        return base_record


def load_today_processed_jobs(current_folder_name: str) -> List[Dict[str, Any]]:
    processed = []
    try:
        today_prefix = "crawl_" + datetime.utcnow().strftime("%Y%m%d")
        data_dir = BASE_DIR / "data"
        if data_dir.exists():
            for folder in data_dir.iterdir():
                if folder.is_dir() and folder.name.startswith(today_prefix) and folder.name != current_folder_name:
                    for filename in ("clean/extracted.json", "fallback/extract_fallback.json"):
                        file_path = folder / filename
                        if file_path.exists():
                            try:
                                txt = file_path.read_text(encoding='utf-8-sig').strip()
                                if txt:
                                    parsed = json.loads(txt)
                                    if isinstance(parsed, list):
                                        for e in parsed:
                                            if isinstance(e, dict) and e.get("status") in ("success", "duplicate"):
                                                processed.append(e)
                            except Exception:
                                pass
    except Exception:
        pass
    return processed


def deduplicate_jobs_by_embeddings(
    jobs: List[Dict[str, Any]], 
    logger: logging.Logger, 
    prev_jobs: List[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not jobs:
        return [], []

    if prev_jobs is None:
        prev_jobs = []

    logger.info("Starting embedding-based deduplication on %d loaded jobs (comparing with %d historical jobs today)...", len(jobs), len(prev_jobs))

    def normalize_company(name):
        if not name:
            return ""
        import unicodedata
        import re
        n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("utf-8").lower()
        suffixes = [
            r'\bcompany\b', r'\bco\b', r'\bltd\b', r'\bjsc\b', r'\bcorp\b', r'\bcorporation\b',
            r'\bjoint\s+stock\b', r'\bthanh\s+vien\b', r'\bco\s+phan\b', r'\bcong\s+ty\b',
            r'\btrach\s+nhiem\s+huu\s+han\b', r'\btnhh\b', r'\bgờ\s+rúp\b', r'\bgroup\b'
        ]
        for suffix in suffixes:
            n = re.sub(suffix, '', n)
        n = re.sub(r'[^a-zA-Z0-9]', '', n).strip()
        return n

    # Group all jobs (both new and old) by normalized company
    groups = {}
    new_job_ids = {id(j) for j in jobs}
    combined_jobs = jobs + prev_jobs

    for job in combined_jobs:
        c_name = job.get("company_name") or (job.get("company") or {}).get("name") or ""
        norm_c = normalize_company(c_name)
        if norm_c:
            groups.setdefault(norm_c, []).append(job)

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Loaded sentence transformer 'all-MiniLM-L6-v2' successfully.")
    except Exception as e:
        logger.warning("Could not load sentence_transformers for deduplication: %s. Skipping embedding deduplication.", e)
        return jobs, []

    import numpy as np

    duplicate_jobs = []
    duplicate_set = set()
    cross_source_dup_count = 0
    same_source_dup_count = 0

    for norm_c, group_jobs in groups.items():
        # Only perform comparison if we have at least 2 jobs and at least one is NEW
        if len(group_jobs) < 2 or not any(id(j) in new_job_ids for j in group_jobs):
            continue

        texts = []
        valid_indices = []
        for i, job in enumerate(group_jobs):
            text = build_llm_input_text(job)
            text = text.strip()
            if len(text) > 50:
                texts.append(text)
                valid_indices.append(i)

        if len(texts) < 2:
            continue

        try:
            embeddings = model.encode(texts, convert_to_numpy=True)
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            embeddings_norm = embeddings / norms
            sim_matrix = np.dot(embeddings_norm, embeddings_norm.T)
        except Exception as e:
            logger.error("Error computing embeddings/similarity: %s", e)
            continue

        duplicate_group_indices = set()
        for i in range(len(texts)):
            if i in duplicate_group_indices:
                continue
            for j in range(i + 1, len(texts)):
                if j in duplicate_group_indices:
                    continue
                similarity = sim_matrix[i, j]
                if similarity > 0.9:
                    job_i = group_jobs[valid_indices[i]]
                    job_j = group_jobs[valid_indices[j]]
                    
                    # Ensure job_j is always the NEW job that gets marked as duplicate.
                    if id(job_j) not in new_job_ids:
                        if id(job_i) in new_job_ids:
                            job_i, job_j = job_j, job_i
                        else:
                            continue

                    src_i = job_i.get("source_name") or ""
                    src_j = job_j.get("source_name") or ""
                    c_name_i = job_i.get("company_name") or (job_i.get("company") or {}).get("name") or ""

                    # Mark job_j as duplicate
                    job_j["status"] = "duplicate"
                    job_j["duplicate_of"] = job_i.get("job_url")
                    
                    if src_i.lower() != src_j.lower():
                        cross_source_dup_count += 1
                        job_j["failure_reason"] = "duplicate_cross_source"
                        job_j["error"] = f"Filtered as cross-source duplicate (similarity: {similarity:.3f}) with job from {src_i} (URL: {job_i.get('job_url')})"
                        logger.info("Found cross-source duplicate job at similarity %.3f for company '%s':", similarity, c_name_i)
                        logger.info("  - Keep Job: Title='%s', Source='%s', URL='%s'", job_i.get("title"), src_i, job_i.get("job_url"))
                        logger.info("  - Skip Job: Title='%s', Source='%s', URL='%s'", job_j.get("title"), src_j, job_j.get("job_url"))
                    else:
                        same_source_dup_count += 1
                        job_j["failure_reason"] = "duplicate_same_source"
                        job_j["error"] = f"Filtered as same-source duplicate (similarity: {similarity:.3f}) with job URL: {job_i.get('job_url')}"
                        logger.info("Found same-source duplicate job at similarity %.3f for company '%s':", similarity, c_name_i)
                        logger.info("  - Keep Job: Title='%s', Source='%s', URL='%s'", job_i.get("title"), src_i, job_i.get("job_url"))
                        logger.info("  - Skip Job: Title='%s', Source='%s', URL='%s'", job_j.get("title"), src_j, job_j.get("job_url"))

                    duplicate_group_indices.add(j)
                    duplicate_set.add(id(job_j))

    jobs_to_keep = []
    for job in jobs:
        if id(job) in duplicate_set:
            duplicate_jobs.append(job)
        else:
            jobs_to_keep.append(job)

    logger.info("Deduplication completed. Total input jobs: %d. Kept: %d. Filtered cross-source duplicates (trung lien nguon): %d. Filtered same-source duplicates: %d.", 
                len(jobs), len(jobs_to_keep), cross_source_dup_count, same_source_dup_count)
    return jobs_to_keep, duplicate_jobs


def save_jobs(output_path: Path, jobs: List[Dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # atomic write: write to temp then replace to avoid truncated JSON
    tmp_path = output_path.parent / (output_path.name + ".tmp")
    tmp_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.replace(str(tmp_path), str(output_path))
    except Exception:
        # best-effort fallback
        output_path.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def derive_output_path(input_path: Path, output_dir: Path) -> Path:
    # Prefer placing extracted output under a crawl-specific folder when the
    # input filename encodes a date (jobs_YYYY-MM-DD...). This writes to
    # workspace_root/Db/data/crawlMMDDYYYY/clean/extracted.json which matches
    # the requested `Db/data/crawlmmddyyy/clean` layout.
    try:
        import re
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(input_path))
        if m:
            yyyy, mm, dd = m.groups()
            # workspace root is two parents above BASE_DIR (..../JobVisualization_BE)
            workspace_root = BASE_DIR.parents[2]
            crawl_dir = workspace_root / "Db" / "data" / f"crawl{mm}{dd}{yyyy}" / "clean"
            return crawl_dir / "extracted.json"
    except Exception:
        pass

    # If the caller passed an `extracted` directory (legacy), write the file
    # next to it as `extracted.json` instead of creating an `extracted/` folder.
    if output_dir.name == "extracted":
        return output_dir.parent / "extracted.json"
    return output_dir / "extracted.json"


def main() -> int:
    args = parse_args()
    logger = setup_logging()

    # Prefer loading .env from the project `Db/` root so GEMINI_API_KEY_* and other
    # global settings defined there are available when this script runs.
    # Fallback to BASE_DIR/.env if project-level .env not present.
    project_env = (BASE_DIR.parents[1] / '.env') if len(BASE_DIR.parents) > 1 else (BASE_DIR / '.env')
    env_used = project_env if project_env.exists() else (BASE_DIR / '.env')
    load_dotenv(env_used)
    logger = setup_logging()
    logger.info("Loaded .env from: %s", env_used)

    # Debug: check API keys availability and prompt extraction template
    api_keys = _load_api_keys()
    logger.info("[LLM CONFIG] provider=gemini api_keys_found=%s", len(api_keys))
    # Load prompt file using strict YAML parsing (do NOT mutate raw before parsing)
    prompt_text = ''
    prompt_loaded = False
    try:
        cfg_path = Path(args.config_path)
        # print resolved path for diagnostics
        logger.info("[LLM CONFIG] prompt_path_resolved=%s", cfg_path.resolve())
        exists = cfg_path.exists()
        size = cfg_path.stat().st_size if exists else 0
        logger.info("[LLM CONFIG] prompt_file_exists=%s prompt_file_size=%s bytes path=%s", exists, size, cfg_path)
        if exists:
            # read using UTF-8 (fallback to utf-8-sig if needed)
            try:
                raw = cfg_path.read_text(encoding='utf-8')
            except Exception:
                raw = cfg_path.read_text(encoding='utf-8-sig')

            # show a snippet and a problematic slice around the earlier parse error area
            snippet = raw[:400].replace('\n', '\\n')
            logger.info("[LLM CONFIG] prompt_file_snippet=%s", snippet)
            try:
                # raw slice near previously reported line (around 18k-19k bytes)
                start = min(len(raw), 17000)
                slice_repr = repr(raw[start:19000])
                logger.info("[LLM CONFIG] prompt_raw_slice_repr=%s", slice_repr)
            except Exception:
                pass

            # Parse YAML directly without any modifications
            import yaml as _yaml
            cfg = _yaml.safe_load(raw)
            if isinstance(cfg, dict):
                keys = list(cfg.keys())
                logger.info("[LLM CONFIG] clean_config top-level keys=%s", keys)
                prompt_text = cfg.get('prompt_extraction', '')
                prompt_loaded = bool(prompt_text and str(prompt_text).strip())
                logger.info("[LLM CONFIG] prompt_extraction_type=%s", type(prompt_text).__name__)
            else:
                logger.info("[LLM CONFIG] clean_config YAML parsed to non-dict: %s", type(cfg).__name__)
    except Exception as e:
        logger.exception("[LLM CONFIG] failed parsing clean_config.yaml: %s", e)

    if not api_keys:
        logger.error("No GEMINI_API_KEY_* found in environment after loading %s; aborting.", env_used)
        return 2
    if not prompt_loaded:
        logger.error("Extraction prompt not found or empty at %s; aborting.", args.config_path)
        return 3
    # Quick runtime verification (print to stdout for immediate visibility)
    try:
        print("PROMPT_LENGTH:", len(prompt_text))
        print("PROMPT_PREVIEW:", (prompt_text or '')[:200])
        logger.info("[LLM CONFIG] PROMPT_LENGTH=%d", len(prompt_text))
    except Exception:
        logger.exception("[LLM CONFIG] error while printing prompt preview")
    # Verify LLM SDK and child helper present so we fail early for missing deps
    try:
        import google.generativeai as _genai  # type: ignore
        logger.info("[LLM CONFIG] google.generativeai available")
    except Exception:
        logger.exception("[LLM CONFIG] google.generativeai (genai) not importable; install required package")
        return 4

    # Ensure debug child helper exists (used by adapter to isolate SDK calls)
    try:
        child_path = Path(__file__).resolve().parents[2] / 'llm' / 'debug_llm_child.py'
        if not child_path.exists():
            logger.error("[LLM CONFIG] debug_llm_child.py missing at %s; aborting.", child_path)
            return 5
        logger.info("[LLM CONFIG] debug_llm_child present: %s", child_path)
    except Exception:
        logger.exception("[LLM CONFIG] error while checking debug_llm_child.py")
        return 6

    input_path = args.input_path
    if not input_path.is_absolute():
        input_path = BASE_DIR / input_path

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir

    output_path = args.output_path
    if output_path is None:
        if "batch_1.json" in str(input_path):
            output_path = input_path.parent / "batch_1_extracted_clean.json"
        else:
            output_path = derive_output_path(input_path, output_dir)
    elif not output_path.is_absolute():
        output_path = BASE_DIR / output_path

    fallback_path = args.fallback_path
    if fallback_path is not None and not fallback_path.is_absolute():
        fallback_path = BASE_DIR / fallback_path
    if fallback_path is None:
        # By default write the fallback file next to the main output file
        # (previous behavior wrote to DEFAULT_FALLBACK_DIR which often
        # caused files to appear in an unexpected location).
        fallback_path = output_path.parent / (output_path.stem + "_fallback.json")

    jobs = load_jobs(input_path)
    total_jobs = len(jobs)
    logger.info("Loaded %s pending job(s) from %s", total_jobs, input_path)

    passed_jobs: List[Dict[str, Any]] = []
    failed_jobs: List[Dict[str, Any]] = []

    # Load previously processed jobs today for cross-batch deduplication
    try:
        current_folder_name = output_path.parent.parent.name
        prev_processed_jobs = load_today_processed_jobs(current_folder_name)
    except Exception as e:
        logger.warning("Error resolving current folder name or loading historical jobs: %s", e)
        prev_processed_jobs = []

    # Embedding-based cross-source deduplication before calling LLM
    jobs, duplicate_jobs = deduplicate_jobs_by_embeddings(jobs, logger, prev_processed_jobs)
    total_jobs = len(jobs)

    # Add duplicate jobs to failed_jobs so they are written to fallback file and not processed by LLM
    failed_jobs.extend(duplicate_jobs)

    api_keys = _load_api_keys()
    # Initialize API key controller which persists per-day states (no secrets stored)
    try:
        ak_mod = _load_2cd_module('api_key_controller')
        APIKeyController = getattr(ak_mod, 'APIKeyController')
    except Exception:
        APIKeyController = None

    if APIKeyController:
        key_state_path = BASE_DIR / "2_clean_data" / "cache" / "api_key_state.json"
        controller = APIKeyController(provider='gemini', state_file=key_state_path, max_requests_per_day=20)
        if not controller.has_active_keys():
            raise RuntimeError("No GEMINI_API_KEY_X keys found in environment or all keys exhausted for today.")
    else:
        controller = None

    success_count = 0
    api_fail_count = 0
    parse_fail_count = 0
    pending_next_day_jobs: List[Dict[str, Any]] = []

    # Max retries per job per run controlled by env
    MAX_ATTEMPTS_PER_DAY = int(LLM_MAX_RETRY_PER_JOB)

    def _has_benefits(rec: Dict[str, Any]) -> bool:
        # accept non-empty list or non-empty string in common benefit keys
        benefit_keys = ("benefits", "extracted_benefits", "benefit_list", "benefits_list")
        for k in benefit_keys:
            v = rec.get(k)
            if isinstance(v, list) and len(v) > 0:
                return True
            if isinstance(v, str) and v.strip():
                return True
        return False

    def _has_requirements(rec: Dict[str, Any]) -> bool:
        for k in ("requirements_text", "requirements", "requirements_raw"):
            v = rec.get(k)
            if isinstance(v, str) and v.strip():
                return True
        return False

    def _has_posted_or_expiry(rec: Dict[str, Any]) -> bool:
        for k in ("posted_date", "expiry_date", "listed_time", "posted_at", "expires_at", "expiry_time"):
            if rec.get(k):
                return True
        return False

    def _count_skills(rec: Dict[str, Any]) -> int:
        skills = rec.get("extracted_skills") or []
        if isinstance(skills, list):
            return len(skills)
        return 0

    # Build queues: active_queue for immediate processing, delayed_retry_queue for future retries.
    ignore_flag = args.ignore_retry_queue or os.getenv('IGNORE_RETRY_QUEUE', '').lower() in ('1', 'true', 'yes')
    retry_jobs = [] if ignore_flag else (load_retry_queue() or [])
    if ignore_flag:
        logger.info("IGNORE_RETRY_QUEUE enabled: skipping merge of existing retry queue and processing only current pending file")
    delayed_retry_jobs: List[Dict[str, Any]] = []
    # in-memory queue for jobs deferred because no key was available within the short-wait window
    no_key_wait_queue: List[Dict[str, Any]] = []
    active_jobs: List[Dict[str, Any]] = []
    now = datetime.utcnow()

    def _job_key(j: Dict[str, Any]) -> str:
        if not isinstance(j, dict):
            return ''
        if j.get('source_name') and j.get('job_source_id'):
            return f"{j.get('source_name')}|{j.get('job_source_id')}"
        if j.get('job_url'):
            return j.get('job_url')
        return j.get('_fingerprint') or hashlib.md5((str(j.get('title','')) + '|' + str(j.get('company_name','')) + '|' + str(j.get('requirements_text',''))).encode('utf-8')).hexdigest()

    retry_queue_remove_keys = set()

    def _remember_retry_done(job: Dict[str, Any]) -> None:
        for key in (_job_key(job), job.get('_fingerprint'), job.get('job_url')):
            if key:
                retry_queue_remove_keys.add(key)

    def _current_retry_count(job: Dict[str, Any], processed: Optional[Dict[str, Any]] = None) -> int:
        max_count = 0
        for rec in (processed, job):
            if not isinstance(rec, dict):
                continue
            for field in ('retry_count', 'attempt_count'):
                try:
                    max_count = max(max_count, int(rec.get(field, 0) or 0))
                except Exception:
                    continue
        return max_count

    def _build_retry_entry(job: Dict[str, Any], processed: Dict[str, Any], err_text: str) -> Dict[str, Any]:
        previous_count = _current_retry_count(job)
        processed_count = _current_retry_count(processed)
        retry_count = processed_count if processed_count > previous_count else previous_count + 1
        entry = dict(job)
        entry.update({
            'status': 'retryable',
            'last_error': err_text,
            'last_attempt_at': datetime.utcnow().isoformat(),
            'attempt_count': retry_count,
            'retry_count': retry_count,
        })
        if processed.get('api_key_used'):
            entry['api_key_used'] = processed.get('api_key_used')
        return entry

    # Partition retry jobs by next_retry_at. Due entries are processed before new pending jobs.
    for r in retry_jobs:
        nr = r.get('next_retry_at')
        if nr:
            try:
                dt = datetime.fromisoformat(nr)
                if dt <= now:
                    active_jobs.append(r)
                else:
                    delayed_retry_jobs.append(r)
                continue
            except Exception:
                # malformed date -> treat as immediate
                active_jobs.append(r)
        else:
            active_jobs.append(r)

    # load new pending jobs into active_jobs (dedupe against active+delayed and existing extracted)
    seen = { _job_key(j) for j in active_jobs + delayed_retry_jobs }
    
    # load existing extracted to avoid duplicates (Idempotency)
    existing_extracted_keys = set()
    existing_extracted_urls = set()
    try:
        if output_path.exists():
            txt = output_path.read_text(encoding='utf-8-sig').strip()
            if txt:
                parsed = json.loads(txt)
                if isinstance(parsed, list):
                    for e in parsed:
                        existing_extracted_keys.add(_job_key(e))
                        url = get_job_url(e)
                        if url:
                            existing_extracted_urls.add(url)
    except Exception:
        pass

    for j in jobs:
        k = _job_key(j)
        url = get_job_url(j)
        
        # Skip duplicate jobs using both url and standard keys
        if (not k and not url) or k in seen or k in existing_extracted_keys or (url and url in existing_extracted_urls):
            continue
            
        if k:
            seen.add(k)
        if url:
            seen.add(url)
            
        active_jobs.append(j)

    # Sequential processing (single-threaded): iterate active_jobs one-by-one
    sleep_seconds = int(os.getenv('LLM_SLEEP_BETWEEN_REQUESTS', '15'))
    request_timeout = int(os.getenv('LLM_REQUEST_TIMEOUT_SECONDS', '60'))

    # API key state file and utilities (do not store secret values)
    key_state_path = BASE_DIR / '2_clean_data' / 'cache' / 'api_key_state.json'

    def _read_key_state(p: Path) -> Dict[str, Any]:
        try:
            if p.exists():
                txt = p.read_text(encoding='utf-8-sig').strip()
                if txt:
                    st = json.loads(txt)
                    if isinstance(st, dict):
                        return st
        except Exception:
            pass
        return {"date": datetime.utcnow().date().isoformat(), "keys": []}

    def _write_key_state(p: Path, st: Dict[str, Any]) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.parent / (p.name + '.tmp')
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            os.replace(str(tmp), str(p))
        except Exception:
            p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')

    def _sync_keys_with_env(state: Dict[str, Any]) -> None:
        # discover GEMINI_API_KEY_N envs and sync into state.keys (preserve existing metadata)
        found = []
        for name, val in os.environ.items():
            m = re.fullmatch(r"GEMINI_API_KEY_(\d+)", name)
            if not m or not val:
                continue
            idx = int(m.group(1))
            found.append((idx, name))
        found.sort()
        existing = {k.get('env_name'): k for k in state.get('keys', [])}
        new_keys = []
        for idx, env_name in found:
            if env_name in existing:
                new_keys.append(existing[env_name])
            else:
                new_keys.append({
                    'index': idx,
                    'env_name': env_name,
                    'exhausted_today': False,
                    'disabled_until': None,
                    'total_success_today': 0,
                    'total_fail_today': 0,
                    'last_error': None,
                    'last_attempt_at': None,
                })
        state['keys'] = new_keys

    def _reset_daily(state: Dict[str, Any]) -> None:
        if state.get('date') != today_str():
            state['date'] = today_str()
            for k in state.get('keys', []):
                k['exhausted_today'] = False
                k['disabled_until'] = None
                k['total_success_today'] = 0
                k['total_fail_today'] = 0

    def _pick_next_valid(state: Dict[str, Any], start: int) -> Optional[int]:
        keys = state.get('keys', [])
        n = len(keys)
        if n == 0:
            return None
        now_dt = datetime.utcnow()
        for i in range(n):
            idx = (start + i) % n
            k = keys[idx]
            if k.get('exhausted_today'):
                continue
            dis = k.get('disabled_until')
            if dis:
                try:
                    if datetime.fromisoformat(dis) > now_dt:
                        continue
                except Exception:
                    pass
            return idx
        return None

    # prepare key state
    key_state = _read_key_state(key_state_path)
    _reset_daily(key_state)
    _sync_keys_with_env(key_state)
    _write_key_state(key_state_path, key_state)

    metrics = {
        'total_jobs_loaded': len(active_jobs) + len(delayed_retry_jobs),
        'success_count': 0,
        'fallback_count': 0,
        'temporary_deferred_count': 0,
        'no_key_deferred_count': 0,
        'llm_attempted_count': 0,
        'temporary_5xx_deferred_count': 0,
        'dead_letter_count': 0,
        'keys_used': {},
        'keys_429': 0,
        'keys_5xx': 0,
    }

    # Determine extraction mode (parallel vs sequential) from env
    extraction_mode = os.getenv("LLM_EXTRACTION_MODE", "parallel").lower().strip()
    
    if extraction_mode == "sequential":
        logger.info("Starting sequential extraction (single-threaded)")
        sleep_seconds = int(os.getenv('LLM_SLEEP_BETWEEN_REQUESTS', '15'))
        
        for idx, job in enumerate(active_jobs):
            job_key = _job_key(job)
            logger.info("Processing job %s (%d/%d)", job_key, idx + 1, len(active_jobs))
            
            # Acquire key dynamically from the controller
            key_info = controller.acquire_key(wait=True, max_wait=30) if controller else None
            
            if not key_info:
                logger.warning("No valid API keys available for job %s. Deferring to retry.", job_key)
                processed = dict(job)
                processed.update({
                    'status': 'retryable',
                    'last_error': 'no_valid_api_key',
                    'last_attempt_at': datetime.utcnow().isoformat(),
                })
                delayed_retry_jobs.append(processed)
                metrics['no_key_deferred_count'] += 1
                continue
                
            key_idx, env_name, api_key_val = key_info
            logger.info("Using API key: %s", env_name)
            
            try:
                processed = process_job(job, api_key_val, args.config_path, api_key_name=env_name)
            except Exception as exc:
                processed = dict(job)
                processed['status'] = 'llm_api_fail'
                processed['error'] = str(exc)
                
            processed['api_key_used'] = env_name
            status = processed.get('status')
            err_text = (processed.get('error') or '')
            low = err_text.lower() if isinstance(err_text, str) else ''
            
            # Update controller state
            if controller:
                if status == 'success':
                    controller.mark_success(env_name)
                elif '429' in low or 'quota' in low or 'resourceexhausted' in low or 'daily limit' in low:
                    controller.mark_429(env_name)
                else:
                    controller.mark_5xx_or_timeout(env_name)
                    
            # Classify and handle result
            if status == 'success':
                passed_jobs.append(processed)
                save_jobs(output_path, passed_jobs)
                _remember_retry_done(job)
                metrics['success_count'] += 1
            elif status == 'invalid_json_response' or _is_parse_error(Exception(err_text)):
                failed_jobs.append(processed)
                save_jobs(fallback_path, failed_jobs)
                _remember_retry_done(job)
                metrics['fallback_count'] += 1
            else:
                # API or other temporary failure -> decide retry vs fallback
                processed['attempt_count'] = _current_retry_count(job, processed) + 1
                processed['retry_count'] = processed['attempt_count']
                processed['last_error'] = err_text
                processed['last_attempt_at'] = datetime.utcnow().isoformat()
                
                if '429' in low or 'quota' in low or 'resourceexhausted' in low or 'daily limit' in low:
                    metrics['keys_429'] += 1
                elif any(x in low for x in ('503', '504', 'timeout', 'connection')):
                    metrics['keys_5xx'] += 1
                    
                delayed_retry_jobs.append(_build_retry_entry(job, processed, err_text))
                
            # Sleep between requests unless last job
            if idx < len(active_jobs) - 1:
                logger.info("Sleeping %d seconds before next request", sleep_seconds)
                time.sleep(sleep_seconds)
                
    else:
        # Set number of workers from environment variable or default to 8
        num_workers = int(os.getenv("LLM_NUM_WORKERS", "8"))
        logger.info("Starting parallel extraction with %d workers", num_workers)

        import queue
        import threading

        job_queue = queue.Queue()
        for idx, job in enumerate(active_jobs):
            job_queue.put((job, idx + 1))

        # Locks for thread-safe list operations and controller access
        results_lock = threading.Lock()
        controller_lock = threading.Lock()

        def worker_thread(worker_id):
            thread_name = threading.current_thread().name
            logger.info("[%s] Worker %d started", thread_name, worker_id)

            while True:
                try:
                    job, job_index = job_queue.get_nowait()
                except queue.Empty:
                    break

                job_key = _job_key(job)
                logger.info("[%s] Worker %d processing job %s (%d/%d)", thread_name, worker_id, job_key, job_index, len(active_jobs))

                # Acquire key dynamically from the controller
                with controller_lock:
                    key_info = controller.acquire_key(wait=True, max_wait=30) if controller else None

                if not key_info:
                    # No keys available -> write remaining job to retry queue
                    logger.warning("[%s] No valid API keys available for job %s. Deferring to retry.", thread_name, job_key)
                    processed = dict(job)
                    processed.update({
                        'status': 'retryable',
                        'last_error': 'no_valid_api_key',
                        'last_attempt_at': datetime.utcnow().isoformat(),
                    })
                    with results_lock:
                        delayed_retry_jobs.append(processed)
                        metrics['no_key_deferred_count'] += 1
                    job_queue.task_done()
                    continue

                key_idx, env_name, api_key_val = key_info
                logger.info("[%s] Worker %d using API key: %s", thread_name, worker_id, env_name)

                try:
                    processed = process_job(job, api_key_val, args.config_path, api_key_name=env_name)
                except Exception as exc:
                    processed = dict(job)
                    processed['status'] = 'llm_api_fail'
                    processed['error'] = str(exc)

                processed['api_key_used'] = env_name
                status = processed.get('status')
                err_text = (processed.get('error') or '')
                low = err_text.lower() if isinstance(err_text, str) else ''

                # Update controller state
                with controller_lock:
                    if controller:
                        if status == 'success':
                            controller.mark_success(env_name)
                        elif '429' in low or 'quota' in low or 'resourceexhausted' in low or 'daily limit' in low:
                            controller.mark_429(env_name)
                        else:
                            controller.mark_5xx_or_timeout(env_name)

                # Classify and handle result in a thread-safe manner
                with results_lock:
                    if status == 'success':
                        passed_jobs.append(processed)
                        save_jobs(output_path, passed_jobs)
                        _remember_retry_done(job)
                        metrics['success_count'] += 1
                    elif status == 'invalid_json_response' or _is_parse_error(Exception(err_text)):
                        failed_jobs.append(processed)
                        save_jobs(fallback_path, failed_jobs)
                        _remember_retry_done(job)
                        metrics['fallback_count'] += 1
                    else:
                        # API or other temporary failure -> decide retry vs fallback
                        processed['attempt_count'] = _current_retry_count(job, processed) + 1
                        processed['retry_count'] = processed['attempt_count']
                        processed['last_error'] = err_text
                        processed['last_attempt_at'] = datetime.utcnow().isoformat()

                        if '429' in low or 'quota' in low or 'resourceexhausted' in low or 'daily limit' in low:
                            metrics['keys_429'] += 1
                        elif any(x in low for x in ('503', '504', 'timeout', 'connection')):
                            metrics['keys_5xx'] += 1

                        delayed_retry_jobs.append(_build_retry_entry(job, processed, err_text))

                job_queue.task_done()

                # Wait 15s before next job if queue has remaining items
                if not job_queue.empty():
                    sleep_seconds = int(os.getenv('LLM_SLEEP_BETWEEN_REQUESTS', '15'))
                    logger.info("[%s] Worker %d sleeping %d seconds before next job", thread_name, worker_id, sleep_seconds)
                    time.sleep(sleep_seconds)

        # Spawn worker threads
        threads = []
        for w_id in range(num_workers):
            t = threading.Thread(
                target=worker_thread,
                args=(w_id,),
                name=f"LlmWorkerThread_{w_id}"
            )
            t.daemon = True
            threads.append(t)
            t.start()

        # Wait for all threads to finish
        for t in threads:
            t.join()

        logger.info("All parallel workers completed processing.")

    inline_retry_enabled = (
        not args.no_inline_retry
        and os.getenv("LLM_INLINE_RETRY_ENABLED", "true").lower() in ("1", "true", "yes")
    )
    inline_retry_max_rounds = max(1, int(os.getenv("LLM_INLINE_RETRY_MAX_ROUNDS", str(MAX_ATTEMPTS_PER_DAY))))
    inline_retry_wait_seconds = int(os.getenv("LLM_INLINE_RETRY_WAIT_SECONDS", str(LLM_MAX_WAIT_FOR_KEY_SECONDS)))

    def _retry_due_now(job: Dict[str, Any]) -> bool:
        nr = job.get('next_retry_at')
        if not nr:
            return True
        try:
            return datetime.fromisoformat(str(nr)) <= datetime.utcnow()
        except Exception:
            return True

    if inline_retry_enabled and delayed_retry_jobs:
        logger.info(
            "Inline retry enabled: attempting to drain %d retryable job(s) while API keys remain available.",
            len(delayed_retry_jobs),
        )
        remaining_retry_jobs = list(delayed_retry_jobs)
        delayed_retry_jobs = []

        for retry_round in range(1, inline_retry_max_rounds + 1):
            eligible = [
                job for job in remaining_retry_jobs
                if _retry_due_now(job) and _current_retry_count(job) < MAX_ATTEMPTS_PER_DAY
            ]
            not_eligible = [
                job for job in remaining_retry_jobs
                if not (_retry_due_now(job) and _current_retry_count(job) < MAX_ATTEMPTS_PER_DAY)
            ]

            if not eligible:
                delayed_retry_jobs.extend(not_eligible)
                break

            logger.info(
                "Inline retry round %d/%d: %d eligible job(s), %d held for later.",
                retry_round,
                inline_retry_max_rounds,
                len(eligible),
                len(not_eligible),
            )

            next_remaining: List[Dict[str, Any]] = list(not_eligible)
            stopped_for_keys = False

            for retry_index, job in enumerate(eligible):
                job_key = _job_key(job)
                key_info = controller.acquire_key(wait=True, max_wait=inline_retry_wait_seconds) if controller else None
                if not key_info:
                    logger.info(
                        "Inline retry stopped: no API key became available within %ss. Remaining jobs stay in retry queue.",
                        inline_retry_wait_seconds,
                    )
                    next_remaining.extend(eligible[retry_index:])
                    stopped_for_keys = True
                    break

                key_idx, env_name, api_key_val = key_info
                logger.info(
                    "Inline retry processing job %s with %s (attempt %d/%d)",
                    job_key,
                    env_name,
                    _current_retry_count(job) + 1,
                    MAX_ATTEMPTS_PER_DAY,
                )

                try:
                    processed = process_job(job, api_key_val, args.config_path, api_key_name=env_name)
                except Exception as exc:
                    processed = dict(job)
                    processed['status'] = 'llm_api_fail'
                    processed['error'] = str(exc)

                processed['api_key_used'] = env_name
                status = processed.get('status')
                err_text = (processed.get('error') or '')
                low = err_text.lower() if isinstance(err_text, str) else ''

                if controller:
                    if status == 'success':
                        controller.mark_success(env_name)
                    elif '429' in low or 'quota' in low or 'resourceexhausted' in low or 'daily limit' in low:
                        controller.mark_429(env_name)
                    else:
                        controller.mark_5xx_or_timeout(env_name)

                if status == 'success':
                    passed_jobs.append(processed)
                    save_jobs(output_path, passed_jobs)
                    _remember_retry_done(job)
                    metrics['success_count'] += 1
                elif status == 'invalid_json_response' or _is_parse_error(Exception(err_text)):
                    failed_jobs.append(processed)
                    save_jobs(fallback_path, failed_jobs)
                    _remember_retry_done(job)
                    metrics['fallback_count'] += 1
                else:
                    retry_entry = _build_retry_entry(job, processed, err_text)
                    if '429' in low or 'quota' in low or 'resourceexhausted' in low or 'daily limit' in low:
                        metrics['keys_429'] += 1
                    elif any(x in low for x in ('503', '504', 'timeout', 'connection')):
                        metrics['keys_5xx'] += 1
                    next_remaining.append(retry_entry)

            remaining_retry_jobs = next_remaining
            if stopped_for_keys:
                break

        delayed_retry_jobs.extend(remaining_retry_jobs)
        logger.info("Inline retry finished. Remaining retryable job(s): %d", len(delayed_retry_jobs))

    # Synchronize final counters for summary logging
    success_count = metrics['success_count']
    api_fail_count = metrics['keys_429'] + metrics['keys_5xx']
    parse_fail_count = metrics['fallback_count']

    try:
        if retry_queue_remove_keys:
            remove_ok = remove_retry_queue_entries(retry_queue_remove_keys)
            logger.info("retry_queue: removed_completed_count=%s remove_ok=%s", len(retry_queue_remove_keys), remove_ok)
    except Exception:
        pass

    # Persist delayed retry jobs and no-key-wait stashed jobs back to retry queue
    try:
        # Build list of NEW retry entries to write. Do NOT pass the existing queue here;
        # let `save_retry_queue` load+merge/upsert existing entries. This avoids skipping
        # updates when fingerprints already exist in the file.
        new_retry_jobs: List[Dict[str, Any]] = []

        # Add regular delayed retry jobs (these already contain retry metadata)
        try:
            for r in delayed_retry_jobs:
                if isinstance(r, dict):
                    new_retry_jobs.append(r)
        except Exception:
            pass

        # Add processed no-key-wait stashed jobs with normalized metadata
        try:
            now_dt = datetime.utcnow()
            for r in no_key_wait_queue:
                if not isinstance(r, dict):
                    continue
                proc = dict(r)
                proc['keys_tried'] = []
                proc['retry_count'] = proc.get('retry_count', 0)
                proc['reason'] = 'no_key_available_within_wait'
                # compute nearest future key availability as a hint
                min_dt = None
                try:
                    for k in (controller._state.get('keys') or []):
                        try:
                            na = k.get('next_available_at')
                            dis = k.get('disabled_until')
                            cand = None
                            if dis:
                                try:
                                    cand = datetime.fromisoformat(dis)
                                except Exception:
                                    cand = None
                            if na:
                                try:
                                    cand2 = datetime.fromisoformat(na)
                                    if cand is None or (cand2 and cand2 < cand):
                                        cand = cand2
                                except Exception:
                                    pass
                            if cand and cand > now_dt:
                                if min_dt is None or cand < min_dt:
                                    min_dt = cand
                        except Exception:
                            pass
                except Exception:
                    min_dt = None
                if min_dt:
                    proc['next_retry_at'] = min_dt.isoformat()
                else:
                    proc['next_retry_at'] = (now_dt + timedelta(seconds=int(LLM_MAX_WAIT_FOR_KEY_SECONDS))).isoformat()
                new_retry_jobs.append(proc)
        except Exception:
            pass

        # Write new retry jobs list and let retry_queue handle merging/upsert
        try:
            save_ok = save_retry_queue(new_retry_jobs)
        except Exception:
            save_ok = False

        # summary metrics for deferred jobs written to retry queue
        try:
            metrics.setdefault('deferred_count', 0)
            metrics.setdefault('retry_queue_written_count', 0)
            metrics['deferred_count'] = len(delayed_retry_jobs)
            metrics['retry_queue_written_count'] = len(new_retry_jobs) if save_ok else 0
            metrics['no_key_deferred_count'] = metrics.get('no_key_deferred_count', 0)
            logger.info("retry_queue: new_retry_jobs_count=%s save_ok=%s", len(new_retry_jobs), save_ok)
        except Exception:
            pass
    except Exception:
        pass

    # Save only passing records to the main extracted output
    save_jobs(output_path, passed_jobs)

    # Save failures to fallback for debugging/retention
    # Persist any jobs scheduled for next day into global retry queue
    try:
        if pending_next_day_jobs:
            existing = load_retry_queue() or []
            # merge unique by fingerprint
            seen = { (r.get('_fingerprint') or r.get('job_url') or '') for r in existing }
            to_add = []
            for r in pending_next_day_jobs:
                fp = r.get('_fingerprint') or r.get('job_url') or ''
                if fp not in seen:
                    seen.add(fp)
                    to_add.append(r)
            if to_add:
                existing.extend(to_add)
                save_retry_queue(existing)
    except Exception:
        pass

    if failed_jobs:
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        save_jobs(fallback_path, failed_jobs)

    # Log additional key-state summary metrics (non-invasive reporting only)
    try:
        keys = []
        if controller and hasattr(controller, '_state'):
            keys = controller._state.get('keys', [])
        now_dt = datetime.utcnow()
        keys_available = 0
        keys_backoff = 0
        keys_daily_exhausted = 0
        for k in keys:
            try:
                if k.get('exhausted_today'):
                    keys_daily_exhausted += 1
                    continue
                # disabled_until or next_available_at in future => backoff
                dis = k.get('disabled_until')
                na = k.get('next_available_at')
                in_backoff = False
                if dis:
                    try:
                        if datetime.fromisoformat(dis) > now_dt:
                            in_backoff = True
                    except Exception:
                        pass
                if na and not in_backoff:
                    try:
                        if datetime.fromisoformat(na) > now_dt:
                            in_backoff = True
                    except Exception:
                        pass
                if in_backoff:
                    keys_backoff += 1
                else:
                    keys_available += 1
            except Exception:
                pass
        metrics['keys_available_count'] = keys_available
        metrics['keys_backoff_count'] = keys_backoff
        metrics['keys_daily_exhausted_count'] = keys_daily_exhausted
        logger.info("Summary metrics: deferred=%s, retry_written=%s, keys_avail=%s, keys_backoff=%s, keys_exhausted=%s",
                    metrics.get('deferred_count'), metrics.get('retry_queue_written_count'),
                    metrics.get('keys_available_count'), metrics.get('keys_backoff_count'), metrics.get('keys_daily_exhausted_count'))
    except Exception:
        pass

    logger.info("Total jobs to process: %s", total_jobs)
    logger.info("Extract-pass (to normalize): %s", success_count)
    logger.info("LLM/API parse failures: %s", parse_fail_count)
    logger.info("LLM/API other failures: %s", api_fail_count)
    logger.info("Filtered duplicate jobs: %s", len(duplicate_jobs))
    logger.info("Wrote extracted (pass) jobs to: %s", output_path)
    if failed_jobs:
        logger.info("Wrote extract fallback jobs to: %s", fallback_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
