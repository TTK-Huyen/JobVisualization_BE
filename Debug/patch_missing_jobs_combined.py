#!/usr/bin/env python3
"""
Data Patching Task - Isolated Wrapper
======================================
Mục đích: Đảm bảo TẤT CẢ các folder crawl đều có file "jobs_combined"
Hoạt động: Gọi merge_daily_outputs.py qua subprocess để xử lý các folder thiếu

Tính chất:
- Hoàn toàn ĐỘC LẬP, không ảnh hưởng pipeline chính
- KHÔNG sửa file gốc merge_daily_outputs.py
- Chạy trên tiến trình riêng để cách ly lỗi
- An toàn khi chạy đồng thời hoặc từng tuần
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime
import logging

# ============================================================================
# CONFIG
# ============================================================================
DATA_ROOT = Path(__file__).resolve().parent / "Db" / "data"
MERGE_SCRIPT = Path(__file__).resolve().parent / "Db" / "pipeline" / "crawl" / "1_crawl_data" / "merge_daily_outputs.py"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][PATCH] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def has_jobs_combined(raw_dir: Path) -> bool:
    """
    Kiểm tra xem thư mục raw đã có file "jobs_combined" hay chưa.
    Chấp nhận: jobs_combined.json, jobs_combined.csv, jobs_combined.parquet, v.v.
    
    Args:
        raw_dir: Đường dẫn đến thư mục "raw"
    
    Returns:
        True nếu tồn tại file bắt đầu bằng "jobs_combined", False nếu không
    """
    if not raw_dir.exists():
        return False
    
    for file_path in raw_dir.iterdir():
        if file_path.is_file() and file_path.name.startswith("jobs_combined"):
            return True
    
    return False


def extract_crawl_timestamp(crawl_folder_name: str) -> str:
    """
    Trích xuất timestamp từ tên folder theo định dạng crawl_yyyymmdd_hhmmss.
    
    Args:
        crawl_folder_name: Tên folder, ví dụ: "crawl_20260520_130000"
    
    Returns:
        Timestamp định dạng "yyyymmdd_hhmmss", ví dụ: "20260520_130000"
        Hoặc None nếu không hợp lệ
    """
    if not crawl_folder_name.startswith("crawl_"):
        return None
    
    # Format: crawl_yyyymmdd_hhmmss hoặc crawl_yyyymmdd_hhmmss_000000
    parts = crawl_folder_name.split("_")
    
    # crawl_20260520_130000 -> ['crawl', '20260520', '130000']
    if len(parts) >= 3:
        date_part = parts[1]  # yyyymmdd
        time_part = parts[2]  # hhmmss
        
        # Validate date (8 digits) và time (6 digits)
        if len(date_part) == 8 and len(time_part) == 6:
            return f"{date_part}_{time_part}"
    
    return None


def run_merge_for_crawl(crawl_timestamp: str) -> bool:
    """
    Chạy merge_daily_outputs.py cho một folder crawl cụ thể thông qua subprocess.
    
    Cơ chế:
    - Set RUN_DATE environment variable = crawl_timestamp
    - Gọi merge_daily_outputs.py bằng subprocess (tiến trình riêng)
    - Nếu lỗi, log và tiếp tục (không dừng pipeline)
    
    Args:
        crawl_timestamp: Timestamp định dạng "yyyymmdd_hhmmss"
    
    Returns:
        True nếu thành công, False nếu lỗi
    """
    try:
        # Chuẩn bị environment variable
        env = os.environ.copy()
        env["RUN_DATE"] = crawl_timestamp
        
        # Gọi merge_daily_outputs.py bằng subprocess
        logger.info(f"Executing merge for: {crawl_timestamp}")
        result = subprocess.run(
            [sys.executable, str(MERGE_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout
        )
        
        # Log output
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                logger.info(f"  {line}")
        
        if result.returncode != 0:
            logger.error(f"Merge failed for {crawl_timestamp}")
            if result.stderr:
                logger.error(f"  Error: {result.stderr}")
            return False
        
        logger.info(f"✓ Successfully merged: {crawl_timestamp}")
        return True
    
    except subprocess.TimeoutExpired:
        logger.error(f"Merge timeout for {crawl_timestamp} (>300s)")
        return False
    except Exception as e:
        logger.error(f"Exception during merge {crawl_timestamp}: {e}")
        return False


def scan_and_patch() -> dict:
    """
    Quét tất cả các folder crawl trong Db/data/ và vá những folder thiếu jobs_combined.
    
    Quy trình:
    1. Tìm tất cả folder có tên "crawl_*"
    2. Kiểm tra từng folder: có "crawl_yyyymmdd_hhmmss/raw" hay không?
    3. Kiểm tra raw dir có "jobs_combined*" chưa?
    4. Nếu không có -> gọi merge qua subprocess
    5. Nếu có -> skip (an toàn, không ghi đè)
    
    Returns:
        dict với các thống kê:
        {
            "total_crawl_folders": int,
            "already_have_jobs_combined": int,
            "patched_success": int,
            "patched_failed": int,
            "errors": list
        }
    """
    stats = {
        "total_crawl_folders": 0,
        "already_have_jobs_combined": 0,
        "patched_success": 0,
        "patched_failed": 0,
        "errors": []
    }
    
    if not DATA_ROOT.exists():
        logger.error(f"Data root not found: {DATA_ROOT}")
        stats["errors"].append(f"Data root not found: {DATA_ROOT}")
        return stats
    
    if not MERGE_SCRIPT.exists():
        logger.error(f"Merge script not found: {MERGE_SCRIPT}")
        stats["errors"].append(f"Merge script not found: {MERGE_SCRIPT}")
        return stats
    
    # Tìm tất cả folder crawl_*
    crawl_folders = sorted([
        d for d in DATA_ROOT.iterdir()
        if d.is_dir() and d.name.startswith("crawl_")
    ])
    
    logger.info(f"Found {len(crawl_folders)} crawl folder(s)")
    
    for crawl_folder in crawl_folders:
        stats["total_crawl_folders"] += 1
        crawl_name = crawl_folder.name
        raw_dir = crawl_folder / "raw"
        
        # Kiểm tra cấu trúc "crawl_yyyymmdd_hhmmss/raw"
        if not raw_dir.exists():
            logger.debug(f"⊘ {crawl_name}: raw directory not found (skipped)")
            continue
        
        # Kiểm tra xem đã có jobs_combined chưa
        if has_jobs_combined(raw_dir):
            logger.info(f"✓ {crawl_name}: jobs_combined already exists (skipped)")
            stats["already_have_jobs_combined"] += 1
            continue
        
        # Cần vá: extract timestamp và chạy merge
        logger.info(f"✗ {crawl_name}: jobs_combined NOT found -> patching...")
        crawl_timestamp = extract_crawl_timestamp(crawl_name)
        
        if not crawl_timestamp:
            msg = f"Invalid crawl folder name format: {crawl_name}"
            logger.warning(msg)
            stats["errors"].append(msg)
            stats["patched_failed"] += 1
            continue
        
        # Chạy merge
        success = run_merge_for_crawl(crawl_timestamp)
        if success:
            stats["patched_success"] += 1
        else:
            stats["patched_failed"] += 1
    
    return stats


# ============================================================================
# MAIN
# ============================================================================

def main():
    logger.info("=" * 70)
    logger.info("Data Patching Task - Start")
    logger.info("=" * 70)
    
    stats = scan_and_patch()
    
    # Report
    logger.info("=" * 70)
    logger.info("Data Patching Task - Summary")
    logger.info("=" * 70)
    logger.info(f"Total crawl folders scanned: {stats['total_crawl_folders']}")
    logger.info(f"Already have jobs_combined: {stats['already_have_jobs_combined']}")
    logger.info(f"Patched successfully: {stats['patched_success']}")
    logger.info(f"Patch failed: {stats['patched_failed']}")
    
    if stats["errors"]:
        logger.warning("Errors encountered:")
        for err in stats["errors"]:
            logger.warning(f"  - {err}")
    
    logger.info("=" * 70)
    
    # Exit code
    exit_code = 0 if stats["patched_failed"] == 0 else 1
    if exit_code == 0:
        logger.info("✓ Patch task completed successfully")
    else:
        logger.warning(f"⚠ Patch task completed with {stats['patched_failed']} failure(s)")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
