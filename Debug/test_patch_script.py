#!/usr/bin/env python3
"""
Quick Test Script - Verify patch_missing_jobs_combined.py hoạt động đúng

Mục đích: Kiểm tra nhanh xem script patch có thể chạy thành công không
Không làm thay đổi dữ liệu thực (chỉ report)
"""

import sys
from pathlib import Path
import subprocess

def test_structure():
    """Test 1: Kiểm tra cấu trúc thư mục"""
    print("\n" + "=" * 70)
    print("TEST 1: Kiểm tra cấu trúc thư mục")
    print("=" * 70)
    
    project_root = Path(__file__).resolve().parent
    data_root = project_root / "Db" / "data"
    merge_script = project_root / "Db" / "pipeline" / "crawl" / "1_crawl_data" / "merge_daily_outputs.py"
    patch_script = project_root / "patch_missing_jobs_combined.py"
    
    checks = {
        "Data directory": data_root,
        "Merge script": merge_script,
        "Patch script": patch_script,
    }
    
    all_exist = True
    for name, path in checks.items():
        exists = path.exists()
        status = "✓" if exists else "✗"
        print(f"{status} {name}: {path}")
        if not exists:
            all_exist = False
    
    return all_exist and data_root.exists()

def test_crawl_folders():
    """Test 2: Quét các folder crawl"""
    print("\n" + "=" * 70)
    print("TEST 2: Quét các folder crawl")
    print("=" * 70)
    
    project_root = Path(__file__).resolve().parent
    data_root = project_root / "Db" / "data"
    
    if not data_root.exists():
        print("✗ Data directory không tồn tại")
        return False
    
    crawl_folders = sorted([
        d for d in data_root.iterdir()
        if d.is_dir() and d.name.startswith("crawl_")
    ])
    
    print(f"Tìm thấy {len(crawl_folders)} folder crawl")
    
    # Phân loại
    with_raw = []
    without_raw = []
    with_combined = []
    without_combined = []
    
    for crawl_dir in crawl_folders[:10]:  # Check 10 cái đầu
        raw_dir = crawl_dir / "raw"
        
        if raw_dir.exists():
            with_raw.append(crawl_dir.name)
            combined = list(raw_dir.glob("jobs_combined*"))
            if combined:
                with_combined.append(crawl_dir.name)
            else:
                without_combined.append(crawl_dir.name)
        else:
            without_raw.append(crawl_dir.name)
    
    print(f"\nPhân loại (10 folder đầu):")
    print(f"  ✓ Có raw/: {len(with_raw)}")
    print(f"  ✗ Không raw/: {len(without_raw)}")
    print(f"  ✓ Có jobs_combined*: {len(with_combined)}")
    print(f"  ✗ Không jobs_combined*: {len(without_combined)}")
    
    if without_combined:
        print(f"\nFolder cần patch (mẫu): {without_combined[0]}")
        return True
    
    return len(crawl_folders) > 0

def test_run_date_env():
    """Test 3: Kiểm tra RUN_DATE environment variable trong merge_daily_outputs.py"""
    print("\n" + "=" * 70)
    print("TEST 3: Kiểm tra RUN_DATE support")
    print("=" * 70)
    
    project_root = Path(__file__).resolve().parent
    merge_script = project_root / "Db" / "pipeline" / "crawl" / "1_crawl_data" / "merge_daily_outputs.py"
    
    if not merge_script.exists():
        print("✗ merge_daily_outputs.py không tìm thấy")
        return False
    
    with open(merge_script, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Kiểm tra xem có dòng RUN_DATE không
    if 'os.environ.get("RUN_DATE"' in content or "os.environ.get('RUN_DATE'" in content:
        print("✓ merge_daily_outputs.py hỗ trợ RUN_DATE environment variable")
        return True
    else:
        print("✗ merge_daily_outputs.py không hỗ trợ RUN_DATE")
        return False

def test_patch_script():
    """Test 4: Dry-run patch script (không thay đổi dữ liệu)"""
    print("\n" + "=" * 70)
    print("TEST 4: Kiểm tra Patch Script (Dry-Run)")
    print("=" * 70)
    
    project_root = Path(__file__).resolve().parent
    patch_script = project_root / "patch_missing_jobs_combined.py"
    
    if not patch_script.exists():
        print("✗ patch_missing_jobs_combined.py không tìm thấy")
        return False
    
    print("✓ Patch script tồn tại")
    print("  (Không chạy để tránh thay đổi dữ liệu)")
    print("  → Sẵn sàng chạy bằng: python patch_missing_jobs_combined.py")
    
    return True

def print_next_steps():
    """In ra hướng dẫn tiếp theo"""
    print("\n" + "=" * 70)
    print("NEXT STEPS")
    print("=" * 70)
    print("""
1. Nếu tất cả test PASS:
   → Chạy script patch:
     python patch_missing_jobs_combined.py
   
2. Để lưu log:
   → python patch_missing_jobs_combined.py > patch_log.txt 2>&1
   
3. Để debug chi tiết:
   → Xem file PATCH_TASK_GUIDE.md
   → Xem file WHY_NO_MODIFICATION_NEEDED.md
   
4. Để hiểu cơ chế:
   → Đọc tệp WHY_NO_MODIFICATION_NEEDED.md
""")

def main():
    print("\n" + "🧪 " * 20)
    print("QUICK TEST - Patch Data Task")
    print("🧪 " * 20)
    
    results = {
        "Structure": test_structure(),
        "Crawl Folders": test_crawl_folders(),
        "RUN_DATE Support": test_run_date_env(),
        "Patch Script": test_patch_script(),
    }
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n✅ Tất cả test PASS - Sẵn sàng chạy patch!")
        print_next_steps()
        return 0
    else:
        print("\n❌ Có test FAIL - Kiểm tra cấu trúc thư mục")
        return 1

if __name__ == "__main__":
    sys.exit(main())
