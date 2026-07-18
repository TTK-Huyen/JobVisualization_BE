import os
import re
from datetime import date, datetime, timedelta
from typing import Optional


DEFAULT_IMPORT_MIN_DATE = date(2025, 9, 1)
DEFAULT_REALTIME_DAYS = 2


def _parse_date_env(value: Optional[str], fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return fallback


def get_date_filter_mode() -> str:
    mode = (os.environ.get("JOB_DATE_MODE") or "import").strip().lower()
    if mode in {"import", "historical"}:
        return "import"
    if mode in {"realtime", "real-time", "recent"}:
        return "realtime"
    if mode in {"on", "true", "yes", "1"}:
        return "realtime"
    if mode in {"off", "all", "none"}:
        return "off"
    return "import"


def get_import_min_date() -> date:
    return _parse_date_env(os.environ.get("IMPORT_MIN_DATE"), DEFAULT_IMPORT_MIN_DATE)


def get_realtime_days() -> int:
    raw = os.environ.get("DAYS_BACK")
    try:
        days = int(raw) if raw else DEFAULT_REALTIME_DAYS
        return max(days, 1)
    except Exception:
        return DEFAULT_REALTIME_DAYS



def get_realtime_cutoff_date() -> date:
    days = get_realtime_days()
    return datetime.now().date() - timedelta(days=days)


def get_active_cutoff_date() -> Optional[date]:
    mode = get_date_filter_mode()
    if mode == "off":
        return None
    if mode == "realtime":
        return get_realtime_cutoff_date()
    return get_import_min_date()


def describe_date_filter() -> str:
    mode = get_date_filter_mode()
    if mode == "off":
        return "off"
    if mode == "realtime":
        return f"realtime >= {get_realtime_cutoff_date().isoformat()} (last {get_realtime_days()} day(s))"
    return f"import >= {get_import_min_date().isoformat()}"


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def parse_relative_time_to_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    normalized = value.strip().lower()
    
    # Handle direct shortcuts
    if normalized in ("just now", "now", "today", "yesterday", "posted today", "posted yesterday"):
        if "yesterday" in normalized:
            return (datetime.now() - timedelta(days=1)).date()
        return datetime.now().date()
        
    match = re.search(
        r"(?:posted\s+)?(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago",
        normalized,
    )
    if not match:
        # Handle "a day ago", "an hour ago"
        if re.search(r"\b(?:posted\s+)?(?:a|an)\s+day\s+ago\b", normalized):
            return (datetime.now() - timedelta(days=1)).date()
        if re.search(r"\b(?:posted\s+)?(?:a|an)\s+hour\s+ago\b", normalized):
            return datetime.now().date()
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    now = datetime.now()

    if "minute" in unit or "hour" in unit:
        return now.date()
    if "day" in unit:
        return (now - timedelta(days=amount)).date()
    if "week" in unit:
        return (now - timedelta(weeks=amount)).date()
    if "month" in unit:
        return (now - timedelta(days=amount * 30)).date()
    if "year" in unit:
        return (now - timedelta(days=amount * 365)).date()
    return None


def parse_careerviet_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    # Match DD-MM-YYYY or DD/MM/YYYY
    match = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", value)
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_vietnamworks_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    normalized = value.strip().lower()
    
    # "hôm nay", "giờ trước", "phút trước", "giây trước" are all today
    if "hôm nay" in normalized or "giờ" in normalized or "phút" in normalized or "giây" in normalized:
        return datetime.now().date()
        
    match = re.search(r"(\d+)", normalized)
    if not match:
        return None
        
    amount = int(match.group(1))
    now = datetime.now()
    if "ngày" in normalized:
        return (now - timedelta(days=amount)).date()
    if "tuần" in normalized:
        return (now - timedelta(weeks=amount)).date()
    if "tháng" in normalized:
        return (now - timedelta(days=amount * 30)).date()
    return None


def is_posted_date_allowed(posted_date: Optional[date]) -> bool:
    cutoff = get_active_cutoff_date()
    if cutoff is None:
        return True
    if posted_date is None:
        return True
    return posted_date >= cutoff
