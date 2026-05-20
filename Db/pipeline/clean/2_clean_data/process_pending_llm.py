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

from Db.llm.retry_queue import load_retry_queue, save_retry_queue

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


DEFAULT_INPUT_PATH = BASE_DIR / "data" / "pending_llm" / "jobs_YYYY-MM-DD.pending.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "extracted"
DEFAULT_CONFIG_PATH = BASE_DIR / "2_clean_data" / "clean_config.yaml"
DEFAULT_FALLBACK_DIR = BASE_DIR / "data" / "fallback"

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
    # Prefer `cleaned_text` when available (more complete cleaned HTML->text)
    requirements_text = _normalize_text(job.get("cleaned_text") or job.get("requirements_text"))
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
    try:
        logger.info("LLM input length: %d", len(cleaned))
    except Exception:
        pass

    # Create a shallow copy and set the `requirements_text` placeholder
    job_for_prompt = dict(job)
    job_for_prompt['requirements_text'] = cleaned
    prompt = _build_prompt(job_for_prompt, config_path)
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

    # Description: remove noisy tags then strip HTML
    desc_html = _safe_get('description_html', 'description')
    if isinstance(desc_html, str) and desc_html.strip():
        txt = desc_html
        # remove script/style/header/footer/nav blocks
        txt = re.sub(r'<script[\s\S]*?</script>', ' ', txt, flags=re.I)
        txt = re.sub(r'<style[\s\S]*?</style>', ' ', txt, flags=re.I)
        txt = re.sub(r'<header[\s\S]*?</header>', ' ', txt, flags=re.I)
        txt = re.sub(r'<nav[\s\S]*?</nav>', ' ', txt, flags=re.I)
        txt = re.sub(r'<footer[\s\S]*?</footer>', ' ', txt, flags=re.I)
        # strip remaining tags
        txt = re.sub(r'<[^>]+>', ' ', txt)
        txt = re.sub(r'\s+', ' ', txt).strip()
        if txt:
            parts.append(txt)

    # Prefer explicit `cleaned_text` if present; else fall back to requirements
    req = _safe_get('cleaned_text', 'requirements_text', 'requirements', 'requirements_raw')
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
    pkg_name = f"Db.2_clean_data.{name}"
    try:
        return importlib.import_module(pkg_name)
    except Exception:
        # fallback: load by path
        module_path = BASE_DIR / "2_clean_data" / f"{name}.py"
        if not module_path.exists():
            raise FileNotFoundError(f"Module file not found: {module_path}")
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


def _validate_and_normalize(extracted: Dict[str, Any], original_job: Dict[str, Any]) -> Dict[str, Any]:
    warnings: List[str] = []
    errors: List[str] = []

    # Ensure top-level containers exist
    job = extracted.get('job') or {}
    company = extracted.get('company') or {}
    salary = extracted.get('salary') or {}
    raw = extracted.get('raw') or {}

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


def process_job(job: Dict[str, Any], api_key: str, config_path: Path) -> Dict[str, Any]:
    base_record = dict(job)
    base_record["status"] = "pending_llm"

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
    # If the caller passed an `extracted` directory (legacy), write the file
    # next to it as `extracted.json` instead of creating an `extracted/` folder.
    if output_dir.name == "extracted":
        return output_dir.parent / "extracted.json"
    return output_dir / "extracted.json"


def main() -> int:
    args = parse_args()
    logger = setup_logging()

    load_dotenv(BASE_DIR / ".env")

    input_path = args.input_path
    if not input_path.is_absolute():
        input_path = BASE_DIR / input_path

    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir

    output_path = args.output_path
    if output_path is None:
        output_path = derive_output_path(input_path, output_dir)
    elif not output_path.is_absolute():
        output_path = BASE_DIR / output_path

    fallback_path = args.fallback_path
    if fallback_path is not None and not fallback_path.is_absolute():
        fallback_path = BASE_DIR / fallback_path
    if fallback_path is None:
        # produce a fallback filename based on the output filename stem
        fallback_name = output_path.stem + "_fallback.json"
        fallback_path = DEFAULT_FALLBACK_DIR / fallback_name

    jobs = load_jobs(input_path)
    total_jobs = len(jobs)
    logger.info("Loaded %s pending job(s) from %s", total_jobs, input_path)

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

    passed_jobs: List[Dict[str, Any]] = []
    failed_jobs: List[Dict[str, Any]] = []
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

    # Build queues: active_queue for immediate processing, delayed_retry_queue for future retries
    retry_jobs = load_retry_queue() or []
    # Optionally ignore previously-scheduled retry queue entries for testing.
    ignore_flag = args.ignore_retry_queue or os.getenv('IGNORE_RETRY_QUEUE', '').lower() in ('1', 'true', 'yes')
    if ignore_flag:
        logger.info("IGNORE_RETRY_QUEUE enabled: skipping merge of existing retry queue and processing only current pending file")
        retry_jobs = []
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

    # partition retry jobs by next_retry_at
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
    # load existing extracted to avoid duplicates
    existing_extracted = set()
    try:
        if output_path.exists():
            txt = output_path.read_text(encoding='utf-8-sig').strip()
            if txt:
                parsed = json.loads(txt)
                if isinstance(parsed, list):
                    for e in parsed:
                        existing_extracted.add(_job_key(e))
    except Exception:
        pass

    for j in jobs:
        k = _job_key(j)
        if not k or k in seen or k in existing_extracted:
            continue
        seen.add(k)
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

    pointer = 0
    # sequential loop over active_jobs
    for idx, job in enumerate(active_jobs):
        job_key = _job_key(job)
        started_at = datetime.utcnow()
        logger.info("Processing job %s (%d/%d)", job_key, idx + 1, len(active_jobs))

        pick = _pick_next_valid(key_state, pointer)
        if pick is None:
            # no valid keys -> write remaining jobs to retry and exit
            remaining = active_jobs[idx:]
            for rem in remaining:
                entry = dict(rem)
                entry.update({
                    'status': 'retryable',
                    'last_error': 'no_valid_api_key',
                    'last_attempt_at': datetime.utcnow().isoformat(),
                })
                delayed_retry_jobs.append(entry)
            logger.info("No valid API key remaining; stopping run and persisting remaining jobs to retry queue")
            break

        key_info = key_state['keys'][pick]
        env_name = key_info.get('env_name')
        api_key_val = os.environ.get(env_name)
        logger.info("Using API key: %s", env_name)

        try:
            # call process_job which internally calls call_llm adapter
            processed = process_job(job, api_key_val, args.config_path)
        except Exception as exc:
            processed = dict(job)
            processed['status'] = 'llm_api_fail'
            processed['error'] = str(exc)

        status = processed.get('status')
        err_text = (processed.get('error') or '')
        low = err_text.lower() if isinstance(err_text, str) else ''

        # classify and handle
        if status == 'success':
            passed_jobs.append(processed)
            save_jobs(output_path, passed_jobs)
            key_info['total_success_today'] = int(key_info.get('total_success_today', 0)) + 1
            metrics['success_count'] += 1

        elif status == 'invalid_json_response' or _is_parse_error(Exception(err_text)):
            failed_jobs.append(processed)
            save_jobs(fallback_path, failed_jobs)
            metrics['fallback_count'] += 1

        else:
            # API or other failure -> decide retry vs fallback
            processed.setdefault('attempt_count', 0)
            processed['attempt_count'] = processed.get('attempt_count', 0) + 1
            processed['last_error'] = err_text
            processed['last_attempt_at'] = datetime.utcnow().isoformat()

            # 429/quota/resource exhausted -> mark exhausted_today and push to retry
            if '429' in low or 'quota' in low or 'resourceexhausted' in low or 'daily limit' in low:
                key_info['exhausted_today'] = True
                key_info['last_error'] = err_text
                key_info['last_attempt_at'] = datetime.utcnow().isoformat()
                key_info['total_fail_today'] = int(key_info.get('total_fail_today', 0)) + 1
                metrics['keys_429'] = metrics.get('keys_429', 0) + 1
                entry = dict(job)
                entry.update({'status': 'retryable', 'last_error': err_text, 'last_attempt_at': datetime.utcnow().isoformat()})
                delayed_retry_jobs.append(entry)

            # 5xx/timeout/connection -> temporary backoff, do not mark exhausted_today
            elif any(x in low for x in ('503', '504', 'timeout', 'connection')):
                base = int(LLM_BACKOFF_BASE_SECONDS or 30)
                maxb = int(LLM_BACKOFF_MAX_SECONDS or 300)
                backoff = min(maxb, base)
                try:
                    key_info['disabled_until'] = (datetime.utcnow() + timedelta(seconds=backoff)).isoformat()
                except Exception:
                    key_info['disabled_until'] = None
                key_info['total_fail_today'] = int(key_info.get('total_fail_today', 0)) + 1
                metrics['keys_5xx'] = metrics.get('keys_5xx', 0) + 1
                entry = dict(job)
                entry.update({'status': 'retryable', 'last_error': err_text, 'last_attempt_at': datetime.utcnow().isoformat()})
                delayed_retry_jobs.append(entry)

            else:
                # treat as fallback/permanent
                failed_jobs.append(processed)
                save_jobs(fallback_path, failed_jobs)
                metrics['fallback_count'] += 1

        # persist key state after each job
        _write_key_state(key_state_path, key_state)

        # advance pointer
        pointer = (pick + 1) % max(1, len(key_state.get('keys', [])))

        # sleep between requests unless last job
        if idx < len(active_jobs) - 1:
            logger.info("Sleeping %s seconds before next request", sleep_seconds)
            time.sleep(sleep_seconds)

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

    logger.info("Total jobs: %s", total_jobs)
    logger.info("Extract-pass (to normalize): %s", success_count)
    logger.info("LLM/API parse failures: %s", parse_fail_count)
    logger.info("LLM/API other failures: %s", api_fail_count)
    logger.info("Wrote extracted (pass) jobs to: %s", output_path)
    if failed_jobs:
        logger.info("Wrote extract fallback jobs to: %s", fallback_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())