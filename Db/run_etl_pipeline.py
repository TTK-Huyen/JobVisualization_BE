#!/usr/bin/env python3
"""
ETL PIPELINE ORCHESTRATOR
Điều phối toàn bộ quy trình: Crawl -> Clean -> Import to DB
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
import shutil

# ============================================================================
# CẤU HÌNH
# ============================================================================
BASE_DIR = Path(__file__).parent
CRAWL_DIR = BASE_DIR / "1_crawl_data"
CLEAN_DIR = BASE_DIR / "2_clean_data"
MAPPING_DIR = BASE_DIR / "3_mapping_data_db"

# Timestamp cho folder theo ngày
TODAY = datetime.now().strftime("%d_%m_%y")  # Format: 13_01_26
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# Output folders
CRAWL_OUTPUT_BASE = CRAWL_DIR / "output" / f"crawl_{TODAY}"
CLEAN_OUTPUT_BASE = CLEAN_DIR / "output" / f"clean_{TODAY}"

CRAWL_OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
CLEAN_OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

# File paths
CRAWL_OUTPUT_FILE = CRAWL_OUTPUT_BASE / f"job_combined_{TIMESTAMP}.json"
CLEAN_OUTPUT_FILE = CLEAN_OUTPUT_BASE / f"clean_data_final_{TIMESTAMP}.json"

# Log file
LOG_FILE = BASE_DIR / "etl_pipeline.log"

# ============================================================================
# LOGGING UTILITY
# ============================================================================
def log(message, level="INFO"):
    """Log message to both console and file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [{level}] {message}"
    print(log_msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_msg + "\n")

# ============================================================================
# STEP 1: CRAWL DATA
# ============================================================================
def run_crawl():
    """Chạy crawl_all_daily.bat"""
    log("=" * 60)
    log("🔄 STEP 1: CRAWLING DATA", "INFO")
    log("=" * 60)
    
    try:
        # Windows: chạy .bat file
        bat_file = CRAWL_DIR / "crawl_all_daily.bat"
        if not bat_file.exists():
            log(f"❌ Không tìm thấy: {bat_file}", "ERROR")
            return False
        
        log(f"🚀 Chạy: {bat_file}")
        result = subprocess.run(
            [str(bat_file)],
            cwd=str(CRAWL_DIR),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            log(f"❌ Crawl failed:\n{result.stderr}", "ERROR")
            return False
        
        log(f"✅ Crawl thành công!\n{result.stdout}", "INFO")
        return True
        
    except Exception as e:
        log(f"❌ Lỗi crawl: {e}", "ERROR")
        return False

# ============================================================================
# STEP 2: CLEAN DATA
# ============================================================================
def run_clean(crawl_file):
    """Chạy clean_process.py với input từ crawl"""
    log("=" * 60)
    log("🔄 STEP 2: CLEANING DATA", "INFO")
    log("=" * 60)
    
    try:
        # Kiểm tra file crawl output
        if not crawl_file.exists():
            log(f"❌ Không tìm thấy crawl output: {crawl_file}", "ERROR")
            return False
        
        # Sửa clean_process.py để nhận input từ command line
        clean_script = CLEAN_DIR / "clean_process_cli.py"
        
        if not clean_script.exists():
            log(f"⚠️  {clean_script} không tồn tại, dùng clean_process.py mặc định", "WARN")
            clean_script = CLEAN_DIR / "clean_process.py"
        
        log(f"📥 Input: {crawl_file}")
        log(f"📤 Output: {CLEAN_OUTPUT_FILE}")
        
        # Chạy clean script với arguments
        result = subprocess.run(
            [
                sys.executable,
                str(clean_script),
                "--input", str(crawl_file),
                "--output", str(CLEAN_OUTPUT_FILE)
            ],
            cwd=str(CLEAN_DIR),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            log(f"❌ Clean failed:\n{result.stderr}", "ERROR")
            return False
        
        log(f"✅ Clean thành công!\n{result.stdout}", "INFO")
        
        # Verify output file
        if not CLEAN_OUTPUT_FILE.exists():
            log(f"❌ Output file không được tạo: {CLEAN_OUTPUT_FILE}", "ERROR")
            return False
        
        return True
        
    except Exception as e:
        log(f"❌ Lỗi clean: {e}", "ERROR")
        return False

# ============================================================================
# STEP 3: IMPORT TO DATABASE
# ============================================================================
def run_import(clean_file):
    """Chạy import_to_db.py với input từ clean"""
    log("=" * 60)
    log("🔄 STEP 3: IMPORTING TO DATABASE", "INFO")
    log("=" * 60)
    
    try:
        # Kiểm tra file clean output
        if not clean_file.exists():
            log(f"❌ Không tìm thấy clean output: {clean_file}", "ERROR")
            return False
        
        import_script = MAPPING_DIR / "import_to_db_cli.py"
        
        if not import_script.exists():
            log(f"⚠️  {import_script} không tồn tại, dùng import_to_db.py mặc định", "WARN")
            import_script = MAPPING_DIR / "import_to_db.py"
        
        log(f"📥 Input: {clean_file}")
        
        # Chạy import script với arguments
        result = subprocess.run(
            [
                sys.executable,
                str(import_script),
                "--input", str(clean_file)
            ],
            cwd=str(MAPPING_DIR),
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            log(f"❌ Import failed:\n{result.stderr}", "ERROR")
            return False
        
        log(f"✅ Import thành công!\n{result.stdout}", "INFO")
        return True
        
    except Exception as e:
        log(f"❌ Lỗi import: {e}", "ERROR")
        return False

# ============================================================================
# FIND LATEST CRAWL OUTPUT
# ============================================================================
def find_latest_crawl():
    """Tìm file crawl output mới nhất - kiểm tra nhiều vị trí"""
    # 1. Tìm trong folder theo ngày (crawl_DD_MM_YY)
    if CRAWL_OUTPUT_BASE.exists():
        json_files = sorted(
            CRAWL_OUTPUT_BASE.glob("job_combined_*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        if json_files:
            return json_files[0]
    
    # 2. Fallback: Tìm trực tiếp trong output/ (default của bat file hiện tại)
    default_output = CRAWL_DIR / "output" / "jobs_combined.json"
    if default_output.exists():
        log(f"⚠️  Found crawl output at default location: {default_output}", "WARN")
        return default_output
    
    # 3. Tìm bất kỳ file jobs_combined*.json nào
    output_dir = CRAWL_DIR / "output"
    if output_dir.exists():
        all_combined = sorted(
            output_dir.glob("**/jobs_combined*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        if all_combined:
            log(f"⚠️  Found crawl output in subdirectory: {all_combined[0]}", "WARN")
            return all_combined[0]
    
    return None

# ============================================================================
# FIND LATEST CLEAN OUTPUT
# ============================================================================
def find_latest_clean():
    """Tìm file clean output mới nhất - kiểm tra nhiều vị trí"""
    # 1. Tìm trong folder theo ngày (clean_DD_MM_YY)
    if CLEAN_OUTPUT_BASE.exists():
        json_files = sorted(
            CLEAN_OUTPUT_BASE.glob("clean_data_final_*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        if json_files:
            return json_files[0]
    
    # 2. Fallback: Tìm trong bất kỳ folder clean nào
    output_dir = CLEAN_DIR / "output"
    if output_dir.exists():
        all_clean = sorted(
            output_dir.glob("**/clean_data_final_*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        if all_clean:
            log(f"⚠️  Found clean output in subdirectory: {all_clean[0]}", "WARN")
            return all_clean[0]
    
    return None

# ============================================================================
# MAIN PIPELINE
# ============================================================================
def main():
    log("=" * 80)
    log("🚀 START ETL PIPELINE", "INFO")
    log("=" * 80)
    log(f"Timestamp: {TIMESTAMP}")
    log(f"Today: {TODAY}")
    log("")
    
    # # STEP 1: Crawl
    # if not run_crawl():
    #     log("❌ Pipeline dừng tại CRAWL", "ERROR")
    #     return False
    
    # Tìm file crawl output
    # crawl_file = find_latest_crawl()
    # if not crawl_file:
    #     log("❌ Không tìm thấy crawl output file", "ERROR")
    #     return False
    # log(f"✅ Found crawl output: {crawl_file}", "INFO")
    
    # STEP 2: Clean
    # if not run_clean(crawl_file):
    #     log("❌ Pipeline dừng tại CLEAN", "ERROR")
    #     return False
    
    # Nếu skip Step 2, tìm clean file mới nhất
    clean_file = find_latest_clean()
    if not clean_file:
        log("❌ Không tìm thấy clean output file", "ERROR")
        return False
    log(f"✅ Using clean output: {clean_file}", "INFO")
    
    # STEP 3: Import
    if not run_import(clean_file):
        log("❌ Pipeline dừng tại IMPORT", "ERROR")
        return False
    
    # Success
    log("=" * 80)
    log("✅ ETL PIPELINE COMPLETED SUCCESSFULLY!", "SUCCESS")
    log("=" * 80)
    # log(f"📊 Crawl output: {crawl_file}")
    log(f"📊 Clean output: {clean_file}")
    log(f"📊 Database import: Completed")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log("\n⚠️  Pipeline dừng do user interrupt", "WARN")
        sys.exit(1)
    except Exception as e:
        log(f"❌ Unexpected error: {e}", "ERROR")
        sys.exit(1)
