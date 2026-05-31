"""
📊 Job Processing Configuration
================================
Cấu hình dễ dàng: Số keywords, cách chọn, source crawl, jobs per keyword

Load từ .env file
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
ENV_FILE = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_FILE)

# ============================================================================
# 📋 CONFIG ĐỂ USER DỄ CHỈNH - 4 BẢNG CHÍNH
# ============================================================================

# 1️⃣ JOBS PER KEYWORD - (Removed in favor of page-based limit)
JOBS_PER_KEYWORD = None

# 2️⃣ CRAWL SOURCE - Chọn source nào crawl
JOB_LIMITS = {
    "careerviet": int(os.getenv("CRAWL_CAREERVIET_JOBS", "0")),   # ← EDIT ĐÂY
    "itviec": int(os.getenv("CRAWL_ITVIEC_JOBS", "0")),
    "linkedin": int(os.getenv("CRAWL_LINKEDIN_JOBS", "0")),
    "vietnamworks": int(os.getenv("CRAWL_VIETNAMWORKS_JOBS", "0")),
}

# 3️⃣ KEYWORD SELECTION - Chọn bao nhiêu keywords từ mỗi tier + cách chọn nào
# 
# Cách dùng:
# - num_to_crawl: Số keywords chọn từ tier này (0 = disable tier)
# - selection_method: "random" (chọn ngẫu nhiên) hoặc "sequential" (tuần tự)
#
# Ví dụ: Tier1 num_to_crawl=1, method=random
#   → Chọn 1 keyword ngẫu nhiên từ 8 keywords tier1

KEYWORD_SELECTION_CONFIG = {
    "tier1": {
        "num_to_crawl": int(os.getenv("TIER1_NUM_KEYWORDS", "1")),  # ← EDIT ĐÂY
        "selection_method": os.getenv("TIER1_SELECTION_METHOD", "random"),  # ← "random" hoặc "sequential"
        "description": "Main tier (8 keywords)",
    },
    "tier2": {
        "num_to_crawl": int(os.getenv("TIER2_NUM_KEYWORDS", "0")),  # ← EDIT ĐÂY
        "selection_method": os.getenv("TIER2_SELECTION_METHOD", "sequential"),
        "description": "Secondary tier (5 keywords)",
    },
    "tier3": {
        "num_to_crawl": int(os.getenv("TIER3_NUM_KEYWORDS", "0")),  # ← EDIT ĐÂY
        "selection_method": os.getenv("TIER3_SELECTION_METHOD", "sequential"),
        "description": "Occasional tier (3 keywords)",
    },
}

# Auto-disable tier nếu num_to_crawl = 0
for tier_name, tier_cfg in KEYWORD_SELECTION_CONFIG.items():
    tier_cfg["enabled"] = tier_cfg["num_to_crawl"] > 0

# 4️⃣ CRAWL SETTINGS - Các setting khác
CRAWL_SETTINGS_TABLE = {
    "parallel_crawlers": int(os.getenv("CRAWL_PARALLEL_CRAWLERS", "4")),
    "request_delay_min": float(os.getenv("CRAWL_DELAY_MIN", "0.5")),
    "request_delay_max": float(os.getenv("CRAWL_DELAY_MAX", "1.5")),
    "max_retries": int(os.getenv("CRAWL_MAX_RETRIES", "2")),
    "batch_size": int(os.getenv("CLEAN_BATCH_SIZE", "20")),
}
CRAWL_MAX_PAGES = int(os.getenv("CRAWL_MAX_PAGES", "3"))

# 5️⃣ PIPELINE STEPS - Chọn các bước chạy
#
# Cách dùng:
# - true (1/yes): Chạy bước này
# - false (0/no): Bỏ qua bước này
#
# Ví dụ: chỉ muốn crawl & clean, không import: 
#   CRAWL=true, CLEAN=true, IMPORT=false

PIPELINE_STEPS = {
    "crawl": os.getenv("PIPELINE_CRAWL", "true").lower() in ("true", "1", "yes"),  # ← EDIT ĐÂY
    "clean": os.getenv("PIPELINE_CLEAN", "true").lower() in ("true", "1", "yes"),  # ← EDIT ĐÂY
    "import": os.getenv("PIPELINE_IMPORT", "true").lower() in ("true", "1", "yes"),  # ← EDIT ĐÂY
}

# 6️⃣ CRAWLER TIMEOUTS - Timeout per crawler (giây)
# Nếu crawler chạy quá lâu, sẽ skip và tiếp tục crawlers khác
CRAWLER_TIMEOUTS = {
    "itviec": int(os.getenv("TIMEOUT_ITVIEC", "600")),         # 10 phút
    "linkedin": int(os.getenv("TIMEOUT_LINKEDIN", "300")),     # 5 phút (LinkedIn chậm!)
    "careerviet": int(os.getenv("TIMEOUT_CAREERVIET", "600")), # 10 phút
    "vietnamworks": int(os.getenv("TIMEOUT_VIETNAMWORKS", "600")), # 10 phút
}

# ============================================================================
# 🔧 BUILD CONFIGS - Tính toán từ user config
# ============================================================================

CRAWL_CONFIG = {
    "parallel_crawlers": CRAWL_SETTINGS_TABLE["parallel_crawlers"],
    "request_delay_min": CRAWL_SETTINGS_TABLE["request_delay_min"],
    "request_delay_max": CRAWL_SETTINGS_TABLE["request_delay_max"],
    "max_retries": CRAWL_SETTINGS_TABLE["max_retries"],
}

KEYWORD_CONFIG = {
    "selection_config": KEYWORD_SELECTION_CONFIG,
    "jobs_per_keyword": JOBS_PER_KEYWORD,
}

CLEAN_CONFIG = {
    "batch_size": CRAWL_SETTINGS_TABLE["batch_size"],
    "fuzzy_threshold": float(os.getenv("CLEAN_FUZZY_THRESHOLD", "0.78")),
    "use_llm": os.getenv("CLEAN_USE_LLM", "true").lower() == "true",
}

# ============================================================================
# 📈 UTILITIES
# ============================================================================

def calculate_total_keywords():
    """Tính tổng số keywords sẽ crawl"""
    total = 0
    breakdown = {}
    
    for tier_name, tier_cfg in KEYWORD_SELECTION_CONFIG.items():
        if tier_cfg["enabled"]:
            num = tier_cfg["num_to_crawl"]
            breakdown[tier_name] = num
            total += num
    
    breakdown["total"] = total
    return breakdown


def calculate_total_jobs():
    """Tính tổng số jobs sẽ crawl (bằng số trang)"""
    total_keywords = calculate_total_keywords()["total"]
    
    breakdown = {
        "keywords": total_keywords,
        "by_source": {}
    }
    
    for source_name, job_limit in JOB_LIMITS.items():
        if job_limit > 0:
            breakdown["by_source"][source_name] = {
                "max_pages": CRAWL_MAX_PAGES,
            }
    
    return breakdown


def estimate_crawl_time():
    """Ước tính thời gian crawl (giây)"""
    # Tốc độ crawl theo trang (giây/trang)
    speeds = {
        "careerviet": 60,
        "itviec": 40,
        "linkedin": 90,
        "vietnamworks": 45,
    }
    
    total_time = 0
    for source_name, enabled in JOB_LIMITS.items():
        if enabled > 0:
            total_keywords = calculate_total_keywords()["total"]
            time_for_source = total_keywords * CRAWL_MAX_PAGES * speeds.get(source_name, 50)
            total_time += time_for_source
    
    # Parallel crawlers
    parallel = CRAWL_SETTINGS_TABLE["parallel_crawlers"]
    if parallel > 1:
        total_time = total_time / parallel
    
    return total_time


def print_config():
    """In config hiện tại"""
    print("\n" + "="*80)
    print("📊 KEYWORD & JOB CONFIGURATION")
    print("="*80)
    
    # Keyword selection
    print("\n📋 KEYWORD SELECTION:")
    print(f"{'Tier':<10} {'Num to Crawl':<15} {'Method':<12} {'Enabled':<10}")
    print("-" * 80)
    
    keywords_breakdown = calculate_total_keywords()
    for tier_name, tier_cfg in KEYWORD_SELECTION_CONFIG.items():
        status = "✓" if tier_cfg["enabled"] else "✗"
        print(f"{tier_name:<10} {tier_cfg['num_to_crawl']:<15} {tier_cfg['selection_method']:<12} {status:<10}")
    
    total_keywords = keywords_breakdown["total"]
    print("-" * 80)
    print(f"{'TOTAL':<10} {total_keywords:<15}")
    
    # Jobs config
    print(f"\n💼 JOBS CONFIGURATION:")
    print(f"  Crawl page limit per keyword: {CRAWL_MAX_PAGES} pages")
    
    # Source config
    print(f"\n🌐 CRAWL SOURCES:")
    for source_name, limit in JOB_LIMITS.items():
        if limit > 0:
            print(f"  ✓ {source_name} (enabled)")
    
    if not any(limit > 0 for limit in JOB_LIMITS.values()):
        print("  (No sources enabled)")
    
    # Estimate
    jobs = calculate_total_jobs()
    estimate_time = estimate_crawl_time()
    print(f"\n⏱️  ESTIMATES:")
    print(f"  Total keywords: {jobs['keywords']}")
    print(f"  Max pages per source: {CRAWL_MAX_PAGES}")
    print(f"  Estimate time: ~{int(estimate_time)}s ({estimate_time/60:.1f}m)")
    
    # Settings
    print(f"\n⚙️  CRAWL SETTINGS:")
    print(f"  Parallel crawlers: {CRAWL_SETTINGS_TABLE['parallel_crawlers']}")
    print(f"  Request delay: {CRAWL_SETTINGS_TABLE['request_delay_min']}-{CRAWL_SETTINGS_TABLE['request_delay_max']}s")
    print(f"  Max retries: {CRAWL_SETTINGS_TABLE['max_retries']}")
    print(f"  Batch size: {CRAWL_SETTINGS_TABLE['batch_size']}")
    print(f"  Max pages per source: {CRAWL_MAX_PAGES}")
    
    # Pipeline steps
    print(f"\n🔄 PIPELINE STEPS:")
    print(f"  🔍 Crawl:  {'✓ ENABLED' if PIPELINE_STEPS['crawl'] else '✗ DISABLED'}")
    print(f"  🧹 Clean:  {'✓ ENABLED' if PIPELINE_STEPS['clean'] else '✗ DISABLED'}")
    print(f"  📤 Import: {'✓ ENABLED' if PIPELINE_STEPS['import'] else '✗ DISABLED'}")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    print_config()
