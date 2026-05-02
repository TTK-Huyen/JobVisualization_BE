"""
Normalization constants and helper maps used by STEP 2 extraction/validation.

This module contains enums, lookup maps and common patterns for
normalizing non-skill metadata (work type, currency, pay period,
salary unit parsing, date formats, Vietnam cities, company size ranges,
and unknown/null markers).

Do NOT include skill or benefit canonicalization here.
"""
from __future__ import annotations

from typing import Dict, List, Pattern
import re

# Unknown / null markers
UNKNOWN = "unknown"
NULL = None


# Work type canonical mapping: map common textual variants to enum values
WORK_TYPE_MAP: Dict[str, str] = {
    "full-time": "full_time",
    "full time": "full_time",
    "fulltime": "full_time",
    "part-time": "part_time",
    "part time": "part_time",
    "parttime": "part_time",
    "intern": "internship",
    "internship": "internship",
    "contract": "contract",
    "temporary": "temporary",
    "temp": "temporary",
    "freelance": "freelance",
    "other": "other",
}

WORK_TYPE_ENUM = [
    "full_time",
    "part_time",
    "internship",
    "contract",
    "temporary",
    "freelance",
    "other",
    "unknown",
]


# Currency canonical values
CURRENCY_ENUM = ["VND", "USD", "EUR", "JPY", "KRW", "SGD", "OTHER", "unknown"]
CURRENCY_SYMBOL_MAP: Dict[str, str] = {
    "vnd": "VND",
    "đ": "VND",
    "vnđ": "VND",
    "dongs": "VND",
    "usd": "USD",
    "$": "USD",
    "eur": "EUR",
    "€": "EUR",
    "jpy": "JPY",
    "krw": "KRW",
    "sgd": "SGD",
}


# Pay period canonical values
PAY_PERIOD_ENUM = ["monthly", "yearly", "hourly", "daily", "negotiable", "unknown"]
PAY_PERIOD_MAP: Dict[str, str] = {
    "month": "monthly",
    "monthly": "monthly",
    "tháng": "monthly",
    "year": "yearly",
    "yearly": "yearly",
    "năm": "yearly",
    "hour": "hourly",
    "hourly": "hourly",
    "giờ": "hourly",
    "day": "daily",
    "daily": "daily",
    "negotiable": "negotiable",
    "thoả thuận": "negotiable",
}


# Remote/hybrid detection
REMOTE_KEYWORDS = ["remote", "work from home", "wfh", "from home", "làm việc từ xa"]
HYBRID_KEYWORDS = ["hybrid", "kết hợp", "hybrid work"]


# Common Vietnam cities and provinces (short list for recognition)
VIETNAM_CITIES = [
    "Hà Nội", "Ha Noi", "Hanoi", "HCM", "TP Hồ Chí Minh", "Ho Chi Minh", "Hồ Chí Minh", "Đà Nẵng", "Da Nang",
    "Hải Phòng", "Hai Phong", "Cần Thơ", "Can Tho", "Bắc Ninh", "Bình Dương", "Bình Thuận", "Đồng Nai",
]


# Company size parsing labels and approximate ranges (min, max)
COMPANY_SIZE_LABELS: Dict[str, tuple] = {
    "micro": (1, 9),
    "small": (10, 49),
    "medium": (50, 249),
    "large": (250, 1999),
    "enterprise": (2000, 9999999),
}

# Common raw size patterns -> approximate min/max
COMPANY_SIZE_PATTERNS: Dict[Pattern, tuple] = {
    re.compile(r"\b(\d{1,3}[.,]?\d{0,3})\s*[-–~]\s*(\d{1,3}[.,]?\d{0,3})\b"): (None, None),
}


# Salary units mapping (Vietnamese/English shorthand)
SALARY_UNIT_MAP: Dict[str, float] = {
    "tr": 1_000_000,      # 'tr' shorthand => million VND
    "trieu": 1_000_000,
    "triệu": 1_000_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "k": 1_000,           # 'k' thousand
    "usd": 1.0,           # for USD leave as 1.0 marker for currency handling
    "vnd": 1.0,
}

# Regex patterns commonly used to extract numbers and currency
RE_SALARY_NUMBER = re.compile(r"([0-9]+[.,]?[0-9]*)")
RE_CURRENCY = re.compile(r"\b(vnd|vnđ|đ|usd|eur|jpy|krw|sgd|\$|€)\b", re.IGNORECASE)


# Common date formats encountered in job posts (for light parsing attempts)
COMMON_DATE_FORMATS: List[str] = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d %b %Y",
    "%d %B %Y",
]


__all__ = [
    "WORK_TYPE_MAP",
    "WORK_TYPE_ENUM",
    "CURRENCY_ENUM",
    "CURRENCY_SYMBOL_MAP",
    "PAY_PERIOD_ENUM",
    "PAY_PERIOD_MAP",
    "REMOTE_KEYWORDS",
    "HYBRID_KEYWORDS",
    "VIETNAM_CITIES",
    "COMPANY_SIZE_LABELS",
    "SALARY_UNIT_MAP",
    "RE_SALARY_NUMBER",
    "RE_CURRENCY",
    "COMMON_DATE_FORMATS",
    "UNKNOWN",
    "NULL",
]
