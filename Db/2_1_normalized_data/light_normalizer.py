from __future__ import annotations

import re
from typing import Any, Dict, Optional
from bs4 import BeautifulSoup
from datetime import datetime
import hashlib


def _clean_text_light(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    # remove surrounding whitespace, collapse spaces, remove control chars
    s = re.sub(r"\s+", " ", value).strip()
    # remove common fence markers and repeated punctuation at ends
    s = re.sub(r"(^[`~\-\s]{1,}|[`~\-\s]{1,}$)", "", s)
    # strip HTML if present
    if "<" in s and ">" in s:
        try:
            s = BeautifulSoup(s, "html.parser").get_text(" ")
            s = re.sub(r"\s+", " ", s).strip()
        except Exception:
            pass
    return s


def _parse_date_light(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(int(value)).isoformat()
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    # Try ISO
    try:
        dt = datetime.fromisoformat(s)
        return dt.isoformat()
    except Exception:
        pass

    # Try common formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.isoformat()
        except Exception:
            continue
    # If contains numeric timestamp
    m = re.search(r"(\d{10,13})", s)
    if m:
        try:
            ts = int(m.group(1))
            # if 13 digits, ms
            if ts > 1e12:
                ts = ts // 1000
            return datetime.fromtimestamp(ts).isoformat()
        except Exception:
            pass
    return None


def _map_employment_type_light(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if "full" in v and "part" not in v:
        return "Full-time"
    if "part" in v:
        return "Part-time"
    if "contract" in v:
        return "Contract"
    if "intern" in v:
        return "Internship"
    return None


def _map_experience_light(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    if re.search(r"\b(entry|graduate|fresher)\b", v):
        return "Entry"
    if re.search(r"\b(junior|jr)\b", v):
        return "Junior"
    if re.search(r"\b(mid|experienced|mid-level)\b", v):
        return "Mid"
    if re.search(r"\b(senior|sr)\b", v):
        return "Senior"
    if re.search(r"\b(lead)\b", v):
        return "Lead"
    if re.search(r"\b(manager|management)\b", v):
        return "Manager"
    return None


def light_normalize_for_import(raw_job: Dict[str, Any]) -> Dict[str, Any]:
    """Perform light, format-only normalization and map fields to jobs schema.

    Returns a new dict with keys matching the jobs table and preserves/raw fields
    per the user's specification.
    """
    out: Dict[str, Any] = {}

    # In-place light clean for title
    title_raw = raw_job.get("title")
    title_clean = _clean_text_light(title_raw)
    out["title"] = title_clean or None

    # skills_desc from requirements_text
    req_raw = raw_job.get("requirements_text") or raw_job.get("requirements")
    skills_desc = _clean_text_light(req_raw)
    out["skills_desc"] = skills_desc or None

    # description: keep original HTML unchanged if present (user request)
    desc_html = raw_job.get("description_html")
    if isinstance(desc_html, str) and desc_html.strip():
        out["description"] = desc_html
    else:
        out["description"] = skills_desc or None

    # work_type
    out["work_type"] = _map_employment_type_light(raw_job.get("employment_type"))

    # formatted_experience_level
    exp_mapped = _map_experience_light(raw_job.get("experience_raw") or "")
    out["formatted_experience_level"] = exp_mapped or None

    # location
    loc = raw_job.get("location_raw") or raw_job.get("location")
    loc_clean = _clean_text_light(loc)
    # collapse commas/spaces
    loc_clean = re.sub(r"\s*,\s*", ", ", loc_clean)
    out["location"] = loc_clean or None

    # is_remote: light detect
    loc_lower = (loc_clean or "").lower()
    out["is_remote"] = True if "remote" in loc_lower or "work from home" in loc_lower else False

    # dates
    listed = _parse_date_light(raw_job.get("posted_date") or raw_job.get("listed_time") or raw_job.get("posted_at"))
    expiry = _parse_date_light(raw_job.get("expiry_date") or raw_job.get("expires_at"))
    scraped = _parse_date_light(raw_job.get("scraped_at"))
    out["listed_time"] = listed
    out["expiry_time"] = expiry
    out["scraped_at"] = scraped or raw_job.get("scraped_at")

    # URLs
    out["job_posting_url"] = raw_job.get("job_url") or raw_job.get("job_posting_url") or None

    # fingerprint: prefer existing, else compute from title|company|skills_desc
    fp = raw_job.get("fingerprint")
    if not fp:
        title_for_fp = out.get("title") or ""
        company = raw_job.get("company_name") or raw_job.get("company") or ""
        skills_for_fp = out.get("skills_desc") or ""
        fp_input = f"{title_for_fp}|{company}|{skills_for_fp}"
        fp = hashlib.md5(fp_input.encode("utf-8")).hexdigest()
    out["fingerprint"] = fp

    # keep some raw fields unchanged as requested
    for k in (
        "source_name",
        "job_source_id",
        "description_html",
        "search_keyword",
        "tags",
        "company_source_id",
        "company_website",
        "company_address",
    ):
        if k in raw_job:
            out[k] = raw_job[k]

    # keep deferred fields for later processing
    for k in ("salary_raw", "benefits", "company_size_raw", "company_industry", "extracted_skills"):
        if k in raw_job:
            out[k] = raw_job[k]

    return out
