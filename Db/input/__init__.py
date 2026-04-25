"""
Input Package - Load configs & static data

Usage:
    from input import GEMINI_CONFIG, TIER_CONFIG, load_keywords
"""

import os
import json
from pathlib import Path

# ============================================================================
# Load Config Modules
# ============================================================================
from .config_api import (
    get_api_key,
    get_all_api_keys,
    on_api_quota_error,
    GEMINI_CONFIG,
    print_api_status,
)

from .config_jobs import (
    JOB_LIMITS,
    JOBS_PER_KEYWORD,
    KEYWORD_SELECTION_CONFIG,
    CRAWL_CONFIG,
    CLEAN_CONFIG,
    KEYWORD_CONFIG,
    PIPELINE_STEPS,
    CRAWLER_TIMEOUTS,
    calculate_total_keywords,
    calculate_total_jobs,
    estimate_crawl_time,
    print_config,
)

from .config_db import (
    POSTGRES_CONFIG,
    get_connection_string,
    get_psycopg2_params,
    test_connection,
    print_db_config,
)

# ============================================================================
# 📁 Static Data Loader
# ============================================================================

DATA_DIR = Path(__file__).parent / "data"

def load_keywords():
    """Load keywords_daily.json từ input/data/"""
    keywords_file = DATA_DIR / "keywords_daily.json"
    
    if not keywords_file.exists():
        print(f"⚠️  Keywords file not found: {keywords_file}")
        return None
    
    try:
        with open(keywords_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"✗ Error loading keywords: {e}")
        return None


def get_keywords_count():
    """Lấy số lượng keywords"""
    keywords = load_keywords()
    if not keywords:
        return 0
    
    tier1 = len(keywords.get("tier1", []))
    tier2 = len(keywords.get("tier2", []))
    tier3 = len(keywords.get("tier3", []))
    
    return {
        "tier1": tier1,
        "tier2": tier2,
        "tier3": tier3,
        "total": tier1 + tier2 + tier3,
    }


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    # API Config
    "GEMINI_CONFIG",
    "get_api_key",
    "get_all_api_keys",
    "on_api_quota_error",
    "print_api_status",
    
    # Jobs Config
    "JOB_LIMITS",
    "JOBS_PER_KEYWORD",
    "KEYWORD_SELECTION_CONFIG",
    "CRAWL_CONFIG",
    "CLEAN_CONFIG",
    "KEYWORD_CONFIG",
    "PIPELINE_STEPS",
    "CRAWLER_TIMEOUTS",
    "calculate_total_keywords",
    "calculate_total_jobs",
    "estimate_crawl_time",
    "print_config",
    
    # DB Config
    "POSTGRES_CONFIG",
    "get_connection_string",
    "get_psycopg2_params",
    "test_connection",
    "print_db_config",
    
    # Static Data
    "load_keywords",
    "get_keywords_count",
    "DATA_DIR",
]
