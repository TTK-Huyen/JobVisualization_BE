"""STEP 2 LLM output validation utilities.

Provides `validate_record(extracted: dict, original_job: dict=None) -> (extracted, validation)`
which performs pre-merge validation and normalization.

Key features added:
- Null handling for optional fields (returns null instead of empty string/omitted)
- ISO date normalization and relative-date parsing using `scraped_at` as reference
- Minimum-quality thresholds: >=10 skills, >=5 benefits
- Forbidden top-level field removal
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


FORBIDDEN_TOPLEVEL = {
    "source_name",
    "job_url",
    "job_source_id",
    "description_html",
    "search_keyword",
    "requirements_text",
    "fingerprint",
}


def _as_null_if_empty(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return value


def _parse_iso_date_safe(s: Any) -> Optional[str]:
    if not s:
        return None
    if isinstance(s, (int, float)):
        try:
            dt = datetime.fromtimestamp(int(s))
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except Exception:
            return None
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    # Accept ISO-like
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%dT%H:%M:%S')
    except Exception:
        pass
    # Date-only formats
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime('%Y-%m-%dT%H:%M:%S')
        except Exception:
            continue
    # Try to extract YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1) + 'T00:00:00'
    return None


def _parse_relative_date(text: str, reference_iso: Optional[str]) -> Optional[str]:
    """Parse relative expressions like '3 days ago', 'expires in 2 weeks'.

    Returns ISO datetime string or None.
    """
    if not text or not isinstance(text, str):
        return None
    txt = text.strip().lower()
    if not txt:
        return None

    # Must have a reference datetime to resolve relative dates
    if not reference_iso:
        return None
    ref = _parse_iso_date_safe(reference_iso)
    if not ref:
        return None
    try:
        ref_dt = datetime.fromisoformat(ref)
    except Exception:
        return None

    # Patterns
    m = re.match(r"^(\d+)\s*days?\s*ago$", txt)
    if m:
        days = int(m.group(1))
        dt = ref_dt - timedelta(days=days)
        return dt.strftime('%Y-%m-%dT00:00:00')

    m = re.match(r"^(\d+)\s*weeks?\s*ago$", txt)
    if m:
        weeks = int(m.group(1))
        dt = ref_dt - timedelta(days=weeks * 7)
        return dt.strftime('%Y-%m-%dT00:00:00')

    m = re.match(r"^(\d+)\s*months?\s*ago$", txt)
    if m:
        months = int(m.group(1))
        dt = ref_dt - timedelta(days=months * 30)
        return dt.strftime('%Y-%m-%dT00:00:00')

    # future variants: '30 days left', 'expires in 2 weeks', 'in 3 days'
    m = re.match(r"^(\d+)\s*days?\s*(left|remaining)?$", txt)
    if m:
        days = int(m.group(1))
        dt = ref_dt + timedelta(days=days)
        return dt.strftime('%Y-%m-%dT00:00:00')

    m = re.match(r"^expires? in (\d+)\s*(days?|weeks?|months?)$", txt)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if 'week' in unit:
            dt = ref_dt + timedelta(days=n * 7)
        elif 'month' in unit:
            dt = ref_dt + timedelta(days=n * 30)
        else:
            dt = ref_dt + timedelta(days=n)
        return dt.strftime('%Y-%m-%dT00:00:00')

    m = re.match(r"^in (\d+)\s*(days?|weeks?|months?)$", txt)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if 'week' in unit:
            dt = ref_dt + timedelta(days=n * 7)
        elif 'month' in unit:
            dt = ref_dt + timedelta(days=n * 30)
        else:
            dt = ref_dt + timedelta(days=n)
        return dt.strftime('%Y-%m-%dT00:00:00')

    return None


def _ensure_optional_fields_as_null(extracted: Dict[str, Any]) -> None:
    """Ensure common optional fields exist and use null (None) when absent/empty.

    This keeps outputs consistent (no empty strings or omitted keys).
    """
    job = extracted.setdefault('job', {})
    company = extracted.setdefault('company', {})
    salary = extracted.setdefault('salary', {})
    raw = extracted.setdefault('raw', {})

    # Common optional keys (kept small to avoid over-changing unknown keys)
    JOB_KEYS = [
        'title', 'description', 'skills_desc', 'work_type', 'location', 'is_remote',
        'listed_time', 'expiry_time', 'job_posting_url', 'search_group'
    ]
    COMPANY_KEYS = ['name', 'description', 'company_size_min', 'company_size_max', 'country', 'city', 'address', 'url', 'industry']
    SALARY_KEYS = ['min_salary', 'max_salary', 'med_salary', 'currency', 'pay_period']
    RAW_KEYS = ['salary_raw', 'experience_raw', 'employment_type_raw', 'company_size_raw', 'company_industry_raw', 'requirements_text', 'location_raw']

    for k in JOB_KEYS:
        if k not in job or job.get(k) == "":
            job[k] = None

    for k in COMPANY_KEYS:
        if k not in company or company.get(k) == "":
            company[k] = None

    for k in SALARY_KEYS:
        if k not in salary or salary.get(k) == "":
            salary[k] = None

    for k in RAW_KEYS:
        if k not in raw or raw.get(k) == "":
            raw[k] = None


def validate_record(extracted: Dict[str, Any], original_job: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Main validation entrypoint.

    Returns (normalized_extracted, validation_dict)
    """
    warnings: List[str] = []
    errors: List[str] = []

    if not isinstance(extracted, dict):
        errors.append('extracted_not_object')
        return {}, {'warnings': warnings, 'errors': errors, 'is_valid_for_import': False}

    # Ensure containers
    extracted.setdefault('job', {})
    extracted.setdefault('company', {})
    extracted.setdefault('salary', {})
    extracted.setdefault('raw', {})
    extracted.setdefault('extracted_skills', [])
    extracted.setdefault('benefits', [])
    extracted.setdefault('is_it_job', False)

    # Remove forbidden top-level fields
    for f in list(FORBIDDEN_TOPLEVEL):
        if f in extracted:
            extracted.pop(f, None)
            warnings.append(f'removed_forbidden_field_{f}')

    # Apply null handling for common optional keys
    _ensure_optional_fields_as_null(extracted)

    # Date normalization: try ISO and plain date formats
    job = extracted.get('job') or {}
    raw = extracted.get('raw') or {}

    # Determine scraped_at reference (original_job preferred)
    ref = None
    if original_job and original_job.get('scraped_at'):
        ref = original_job.get('scraped_at')
    elif extracted.get('scraped_at'):
        ref = extracted.get('scraped_at')

    for date_key in ('listed_time', 'expiry_time'):
        val = job.get(date_key)
        parsed = None
        # If primitive string or wrapper
        if isinstance(val, dict) and 'value' in val:
            candidate = val.get('value')
        else:
            candidate = val

        # First try absolute parse
        parsed = _parse_iso_date_safe(candidate)
        if parsed:
            # Normalize date-only to T00:00:00 already handled
            job[date_key] = parsed
        else:
            # Try relative parse using scraped_at reference
            rel_parsed = _parse_relative_date(str(candidate) if candidate else '', ref)
            if rel_parsed:
                job[date_key] = rel_parsed
            else:
                job[date_key] = None
                if candidate:
                    warnings.append(f'relative_date_unresolved_{date_key}' if ref is None else f'invalid_date_job.{date_key}')

    # Salary normalization
    salary = extracted.get('salary') or {}
    for sk in ('min_salary', 'max_salary', 'med_salary'):
        v = salary.get(sk)
        if v is None:
            salary[sk] = None
        else:
            try:
                if isinstance(v, dict) and 'value' in v:
                    v2 = v.get('value')
                else:
                    v2 = v
                num = None
                if v2 is None:
                    num = None
                elif isinstance(v2, (int, float)):
                    num = int(v2)
                else:
                    s = str(v2)
                    s2 = re.sub(r'[^0-9.-]', '', s)
                    num = int(float(s2)) if s2 else None
                salary[sk] = num
            except Exception:
                salary[sk] = None
    # swap min/max
    try:
        if salary.get('min_salary') is not None and salary.get('max_salary') is not None and salary['min_salary'] > salary['max_salary']:
            salary['min_salary'], salary['max_salary'] = salary['max_salary'], salary['min_salary']
            warnings.append('salary.min_max_swapped')
    except Exception:
        pass

    # currency/pay_period null-handling
    if not salary.get('currency'):
        salary['currency'] = None
    if not salary.get('pay_period'):
        salary['pay_period'] = None

    extracted['salary'] = salary

    # Company size handling
    company = extracted.get('company') or {}
    try:
        cmin = company.get('company_size_min')
        cmax = company.get('company_size_max')
        if cmin is None:
            company['company_size_min'] = None
        else:
            company['company_size_min'] = int(re.sub(r'[^0-9]', '', str(cmin))) if str(cmin).strip() else None
        if cmax is None:
            company['company_size_max'] = None
        else:
            company['company_size_max'] = int(re.sub(r'[^0-9]', '', str(cmax))) if str(cmax).strip() else None
        if company['company_size_min'] is not None and company['company_size_max'] is not None and company['company_size_min'] > company['company_size_max']:
            company['company_size_min'], company['company_size_max'] = company['company_size_max'], company['company_size_min']
            warnings.append('company.size_min_max_swapped')
    except Exception:
        company['company_size_min'] = None
        company['company_size_max'] = None

    extracted['company'] = company

    # Extracted skills normalization
    sks = extracted.get('extracted_skills') or []
    normalized_skills: List[Dict[str, Any]] = []
    seen_sk = set()
    for it in sks:
        if it is None:
            continue
        if isinstance(it, str):
            name = it.strip()
            if not name:
                continue
            key = name.lower()
            if key in seen_sk:
                continue
            seen_sk.add(key)
            normalized_skills.append({'skill_name': name, 'confidence': 80, 'is_direct_skill': True})
            continue
        if isinstance(it, dict):
            name = (it.get('skill_name') or it.get('skill_name_eng') or '').strip()
            if not name:
                continue
            key = name.lower()
            if key in seen_sk:
                continue
            seen_sk.add(key)
            conf = it.get('confidence')
            try:
                conf = int(conf)
            except Exception:
                conf = 80
            conf = max(0, min(100, conf))
            is_direct = it.get('is_direct_skill', True)
            normalized_skills.append({'skill_name': name, 'confidence': conf, 'is_direct_skill': bool(is_direct)})
            continue
    extracted['extracted_skills'] = normalized_skills

    # Benefits normalization
    bens = extracted.get('benefits')
    if isinstance(bens, str):
        # split heuristics
        if ';' in bens:
            bl = [x.strip() for x in bens.split(';') if x.strip()]
        elif ',' in bens and len(bens) < 200:
            bl = [x.strip() for x in bens.split(',') if x.strip()]
        else:
            bl = [bens.strip()] if bens.strip() else []
    elif isinstance(bens, list):
        bl = [str(x).strip() for x in bens if x and str(x).strip()]
    else:
        bl = []
    # dedupe case-insensitive
    out_bens = []
    seen_b = set()
    for b in bl:
        k = b.lower()
        if k in seen_b:
            continue
        seen_b.add(k)
        out_bens.append(b)
    extracted['benefits'] = out_bens

    # Raw fields: ensure null when empty
    raw = extracted.get('raw') or {}
    for k, v in list(raw.items()):
        raw[k] = _as_null_if_empty(v)
    extracted['raw'] = raw

    # Build validation metadata
    validation: Dict[str, Any] = {}
    validation['warnings'] = warnings
    validation['errors'] = errors
    validation['is_valid_for_import'] = True

    # Minimum quality thresholds
    if len(extracted.get('extracted_skills', [])) < 10:
        validation['warnings'].append('insufficient_skills')
        validation['is_valid_for_import'] = False

    if len(extracted.get('benefits', [])) < 5:
        validation['warnings'].append('insufficient_benefits')
        validation['is_valid_for_import'] = False

    # Attach final validation
    extracted['validation'] = validation
    return extracted, validation


__all__ = ['validate_record']
