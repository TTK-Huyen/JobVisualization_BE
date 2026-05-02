"""
STEP 2 extraction output schema definition and sample object.

This module documents the expected JSON structure returned by the LLM
after STEP 2 extraction (DB-ready metadata for jobs, companies, salaries),
with skills/benefits left raw.

Note: `fingerprint` MUST NOT be produced by the LLM and is generated later by code.
"""
from __future__ import annotations

from typing import Any, Dict


# Top-level keys and nested structure expected from STEP 2 LLM output
STEP2_OUTPUT_KEYS = [
    "source_name",
    "job_url",
    "job_source_id",
    "search_keyword",
    "scraped_at",
    "job",
    "company",
    "salary",
    "raw",
    "extracted_skills",
    "benefits",
    "is_it_job",
    "validation",
]


# Example schema (keys with example types/values)
SAMPLE_OUTPUT: Dict[str, Any] = {
    "source_name": "careerviet",
    "job_url": "https://...",
    "job_source_id": "35C71A96",
    "search_keyword": "frontend developer",
    "scraped_at": "2026-04-25T19:52:50",

    "job": {
        "title": "Frontend Developer",
        "description": "Full HTML or text description (optional)",
        "skills_desc": "Requirement text",
        "work_type": "full_time",
        "location": "Hà Nội",
        "is_remote": False,
        "listed_time": "2026-04-25T00:00:00",
        "expiry_time": "2026-05-13T00:00:00",
        "job_posting_url": "https://...",
        "search_group": "frontend developer",
    },

    "company": {
        "name": "TỔNG CÔNG TY CỔ PHẦN BƯU CHÍNH VIETTEL",
        "description": None,
        "company_size_min": 20000,
        "company_size_max": 49999,
        "country": "Việt Nam",
        "city": "Hà Nội",
        "address": "Số 2, ngõ 15 phố Duy Tân, Cầu Giấy, Hà Nội",
        "url": None,
    },

    "salary": {
        "min_salary": 15000000,
        "max_salary": 40000000,
        "med_salary": 27500000,
        "currency": "VND",
        "pay_period": "monthly",
    },

        "raw": {
            "salary_raw": "15 Tr - 40 Tr VND",
            "experience_raw": "Trên 1 năm",
            "employment_type_raw": "Nhân viên chính thức",
            "company_size_raw": "20.000-49.999",
            "company_industry_raw": "CNTT - Phần mềm",
            # Optional trace: original cleaned text from STEP 1 may be preserved here as
            # `raw.requirements_text` for debugging/traceability only. Do NOT treat this
            # field as the final cleaned requirements; `job.skills_desc` is the canonical
            # cleaned requirements section used for extraction and downstream processing.
            "requirements_text": "Full cleaned text from STEP 1 (input only, trace)",
        },

    # Keep these raw; normalization of skills/benefits happens in STEP 3
    "extracted_skills": [
        {"skill_name": "Angular", "confidence": 100, "is_direct_skill": True}
    ],
    "benefits": ["Chế độ bảo hiểm", "Du lịch"],
    "is_it_job": True,

    # validation block is filled by local validation (not LLM)
    "validation": {"is_valid_for_import": True, "warnings": [], "errors": []},
}


def schema_documentation() -> Dict[str, Any]:
    """Return a minimal schema mapping of keys -> types/descriptions."""
    return {
        "top_level": {
            "source_name": "string | null",
            "job_url": "string | null",
            "job_source_id": "string | null",
            "search_keyword": "string | null",
            "scraped_at": "ISO datetime string | null",
        },
        "job": {
            "title": "string | null",
            "description": "string | null",
            "skills_desc": "string | null",
            "work_type": "enum | unknown",
            "location": "string | null",
            "is_remote": "boolean | null",
            "listed_time": "ISO datetime | null",
            "expiry_time": "ISO datetime | null",
            "job_posting_url": "string | null",
            "search_group": "string | null",
        },
        "company": {
            "name": "string | null",
            "description": "string | null",
            "company_size_min": "int | null",
            "company_size_max": "int | null",
            "country": "string | null",
            "city": "string | null",
            "address": "string | null",
            "url": "string | null",
        },
        "salary": {
            "min_salary": "int | null",
            "max_salary": "int | null",
            "med_salary": "int | null",
            "currency": "enum | unknown",
            "pay_period": "enum | unknown",
        },
        "raw": {
            "salary_raw": "string | null",
            "experience_raw": "string | null",
            "employment_type_raw": "string | null",
            "company_size_raw": "string | null",
            "company_industry_raw": "string | null",
            # `raw.requirements_text` (optional): original STEP 1 cleaned text preserved
            # for debugging/trace only. The LLM should NOT return a top-level
            # `requirements_text` field; `job.skills_desc` is the canonical cleaned
            # requirements section used downstream.
                "requirements_text": "string | null",
        },
        "extracted_skills": "list of skill objects: {skill_name, confidence, is_direct_skill}",
        "benefits": "list of raw benefit strings",
        "is_it_job": "bool",
        "validation": "{is_valid_for_import: bool, warnings: list, errors: list}",
    }


__all__ = ["STEP2_OUTPUT_KEYS", "SAMPLE_OUTPUT", "schema_documentation"]

# Fields that must NOT be produced by the LLM and will be removed by local validation
FORBIDDEN_TOPLEVEL = [
    "source_name",
    "job_url",
    "job_source_id",
    "description_html",
    "search_keyword",
    "requirements_text",
    "fingerprint",
]
